"""Local synthetic / NPZ recording replay. No camera, network or flight I/O."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from .course_config import CourseConfig
from .course_perception import CoursePerception, OfflineFrame
from .course_synthetic import adversarial_suite, suite
from .depth_sectors import Intrinsics, SectorConfig
from .trace import JsonlTraceStore


def load_recording(path: Path, index: int) -> OfflineFrame:
    """One aligned BGR/depth frame per archive; no pickle or inferred timestamps/calibration."""
    with np.load(path, allow_pickle=False) as data:
        values = {key: data[key] for key in data.files}
    depth = values.get("depth_m")
    k = values.get("intrinsics")
    if k is not None and k.shape != (4,):
        raise ValueError("intrinsics must be [fx, fy, cx, cy] for the aligned image")

    def timestamp(key):
        raw = values[key]
        if raw.ndim != 0 or raw.dtype.kind not in "iu":
            raise ValueError(f"{key} must be scalar integer nanoseconds")
        return int(raw.item())

    return OfflineFrame(
        image=values["image"],
        frame_index=index,
        timestamp_ns=timestamp("timestamp_ns"),
        evaluated_at_ns=timestamp("evaluated_at_ns"),
        source_id=f"{path.name}:sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        source_type="recording",
        camera_view=str(values["camera_view"].item()),
        depth_m=depth,
        depth_valid=values.get("depth_valid"),
        depth_timestamp_ns=(
            timestamp("depth_timestamp_ns") if "depth_timestamp_ns" in values else None
        ),
        intrinsics=Intrinsics(*map(float, k)) if k is not None else None,
        calibration_id=str(values["calibration_id"].item()) if "calibration_id" in values else None,
    )


def _write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def run(output: Path, config: CourseConfig, samples: list[OfflineFrame]) -> dict:
    if not samples:
        raise ValueError("replay requires at least one offline frame")
    # Thread count is part of this measurement protocol, not a detector threshold.
    cv2.setNumThreads(1)
    output.mkdir(parents=True, exist_ok=False)
    trace = JsonlTraceStore(output / "trace.jsonl")
    perception = CoursePerception(config)
    rows = []
    for sample in samples:
        evidence = perception.observe(sample)
        trace.write(
            {
                "trace_id": "offline-course-perception",
                "sequence": sample.frame_index,
                "evidence": evidence,
                "control_output": "DISABLED",
                "command_executed": False,
                "executed": False,
            }
        )
        line, landing = evidence["line"], evidence["landing"]
        rows.append(
            {
                "source": sample.source_id,
                "state": evidence["state"],
                "line_detected": line["detected"],
                "line_confidence": line["confidence"],
                "line_geometry_consistent": line["geometry_consistent"],
                "line_rejection_reasons": line["rejection_reasons"],
                "opening_candidates": len(evidence["openings"]),
                "opening_clearance_supported": any(
                    x["clearance"]["supported"] for x in evidence["openings"]
                ),
                "depth_valid": evidence["depth"]["valid"],
                "depth_rejection_reasons": evidence["depth"]["rejection_reasons"],
                "low_light": evidence["low_light"]["detected"],
                "low_light_recovered": evidence["low_light"]["line_recovered"],
                "contrast_gain": evidence["low_light"]["contrast_gain"],
                "width_at_probe_m": evidence["clearance"]["width_at_probe_m"],
                "clearance_supported": evidence["clearance"]["supported"],
                "clearance_scope": evidence["clearance"]["scope"],
                "full_3d_traversability": evidence["clearance"]["full_3d_traversability"],
                "gap_rejection_reasons": evidence["clearance"]["rejection_reasons"],
                "pad_detected": landing["detected"],
                "pad_confidence": landing["confidence"],
                "descent_geometry_suitable": landing["descent_geometry_suitable"],
                "landing_rejection_reasons": landing["rejection_reasons"],
                "processing_ms": evidence["processing_ms"],
            }
        )
    times = [r["processing_ms"] for r in rows]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError):
        head, dirty = "unavailable", None
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in (
            "course_config.py",
            "course_perception.py",
            "course_synthetic.py",
            "course_replay.py",
            "depth_sectors.py",
            "perception.py",
            "domain.py",
            "trace.py",
            "stage_timing.py",
        )
    }
    report = {
        "schema": "aegisland.course-report.v2",
        "sample_count": len(rows),
        "configuration": config.snapshot(),
        "samples": rows,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "opencv_threads": cv2.getNumThreads(),
            "git_head": head,
            "dirty_worktree": dirty,
            "source_sha256": source_hashes,
        },
        "latency_ms": {
            "min": min(times),
            "p50": float(np.percentile(times, 50)),
            "p95": float(np.percentile(times, 95)),
            "max": max(times),
            "scope": "observe: validation through evidence construction; includes "
            "input hashing and stage instrumentation; excludes disk I/O; "
            "single pass including cold first sample; CPU only",
        },
        "control_output": "DISABLED",
        "command_executed": False,
        "executed": False,
        "authority_change": "NONE",
        "capabilities": {
            "window_navigation": "unimplemented",
            "return_navigation": "unimplemented",
            "metric_vio_slam": "not_provided",
        },
        "limitations": [
            "synthetic results are not field detection accuracy",
            "no hardware, Orin, flight or full-route validation",
            "no semantic exit/pad identity or temporal obstacle tracking",
            (
                "clearance is projected at the configured camera-z probe plane; "
                "not a physical gate width or swept 3-D vehicle volume"
            ),
            (
                "landing suitability covers observed geometry/depth only; "
                "motion, gravity alignment and full 3-D vehicle footprint remain unassessed"
            ),
            "window and return stretch goals are not implemented",
        ],
    }
    _write_json(output / "report.json", report)
    _write_json(output / "config.json", config.snapshot()["values"])
    md = [
        "# Offline course perception report",
        "",
        (f"Samples: {len(rows)}. CONTROL OUTPUT=DISABLED; COMMAND EXECUTED=FALSE."),
        "",
        "Heuristic scores are not calibrated probabilities. No real-flight validation.",
        (
            "Gap support means local camera-z plane width only; full 3-D traversability is UNKNOWN. "
            "Authority change=NONE; executed=False. Window/return navigation remain unimplemented."
        ),
        "",
        (
            "| Input | Line / score | Opening / depth-supported | Depth valid | Recovery | "
            "Clearance at probe (m) | Pad / geometry suitable | Rejections (line; gap; landing) |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        width = r["width_at_probe_m"]
        md.append(
            f"| {r['source']} | {r['line_detected']} / {r['line_confidence']:.3f} | "
            f"{r['opening_candidates']} / {r['opening_clearance_supported']} | "
            f"{r['depth_valid']} | {r['low_light_recovered']} | "
            f"{width if width is not None else 'unknown'} | "
            f"{r['pad_detected']} / {r['descent_geometry_suitable']} | "
            f"{', '.join(r['line_rejection_reasons'])}; "
            f"{', '.join(r['gap_rejection_reasons'])}; "
            f"{', '.join(r['landing_rejection_reasons'])} |"
        )
    md.extend(
        [
            "",
            (
                f"CPU observe latency: p50={report['latency_ms']['p50']:.3f} ms, "
                f"p95={report['latency_ms']['p95']:.3f} ms, max={max(times):.3f} ms. "
                "One pass, cold first sample included, no disk I/O. Not an Orin benchmark."
            ),
            "",
        ]
    )
    md.extend(f"- {limit}" for limit in report["limitations"])
    (output / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new local output directory")
    parser.add_argument(
        "--recording", type=Path, nargs="+", help="local aligned-frame NPZ archives"
    )
    parser.add_argument("--config", type=Path, help="JSON CourseConfig values with provenance")
    parser.add_argument(
        "--adversarial", action="store_true", help="append deterministic counterexamples"
    )
    args = parser.parse_args()
    if args.recording and args.adversarial:
        parser.error("--adversarial is for synthetic replay only")
    values = json.loads(args.config.read_text()) if args.config else {}
    if args.config and "provenance" not in values:
        parser.error("custom configuration must include provenance")
    if "depth" in values:
        values["depth"] = SectorConfig(**values["depth"])
    config = CourseConfig(**values)
    samples = (
        [load_recording(path, index) for index, path in enumerate(args.recording)]
        if args.recording
        else suite()
    )
    if args.adversarial:
        samples = [
            replace(sample, frame_index=index)
            for index, sample in enumerate([*samples, *adversarial_suite()])
        ]
    report = run(args.output, config, samples)
    print(
        json.dumps(
            {
                "samples": report["sample_count"],
                "output": str(args.output),
                "control_output": "DISABLED",
                "executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
