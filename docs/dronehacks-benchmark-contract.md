# DroneHacks offline benchmark contract, v1

This harness extends the existing [GPS-denied benchmark](dronehacks/gps-denied-benchmark-plan.md).
It reuses `CameraMotionCompensator`, `VisualDeadReckoner`, and the existing SE(3)
ATE/RPE evaluator. Old scripts and results remain intact. The harness never
imports PX4/MAVLink execution code, launches vendor scripts, downloads datasets,
or sends vehicle commands. Manifest, frame and result records carry `executed=false`.

## Run and verify

Use a Python environment with the repository's existing NumPy/OpenCV dependencies.
Set `PYTHONPATH=src` so imports resolve to this checkout even when borrowing a
Python executable from another environment. `PYTHONDONTWRITEBYTECODE=1` avoids
writing bytecode into borrowed environments. No installation or network is needed
when those dependencies are already available.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m aegisland.benchmark_harness run \
  --adapter aegisland-vdr --expected-frames 8 --warmup-frames 1 \
  --platform desktop --hardware 'actual measured CPU model; CPU VDR' \
  --output-root runs/dronehacks-bench

PYTHONPATH=src python -m aegisland.benchmark_harness verify runs/dronehacks-bench/RUN_ID
```

The native smoke run generates eight 120×160 grayscale images from seed 7, at
50 ms synthetic timestamp intervals. Each is a translated texture with a wrapped
border. It saves the actual input arrays and timestamps in `synthetic-inputs.npz`.
There is no physical scale or ground-truth trajectory. This checks plumbing, not
localization accuracy or real-time operation. The CLI prints the new directory;
never infer a run from the newest directory alone.

For a short prefix of an existing EuRoC recording:

```sh
PYTHONPATH=src python -m aegisland.benchmark_harness run \
  --adapter aegisland-vdr --sequence /path/to/mav0 --max-frames 8 \
  --expected-frames 8 --platform desktop --hardware 'actual measured CPU model' \
  --output-root runs/dronehacks-bench
