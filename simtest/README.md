# simtest/ — course box-world renderer (offline test tool)

Renders paired **depth + mono** camera frames from the published course geometry so
`vision/forward_sectors` (and, as a smoke test, `vision/floor_line`) can be exercised against the
real layout while the DroneHacks simulator is unavailable.

It is a coarse **box world**, not the simulator and not photorealistic: walls, boulders, the tunnel
and the net are their axis-aligned bounding boxes; the floor is a plane; pad rings are circles.
Results mean "the depth geometry and the sector logic behave sensibly in the real layout", never
flight evidence.

## Use

```python
from simtest.course_render import world_from_layout, Camera, RenderConfig, render, load_layout
world = world_from_layout(load_layout("course/layout.json"))   # Codex's extracted layout
depth_z, valid, mono, (fx, fy, cx, cy) = render(world, Camera(pos=(-2.3, 1.1, 1.0), yaw_deg=90))
```

`render` returns depth as 32FC1 metres (z along the optical axis, NaN = no return), a validity
mask, a mono8 image, and the pinhole `K` — exactly the message layout the vision code consumes.

Tests: `python3 -m pytest -q simtest/tests/test_course_render.py` (synthetic worlds; no dependency
on `course/layout.json`).

## What it validated

- Depth geometry/units are correct: a wall at 3 m reads 3.0 m at the image centre and slightly
  farther at the edges (range is along the ray). Distance scales with wall position.
- Loading the real `course/layout.json` renders 23 boxes + 4 pad rings; `forward_sectors` returns
  sensible per-direction distances along the corridors (e.g. a divider 0.4 m to one side reads as a
  near return on that side while the lane ahead reads 1.3-2.0 m).

## Findings worth carrying forward

- **The floor reads as an obstacle when the camera is level.** `vision/forward_sectors` does not
  level by vehicle attitude (unlike `refnav/depth.py`, which rotates into a level frame), so the
  lower part of a level view hits the floor at ~0.8/sin(15 deg) ~= 3 m and is reported as the
  nearest return. For real use, either feed attitude and restrict the band to the horizon, or tilt
  the camera/ROI above the floor. Captured in
  `test_level_camera_sees_the_floor_as_nearest_in_the_lower_band`.

## Limits

- AABB geometry only: a wall-with-a-window renders as solid (the opening is not in the layout AABB),
  and the maze guide line's PATH is not in the AABB data, so this renderer does not reproduce the
  line. When `course/passages.json` / `course/floor_markings.json` exist (real mesh openings and the
  guideline polyline), feed those to lift both limits and to test `floor_line` on the real line.
- No materials/lighting/stereo-matching model; mono shading is schematic. Not a latency or rate model.
