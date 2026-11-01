"""Strict, offline DroneHacks adapter/result contract (version 1)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
ADAPTERS = {
    "aegisland-vdr": {"tracking": True, "metric_pose": False, "unit": "normalized_image"},
    "cuvslam-stereo": {"tracking": True, "metric_pose": True, "unit": "m"},
    "cuvslam-inertial": {"tracking": True, "metric_pose": True, "unit": "m"},
    "oak-depthai-stereo": {"tracking": False, "metric_pose": False, "unit": "depth_m"},
    "ffs-research": {"tracking": False, "metric_pose": False, "unit": "depth_m"},
}


def finite_tree(value):
    """Reject nonstandard constants AND overflow such as JSON 1e999, at any depth."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric value")
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text):
    return finite_tree(json.loads(text, object_pairs_hook=_object))


def read_json(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return value


def timestamps(values):
    previous = -1
    for value in values:
        integer(value, "timestamp_ns")
        if value <= previous:
            raise ValueError("timestamps must be strictly increasing; duplicate timestamp rejected")
        previous = value
    return values


def read_jsonl(path, expected_frames):
    integer(expected_frames, "expected_frames", 1)
    content = Path(path).read_bytes()
    if not content or not content.endswith(b"\n"):
        raise ValueError("truncated JSONL: final newline required")
    rows = [strict_json(line) for line in content.decode("utf-8").splitlines()]
    if len(rows) != expected_frames:
        raise ValueError(f"inconsistent frame count: expected {expected_frames}, got {len(rows)}")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("JSONL frames must be objects")
    timestamps([row["timestamp_ns"] for row in rows])
    return rows


def validate_platform(value):
    if not isinstance(value, dict) or value.get("kind") not in ("desktop", "orin", "other"):
        raise ValueError("platform.kind must explicitly be desktop, orin or other")
    for name in ("hardware", "machine", "device_model"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError(f"platform.{name} must be a nonempty string")
    if value["kind"] == "orin" and (
        value["machine"].lower() not in ("aarch64", "arm64")
        or "orin" not in value["device_model"].lower()
    ):
        raise ValueError("Orin requires aarch64/arm64 and an Orin device model; desktop != Orin")
    if value["kind"] == "desktop" and "orin" in value["device_model"].lower():
        raise ValueError("Orin device cannot be labelled desktop")
    return value


def validate_frames(rows, adapter, expected_frames):
    if adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter: {adapter}")
    integer(expected_frames, "expected_frames", 1)
    if len(rows) != expected_frames:
        raise ValueError("inconsistent frame count")
    finite_tree(rows)
    timestamps([row["timestamp_ns"] for row in rows])
    for row in rows:
        required = {
            "timestamp_ns",
            "status",
            "latency_ms",
            "failure_reason",
            "executed",
            "pose",
            "coverage",
        }
        if not required.issubset(row):
            raise ValueError(f"frame missing required fields: {sorted(required - row.keys())}")
        if row.get("executed") is not False:
            raise ValueError("every frame must have executed=False")
        status = row.get("status")
        if status not in ("ok", "lost", "dropped", "error"):
            raise ValueError("invalid frame status")
        if status == "lost" and not ADAPTERS[adapter]["tracking"]:
            raise ValueError("depth-only adapters cannot report tracking loss")
        reason = row.get("failure_reason")
        if status != "ok" and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("unsuccessful frames require a failure_reason")
        if status == "ok" and reason is not None:
            raise ValueError("ok frame cannot have a failure_reason")
        latency = row.get("latency_ms")
        if status == "dropped":
            if latency is not None or row.get("pose") is not None:
                raise ValueError("dropped frames cannot have latency or pose")
        elif latency is not None:
            number(latency, "latency_ms")
        coverage = row.get("coverage")
        if coverage is not None and number(coverage, "coverage") > 1:
            raise ValueError("coverage must be in [0, 1]")
        normalized = row.get("normalized_xy")
        if normalized is not None:
            if adapter != "aegisland-vdr" or len(normalized) != 2:
                raise ValueError("normalized_xy requires VDR and two components")
            for item in normalized:
                number(item, "normalized_xy", minimum=-float("inf"))
        pose = row.get("pose")
        if pose is not None:
            if not ADAPTERS[adapter]["metric_pose"] or status != "ok":
                raise ValueError("metric pose requires a metric tracking adapter and ok status")
            for key, size in (("position_m", 3), ("quaternion_xyzw", 4)):
                vector = pose[key]
                if not isinstance(vector, list) or len(vector) != size:
                    raise ValueError(f"pose.{key} must have {size} components")
                for item in vector:
                    number(item, key, minimum=-float("inf"))
            if not np.isclose(np.linalg.norm(pose["quaternion_xyzw"]), 1, atol=1e-5):
                raise ValueError("pose quaternion must be normalized")
        if ADAPTERS[adapter]["metric_pose"] and status == "ok" and pose is None:
            raise ValueError("metric tracking ok frame requires pose")
    return rows


def percentiles(values):
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None}
    return {
        "count": len(values),
        **{f"p{p}": float(np.percentile(values, p, method="linear")) for p in (50, 95, 99)},
    }


def summarize(rows, adapter, warmup_frames=1, wall_s=None):
    """Warmup uses attempted (non-dropped) frame indices, including untimed attempts."""
    validate_frames(rows, adapter, len(rows))
    integer(warmup_frames, "warmup_frames")
    attempts = [r for r in rows if r["status"] != "dropped"]
    cold = [r["latency_ms"] for r in attempts[:warmup_frames] if r.get("latency_ms") is not None]
    warm = [r["latency_ms"] for r in attempts[warmup_frames:] if r.get("latency_ms") is not None]
    if wall_s is not None:
        number(wall_s, "wall_s")
    dropped = sum(r["status"] == "dropped" for r in rows)
    ok = sum(r["status"] == "ok" for r in rows)
    # Startup invalid frames are distinct from loss AFTER acquiring tracking.
    acquired, start, episodes = False, None, []
    for row in rows:
        if row["status"] == "ok":
            if start is not None:
                episodes.append(
                    {
                        "start_ns": start,
                        "recovered_ns": row["timestamp_ns"],
                        "recovery_ms": (row["timestamp_ns"] - start) / 1e6,
                    }
                )
                start = None
            acquired = True
        elif acquired and start is None:
            start = row["timestamp_ns"]
    if start is not None:
        episodes.append({"start_ns": start, "recovered_ns": None, "recovery_ms": None})
    coverage = [r["coverage"] for r in rows if r.get("coverage") is not None]
    return {
        "counts": {
            "expected": len(rows),
            "attempted": len(attempts),
            "ok": ok,
            "lost": sum(r["status"] == "lost" for r in rows),
            "dropped": dropped,
            "error": sum(r["status"] == "error" for r in rows),
        },
        "latency_ms": {
            "cold": percentiles(cold),
            "warm": percentiles(warm),
            "untimed_attempts": sum(r.get("latency_ms") is None for r in attempts),
        },
        "fps": {
            "attempted_wall": len(attempts) / wall_s if wall_s else None,
            "successful_wall": ok / wall_s if wall_s else None,
            "wall_s": wall_s,
        },
        "drop_rate": dropped / len(rows),
        "coverage": {
            "successful_frame_fraction": ok / len(rows),
            "mean_valid_pixel_fraction": float(np.mean(coverage)) if coverage else None,
            "pixel_samples": len(coverage),
        },
        "tracking": {
            "available": ADAPTERS[adapter]["tracking"],
            "loss_episodes": episodes if ADAPTERS[adapter]["tracking"] else None,
            "recovery_ms": percentiles(
                [e["recovery_ms"] for e in episodes if e["recovery_ms"] is not None]
            )
            if ADAPTERS[adapter]["tracking"]
            else None,
        },
    }
