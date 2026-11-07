"""vision.forward_sectors without ROS: synthetic depth messages in the exact sensor_msgs/Image byte
layout (encoding, step padding, byte order). Pins the rules that matter to a consumer:
no return is UNKNOWN (never clear), stale frames are flagged, bad input raises, and the module
never produces a control output."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import forward_sectors as F  # noqa: E402

W, H, FX = 160, 100, 106.0  # same small camera as tests/test_refnav_core.py
K = [FX, 0.0, W / 2, 0.0, FX, H / 2, 0.0, 0.0, 1.0]
NOW = 10_000_000_000  # 10 s simulation time
FRESH = NOW - 50_000_000  # 50 ms old


def msg_16uc1(z_m, pad=0, big=False):
    mm = np.where(np.isfinite(z_m), np.round(z_m * 1000.0), 0).astype(np.uint16)
    dt = np.dtype(">u2" if big else "<u2")
    rows = np.zeros((z_m.shape[0], z_m.shape[1] + pad), dtype=dt)
    rows[:, : z_m.shape[1]] = mm
    return "16UC1", z_m.shape[0], z_m.shape[1], rows.shape[1] * 2, rows.tobytes(), big


def msg_32fc1(z_m, pad=0):
    rows = np.zeros((z_m.shape[0], z_m.shape[1] + pad), dtype="<f4")
    rows[:, : z_m.shape[1]] = z_m
    return "32FC1", z_m.shape[0], z_m.shape[1], rows.shape[1] * 4, rows.tobytes(), False


def run(msg, stamp=FRESH, k=K):
    enc, h, w, step, data, big = msg
    return F.forward_sectors(
        enc, h, w, step, data, k, stamp, NOW, "camera_depth_optical", is_bigendian=big
    )


def wall(z):
    return np.full((H, W), z, dtype=np.float32)


def observed(doc):
    return [s for s in doc["sectors"] if s["observed"]]


def test_flat_wall_two_metres_ahead():
    doc = run(msg_16uc1(wall(2.0)))
    assert doc["schema"] == F.SCHEMA and doc["fresh"] is True
    assert len(observed(doc)) == len(doc["sectors"]) == 7
    centre = doc["sectors"][3]
    assert centre["nearest_m"] == pytest.approx(2.0, abs=0.02)
    # range is along the ray: edge sectors see the same plane farther away, never nearer
    assert doc["sectors"][0]["nearest_m"] > centre["nearest_m"]
    assert doc["nearest_m"] == pytest.approx(2.0, abs=0.02)


def test_32fc1_with_row_padding_matches_16uc1():
    a = run(msg_16uc1(wall(3.0)))
    b = run(msg_32fc1(wall(3.0), pad=7))
    for sa, sb in zip(a["sectors"], b["sectors"]):
        assert sa["nearest_m"] == pytest.approx(sb["nearest_m"], abs=0.01)


def test_big_endian_bytes_decode_the_same():
    little = run(msg_16uc1(wall(1.5)))
    big = run(msg_16uc1(wall(1.5), big=True))
    assert little["sectors"] == big["sectors"]


@pytest.mark.parametrize("make", [lambda: msg_16uc1(wall(0.0)), lambda: msg_32fc1(wall(np.nan))])
def test_no_return_is_unknown_not_clear(make):
    doc = run(make())
    assert observed(doc) == []
    assert doc["nearest_m"] is None
    assert all(s["reason"] == "too few valid depth pixels" for s in doc["sectors"])


def test_obstacle_on_the_right_only():
    z = wall(5.0)
    z[:, W // 2 + 10 :] = 1.0  # optical x right: right half of the image
    doc = run(msg_16uc1(z))
    left, right = doc["sectors"][0], doc["sectors"][-1]
    assert left["azimuth_deg"][1] < 0 < right["azimuth_deg"][0]  # + azimuth = right
    assert right["nearest_m"] < 1.5 < 4.0 < left["nearest_m"]


def test_far_beyond_max_range_is_observed_clear_with_no_number():
    doc = run(msg_32fc1(wall(25.0)))
    assert all(s["observed"] and s["nearest_m"] is None for s in doc["sectors"])
    assert all("clear to max range" in s["reason"] for s in doc["sectors"])


def test_inside_blind_zone_is_not_observed():
    doc = run(msg_32fc1(wall(0.1)))  # closer than SectorConfig.min_range_m (0.2 m)
    assert observed(doc) == []
    assert all("blind zone" in s["reason"] for s in doc["sectors"])


def test_stale_frame_is_flagged():
    doc = run(msg_16uc1(wall(2.0)), stamp=NOW - 500_000_000)  # 500 ms old > 200 ms limit
    assert doc["fresh"] is False and doc["age_ms"] == pytest.approx(500.0)


@pytest.mark.parametrize(
    "bad",
    [
        ("rgb8", H, W, W * 3, bytes(H * W * 3), False),  # not depth
        ("16UC1", H, W, W * 2, bytes(H * W * 2 - 2), False),  # short buffer
        (
            "16UC1",
            H,
            W,
            W * 2 - 2,
            bytes(H * (W * 2 - 2)),
            False,
        ),  # row shorter than width
        ("32FC1", 0, W, W * 4, b"", False),  # empty
    ],
)
def test_malformed_images_raise(bad):
    with pytest.raises(ValueError):
        run(bad)


@pytest.mark.parametrize("k", [[0.0] * 9, [math.nan, 0, 80, 0, 106, 50, 0, 0, 1], [106, 0, 80]])
def test_uncalibrated_or_invalid_k_raises(k):
    with pytest.raises(ValueError):
        run(msg_16uc1(wall(2.0)), k=k)


def test_output_is_strict_json_and_never_a_command():
    for msg in (msg_16uc1(wall(2.0)), msg_32fc1(wall(np.nan)), msg_32fc1(wall(25.0))):
        doc = run(msg)
        json.dumps(doc, allow_nan=False)  # no NaN/inf leaks into the topic
        assert doc["control_output"] == "DISABLED"
        assert not ({"setpoint", "velocity", "command"} & set(doc))


def _mat_to_quat(R):
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return w, x, y, z


def test_forward_camera_check_matches_refnav_convention():
    forward = np.array([[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])  # FLU <- optical
    down = np.array([[0.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, -1.0]])  # optical z = body down
    assert F.optical_axis_offset_deg(*_mat_to_quat(forward)) == pytest.approx(0.0, abs=1e-6)
    assert F.optical_axis_offset_deg(*_mat_to_quat(down)) == pytest.approx(90.0, abs=1e-6)
    assert F.optical_axis_offset_deg(0.0, 0.0, 0.0, 0.0) == 180.0  # invalid TF fails closed
