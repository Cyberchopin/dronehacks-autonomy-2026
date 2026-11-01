"""Deterministic synthetic sensor recordings. No capture or vendor runtime."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .integration import STREAMS
from .model import sha256
from .recorder import json_bytes


def frame_bytes() -> bytes:
    import numpy as np

    arrays = {
        "rgb": np.arange(48, dtype=np.uint8).reshape(4, 4, 3),
        "depth_m": np.full((4, 4), 2.0, dtype="<f4"),
        "valid": np.ones((4, 4), dtype=bool),
    }
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, array in arrays.items():
            payload = io.BytesIO()
            np.lib.format.write_array(payload, array, allow_pickle=False)
            item = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o600 << 16
            archive.writestr(item, payload.getvalue())
    return result.getvalue()


def bundle_payloads(scenario: str = "consistent") -> dict[str, bytes]:
    if scenario not in {"consistent", "adverse"}:
        raise ValueError("Synthetic scenario must be consistent or adverse")
    asset = frame_bytes()
    schedule = [{"frame_id": i, "timestamp_ns": 1_000_000_000 + i * 50_000_000} for i in range(3)]
    streams = {
        name: {
            "clock_domain": "replay",
            "schedule": schedule,
            "calibration_id": "oak-c1" if name == "oak_rgb_depth" else "tof-c1",
            "transform_id": "oak-to-body" if name == "oak_rgb_depth" else "tof-to-body",
        }
        for name in STREAMS
    }
    manifest = {
        "schema": "dronehacks.integration-replay.v1",
        "executed": False,
        "authority": "NONE",
        "source_type": "synthetic",
        "origin_environment": "replay",
        "streams": streams,
        "calibrations": {
            "oak-c1": {
                "sensor": "oak_rgb_depth",
                "width": 4,
                "height": 4,
                "intrinsics": [4.0, 4.0, 1.5, 1.5],
                "unit": "m",
                "depth_semantics": "optical_axis_z",
                "provenance": "synthetic",
            },
            "tof-c1": {"sensor": "vl53l1x_downward", "unit": "m", "provenance": "synthetic"},
        },
        "transforms": {
            name: {
                "parent": "body_frd",
                "child": child,
                "translation_m": [0.0, 0.0, 0.0],
                "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
                "convention": "parent_from_child",
                "calibration_id": cid,
                "provenance": "synthetic",
            }
            for name, child, cid in (
                ("oak-to-body", "oak_optical", "oak-c1"),
                ("tof-to-body", "tof_optical", "tof-c1"),
            )
        },
        "clock_pairs": [],
    }
    rows = []
    for slot in schedule:
        for stream in STREAMS:
            row = {
                "schema_version": 1,
                "stream": stream,
                **slot,
                "clock_domain": "replay",
                "evaluated_at_ns": slot["timestamp_ns"] + 10_000_000,
                "evaluation_clock_domain": "replay",
                "calibration_id": None,
                "transform_id": None,
                "executed": False,
            }
            if stream == "oak_rgb_depth":
                row.update(calibration_id="oak-c1", transform_id="oak-to-body")
                data = {
                    "asset": "frames/frame.npz",
                    "sha256": sha256(asset),
                    "encoding": "RGB8",
                    "camera_view": "downward",
                    "comparison_target": "synthetic-coincident-plane",
                }
            elif stream == "px4_telemetry":
                data = {
                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                    "attitude_frame": "ned_from_frd",
                    "battery_voltage_v": 12.0,
                    "local_position_valid": True,
                    "failsafe": False,
                    "nav_state": 3,
                }
            elif stream == "vl53l1x_downward":
                row.update(calibration_id="tof-c1", transform_id="tof-to-body")
                data = {
                    "range_m": 2.0,
                    "range_status": "valid",
                    "sigma_m": 0.02,
                    "mount": "downward",
                    "comparison_target": "synthetic-coincident-plane",
                }
            else:
                row.update(calibration_id="oak-c1", transform_id="oak-to-body")
                data = {
                    "source_frame_id": slot["frame_id"],
                    "source_frame_sha256": sha256(asset),
                    "configuration_sha256": sha256(b"synthetic-config-only"),
                    "state": "line_supported",
                    "confidence": 0.9,
                    "rejection_reasons": [],
                    "advisory_only": True,
                    "control_output": "DISABLED",
                    "command_executed": False,
                    "authority_change": "NONE",
                    "local_sensing_planes": [],
                }
            row["data"] = data
            rows.append(row)
    if scenario == "adverse":
        rows[0]["evaluated_at_ns"] += 500_000_000
        rows[6]["data"]["range_m"] = 4.0
        rows[8]["calibration_id"] = "wrong-calibration"
        rows.pop()  # Missing scheduled advisory slot is detectable, including whole-line truncation.
        rows[1], rows[5] = rows[5], rows[1]
        manifest["clock_pairs"] = [
            {
                "source_clock": "oak_device",
                "target_clock": "jetson_monotonic",
                "source_ns": 1_000_000_000,
                "target_ns": 9_000_000_000,
                "uncertainty_ns": 10,
            },
            {
                "source_clock": "oak_device",
                "target_clock": "jetson_monotonic",
                "source_ns": 2_000_000_000,
                "target_ns": 10_010_000_000,
                "uncertainty_ns": 10,
            },
        ]
    return {
        "manifest.json": json_bytes(manifest),
        "frames/frame.npz": asset,
        "records.jsonl": (
            "\n".join(json.dumps(row, sort_keys=True, allow_nan=False) for row in rows) + "\n"
        ).encode(),
    }


def write_bundle(output: Path, scenario: str = "consistent") -> None:
    payloads = bundle_payloads(scenario)
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(payload)
