# OAK / PX4 / VL53L1X / perception replay contracts

Version: `dronehacks.integration-replay.v1`. This is a local recording format,
not a device driver or live integration. Every conclusion uses `observed`,
`inferred`, or `unknown`; every authority record is `NONE` and `executed=False`.
Even consistent synthetic evidence cannot increase authority.

The B harness, D perception and baseline-audit handoffs were read without modifying
their worktrees. The provenance audit is **pending final exit-0 verification**.
Its dependency decisions remain provisional. This extension adds no dependencies,
imports no vendor/hardware runtime and uses the existing local Python environment.
The earlier PyULog/NumPy pins in `requirements-forensics.txt` describe this isolated
workbench environment, not an approved shared Jetson dependency set.

## Commands and exclusive evidence runs

Run from this worktree, using the existing `.venv`; no install or network is needed:

```bash
# Deterministic arrays, calibration declarations, schedules and records.
# Fixture output must not exist. Both scenarios are invented, not hardware captures.
PYTHONPATH=src .venv/bin/python -m aegisland.forensics integration-fixtures \
  --output runs/synthetic-sensors --scenario consistent
PYTHONPATH=src .venv/bin/python -m aegisland.forensics integration-fixtures \
  --output runs/adverse-sensors --scenario adverse

PYTHONPATH=src .venv/bin/python -m aegisland.forensics integration \
  --bundle runs/synthetic-sensors --output-root runs/integration --run-id review-001
PYTHONPATH=src .venv/bin/python -m aegisland.forensics verify runs/integration/review-001

# Static host/package metadata only. No driver/device import, enumeration or opening.
PYTHONPATH=src .venv/bin/python -m aegisland.forensics preflight \
  --environment replay --output-root runs/preflight --run-id metadata-001
PYTHONPATH=src .venv/bin/python -m aegisland.forensics verify runs/preflight/metadata-001
```

Without `--run-id`, a UTC/UUID name is allocated. An existing run directory is
always rejected, including an incomplete one. Outputs must be outside the input
bundle. No input file is modified. Invalid bundles still receive diagnostic runs;
the CLI returns `2` for findings, `0` for internally consistent replay, and `1` for
configuration/storage/seal failures. No exit code asserts hardware readiness.
`verify` returning zero means integrity/recomputed classifications, not good sensors.

Each run contains `summary.json`, self-contained `report.html`, `findings.md`,
`implementation.json` with local tool-source hashes, consumed `source/` snapshots,
and `seal.json` with an exact SHA-256 inventory. The seal is written last; a missing
seal is rejected. Verification checks identity, inventory, hashes, authority and,
for integration runs, recomputes record counts and finding categories/references
from the sealed copies. OS error text can contain the original path; that text is
sealed, while stable categories are recomputed. Hashes detect corruption; they do
not establish authenticity against someone who rewrites both data and seals.

Malformed raw source bytes can contain producer claims such as `executed=true`;
they are retained only as quarantined source bytes, never accepted authority/action
records. All generated summaries, findings and authority records remain false/NONE.

Individual files are limited to 32 MiB and consumed snapshots to 128 MiB per audit.
NPZ uncompressed array bytes are also bounded to 32 MiB. Symlinks, parent traversal,
devices, FIFOs, pickle and unexpected archive members are rejected. The recorder
uses POSIX no-follow/nonblocking open flags; this implementation was tested on Linux.
It is not a streaming recorder or a crash-proof database. A hard kill may leave an
unsealed directory; preserve it for inspection and allocate a new run.

The older `report --px4 ... --jetson ... --output ...` command generates regenerable
ULog/Jetson diagnostic reports, without a seal. Use `integration` for exclusive,
hashed four-stream evidence runs; do not confuse those older pages with sealed runs.

## Bundle and schedule

Input directory:

```text
manifest.json
records.jsonl
frames/frame.npz        # any explicitly referenced relative asset filename
```

Manifest fields:

| Field | Contract |
| --- | --- |
| `schema` | `dronehacks.integration-replay.v1` |
| `executed`, `authority` | literal `false`, `NONE` |
| `source_type` | `synthetic` or `recording`; no silent synthetic fallback |
| `origin_environment` | `desktop`, `jetson_orin_nano`, `replay`, `sitl`, `unknown`; producer declaration only |
| `streams` | all four stream names below; each declares clock, expected schedule and sensor calibration/transform IDs |
| `calibrations` | registry of explicit calibration snapshots keyed by ID |
| `transforms` | registry of static `body_frd_from_sensor` transforms keyed by ID |
| `clock_pairs` | optional paired-clock rate observations; no automatic cross-clock fusion |

