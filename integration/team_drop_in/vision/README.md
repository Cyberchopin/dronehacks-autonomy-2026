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
 "fresh": true, "frame_valid_fraction": 0.93, "nearest_m": 1.82,
 "sectors": [{"azimuth_deg": [-37.0, -26.4], "nearest_m": 3.1, "valid_fraction": 0.9,
              "observed": true, "reason": "ok"}, "... 7 sectors, left to right ..."],
 "control_output": "DISABLED"}
```

- `azimuth_deg`: degrees from the optical axis, **+ = right**.
- `nearest_m`: robust nearest range **along the ray** (5th percentile), metres.
- `observed: false` means **unknown** (no return, too few pixels, or something inside the 0.2 m blind
  zone). Unknown is never free space.
- `observed: true, nearest_m: null` means returns exist but everything is beyond `max_range_m`.
- `fresh: false` when the frame is older than `max_age_ms` (simulation time with `use_sim_time:=true`).
- A frame that cannot be used is still published as `{"rejected": "<reason>", "sectors": []}`.

## Run

Nothing here starts automatically. With the team's agreement, in the companion terminal:

```bash
python3 -m pytest -q tests/test_vision_forward_sectors.py     # offline, no ROS
python3 -m vision.node --ros-args -p use_sim_time:=true         # observer; Ctrl+C to stop
timeout 30s ros2 topic echo /vision/forward_sectors            # in another terminal
```

Parameters: `depth_topic`, `depth_info_topic`, `base_frame`, `out_topic`, `sectors` (7),
`max_range_m` (10.0), `max_age_ms` (200.0).

## Status

- Unit tests: 18 offline cases on synthetic depth (16UC1/32FC1, row padding, byte order, no return,
  blind zone, stale frame, bad input, forward-camera check).
- **Not yet run against the simulator or hardware.** Passing unit tests are not flight evidence.

## Credits

`vision/depth_sectors.py` is copied unchanged from the author's pre-event repository
[Cyberchopin/dronehacks-autonomy-2026](https://github.com/Cyberchopin/dronehacks-autonomy-2026)
(`src/aegisland/depth_sectors.py`, commit `01d9ded`, SHA-256
`1a7672003c775a53de79672e6339e0be59f235e8c1275027433e968b8de06fe0`). Credited per rule 9.1.
Depends only on NumPy.
