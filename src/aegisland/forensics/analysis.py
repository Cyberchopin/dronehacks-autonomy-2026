"""Evidence rules for post-flight review. No action selection or execution."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .alignment import Alignment, load_alignment
from .ingest import ingest_jetson, ingest_px4
from .model import PX4_CLOCK, Finding, Ingestion, Sample, finite
from .scope import geometry_boundary


@dataclass(frozen=True)
class Thresholds:
    depth_coverage_min: float = 0.5
    invalid_depth_ratio_max: float = 0.5
    line_confidence_min: float = 0.3
    latency_ms_max: float = 100.0
    saturation_abs_min: float = 0.95

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not finite(value) or value <= 0 or (name != "latency_ms_max" and value > 1):
                raise ValueError(f"Invalid analysis threshold: {name}")


def detect(result: Ingestion, thresholds: Thresholds) -> list[Finding]:
    findings = list(result.findings)
    previous: dict[str, Sample] = {}

    def add(sample: Sample, category: str, knowledge: str, detail: str, evidence: dict) -> None:
        findings.append(
            Finding(
                category,
                knowledge,
                sample.source,
                sample.stream,
                sample.index,
                sample.timestamp,
                sample.clock,
                detail,
                evidence,
            )
        )

    for sample in result.samples:  # Preserve acquisition order to expose rollback.
        values = sample.values
        prior = previous.get(sample.stream)
        if (
            prior
            and prior.timestamp is not None
            and sample.timestamp is not None
            and sample.timestamp < prior.timestamp
        ):
            add(
                sample,
                "timestamp_rollback",
                "observed",
                "Timestamp decreased in source order; "
                "reset, reordering and corruption cannot be distinguished.",
                {"previous": prior.timestamp, "current": sample.timestamp},
            )
            prior = None  # Never compare modes/frame gaps across an ambiguous epoch.
        mode_field = "mode" if sample.source == "jetson" else "nav_state"
        if (
            prior
            and mode_field in values
            and mode_field in prior.values
            and values[mode_field] is not None
            and prior.values[mode_field] is not None
            and values[mode_field] != prior.values[mode_field]
        ):
            add(
                sample,
                "mode_switch",
                "observed",
                "Recorded mode changed.",
                {"from": prior.values[mode_field], "to": values[mode_field]},
            )
        if sample.source == "px4":
            invalid = {
                key: value for key, value in values.items() if key.endswith("_valid") and value == 0
            }
            if invalid:
                add(
                    sample,
                    "estimator_invalid",
                    "observed",
                    "Logged local-position validity flag is false; cause is unknown.",
                    invalid,
                )
            if values.get("failsafe") == 1:
                add(
                    sample,
                    "failsafe",
                    "observed",
                    "vehicle_status.failsafe is true; "
                    "trigger and actual vehicle response are unknown.",
                    {"failsafe": 1},
                )
            controls = {
                k: v
                for k, v in values.items()
                if k.startswith("control[")
                and v is not None
                and abs(v) >= thresholds.saturation_abs_min
            }
            if controls:
                add(
                    sample,
                    "control_saturation_candidate",
                    "inferred",
                    "Normalized motor request is near a bound; this does not establish "
                    "controller or physical actuator saturation.",
                    controls,
                )
        else:
            if values.get("tracking_valid") is False:
                add(
                    sample,
                    "tracking_loss",
                    "observed",
                    "Jetson tracking_valid is false.",
                    {"tracking_valid": False},
                )
            elif (
                values.get("line_confidence") is not None
                and values["line_confidence"] < thresholds.line_confidence_min
            ):
                add(
                    sample,
                    "tracking_loss",
                    "inferred",
                    "Low line confidence suggests tracking "
                    "loss; no explicit tracking failure was observed.",
                    {"line_confidence": values["line_confidence"]},
                )
            depth = {k: values[k] for k in ("depth_coverage", "invalid_depth_ratio")}
            if (
                depth["depth_coverage"] is not None
                and depth["depth_coverage"] < thresholds.depth_coverage_min
            ) or (
                depth["invalid_depth_ratio"] is not None
                and depth["invalid_depth_ratio"] > thresholds.invalid_depth_ratio_max
            ):
                add(
                    sample,
                    "depth_hole",
                    "inferred",
                    "Depth quality crossed a review threshold; "
                    "hole geometry and cause are unknown.",
                    depth,
                )
            if values["dropped_frame"]:
                add(
                    sample,
                    "dropped_frame",
                    "observed",
                    "Producer flagged a dropped frame.",
                    {"dropped_frame": True},
                )
            if prior and values["frame_id"] > prior.values["frame_id"] + 1:
                add(
                    sample,
                    "dropped_frame",
                    "inferred",
                    "Frame ID gap; capture loss, producer "
                    "subsampling and logging loss remain possible.",
                    {"previous_frame_id": prior.values["frame_id"], "frame_id": values["frame_id"]},
                )
            if prior and values["frame_id"] <= prior.values["frame_id"]:
                add(
                    sample,
                    "frame_sequence_anomaly",
                    "observed",
                    "Frame ID repeated or decreased.",
                    {"previous_frame_id": prior.values["frame_id"], "frame_id": values["frame_id"]},
                )
            if (
                values["latency_ms"] is not None
                and values["latency_ms"] > thresholds.latency_ms_max
            ):
                add(
                    sample,
                    "latency_spike",
                    "inferred",
                    "Recorded latency exceeds the configured "
                    "review threshold; latency is producer-reported, not independently measured.",
                    {"latency_ms": values["latency_ms"]},
                )
        previous[sample.stream] = sample
    return findings


def _coverage(px4: Ingestion, jetson: Ingestion) -> dict:
    fields = {
        key for sample in px4.samples for key, value in sample.values.items() if value is not None
    }
    jetson_fields = {
        key
        for sample in jetson.samples
        for key, value in sample.values.items()
        if value is not None
    }
    supported = {
        "estimator_invalid": bool(fields & {"xy_valid", "z_valid", "v_xy_valid", "v_z_valid"}),
        "tracking_loss": bool(jetson_fields & {"line_confidence", "tracking_valid"}),
        "depth_hole": bool(jetson_fields & {"depth_coverage", "invalid_depth_ratio"}),
        "dropped_frame": "dropped_frame" in jetson_fields,
        "latency_spike": "latency_ms" in jetson_fields,
        "mode_switch": "mode" in jetson_fields or "nav_state" in fields,
        "failsafe": "failsafe" in fields,
        "control_saturation_candidate": any(key.startswith("control[") for key in fields),
        "timestamp_rollback": any(
            s.timestamp is not None for r in (px4, jetson) for s in r.samples
        ),
    }
    return {
        key: {
            "status": "observed" if value else "unknown",
            "detail": "Usable rule input present; coverage may be partial. No event is not "
            "proof of health."
            if value
            else "Required rule inputs absent or invalid.",
        }
        for key, value in supported.items()
    }


@dataclass(frozen=True)
class Analysis:
    px4: Ingestion
    jetson: Ingestion
    alignment: Alignment
    findings: tuple[Finding, ...]
    thresholds: Thresholds

    @property
    def executed(self) -> bool:
        return False

    def to_dict(self) -> dict:
        sources = {}
        for source in (self.px4, self.jetson):
            sources[source.source] = {
                "path": source.path,
                "sha256": source.sha256,
                "parser": source.parser,
                "samples": len(source.samples),
                "complete": source.complete,
                "metadata": source.metadata,
            }
        findings = []
        for index, finding in enumerate(self.findings, 1):
            item = finding.to_dict()
            item["id"] = f"F{index:04d}"
            item["timestamp_text"] = (
                str(finding.timestamp) if finding.timestamp is not None else None
            )
            item["px4_boot_us_estimate"] = (
                self.alignment.map_jetson(finding.timestamp)
                if finding.source == "jetson" and finding.timestamp is not None
                else None
            )
            findings.append(item)
        samples = []
        for result in (self.px4, self.jetson):
            for sample in result.samples:
                samples.append(
                    {
                        "source": sample.source,
                        "stream": sample.stream,
                        "index": sample.index,
                        "timestamp": sample.timestamp,
                        "clock": sample.clock,
                        "timestamp_text": str(sample.timestamp)
                        if sample.timestamp is not None
                        else None,
                        "values": sample.values,
                        "executed": False,
                        "px4_boot_us_estimate": self.alignment.map_jetson(sample.timestamp)
                        if sample.source == "jetson" and sample.timestamp is not None
                        else None,
                    }
                )
        return {
            "schema_version": 1,
            "tool": "DroneHacks Flight Forensics & Replay Workbench",
            "executed": False,
            "geometry": geometry_boundary(),
            "purpose": "offline_post_flight_evidence_only",
            "validation": "Synthetic fixture tests do not validate real PX4 behavior.",
            "sources": sources,
            "alignment": self.alignment.to_dict(),
            "thresholds": asdict(self.thresholds),
            "coverage": _coverage(self.px4, self.jetson),
            "finding_counts": dict(Counter(f.category for f in self.findings)),
            "knowledge_counts": dict(Counter(f.knowledge for f in self.findings)),
            "findings": findings,
            "samples": samples,
            "limitations": [
                "Observed means recorded in an input, not independently verified flight truth.",
                "Inferred means a threshold or clock model, not a confirmed failure or causality.",
                "Unknown means absent/invalid evidence; missing events do not prove health.",
                "Timestamp decreases may be resets or reordered records; epochs are not guessed.",
                (
                    "Source hashes in Jetson records are producer claims; only input file hashes "
                    "and supplied alignment evidence hashes are computed by this tool."
                ),
                (
                    "Samples remain in source/stream order. Separate clocks must not be compared "
                    "without bounded evidence; physical synchronization is unknown."
                ),
                "No map, coordinates, trajectory, mission, command or future-flight export.",
                (
                    "Local sensing plane only; full_3d_traversability=UNKNOWN. Local depth/width "
                    "and descent geometry do not establish 3D traversability."
                ),
            ],
            "native_clocks": {"px4": PX4_CLOCK, "jetson": "jetson_monotonic_ns"},
        }


def analyze(
    px4_path: Path | None = None,
    jetson_path: Path | None = None,
    alignment_path: Path | None = None,
    thresholds: Thresholds | None = None,
) -> Analysis:
    thresholds = thresholds or Thresholds()
    px4 = ingest_px4(px4_path)
    jetson = ingest_jetson(jetson_path)
    alignment = load_alignment(alignment_path, px4, jetson)
    findings = detect(px4, thresholds) + detect(jetson, thresholds)
    if alignment.status == "unknown":
        findings.append(
            Finding(
                "time_alignment",
                "unknown",
                "alignment",
                "clock",
                None,
                None,
                None,
                alignment.reason,
            )
        )
    return Analysis(px4, jetson, alignment, tuple(findings), thresholds)
