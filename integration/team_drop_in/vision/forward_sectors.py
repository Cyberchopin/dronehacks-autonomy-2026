"""Team depth image -> forward obstacle sectors. PURE (numpy only), no ROS import.

Input is exactly what refnav already subscribes to (flight.yaml):
  sensor_msgs/Image on depth_topic   32FC1 metres or 16UC1 millimetres (0 / NaN / <=0 = no return)
  sensor_msgs/CameraInfo             k = [fx, 0, cx, 0, fy, cy, 0, 0, 1]
The image must be in a REP-103 optical frame (x right, y down, z forward) of a FORWARD camera;
this module does not check TF - the ROS node does (same rule as refnav/node.py).

Output is a JSON-ready dict: per azimuth sector the nearest range along the ray (m), whether the
sector was actually observed, and why not. "No return" is UNKNOWN, never free space. Nothing here
produces a velocity, setpoint or command: control_output is always "DISABLED".

The sector maths is vision/depth_sectors.py, copied unchanged from Cyberchopin/dronehacks-autonomy-2026
(see vision/README.md for provenance).
"""
from __future__ import annotations

import math

import numpy as np

from .depth_sectors import Intrinsics, ObstacleReport, SectorConfig, sector_report

SCHEMA = "vision.forward_sectors/1"


def decode_depth(
    encoding: str, height: int, width: int, step: int, data: bytes, is_bigendian: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """sensor_msgs/Image depth -> (z metres float32, valid bool mask).

    Same accepted encodings and invalid-value rules as refnav/depth.py::decode_depth, but returns an
    explicit mask instead of NaN so depth_sectors can tell 'no return' from 'far'. Honours row padding
    (step) and byte order, as the lab's camera lesson requires; the buffer must be exactly step*height."""
    enc = encoding.lower()
    if enc == "32fc1":
        base, scale = "f4", 1.0
    elif enc in ("16uc1", "mono16"):
        base, scale = "u2", 1e-3
    else:
        raise ValueError(f"unsupported depth encoding {encoding!r} (need 32FC1 metres or 16UC1 millimetres)")
    dt = np.dtype((">" if is_bigendian else "<") + base)
    if not (0 < height <= 4096 and 0 < width <= 4096):
        raise ValueError(f"invalid image size {width}x{height}")
    if step < width * dt.itemsize or len(data) != step * height:
        raise ValueError(f"buffer is {len(data)} bytes, expected step*height = {step}*{height} with step >= width*{dt.itemsize}")
    image = np.ndarray((height, width), dtype=dt, buffer=bytes(data), strides=(step, dt.itemsize))
    z = image.astype(np.float32) * np.float32(scale)
    valid = np.isfinite(z) & (z > 0.0)
    z[~valid] = 0.0
    return z, valid


def intrinsics_from_k(k) -> Intrinsics:
    """CameraInfo.k (row-major 3x3) -> Intrinsics. Rejects an uncalibrated (all-zero) or non-finite K."""
    if len(k) != 9:
        raise ValueError("CameraInfo.k must have 9 entries")
    fx, cx, fy, cy = float(k[0]), float(k[2]), float(k[4]), float(k[5])
    if not all(math.isfinite(v) for v in (fx, fy, cx, cy)) or fx <= 0.0 or fy <= 0.0:
        raise ValueError(f"invalid intrinsics fx={fx} fy={fy} cx={cx} cy={cy}")
    return Intrinsics(fx=fx, fy=fy, cx=cx, cy=cy)


def optical_axis_offset_deg(w: float, x: float, y: float, z: float) -> float:
    """Angle (deg) between the camera's optical axis and body forward, from the TF rotation
    base_link <- camera optical frame (quaternion w first). Same test as refnav/node.py."""
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if not math.isfinite(n) or n == 0.0:
        return 180.0
    w, x, y, z = w / n, x / n, y / n, z / n
    # third column of the rotation matrix = optical z axis expressed in the body frame
    fwd = np.array([2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)])
    return math.degrees(math.acos(max(-1.0, min(1.0, float(fwd[0] / np.linalg.norm(fwd))))))


def report_to_dict(report: ObstacleReport, frame_id: str = "") -> dict:
    """ObstacleReport -> plain dict for std_msgs/String JSON. Azimuth: + = right of the optical axis."""
    return {
        "schema": SCHEMA,
        "frame_id": frame_id,
        "stamp_ns": int(report.timestamp_ns),
        "age_ms": round(float(report.age_ms), 1),
        "fresh": bool(report.fresh),
        "frame_valid_fraction": round(float(report.frame_valid_fraction), 3),
        "nearest_m": None if report.nearest_m is None else round(float(report.nearest_m), 3),
        "sectors": [
            {
                "azimuth_deg": [round(float(s.azimuth_deg[0]), 1), round(float(s.azimuth_deg[1]), 1)],
                "nearest_m": None if s.nearest_m is None else round(float(s.nearest_m), 3),
                "valid_fraction": round(float(s.valid_fraction), 3),
                "observed": bool(s.valid),
                "reason": s.reason,
            }
            for s in report.sectors
        ],
        "control_output": report.control_output,
    }


def forward_sectors(
    encoding: str,
    height: int,
    width: int,
    step: int,
    data: bytes,
    k,
    stamp_ns: int,
    now_ns: int,
    frame_id: str = "",
    config: SectorConfig | None = None,
    is_bigendian: bool = False,
) -> dict:
    """One depth message + its CameraInfo.k -> forward-sector dict. Raises ValueError on bad input."""
    z, valid = decode_depth(encoding, height, width, step, data, is_bigendian)
    report = sector_report(z, valid, int(stamp_ns), intrinsics_from_k(k), now_ns=int(now_ns), config=config)
    return report_to_dict(report, frame_id)
