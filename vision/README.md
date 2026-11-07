# vision/ — forward depth sectors (observer only)

Reads the same depth image refnav uses and publishes, for each forward direction, how far the
nearest obstacle is. It is **perception only**: no PX4 publisher, no vehicle command, no arming,
mode or parameter client. refnav does not read its output yet.

```
/camera/depth/image_raw  (sensor_msgs/Image, 16UC1 mm or 32FC1 m)  ─┐
/camera/depth/camera_info (sensor_msgs/CameraInfo)                  ├─> vision.node ─> /vision/forward_sectors
TF base_link <- depth optical frame (must face forward, ≤25°)       ─┘                  (std_msgs/String JSON)
```

## Output (`schema: vision.forward_sectors/1`)

```json
{"schema": "vision.forward_sectors/1", "frame_id": "...", "stamp_ns": 0, "age_ms": 48.0,
 "fresh": true, "leveled": false, "frame_valid_fraction": 0.93, "nearest_m": 1.82,
 "sectors": [{"azimuth_deg": [-37.0, -26.4], "nearest_m": 3.1, "valid_fraction": 0.9,
              "observed": true, "reason": "ok"}, "... 7 sectors, left to right ..."],
 "control_output": "DISABLED"}
```

- `azimuth_deg`: degrees from optical forward when `leveled: false`, or gravity-level body
  forward when `leveled: true`; **+ = right** in both modes.
- `nearest_m`: robust nearest range **along the ray** (5th percentile), metres.
- `observed: false` means **unknown** (no return, too few pixels, or something inside the 0.2 m blind
  zone). Unknown is never free space.
- `observed: true, nearest_m: null` means returns exist but everything is beyond `max_range_m`.
- `fresh: false` when the frame is older than `max_age_ms` (simulation time with `use_sim_time:=true`).
- A frame that cannot be used is still published as `{"rejected": "<reason>", "sectors": []}`.

## Attitude-aware horizon band

The pure `forward_sectors(...)` function accepts keyword-only `R_level_cam`,
`camera_height_m`, and `floor_margin_m` (default 0.15 m). `R_level_cam` is a finite proper
orthonormal 3×3 rotation: **camera optical (x right, y down, z forward) → gravity-level
body (x forward, y left, z up)**. Pixels are binned by their rotated azimuth, retaining
positive-right output, and selected within `SectorConfig.vertical_band_deg` (default ±15°)
of the level horizon. Sector edges retain the calibrated horizontal field of view;
unseen areas remain unobserved. Ranges are still Euclidean ray distances.

With a finite positive camera height, points at or below `floor_margin_m` above a locally
horizontal floor are excluded. This needs height at the **camera optical centre**, in metres.
Floor-only evidence becomes UNKNOWN, never observed-clear. The filter also excludes any
low obstacle below that margin; this is a horizon wall sensor, not a floor-hazard detector.
Without height, the horizon band can still include floor returns. Without a rotation,
the existing optical-frame calculation is preserved exactly and reports `leveled: false`;
height alone does not enable the filter. Invalid rotations/heights/margins raise `ValueError`.

The ROS observer subscribes read-only to `/fmu/out/vehicle_attitude` and
`/fmu/out/vehicle_local_position_v1` when compatible `px4_msgs` definitions are available.
It composes the TF rotation `base_link <- depth optical` at the image stamp with PX4
attitude roll/pitch, removing yaw. `base_frame` must denote the PX4 body reference with
FLU axes. If `R_NED_FRD` is the PX4 rotation and `S = diag(1,-1,-1)`, the composition is
`R_level_cam = S @ Rz(-yaw) @ R_NED_FRD @ S @ R_base_cam`.

Only valid, finite, positive `dist_bottom` enables the floor filter. Camera height adds
the vertical component of the TF camera translation after leveling; this assumes
`dist_bottom` and `base_link` share the vehicle reference. Invalid or stale height disables
the floor filter. Missing/invalid/stale attitude publishes `leveled: false` and warns once
per reason; it never substitutes an identity attitude. The TF forward-camera guard remains.
The sole publisher is the JSON observer topic; resolving/remapping it to `/fmu/in/*` is rejected.

Freshness uses local ROS reception time minus PX4's `timestamp - timestamp_sample` delay,
checked against `max_age_ms` (200 ms default) and the image stamp. PX4 boot microseconds
are never compared directly with ROS nanoseconds. Duplicate/out-of-order source messages
cannot refresh evidence; backward ROS clock jumps fail stale. After a PX4 timestamp reset,
restart the observer. **Transport delay and clock alignment are UNKNOWN** without measured
synchronisation; receipt freshness alone cannot detect an old packet delayed in transit.