```

Without `--max-frames`, the input CSV row count must equal `--expected-frames`.
The count is checked before decoding images. All selected image files and the
input CSV are SHA-256 hashed. This path is the core VDR baseline, not a benchmark
of the full landing agent or active-perception retry path.

## Adapter capabilities

| Adapter ID | Supported execution/input | Localization units | Accuracy interpretation |
| --- | --- | --- | --- |
| `aegisland-vdr` | Native core replay; existing VDR artifacts; canonical records | Normalized image displacement | No metric ATE/RPE |
| `cuvslam-stereo` | Existing stereo artifacts; canonical records | Metric imu0 pose | SE(3) ATE and fixed-matched-frame RPE when GT supplied |
| `cuvslam-inertial` | Existing inertial artifacts; canonical records | Metric imu0 pose | Same, with explicit mode validation |
| `oak-depthai-stereo` | Canonical recorded StereoDepth results | Metric depth; no localization pose | Valid-pixel coverage; no trajectory accuracy |
| `ffs-research` | Existing FFS artifacts; canonical records | Metric depth; no localization pose | Optional research comparison; coverage is a proxy |

cuVSLAM and FFS run in the existing separate environments before import. No vendor
runtime, checkpoint or license is bundled. A missing source/device is not treated
as a synthetic vendor success. The existing OAK flat-target script emits aggregate
statistics, which cannot reconstruct per-frame tails or drops; it is intentionally
not accepted as canonical per-frame evidence.

## Platform is part of every result

`result.platform` describes the original measurement platform, including imports:

```json
{
  "kind": "desktop",
  "hardware": "actual CPU / GPU model and memory",
  "machine": "x86_64",
  "device_model": "actual host or board model"
}
```

`kind` must be `desktop`, `orin`, or `other`. There is no automatic desktop default.
Native runs inspect the local architecture and `/proc/device-tree/model` where
available. `orin` requires ARM64 and an Orin device model. Legacy x86/WSL artifacts
cannot be relabelled Orin. Imports preserve the original metadata separately from
the importing host's `environment.json`. Labels supplied for imports are
declarations of provenance, not hardware attestation.

**Desktop != Orin.** Group comparisons by adapter, dataset/window, configuration,
latency scope, platform and warmup policy. Do not pool desktop and Orin samples or
use desktop latency as an Orin estimate. Board power mode, clocks, JetPack/CUDA,
camera and synchronization evidence still need recording on the actual board.

## Producer interface for canonical records

A producer supplies `metadata.json` and `frames.jsonl` in a read-only directory.
Use `--source DIR --format contract --expected-frames N --adapter ADAPTER_ID`.
The producer metadata contains:

| Field | Requirement |
| --- | --- |
| `schema_version`, `executed` | `1`, `false` |
| `adapter`, `expected_frames` | Exact requested adapter and selected input slot count |
| `timestamps_ns` | Full expected schedule, strictly increasing integer nanoseconds |
| `platform` | Explicit measurement platform object above |
| `latency_scope` | Named measured boundaries; say whether transfer/decode/queueing are included |
| `head`, `command`, `environment` | Producer revision, nonempty command argv, environment object |
| `wall_s` | Optional original replay wall time; never the import duration |
| `memory` | Optional peak values and scopes below; absent means unavailable |

Do not fabricate a producer HEAD when none exists: preserve a source/version
identifier and describe the limitation in the environment metadata. The harness's
own actual Git HEAD is independently recorded in `revision.json`.

Each expected input slot has one JSON object and a terminating newline. Missing
outputs must be explicit `dropped` slots, rather than silently removing timestamps.
Required frame keys:

| Key | Meaning |
| --- | --- |
| `timestamp_ns` | Nonnegative integer; capture/dataset clock, not host arrival time |
| `status` | `ok`, `lost`, `dropped`, or `error` |
| `latency_ms` | Finite nonnegative measured value, or `null` if unavailable; `dropped` requires `null` |
| `failure_reason` | Nonempty string for every unsuccessful slot; `null` for `ok` |
| `executed` | Exactly `false` |
| `pose` | `null`, or `{position_m: [x,y,z], quaternion_xyzw: [x,y,z,w]}` |
| `coverage` | `null`, or valid depth pixels / total pixels in [0,1] |

Only successful metric tracking adapters accept a pose, and each successful metric
tracking frame requires one. Poses are `world_from_body`, body=imu0, metres,
right-handed, with a normalized xyzw quaternion. OAK/FFS depth is not a pose and
cannot claim tracking loss or ATE. VDR may add `normalized_xy: [x,y]`.
Additional diagnostic keys are retained and checked for non-finite numbers.

Use `lost` for an attempted tracking update with no valid pose, `dropped` when an
expected input was not processed, and `error` for an attempted update that failed
with an adapter error. A produced depth image may be `ok` even if its valid-pixel
coverage is zero; output production and depth quality are separate metrics.

The importer rejects missing final newlines (even after a complete final object),
partial JSON objects, blank lines, duplicate JSON keys, duplicate/decreasing
timestamps, booleans used as timestamps/counts, NaN/Infinity, overflowing numeric
literals such as `1e999`, and frame/schedule/summary/trajectory count conflicts.
It never repairs these inputs or silently salvages a prefix.

## Metric definitions

- **Cold/warm:** the first `warmup_frames` attempted slots are cold; later attempts
  are warm. Drops do not consume warmup. Untimed attempts still consume their
  position in that policy. Both groups include failed attempts when timed. The
  default is one cold attempt, not separate process cold-start trials. Native VDR
  first calls `current()` to initialize its reference; initialization/import/decode
  time is excluded and the scope says so. This cold sample is not a cold ORB call.
- **Latency tails:** p50/p95/p99 in milliseconds use NumPy's linear percentile
  interpolation on raw samples. Empty groups have count zero and null percentiles.
  No latency is inferred from old percentile summaries. Small groups support smoke
  checks, not credible tail claims.
- **FPS:** attempted slots / original `wall_s`, and successful slots / original
  `wall_s`. Native wall time covers the VDR replay loop including record construction,
  excluding input decode and model creation. Imported wall boundaries remain those
  of the original producer. No wall time means null FPS; never use inverse median
  latency or the speed of the importer as throughput.
- **Drop rate:** `dropped / expected`. A processed but untracked frame is not a drop.
  Legacy runner artifacts do not establish upstream camera drop rates; the scope
  is their selected logged replay slots. cuVSLAM unpaired camera metadata remains
  in the source snapshot and is not silently converted into a new frame denominator.
- **Coverage:** successful slots / expected, plus mean valid-pixel fraction and its
  sample count when available. These are separate frame and pixel metrics.
- **Tracking loss/recovery:** after the first `ok`, a contiguous non-ok interval
  starts a loss episode. It ends at the next `ok`; recovery time uses capture
  timestamps in milliseconds. Startup invalid frames are counted as lost slots
  but are not recovery episodes. A terminal episode has null recovery, not zero.
  Depth-only adapters expose tracking as unavailable.
- **ATE/RPE:** reuse the existing evaluator, SE(3) rigid alignment without scale
  correction; translation in metres, rotation in degrees. Optional `--groundtruth`
  accepts EuRoC imu0 ground truth; default association tolerance is 5 ms, default
  RPE delta is 20 matched estimate frames. Results include pairs and delta. A
  short run with insufficient associations/delta exposes null metrics and a reason.
  Malformed GT fails the run. VDR is never given metric ATE. No Sim(3) number is
  promoted to metric accuracy.
- **Memory:** `peak_ram_bytes`, `peak_vram_bytes`, `ram_scope`, `vram_scope`. Native
  Unix VDR records process-lifetime peak RSS, including interpreter/imports/input
  decode. Imported missing peaks remain null. FFS's old peak is PyTorch allocated
  memory converted from MiB, not total device or reserved memory. CPU VDR has no
  GPU allocation; this is recorded with null VRAM and a scope, not a measured zero.

The existing pacing/clock/session rules continue to apply. This harness always
sets `valid_for_performance_claims=false`: offline smoke/import verification does
not certify real-time performance. Original flags and clock logs are preserved;
a performance report needs separate review of actual paced runs and clock evidence.
No new performance numbers are supplied by this document.

## Run artifacts, failure and integrity

Every `run` allocates `output_root/UTC_MICROSECONDS-UUID/` with exclusive creation.
It writes `manifest.json` with `status=running` first. A caught validation, input,
dependency or adapter error changes it to `failed`, records exception type/reason,
and produces checksums. Success yields `complete`. An OS kill or power loss may
leave `running`/unsealed evidence; readers reject it. CLI syntax errors and an
unwritable output root cannot create a run. Exit codes are zero for completion or
verification and one for a failed run/verification.

| Artifact | Purpose |
| --- | --- |
| `manifest.json` | Schema, unique run ID, input hashes, measurement kind, failure status, `executed=false` |
| `config.json`, `command.json` | Effective CLI options, exact command argv and cwd |
| `revision.json` | Harness repository, actual HEAD/branch/dirty state, hashes of Python source |
| `environment.json` | Importing/native host OS, architecture, Python/executable, package versions; no credential dump |
| `frames.jsonl` | Validated canonical frames, when normalization reaches that stage |
| `result.json` | Platform, capabilities, metrics, accuracy, memory, scopes and claim eligibility |
| `source/` | Copies of consumed producer evidence; originals remain unchanged |
| `origin-platform.json` | Legacy measurement platform declaration when importing |
| `groundtruth.csv` | Copied optional GT with recorded input hash |
| `synthetic-inputs.npz` | Actual generated native smoke inputs, when used |
| `SHA256SUMS` | All artifacts recursively except the root index itself, including copied source indexes |

If a legacy source has `SHA256SUMS`, all ingested source files must match it before
normalization. `verify` checks the new complete artifact inventory and hashes,
then reparses raw frames and recomputes counts, tails, coverage, FPS and recovery
summaries. Hashes detect corruption, not authenticity against an adversary who
can rewrite both evidence and indexes. Failed runs can retain partial diagnostic
results; they must not enter a comparison table.
