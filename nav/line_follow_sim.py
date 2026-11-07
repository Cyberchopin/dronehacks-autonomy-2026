"""Offline closed-loop check for the perception -> steering chain. PURE (numpy + OpenCV), no ROS.

This is NOT the DroneHacks simulator and NOT a flight dynamics model. It is a kinematic sanity loop
that answers one question before we ever touch the real sim: do vision/floor_line (the real
detector) and nav/line_follow (the real controller), wired together, actually pull a drone back
onto a straight floor line, with the sign convention right and the default gains stable?

Each step:
  1. render the floor line into a mono image as a forward/down camera would see it, given the
     drone's lateral offset y (metres, + = right of the line) and heading error psi (rad, + = nose
     right of the line direction);
  2. run the REAL floor_line detector on that image;
  3. run the REAL LineFollower on its output;
  4. advance a simple kinematic model with the advisory's lateral_mps and yaw_rate_dps.

Assumptions are deliberately crude and documented; treat the result as "the loop converges / the
signs are right / these gains don't blow up", never as proof of real flight. The image mapping is a
small-angle pinhole approximation (see render_line). Replace this with the DroneHacks sim for real
evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from vision.floor_line import LineConfig, floor_line_message
from nav.line_follow import FollowConfig, LineFollower


@dataclass(frozen=True)
class SimConfig:
    width: int = 640
    height: int = 400
    forward_mps: float = 0.6            # constant forward speed along the heading
    dt: float = 0.1                     # 10 Hz, close to the 15 Hz depth/stereo rate
    steps: int = 120
    # image mapping gains (normalized-image units per metre / per radian); small-angle approximation
    offset_per_m: float = 0.6           # bottom_offset moves this much per metre of lateral error
    lean_per_rad: float = 0.9           # top-of-line shift per radian of heading error
    line_value: int = 205
    floor_value: int = 90
    wall_value: int = 130
    noise_std: float = 2.0
    max_offset_clip: float = 0.95       # line that would fall off-image saturates at the edge

    def __post_init__(self):
        if self.dt <= 0 or self.steps <= 0:
            raise ValueError("dt and steps must be positive")


def render_line(y_m: float, psi_rad: float, sc: SimConfig, rng: np.random.Generator) -> bytes:
    """Mono image (mono8 bytes) of a straight floor line seen by the forward/down camera.

    y_m > 0 (drone right of the line) puts the line to the LEFT in the image (negative bottom
    offset); psi_rad > 0 (nose right) makes the line's far end swing LEFT (negative lean). This is
    the sign chain line_follow must close into negative feedback."""
    w, h = sc.width, sc.height
    img = np.full((h, w), sc.floor_value, np.float32)
    img[: int(h * 0.30)] = sc.wall_value
    # normalized bottom position of the line: centre 0.5, minus the lateral error mapping
    x_bottom = 0.5 - sc.offset_per_m * y_m
    x_top = x_bottom - sc.lean_per_rad * psi_rad
    x_bottom = min(1 - 0.01, max(0.01, x_bottom))
    x_top = min(1 - 0.01, max(0.01, x_top))
    y0 = int(h * 0.40)
    half = 9
    for row in range(y0, h):
        t = (h - 1 - row) / (h - 1 - y0)            # 0 at bottom, 1 at the top of the ROI
        cx = (x_bottom + (x_top - x_bottom) * t) * w
        lo = max(0, int(cx - half))
        hi = min(w, int(cx + half))
        if hi > lo:
            img[row, lo:hi] = sc.line_value
    img += rng.normal(0, sc.noise_std, img.shape)
    return np.clip(np.rint(img), 0, 255).astype(np.uint8).tobytes()


def run(y0_m: float, psi0_rad: float, *, sim: SimConfig | None = None,
        follow: FollowConfig | None = None, line_cfg: LineConfig | None = None,
        blank_from: int | None = None, seed: int = 0) -> dict:
    """Fly the kinematic loop from an initial (y0, psi0). If blank_from is set, from that step the
    camera sees no line (floor only), to exercise the follower's lost-line fail-safe.

    Returns a trace dict: per-step y, psi, detected, action, lateral, yaw; plus summary fields."""
    sc = sim or SimConfig()
    rng = np.random.default_rng(seed)
    follower = LineFollower(follow)
    y, psi = float(y0_m), float(psi0_rad)
    t = 0.0
    ys, psis, actions, detected = [], [], [], []
    stamp = 1_000_000_000
    for i in range(sc.steps):
        if blank_from is not None and i >= blank_from:
            img = np.clip(np.rint(np.full((sc.height, sc.width), sc.floor_value, np.float32)
                                  + rng.normal(0, sc.noise_std, (sc.height, sc.width))), 0, 255
                          ).astype(np.uint8).tobytes()
        else:
            img = render_line(y, psi, sc, rng)
        stamp += int(sc.dt * 1e9)
        doc = floor_line_message("mono8", sc.height, sc.width, sc.width, img, stamp, stamp,
                                 "left_optical", line_cfg)
        adv = follower.update(doc, t)
        ys.append(y)
        psis.append(psi)
        detected.append(bool(doc["detected"]))
        actions.append(adv["action"])
        # kinematics: forward along heading + commanded body-right; yaw by the commanded rate
        lateral = adv["lateral_mps"]
        yaw_rate = math.radians(adv["yaw_rate_dps"])
        y += (sc.forward_mps * math.sin(psi) + lateral * math.cos(psi)) * sc.dt
        psi += yaw_rate * sc.dt
        t += sc.dt
    tail = slice(max(0, sc.steps - 20), sc.steps)
    return {
        "y": ys, "psi": psis, "action": actions, "detected": detected,
        "y_final_abs": abs(ys[-1]), "psi_final_abs_deg": abs(math.degrees(psis[-1])),
        "y_tail_max_abs": max(abs(v) for v in ys[tail]),
        "converged": abs(ys[-1]) < abs(y0_m) * 0.5 + 0.05,
        "stopped": "stop" in actions,
        "first_stop_step": actions.index("stop") if "stop" in actions else None,
    }


if __name__ == "__main__":  # quick manual look
    for y0 in (0.3, -0.4):
        r = run(y0, 0.0)
        print(f"y0={y0:+.2f} -> y_final={r['y'][-1]:+.3f} converged={r['converged']} "
              f"tail_max={r['y_tail_max_abs']:.3f}")
    r = run(0.2, 0.0, blank_from=30)
    print(f"blank@30 -> first_stop_step={r['first_stop_step']} stopped={r['stopped']}")
