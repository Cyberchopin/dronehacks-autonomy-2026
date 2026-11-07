# nav/ — line-following steering (advisory only)

Turns the floor-line evidence from `vision/floor_line.py` into a bounded steering **advisory**: a
lateral nudge and a yaw-rate that would keep the maze's floor line centred under the forward camera.

It is advice, not control: it issues no setpoint, never arms, and `executed` is always `False`.
Nothing in refnav applies it yet. refnav's own safety — depth stop, estimator health, Offboard
authority — is untouched and still decides whether the aircraft moves at all.

```
/vision/floor_line (vision.floor_line/1)  ->  nav.line_follow.LineFollower.update()  ->  steering advisory
```

## Advisory (`schema: nav.line_follow/1`)

```json
{"schema": "nav.line_follow/1", "action": "steer", "steer": true,
 "lateral_mps": 0.30, "yaw_rate_dps": 8.0, "cross_track_offset": 0.50,
 "heading_lean_deg": 10.0, "on_line": false, "reason": "following line",
 "executed": false, "control_output": "ADVISORY", "authority_change": "NONE"}
```

- `action`: `steer` (trusted line driving the nudge), `coast` (brief dropout — hold heading, no
  nudge) or `stop` (no trusted line yet, or lost longer than `lost_s` — recommend stopping).
- `lateral_mps`: body-right, **+ = move right**; `yaw_rate_dps`: **+ = yaw right**. Both bounded and
  dead-banded.
- `on_line`: trusted line within `centered_offset` of centre.
- Sign rule: a line to the right means the aircraft is left of it, so centring nudges right.

## Fail-safe

A frame that is not `detected`, not `fresh`, low-confidence or `ambiguous` produces **zero steering**
and never counts as centred. The follower never invents a line position from silence. A gap up to
`coast_s` coasts straight; beyond `lost_s` it recommends `stop`. `reset()` clears this between legs.

## How it would wire into refnav (NOT done yet)

refnav flies pre-planned legs and only stops for depth obstacles (`refnav/core.py`); it does not
follow the line. The intended integration keeps `core.py`'s safety intact:

1. A thin adapter subscribes to `/vision/floor_line`, runs `LineFollower`, and offers the advisory.
2. While a leg is flown, the lateral/yaw advisory biases the setpoint **within bounds**, behind the
   same depth-clearance and health gates refnav already enforces.
3. `action == "stop"` is advisory; the depth stop and PX4 authority remain the real stops.

Step 2 edits shared flight code and must be a separate, reviewed change with the team, after this
advisory is validated in the simulator. This module and its tests do not touch `refnav/`.

## Run

```bash
python3 -m pytest -q tests/test_nav_line_follow.py     # offline, stdlib only (+ 1 cv2 end-to-end test)
```

## Closed-loop sanity (`nav/line_follow_sim.py`)

A kinematic offline loop runs the **real** detector and controller together: it renders a straight
floor line as a forward/down camera would see it, detects it, steers, and advances a simple
kinematic model. It is **not** the DroneHacks simulator and not flight dynamics — it checks that the
sign convention is right and the default gains converge rather than diverge.

Result with defaults: from a 0.3-0.5 m lateral offset the loop settles to < 5 cm without
overshooting past the start; a heading error alone stays within ~25 cm; and when the line is
blanked, the follower recommends `stop` ~1.5 s later (= `lost_s`). Run it:
`python3 -m nav.line_follow_sim`.

## Status

29 offline tests pass: 21 on the controller (sign convention, bounds, deadbands, fail-safe, one
end-to-end through `vision/floor_line.py`) and 8 closed-loop convergence/fail-safe checks.
**Not wired into refnav and not run in the DroneHacks simulator.** Gains converge in the kinematic
loop but are still guesses; they need tuning against the real camera and flight response.