Verified against official PX4 source definitions:
[VehicleAttitude.msg](https://github.com/PX4/px4_msgs/blob/main/msg/VehicleAttitude.msg)
defines Hamilton `q` in w,x,y,z order, FRD→NED, message version 0;
[VehicleLocalPosition.msg](https://github.com/PX4/px4_msgs/blob/main/msg/VehicleLocalPosition.msg)
defines `dist_bottom`, `dist_bottom_valid`, and message version 1. Retrieved blob IDs were
`fde3a85546c705676f1ff9be8e241f09af13ef54` and
`f87436cc1e7a06345a381e3c791ddb55fef84c24`, respectively.
Installed ROS/PX4 message definitions are **UNKNOWN** here: none are installed.
Startup checks the required fields and message versions; missing or incompatible definitions
disable the affected path. Node wiring is **untested against ROS**. Offline callback tests
use message/TF doubles, not middleware, hardware, or flight evidence.

## Run

Nothing here starts automatically. With the team's agreement, in the companion terminal:

```bash
python3 -m pytest -q tests/test_vision_forward_sectors.py     # offline, no ROS
python3 -m pytest -q tests/test_vision_forward_sectors_level.py # CPU renderer + callback doubles
python3 -m vision.node --ros-args -p use_sim_time:=true         # observer; Ctrl+C to stop
timeout 30s ros2 topic echo /vision/forward_sectors            # in another terminal
```

Parameters: `depth_topic`, `depth_info_topic`, `base_frame`, `out_topic`, `sectors` (7),
`max_range_m` (10.0), `max_age_ms` (200.0).

## Status

- Floor line: 18 offline cases on synthetic 640x400 mono frames.
- Forward sectors: 18 offline cases on synthetic depth (16UC1/32FC1, row padding, byte order, no return,
  blind zone, stale frame, bad input, forward-camera check).
- **Not yet run against the simulator or hardware.** Passing unit tests are not flight evidence.

## Floor guide line (`vision/floor_line.py`, `vision/line_node.py`)

Finds the maze's floor line in the **left mono** camera (`/stereo/left/image`; the RGB view is a
browser preview and is not on ROS) and publishes `vision.floor_line/1` JSON on `/vision/floor_line`:

- `detected`, `status` (`supported` / `ambiguous` / `unknown`), `confidence`, `rejection_reasons`
- `bottom_offset`: where the line meets the bottom image row, −1 left … 0 centre … +1 right
- `image_lean_deg`: lean of the line going up the image, + = right. **Image-space only**, not a
  ground heading (that needs CameraInfo, TF and height).
- `low_light`: dark-frame flag; a CLAHE retry is kept only when it clearly helps.

Branched, cropped, competing and wall-edge stripes are not reported as a line. Needs OpenCV.
Thresholds are the prototype's synthetic-tuned values; `polarity` (bright/dark line) and
`roi_top` must be checked against the real camera view in the sim.

Router-confirmed site appearance: black tape on an orange tarp. Black rectangular **zone
borders** and the **route guide line** are separate marking classes; colour alone does not
establish which is which. No new image interpretation or course geometry is inferred here.

```bash
python3 -m pytest -q tests/test_vision_floor_line.py
python3 -m vision.line_node --ros-args -p use_sim_time:=true    # observer; Ctrl+C to stop
```

Change from the prototype: the wall-edge check now compares the stripe with its own row neighbours.
The prototype compared with the floor median, which rejected every real line when walls were
brighter than the floor (regression test `test_bright_walls_alone_do_not_hide_a_floor_line`).

### Cluttered floors

The sim floors are white with scattered black dots (local sim) or multicoloured terrazzo chips (lab
sim), and the venue tarp has dark printed spots. When clutter touches the tape, the two fuse into
one "branched" blob that the shape gates reject. Before rejecting, the detector now tries a
deterministic RANSAC fit through the blob's **narrow** runs, rebuilds the stripe from the run on
that spine in each row, and trims runs widened by clutter to the local stripe width. The rebuilt
stripe must still pass every normal gate. It is refused unless clean narrow runs on the spine
support at least half of the search rows and 60% of the kept rows, and at most 35% of rows needed
trimming. Output field `clutter_pruned` is `true` when a detection came from this path.

Synthetic 640×400 frames, 100 per case, `polarity="dark"`:

| floor | tape present: found before → after | no tape: false detections |
| --- | --- | --- |
| plain | 100% → 100% | 0% |
| black dots | 30% → 85% | 0% |
| terrazzo chips | 13% → 100% | 0% |

The bottom-offset error stays at a median of 0.003 (max 0.010) with clutter, the same as on a
plain floor. Plain-floor detections never use this path. Misses on dotted floors are refusals
(fail-safe), not wrong lines. Synthetic only: real sim frames are still needed (see `replay/`).
Tests: `test_tape_on_cluttered_floor_is_found_where_it_is`, `test_clutter_alone_never_becomes_a_line`,
`test_clean_tape_does_not_use_pruning`, `test_fused_blob_without_a_stripe_is_not_pruned_into_a_line`.

## Credits

`vision/depth_sectors.py` was originally copied from the author's pre-event repository
[Cyberchopin/dronehacks-autonomy-2026](https://github.com/Cyberchopin/dronehacks-autonomy-2026)
(`src/aegisland/depth_sectors.py`, commit `01d9ded`, SHA-256
`1a7672003c775a53de79672e6339e0be59f235e8c1275027433e968b8de06fe0`). It now also accepts
gravity-level ray geometry and a height-based floor mask; its legacy sector aggregation remains.
Credited per rule 9.1. `vision/floor_line.py` adapts `_line` / `_line_geometry` from
`src/aegisland/course_perception.py` at the same commit (grey-image algorithm unchanged except the
wall-edge check noted above).
Depends only on NumPy.
