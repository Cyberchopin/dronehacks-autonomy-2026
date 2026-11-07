# Offline bag → perception replay

Exports existing ROS 2 recordings, then evaluates the unchanged `vision.floor_line`,
`vision.forward_sectors` and `nav.line_follow` modules. There is no live recorder,
publisher, ROS node, playback process, or flight adapter here.

**Rule 6.4: recordings are for offline tuning only, never an input during a run.**
Do not connect an exported frames folder, replay report, or sweep to a running navigator.
Sweeps recommend detector settings for review; they never write flight-time configuration.

No team bag or real simulator frames were available for this implementation. Tests use
synthetic pinhole images/depth from `simtest.course_render` with controlled stripe/dot
textures. Real-sim detection rates and false-positive rates remain **UNKNOWN** until the
Router supplies an export. Actual ROS 2 Jazzy bag reading is **untested against ROS** here;
the reader boundary is tested with doubles.

The reported environments differ: local sim white/dotted floor and numbered cardboard
walls, lab sim multicoloured terrazzo, real venue black tape on orange tarp. A high
detection frequency can be texture false positives; it is not accuracy without human
labels. Real-venue rectangular zone borders and the route guideline remain separate
semantic classes. This replay does not infer their identity from colour or a fitted stripe.

## Export on the teammate's ROS 2 Jazzy machine

Use the `replay/frames` branch, a sourced Jazzy environment, NumPy, and the **matching
recorded message definitions**, including `px4_msgs` and `tf2_msgs` when present. No
simulator needs to be running. Replace the paths with an existing local bag and a new
output directory. The exporter never modifies the bag and refuses output inside it.

```bash
source /opt/ros/jazzy/setup.bash
# Source the team's existing px4_msgs overlay too, if not already in the environment.
ros2 bag info /path/to/hinson-follow_TIMESTAMP
python3 replay/export_bag.py /path/to/hinson-follow_TIMESTAMP \
  --out /path/to/exports/hinson-follow_TIMESTAMP \
  --every 3 --max-frames 600 --max-mb 300
```

`--max-mb` uses decimal MB and includes NPZ files plus manifest. Space is reserved for
metadata, so the export can stop below the limit. `--max-frames` counts **all sampled
packets combined**, including CameraInfo; it does not mean 600 synchronized image pairs.
Each image/CameraInfo stream is sampled independently at indices 0, N, 2N, …; default N=3.
The first limit reached stops further packet writes. Both input passes still scan their
selected topics for complete counts and nearest telemetry. Increase `--every` to cover
a longer recording within the same packet budget. A latched, one-message CameraInfo is
retained because sampling starts with index 0.

Output directories must be new. Interrupted/failed exports are left in place for inspection;
choose a different output path to retry. No files are deleted. Missing custom message
packages or unsupported serialization/storage fail explicitly. For ordinary sqlite3/MCAP
bags the storage ID is inferred from metadata; `--storage-id sqlite3` or `--storage-id mcap`
can select it explicitly. External file/message-compressed bags may require conversion
by the bag owner; this tool does not rewrite them.

These defaults are **UNKNOWN for any actual team bag** until its metadata is inspected:

| Role | Requested topic | Override |
| --- | --- | --- |
| Mono | `/stereo/left/image` | `--mono-topic` |
| Depth | `/camera/depth/image_raw` | `--depth-topic` |
| Depth intrinsics | `/camera/depth/camera_info` | `--camera-info-topic` |
| PX4 attitude | `/fmu/out/vehicle_attitude` | `--attitude-topic` |
| PX4 local position | `/fmu/out/vehicle_local_position_v1` | `--position-topic` |
| Static camera mounting TF | `/tf_static` | `--tf-static-topic` |

The manifest lists the available bag topics and checks the requested topic names/types.
Absent or mismatched topics are flagged UNKNOWN, not guessed from similar names. At least
one supported mono/depth topic is required. Unsupported image encodings are preserved by
the exporter and reported as input errors during replay.

## Timestamps and camera calibration

Each NPZ preserves the raw image message bytes, including padding and byte order. Image
header stamps and frame IDs, bag record stamps, and PX4 `timestamp`/`timestamp_sample`
microseconds are kept separately. Two read-only passes select images/CameraInfo, then
find the nearest attitude/position **by bag record time**, with signed `delta_ns` retained.
Ties use the first sample encountered in reader order. The nearest sample can be in the
future: this is offline analysis, not causal playback. Invalid nearest telemetry remains
UNKNOWN; the exporter does not replace it with a farther valid sample.

Image/PX4/source clock alignment, transport delay, and whether bag header timestamps
really use simulation time remain UNKNOWN without producer confirmation. The manifest's
`sim_time_span_ns` is the image-header span of scanned streams; `exported_sim_time_span_ns`
is the actual saved image span. `bag_record_span_ns` covers the requested, confirmed topics,
not unrelated bag topics. Replay traces use image header time; advisory state resets on a
backward mono timestamp, and the report counts resets. The perception call's `now` equals
its image stamp for offline evaluation, so its `fresh` value is **not live latency evidence**.

CameraInfo must match the depth frame ID and image dimensions. The latest sampled preceding
calibration is held (no expiry for a fixed camera); if none precedes an image, the first
future one may be used only within the synchronization tolerance. Its stamp and association
delta remain visible. Changes between sampled calibration messages are not reconstructed.

Leveling needs both a valid nearby attitude and the optical-to-body mounting transform.
It composes recorded `/tf_static` chains into `base_link <- depth optical`, or accepts
an explicitly verified calibration JSON with `--extrinsics /path/to/camera_mount.json`:

