"""nav.line_follow: steering advisory from floor-line dicts. Pure, no ROS, stdlib only.
Pins the sign convention, the bounds and deadbands, and the fail-safe (never steer on an untrusted
line; coast briefly then recommend stop; never emit a command)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nav import line_follow as LF  # noqa: E402


def line(
    offset=0.0,
    lean=0.0,
    detected=True,
    confidence=0.9,
    status="supported",
    fresh=True,
    ambiguous=False,
    reasons=None,
):
    return {
        "schema": "vision.floor_line/1",
        "detected": detected,
        "status": status,
        "confidence": confidence,
        "fresh": fresh,
        "ambiguous": ambiguous,
        "bottom_offset": None if not detected else offset,
        "image_lean_deg": None if not detected else lean,
        "rejection_reasons": reasons
        or ([] if detected else ["insufficient_line_support"]),
    }


def follower(**cfg):
    return LF.LineFollower(LF.FollowConfig(**cfg) if cfg else None)


def test_centred_line_holds_straight():
    out = follower().update(line(offset=0.0, lean=0.0), 0.0)
    assert out["action"] == "steer" and out["steer"] and out["on_line"]
    assert out["lateral_mps"] == 0.0 and out["yaw_rate_dps"] == 0.0


def test_line_to_the_right_steers_right():
    out = follower().update(line(offset=0.5), 0.0)
    assert out["steer"] and out["lateral_mps"] > 0 and not out["on_line"]


def test_line_to_the_left_steers_left():
    out = follower().update(line(offset=-0.5), 0.0)
    assert out["lateral_mps"] < 0


def test_lean_right_yaws_right_and_left_yaws_left():
    assert follower().update(line(lean=20.0), 0.0)["yaw_rate_dps"] > 0
    assert follower().update(line(lean=-20.0), 0.0)["yaw_rate_dps"] < 0


def test_outputs_are_bounded():
    out = follower().update(line(offset=1.0, lean=80.0), 0.0)
    c = LF.FollowConfig()
    assert out["lateral_mps"] == pytest.approx(c.max_lateral_mps)
    assert out["yaw_rate_dps"] == pytest.approx(c.max_yaw_rate_dps)


def test_small_offset_within_deadband_gives_no_nudge():
    out = follower().update(line(offset=0.03, lean=1.0), 0.0)
    assert out["lateral_mps"] == 0.0 and out["yaw_rate_dps"] == 0.0
    assert out["steer"] and out["on_line"]


@pytest.mark.parametrize(
    "bad",
    [
        dict(detected=False),
        dict(detected=False, reasons=["competing_lines"]),
        dict(confidence=0.3),
        dict(status="ambiguous", ambiguous=True),
        dict(fresh=False),
    ],
)
def test_untrusted_line_never_steers(bad):
    out = follower().update(line(**bad), 0.0)
    assert not out["steer"] and out["lateral_mps"] == 0.0 and out["yaw_rate_dps"] == 0.0
    assert out["action"] in ("coast", "stop")


def test_no_line_at_start_recommends_stop_not_coast():
    out = follower().update(line(detected=False), 0.0)
    assert out["action"] == "stop" and "no trusted line yet" in out["reason"]


def test_brief_dropout_coasts_then_long_dropout_stops():
    f = follower(coast_s=0.4, lost_s=1.5)
    assert f.update(line(offset=0.3), 0.0)["steer"]
    coast = f.update(line(detected=False), 0.2)
    assert coast["action"] == "coast" and coast["lateral_mps"] == 0.0
    still = f.update(line(detected=False), 1.0)
    assert still["action"] == "coast"
    lost = f.update(line(detected=False), 2.0)
    assert lost["action"] == "stop" and "recommend stop" in lost["reason"]


def test_recovered_line_resumes_steering_and_resets_timer():
    f = follower()
    f.update(line(offset=0.3), 0.0)
    f.update(line(detected=False), 1.0)
    out = f.update(line(offset=-0.4), 1.2)
    assert out["steer"] and out["lateral_mps"] < 0
    # after recovery a new dropout coasts again (timer reset), not an immediate stop
    assert f.update(line(detected=False), 1.4)["action"] == "coast"


def test_reset_clears_memory():
    f = follower()
    f.update(line(offset=0.3), 0.0)
    f.reset()
    assert f.update(line(detected=False), 0.1)["action"] == "stop"


def test_missing_lean_is_treated_as_zero():
    out = follower().update({**line(offset=0.2), "image_lean_deg": None}, 0.0)
    assert out["steer"] and out["yaw_rate_dps"] == 0.0


def test_output_never_carries_a_command_and_executed_is_false():
    for upd in (line(offset=0.5), line(detected=False)):
        out = follower().update(upd, 0.0)
        assert out["executed"] is False and out["control_output"] == "ADVISORY"
        assert not ({"setpoint", "velocity", "command", "arm"} & set(out))


@pytest.mark.parametrize(
    "cfg",
    [
        dict(min_confidence=1.5),
        dict(max_lateral_mps=-1.0),
        dict(coast_s=2.0, lost_s=1.0),
    ],
)
def test_invalid_config_raises(cfg):
    with pytest.raises(ValueError):
        LF.FollowConfig(**cfg)


def test_end_to_end_real_floor_line_dict_drives_steering():
    """The vision node's own output (not a hand-built dict) must steer the follower: proves the
    floor_line/1 schema the two modules share actually lines up."""
    pytest.importorskip("cv2")
    import numpy as np

    from vision import floor_line as FL

    H, W = 400, 640
    rng = np.random.default_rng(0)
    img = np.full((H, W), 90.0, np.float32)
    img[: int(H * 0.30)] = 130.0
    img += rng.normal(0, 3, img.shape)
    for y in range(int(H * 0.40), H):  # a straight stripe to the right of centre
        cx = int(0.68 * W)
        img[y, cx - 9 : cx + 9] = 200.0
    data = np.clip(np.rint(img), 0, 255).astype(np.uint8).tobytes()

    doc = FL.floor_line_message(
        "mono8", H, W, W, data, 1_000_000_000, 1_000_040_000, "left_optical"
    )
    assert doc["detected"]
    out = LF.LineFollower().update(doc, 1.0)
    assert out["steer"] and out["lateral_mps"] > 0  # line on the right -> nudge right