A schedule is a nonempty array of `{frame_id, timestamp_ns}` with strictly
increasing integers in each stream. Missing complete JSONL lines, including a
whole missing tail, are detected by this schedule. A missing final newline is
also reported. The producer schedule is itself a declaration, not an independent
proof of the upstream capture denominator. Do not derive it from only surviving
outputs and then claim no camera drops.

Each JSONL object has **exactly** these fields:

| Common field | Contract |
| --- | --- |
| `schema_version` | integer `1` |
| `stream` | `oak_rgb_depth`, `px4_telemetry`, `vl53l1x_downward`, `perception_advisory` |
| `timestamp_ns`, `frame_id` | integers in `[0,2^63-1]`, matching the expected stream schedule |
| `clock_domain` | `oak_device`, `px4_boot`, `jetson_monotonic`, `vl53_monotonic`, `replay` |
| `evaluated_at_ns`, `evaluation_clock_domain` | explicit replay assessment time; age is evaluated only in the capture clock domain |
| `calibration_id`, `transform_id` | required keys; sensor/advisory binding IDs or `null` for standardized PX4 telemetry |
| `executed` | literal `false` |
| `data` | exact stream-specific payload below; additional payload keys rejected |

All timestamps here are **nanoseconds**. A future ULog bridge must multiply PX4
boot microseconds by exactly 1000, preserve the original unit/source and reject
overflow. It must not label device time as host monotonic time. Assessing historical
frames against the current wall clock is prohibited. Same name/different boots
are not automatically the same clock session.

## Stream payloads

| Stream | Exact `data` keys |
| --- | --- |
| `oak_rgb_depth` | `asset`, `sha256`, `encoding`, `camera_view`, `comparison_target` |
| `px4_telemetry` | `quaternion_wxyz`, `attitude_frame`, `battery_voltage_v`, `local_position_valid`, `failsafe`, `nav_state` |
| `vl53l1x_downward` | `range_m`, `range_status`, `sigma_m`, `mount`, `comparison_target` |
| `perception_advisory` | `source_frame_id`, `source_frame_sha256`, `configuration_sha256`, `state`, `confidence`, `rejection_reasons`, `advisory_only`, `control_output`, `command_executed`, `authority_change`, `local_sensing_planes` |

**OAK-D S2 recording:** encoding is `RGB8` or `BGR8`; view is explicitly `forward`
or `downward`. The NPZ file contains exactly `rgb:uint8[H,W,3]`,
`depth_m:float[H,W]`, and `valid:bool[H,W]`. The array named `rgb` uses the declared
channel order. Depth is registered to that image and is optical-axis z in metres,
not Euclidean ray range. Invalid pixels use a false mask and finite storage values;
all non-finite values are rejected. True-mask depths must be positive. Unknown
center depth is never interpreted as clearance. Payload SHA-256 must match.
Calling this stream OAK is a producer claim; no OAK model or capture was measured.

**PX4:** attitude is a finite normalized quaternion in **wxyz** order and
`attitude_frame=ned_from_frd`; this differs deliberately from static-transform
xyzw order. Battery voltage is positive finite volts or null, validity/failsafe
are booleans or null, and nav_state is an integer `[0,255]` or null. Unknown fields
do not imply a nominal vehicle. No control, arming or parameter fields are accepted.
This canonical JSON reader does not add a live PX4 adapter. Existing `.ulg`
ingestion remains separately available for diagnostic topics.

**VL53L1X:** mount is `downward`; `range_status` is `valid`, `invalid`, or `unknown`.
`range_m` is finite `(0,10]` metres or null; valid status requires a distance.
`sigma_m` is finite `[0,10]` metres or null. The 10 m parser ceiling is a sanity
bound, **not a VL53L1X accuracy/range specification**. Status decoding, actual FoV,
surface/material behavior, mounting offsets and firmware units remain unverified.

**Advisory:** `advisory_only=true`, `control_output=DISABLED`,
`command_executed=false`, `authority_change=NONE`; confidence is finite `[0,1]`
and not a correctness probability. State is text, rejection_reasons is a list of
strings. The advisory must bind to a usable OAK source frame by ID, file hash,
clock, time within 25 ms, calibration and transform. Missing bindings are unknown.
The configuration hash is a producer claim until its full configuration snapshot
is integrated and independently hashed. No `safe`, action, mission or control
field is accepted. A high-confidence advisory never increases authority.