- `base_frame`: the FLU body frame at the PX4 vehicle reference (default `base_link`).
- `optical_frame`: exactly the depth header frame ID.
- `rotation`: 3×3 proper rotation, optical (right/down/forward) → body (forward/left/up).
- `translation_m`: optical centre position `[x,y,z]` in that body frame, metres.
- `source`: the calibration provenance.

No default rotation/translation is invented. Changing/ambiguous static transforms fail
UNKNOWN. Dynamic `/tf` mounting is not supported; a moving camera needs a future reviewed
extension, not a guessed static transform. The optical axis must be within 25° of body
forward. PX4 Hamilton wxyz attitude FRD→NED is leveled using roll/pitch only, as in the
existing `vision.attitude` module. Invalid/missing/stale attitude or missing calibration
keeps the legacy `leveled: false` path and records the reason.

`--max-sync-ms` defaults to 200. It bounds absolute record-time association delta and PX4
sample-to-publication delay. These checks do not establish physical synchronization.
Only valid positive `dist_bottom` enables the floor mask; the leveled camera translation
adjusts vehicle height to camera height. This assumes a shared base/PX4 height reference,
which must be verified on the recording setup. The existing 0.15 m floor margin also
excludes low obstacles. Missing height disables only the floor filter.

## Replay anywhere with NumPy and OpenCV

No ROS dependencies are imported by replay or sweep. From the repository root:

```bash
python3 replay/run.py /path/to/exports/hinson-follow_TIMESTAMP \
  --out /path/to/reports/hinson-follow_TIMESTAMP-dark \
  --polarity dark --roi-top 0.35 --contrast-delta 18 \
  --sectors 7 --max-range 10
python3 replay/sweep.py /path/to/exports/hinson-follow_TIMESTAMP \
  --polarities dark bright --roi-tops 0.25 0.35 0.45 --contrast-deltas 10 18 30
```

Open `report.html` locally; its SVG charts and up to 10 downscaled PNG thumbnails are fully
embedded, with no CDN, web server, plotting library, browser automation, or external assets.
Fewer than 10 mono frames yield fewer thumbnails, without duplicated examples. Hover trace
points for values. Green polylines show detected image-space evidence; other frames say
“no line.” The JSON contains complete per-frame measurements.

Mono and depth streams are evaluated independently at their own timestamps rather than
duplicating nearest image pairs. Every mono packet drives floor-line detection and a stateful
`LineFollower` advisory; every depth packet drives sectors. Sparse/no-return depth is not
filled or interpolated. Corrupt packets remain in denominators, produce explicit errors,
and yield UNKNOWN evidence rather than disappearing from statistics.

Sweep score = `detection_rate * (1 - ambiguity_rate)`, then lower ambiguity and higher mean
confidence break ties. The same frames and unchanged detector are used for every grid cell.
Reject all recommendations if the inputs are unusable; inspect both stripe and negative
scenes before accepting a setting. No labels means true/false-positive rates are UNKNOWN.

## Schemas

`manifest.json` (`replay.frames/1`) contains:

- Bag name, source kind, topic availability/type status, scanned/exported counts, errors,
  limits and stopping reason, time spans, exact export command, repo commit and dirty flag.
- `frames[]`: role (`mono`, `depth`, `camera_info`), file/SHA-256, bag/header stamps, frame ID,
  image dimensions/encoding/stride/endianness, or CameraInfo K. Each NPZ contains this original
  metadata as a scalar JSON string plus `data` (raw uint8 bytes) or `k` (nine floats).
- Image frame entries additionally carry nearest `attitude` and `position` records;
  depth entries reference `camera_info` and resolved `extrinsics`, or UNKNOWN with a reason.
  NPZ loading forbids pickle and verifies checksums/metadata. Calibration packets are verified too.

`report.json` (`replay.report/1`) contains:

- Source manifest hash and provenance, exact replay/export commands, detector/sector config,
  summary rates with explicit denominators, and UNKNOWN reasons.
- `line_frames[]`: stamps/time, full detector result, rolling detection rate over the last
  30 sampled mono frames, bottom offset/lean/confidence, and unexecuted steering advisory.
- `depth_frames[]`: raw finite-positive depth fraction, per-sector ray ranges and observed
  flags, unknown-sector fraction, leveling/floor-filter availability and association deltas.
- Rejection/error counts and embedded thumbnails. Empty denominators are JSON `null`
  (UNKNOWN). An observed sector beyond max range and an unobserved sector both have null
  range; use `observed` to distinguish them. HTML range traces leave gaps for both.

## Verification and source

```bash
python3 -m pytest -q tests/test_replay_pipeline.py
ruff check replay tests/test_replay_pipeline.py
ruff format --check replay tests/test_replay_pipeline.py
ruff check src tests && ruff format --check src tests && pytest -q && git diff --check
```

Use Ruff **0.14.3** from the repository root. Synthetic fixtures cover dark stripes,
scattered dark dots with no line, sparse depth, timestamp/NPZ round-trip, bounded export,
invalid/missing telemetry/calibration, static-TF composition, offline report/CLI/sweep,
and a static check for publication/spin calls. The dots test is not weakened if it fails.

The reader API was checked against the official
[ROS 2 Jazzy sequential-reader tests](https://github.com/ros2/rosbag2/blob/jazzy/rosbag2_py/test/test_sequential_reader.py)
(blob `2527e39391dbba8d105508970022f4ded559bf39`). No course data or bag was downloaded.
Perception, steering and renderer code are reused unchanged from this repository.
