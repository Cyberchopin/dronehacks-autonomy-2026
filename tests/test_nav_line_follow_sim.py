"""Closed-loop sanity for the perception->steering chain (nav.line_follow_sim). Kinematic, offline,
with the REAL detector and controller in the loop. Not the DroneHacks sim; proves sign convention,
convergence and the lost-line fail-safe, not flight behaviour."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nav.line_follow_sim import SimConfig, run  # noqa: E402


@pytest.mark.parametrize("y0", [0.3, -0.3, 0.5, -0.5])
def test_converges_from_lateral_offset(y0):
    r = run(y0, 0.0)
    assert r["converged"]  # final offset at least halved
    assert r["y_final_abs"] < 0.1  # ends near the line (< 10 cm)
    assert r["y_tail_max_abs"] <= abs(y0)  # never diverges past the start


def test_converges_from_heading_error():
    r = run(0.0, 0.35)  # ~20 deg nose off, on the line
    assert r["y_tail_max_abs"] < 0.25  # heading error doesn't throw it far off
    assert r["y_final_abs"] < 0.1


def test_signs_are_negative_feedback_not_runaway():
    # a wrong sign would grow the offset; assert it shrinks overall
    r = run(0.4, 0.0)
    assert r["y_final_abs"] < 0.4 * 0.5


def test_lost_line_triggers_stop_near_lost_s():
    sc = SimConfig()
    r = run(0.2, 0.0, blank_from=30)
    assert r["stopped"]
    # stop should land ~lost_s after the line disappears (default lost_s = 1.5 s, dt = 0.1 s)
    expected = 30 + round(1.5 / sc.dt)
    assert abs(r["first_stop_step"] - expected) <= 2


def test_line_present_never_stops():
    r = run(0.3, 0.0)
    assert not r["stopped"] and r["action"][-1] in ("steer", "coast")
