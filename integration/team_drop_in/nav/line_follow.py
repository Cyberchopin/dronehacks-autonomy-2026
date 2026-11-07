"""Line-following steering from floor-line evidence. PURE (stdlib only), no ROS, no clock reads.

Consumes the JSON that vision/floor_line.py publishes on /vision/floor_line and turns it into a
bounded STEERING ADVISORY: a lateral nudge (body-right, m/s) and a yaw-rate (deg/s) that would keep
the maze's floor line centred under a forward camera. It is advice, not a command: it issues no
setpoint, never arms, and `executed` is always False. A gated adapter in the flight code decides
whether to apply it, and refnav's own safety (depth stop, health, authority) is unchanged.

Sign convention (matches vision/floor_line.py):
  bottom_offset  -1 line at left edge .. 0 centred .. +1 right edge  (line position at the image bottom)
  image_lean_deg + = line leans right going away from the camera
A line to the right means the aircraft is left of it, so centring asks for a move/turn to the RIGHT:
lateral_mps and yaw_rate_dps take the sign of the offset / lean.

Fail safe: a frame that is not detected, not fresh, low-confidence or ambiguous produces ZERO
steering and does not count as "centred". Brief gaps coast straight (hold heading); a gap longer
than lost_s recommends stopping. The module never invents a line position from silence.
"""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA = "nav.line_follow/1"


@dataclass(frozen=True)
class FollowConfig:
    lateral_gain_mps: float = 0.6       # body-right m/s per unit bottom_offset (offset is -1..1)
    yaw_gain_dps: float = 0.8           # deg/s of yaw per deg of image lean
    max_lateral_mps: float = 0.4
    max_yaw_rate_dps: float = 25.0
    offset_deadband: float = 0.05       # |offset| below this: treat as centred, no lateral nudge
    lean_deadband_deg: float = 3.0      # |lean| below this: no yaw correction
    min_confidence: float = 0.55        # below this the line is not trusted for steering
    coast_s: float = 0.4                # a shorter gap: keep the last heading, no nudge
    lost_s: float = 1.5                 # a longer gap with no trusted line: recommend stop
    centered_offset: float = 0.12       # |offset| below this AND trusted: "on the line"

    def __post_init__(self):
        if self.max_lateral_mps < 0 or self.max_yaw_rate_dps < 0:
            raise ValueError("limits must be non-negative")
        if not 0 < self.min_confidence <= 1:
            raise ValueError("min_confidence must be in (0, 1]")
        if self.lost_s < self.coast_s:
            raise ValueError("lost_s must be >= coast_s")


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _deadband(value: float, width: float) -> float:
    return 0.0 if abs(value) < width else value


class LineFollower:
    """Stateful only for the last-trusted-line time, so a brief dropout coasts and a long one stops.
    One instance per leg/run; call reset() between legs."""

    def __init__(self, config: FollowConfig | None = None):
        self.c = config or FollowConfig()
        self.reset()

    def reset(self) -> None:
        self._last_trusted_t: float | None = None
        self._last_offset = 0.0
        self._last_lean = 0.0

    def _trusted(self, line: dict) -> bool:
        return bool(
            line.get("detected")
            and line.get("fresh", True)
            and line.get("status") == "supported"
            and not line.get("ambiguous", False)
            and float(line.get("confidence", 0.0)) >= self.c.min_confidence
            and line.get("bottom_offset") is not None
        )

    def update(self, line: dict, now_s: float) -> dict:
        """line: a vision.floor_line/1 dict (or compatible). now_s: time on the caller's clock.
        Returns a steering advisory dict. Pure given its inputs and this instance's state."""
        c = self.c
        now_s = float(now_s)
        trusted = self._trusted(line)
        if trusted:
            offset = float(line["bottom_offset"])
            lean = float(line.get("image_lean_deg") or 0.0)
            self._last_trusted_t = now_s
            self._last_offset, self._last_lean = offset, lean
            lateral = _clamp(_deadband(offset, c.offset_deadband) * c.lateral_gain_mps, c.max_lateral_mps)
            yaw = _clamp(_deadband(lean, c.lean_deadband_deg) * c.yaw_gain_dps, c.max_yaw_rate_dps)
            centered = abs(offset) < c.centered_offset
            return self._out("steer", True, lateral, yaw, offset, lean, centered,
                             "following line" if not centered else "centred on line")

        # Not trusted this frame: decide coast vs stop by how long since a trusted line.
        if self._last_trusted_t is None:
            return self._out("stop", False, 0.0, 0.0, None, None, False,
                             "no trusted line yet: " + self._why(line))
        gap = now_s - self._last_trusted_t
        if gap <= c.coast_s:
            return self._out("coast", False, 0.0, 0.0, self._last_offset, self._last_lean, False,
                             f"line dropped {gap:.2f}s: holding heading")
        if gap <= c.lost_s:
            return self._out("coast", False, 0.0, 0.0, self._last_offset, self._last_lean, False,
                             f"line gone {gap:.2f}s: holding, will stop at {c.lost_s:g}s")
        return self._out("stop", False, 0.0, 0.0, None, None, False,
                         f"line lost for {gap:.2f}s (> lost_s {c.lost_s:g}s): recommend stop")

    def _why(self, line: dict) -> str:
        if not line.get("detected"):
            reasons = line.get("rejection_reasons") or []
            return "no line detected" + (f" ({reasons[0]})" if reasons else "")
        if not line.get("fresh", True):
            return "line frame stale"
        if line.get("ambiguous"):
            return "line ambiguous"
        return f"line confidence {float(line.get('confidence', 0.0)):.2f} below {self.c.min_confidence:g}"

    def _out(self, action, steer, lateral, yaw, offset, lean, centered, reason) -> dict:
        return {
            "schema": SCHEMA,
            "action": action,                 # "steer" | "coast" | "stop"
            "steer": bool(steer),             # True only when a trusted line is driving the nudge
            "lateral_mps": round(float(lateral), 4),   # body-right; + = move right
            "yaw_rate_dps": round(float(yaw), 3),      # + = yaw right
            "cross_track_offset": None if offset is None else round(float(offset), 4),
            "heading_lean_deg": None if lean is None else round(float(lean), 2),
            "on_line": bool(centered),
            "reason": reason,
            "executed": False,
            "control_output": "ADVISORY",
            "authority_change": "NONE",
        }