`local_sensing_planes` is a required list (empty if no local plane was assessed).
Each item has exactly `evidence_path`, `scope`, `supported_meaning`,
`local_plane_supported`, `full_3d_traversability`, `supports_3d_traversal`,
`probe_z_m`, `width_at_probe_m`, `sampled_bbox_normalized`, `unassessed`, `executed`,
`authority_change`, `rejection_reasons`, `rgb_depth_consistency`.
The scope is **local_camera_z_probe_plane**, meaning **observed_local_plane_width_only**.
`full_3d_traversability=UNKNOWN`, `supports_3d_traversal=false`, `executed=false`,
`authority_change=NONE` are mandatory. Local support is boolean and cannot ignore
missing width/ROI/probe geometry, rejection reasons or RGB/depth ambiguity.
ROI is `[x,y,w,h]` within `[0,1]`; width/probe are finite nonnegative metres or
null (supported requires positive probe). RGB/depth consistency is `unverified`
or `ambiguous`. Unassessed items must retain `outside_sampled_roi`,
`beyond_probe_plane`, `occluded_volume`, `swept_vehicle_volume`, `dynamic_obstacles`.
Positive local width does **not** establish a free volume or route. The summary
and every report explicitly keep **3D traversability UNKNOWN**, including when
downward ranges agree or static descent geometry is favorable.

The later B/D bridge plan and refreshed handoff hashes are in
[integration-plan.md](integration-plan.md).

## Calibration, transforms and contradictions

OAK calibration declares sensor name, width/height, `[fx,fy,cx,cy]`, `unit=m`,
`depth_semantics=optical_axis_z`, and `provenance=synthetic|recording`.
Intrinsics must be finite, focal lengths positive and principal point inside the
image. VL53L1X calibration declares its sensor name, unit and provenance. Registry
IDs must match the stream's expected IDs and each recorded sensor row.

Static transforms declare `parent=body_frd`, a nonempty different `child`,
`translation_m:[x,y,z]`, normalized finite `quaternion_xyzw`,
`convention=parent_from_child`, calibration ID, and provenance. Translation is a
static sensor offset, not a vehicle trajectory or future-flight route. The tool
does not publish transforms to a vehicle. IDs and valid numbers do not certify a
physical calibration; all physical registration conclusions remain unknown.

Only matching frame IDs with the same clock, at most 25 ms apart, explicit
downward OAK view, a shared nonempty comparison_target, origin separation at most
2 cm, beam-axis dot product at least 0.999, and a downward body axis support a
range comparison. OAK uses its center valid pixel; VL53L1X needs valid status and
stated sigma. Disagreement over `max(0.25 m, 3*sigma)` is an **inferred contradiction
candidate**, not proof that either sensor is wrong. Surface identity, plane angle,
FoV and physical calibration remain unverified. Different rays, targets, clocks,
missing depth or unknown sigma produce unknown; no false agreement is claimed.

## Time and evidence degradation

Age over 200 ms is stale. Future timestamps in the same domain are clock-skew
candidates. Clock-domain mismatch makes age unknown; timestamps are never silently
converted. Duplicate/decreasing timestamps or IDs are out of order. ID gaps flag
possible drops/subsampling; schedule gaps flag observed missing recording slots.
Calibrations, transforms, asset bytes, frame bindings and finite values must all
pass before a sensor record is considered usable. Missing, stale, contradictory
or malformed evidence degrades the run, but even a clean run has authority NONE.

Optional clock pairs contain exactly `source_clock`, `target_clock`, `source_ns`,
`target_ns`, `uncertainty_ns`. At least two increasing pairs in one domain pair
are required. Rate difference beyond 2000 ppm plus endpoint uncertainty flags
inferred skew; inconsistent interior pairs also flag skew. Stated uncertainty
must not exceed 5 ms. These are supplied observations, not a measured sync service.
This interface does not use them to fuse sensor records across clocks. The
separate ULog/Jetson `--alignment` interface provides hash-bound bounded estimates
as described in the main README; physical synchronization remains unknown there too.

## No-hardware preflight and platform manifest

Preflight observes Python distribution metadata, OS architecture/system, filesystem
capacity and Linux kernel memory accounting. It does not import CUDA, Torch,
DepthAI, MAVSDK or pymavlink; run nvidia-smi; enumerate cameras; inspect/open `/dev`;
connect PX4; allocate test GPU memory; change groups/permissions; or access a network.

CUDA runtime, camera availability, PX4 connectivity, writable storage, expected
USB/serial/I2C/GPU permissions and device memory remain unknown where unmeasured.
Installed package metadata is not proof that its native runtime works.

The manifest separates execution_context (always replay here), declared_environment,
and inferred host class. All five labels—desktop, jetson_orin_nano, replay, sitl,
unknown—are distinct. ARM64 plus an explicitly declared Orin Nano model can only
produce an inferred host class, never validation; x86 cannot be relabelled Orin.
An unspecified ARM board remains unknown; Orin NX is not silently treated as Nano.
Every measured_validation flag remains false. SITL recording labels do not launch
SITL or prove SITL validation. No desktop timings become Orin claims.
