"""Auditable bounded clock mapping; never align by start times or signal similarity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .model import Ingestion, integer, sha256, strict_json


@dataclass(frozen=True)
class Alignment:
    status: str = "unknown"
    reason: str = "No paired clock evidence supplied."
    anchors: tuple[dict, ...] = ()
    uncertainty_us: float | None = None
    drift_ppm: float | None = None
    provenance: dict = field(default_factory=dict)

    def map_jetson(self, timestamp_ns: int) -> float | None:
        if self.status != "inferred" or not integer(timestamp_ns):
            return None
        first, last = self.anchors[0], self.anchors[-1]
        if not first["jetson_monotonic_ns"] <= timestamp_ns <= last["jetson_monotonic_ns"]:
            return None  # No extrapolation beyond the evidence interval.
        fraction = (timestamp_ns - first["jetson_monotonic_ns"]) / (
            last["jetson_monotonic_ns"] - first["jetson_monotonic_ns"]
        )
        return first["px4_boot_us"] + fraction * (last["px4_boot_us"] - first["px4_boot_us"])

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "anchors": list(self.anchors),
            "uncertainty_us": self.uncertainty_us,
            "drift_ppm": self.drift_ppm,
            "provenance": self.provenance,
            "extrapolation": False,
            "executed": False,
        }


def has_rollback(result: Ingestion) -> bool:
    previous = {}
    for sample in result.samples:
        if sample.timestamp is None:
            continue
        if sample.stream in previous and sample.timestamp < previous[sample.stream]:
            return True
        previous[sample.stream] = sample.timestamp
    return False


def load_alignment(path: Path | None, px4: Ingestion, jetson: Ingestion) -> Alignment:
    if path is None:
        return Alignment()
    provenance = {"descriptor": str(path)}

    def unknown(reason: str) -> Alignment:
        return Alignment(reason=reason, provenance=provenance)

    try:
        raw = path.read_bytes()
        provenance["descriptor_sha256"] = sha256(raw)
        descriptor = strict_json(raw.decode("utf-8"))
        if not isinstance(descriptor, dict):
            return unknown("Alignment descriptor must be an object.")
        evidence_name = descriptor.get("evidence_file")
        # Preserve the declared evidence location even when other checks fail,
        # so report generation cannot overwrite a rejected evidence input.
        evidence_path = None
        if isinstance(evidence_name, str) and evidence_name:
            evidence_path = (path.parent / evidence_name).resolve()
            provenance["evidence_file"] = str(evidence_path)
        if not px4.samples or not jetson.samples or not px4.complete or not jetson.complete:
            return unknown("Both inputs must contain complete, valid samples for clock mapping.")
        if has_rollback(px4) or has_rollback(jetson):
            return unknown("Timestamp rollback: boot/session association cannot be proved.")
        if (
            type(descriptor.get("schema_version")) is not int
            or descriptor["schema_version"] != 1
            or descriptor.get("executed") is not False
            or descriptor.get("method") != "paired-clock-observation"
        ):
            return unknown("Unsupported alignment schema, method or executed boundary.")
        if descriptor.get("source_hashes") != {"px4": px4.sha256, "jetson": jetson.sha256}:
            return unknown("Clock evidence is not bound to these exact two input hashes.")
        if evidence_path is None:
            return unknown("No clock evidence file.")
        evidence = evidence_path.read_bytes()
        provenance.update(evidence_file=str(evidence_path), evidence_sha256=sha256(evidence))
        if descriptor.get("evidence_sha256") != sha256(evidence):
            return unknown("Clock evidence hash mismatch.")
        anchors = [
            strict_json(line.decode("utf-8")) for line in evidence.splitlines() if line.strip()
        ]
        if len(anchors) < 2:
            return unknown("At least two independently paired clock observations are required.")
        event_ids = set()
        for index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict) or set(anchor) != {
                "event_id",
                "px4_boot_us",
                "jetson_monotonic_ns",
                "uncertainty_us",
            }:
                return unknown("Malformed paired clock observation.")
            event_id = anchor["event_id"]
            if not isinstance(event_id, str) or not event_id or event_id in event_ids:
                return unknown("Clock observation event IDs must be nonempty and unique.")
            event_ids.add(event_id)
            if (
                not all(
                    integer(anchor[key])
                    for key in ("px4_boot_us", "jetson_monotonic_ns", "uncertainty_us")
                )
                or anchor["uncertainty_us"] > 5000
            ):
                return unknown("Invalid clock observation or uncertainty above 5000 us.")
            if index and any(
                anchor[key] <= anchors[index - 1][key]
                for key in ("px4_boot_us", "jetson_monotonic_ns")
            ):
                return unknown("Clock observations must increase in both clock domains.")
        first, last = anchors[0], anchors[-1]
        ratio = (last["px4_boot_us"] - first["px4_boot_us"]) / (
            (last["jetson_monotonic_ns"] - first["jetson_monotonic_ns"]) / 1000
        )
        drift_ppm = (ratio - 1) * 1e6
        if abs(drift_ppm) > 2000:
            return unknown("Clock drift exceeds the supported 2000 ppm bound.")
        uncertainty = max(a["uncertainty_us"] for a in anchors)
        residual = max(
            abs(
                a["px4_boot_us"]
                - first["px4_boot_us"]
                - (a["jetson_monotonic_ns"] - first["jetson_monotonic_ns"]) / 1000 * ratio
            )
            for a in anchors
        )
        if residual + uncertainty > 5000:
            return unknown("Clock residual plus stated uncertainty exceeds 5000 us.")
        # This is a model conditional on supplied observations, not independently
        # verified hardware sync, causality, or proof that a clock never reset.
        return Alignment(
            "inferred",
            "Hash-bound paired observations support interpolation only; "
            "physical synchronization remains unverified.",
            tuple(anchors),
            uncertainty + residual,
            drift_ppm,
            provenance,
        )
    except (OSError, ValueError, UnicodeError, TypeError, OverflowError, RecursionError) as error:
        return unknown(f"Cannot validate clock evidence: {type(error).__name__}: {error}")
