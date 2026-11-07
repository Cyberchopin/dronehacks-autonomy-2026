# Task card 5 v2 — offline bag replay

Branch `replay/frames`, created from `vision/attitude-level` at `5a50f78`.
Destination: `Cyberchopin/dronehacks-autonomy-2026` only; no PR or merge.

Implemented the read-only existing-bag exporter, portable NPZ/manifest format,
offline perception/advisory report with self-contained HTML, and recommendation-only
parameter sweep. No live recorder was written. The perception and navigator modules
are unchanged. Recordings are for offline tuning only, never an input during a run
(rule 6.4).

## Evidence and remaining UNKNOWNs

No real bag was fetched, copied, opened, or supplied. Real simulator performance,
the actual bag topic names, camera calibration, clock alignment and transport latency
remain UNKNOWN. ROS 2 Jazzy is not installed here: actual ROS deserialization/storage
integration is untested. The official Jazzy reader API was inspected; an offline reader
double exercises the adapter. See README for teammate export commands and source link.

Synthetic fixtures use `simtest.course_render` pinhole depth and controlled mono floor
textures. Dark stripe: 12/12 detections, no ambiguity. Dark dots with no line: 0/16
detections, no steering. The detector and negative assertion were not relaxed.

Sparse fixtures retain 30% of already-valid renderer returns, producing approximately
21% valid pixels across the whole image. After horizon/floor selection the existing
sector support threshold leaves **100% of sectors UNKNOWN**. This result is preserved,
not filled or retuned away. A separate dense-depth test observes the wall at approximately
5 m with zero unknown sectors. None of these results are real-sim or flight evidence.

Each example HTML embeds 10 PNG thumbnails. Stripe HTML: 115479 bytes; dots HTML:
113241 bytes. Generated examples are under ignored `replay/local-output/task5-validation/`;
they are explicitly labelled synthetic and are not committed as recordings.

## Exact validation commands and output

All commands ran from `/home/shiyue1128/dronehacks-autonomy-2026`.

```bash
ruff --version
python3 -m pytest -q -o addopts='' tests/test_replay_pipeline.py
ruff check replay tests/test_replay_pipeline.py
ruff format --check replay tests/test_replay_pipeline.py
```

```text
ruff 0.14.3
...................                                                      [100%]
19 passed in 3.98s
All checks passed!
7 files already formatted
```

Required pre-push command, exit 0:

```bash
ruff check src tests && ruff format --check src tests && pytest -q && git diff --check
```

```text
All checks passed!
57 files already formatted
........................................................................ [ 13%]
........................................................................ [ 27%]
........................................................................ [ 41%]
........................................................................ [ 55%]
........................................................................ [ 69%]
........................................................................ [ 83%]
........................................................................ [ 97%]
..............                                                           [100%]
```

`git diff --check` emitted nothing. Test count confirmation:

```bash
pytest --collect-only -q -o addopts='' | tail -n 1
```

```text
518 tests collected in 0.39s
```

Generate the isolated synthetic CLI examples (output directories must be new):

```bash
python3 - <<'PY'
from pathlib import Path
import runpy
fixture = runpy.run_path('tests/test_replay_pipeline.py')
base = Path('replay/local-output/task5-validation')
for kind, count in [('line', 12), ('dots', 16)]:
    doc = fixture['make_export'](base / f'{kind}-frames', kind=kind, count=count)
    print(f"{kind}: {doc['exported_counts']}; source={doc['source_kind']}")
PY
```

```text
line: {'camera_info': 1, 'mono': 12, 'depth': 12}; source=synthetic renderer
dots: {'camera_info': 1, 'mono': 16, 'depth': 16}; source=synthetic renderer
```

```bash
python3 replay/run.py replay/local-output/task5-validation/line-frames --out replay/local-output/task5-validation/line-report --polarity dark --roi-top 0.35 --contrast-delta 18 --sectors 7 --max-range 10
```

```text
{
  "mono_frames": 12,
  "depth_frames": 12,
  "detection_rate": 1.0,
  "ambiguity_rate": 0.0,
  "mean_confidence": 0.8539999999999998,
  "unknown_sector_rate": 1.0,
  "mean_depth_valid_fraction": 0.21022656250000002,
  "leveled_frames": 12,
  "floor_filtered_frames": 12,
  "line_clock_resets": 0,
  "input_error_count": 0
}
Wrote replay/local-output/task5-validation/line-report/report.json and replay/local-output/task5-validation/line-report/report.html
```

```bash
python3 replay/run.py replay/local-output/task5-validation/dots-frames --out replay/local-output/task5-validation/dots-report --polarity dark --roi-top 0.35 --contrast-delta 18 --sectors 7 --max-range 10
```

```text
{
  "mono_frames": 16,
  "depth_frames": 16,
  "detection_rate": 0.0,
  "ambiguity_rate": 0.0,
  "mean_confidence": 0.0,
  "unknown_sector_rate": 1.0,
  "mean_depth_valid_fraction": 0.2102783203125,
  "leveled_frames": 16,
  "floor_filtered_frames": 16,
  "line_clock_resets": 0,
  "input_error_count": 0
}
Wrote replay/local-output/task5-validation/dots-report/report.json and replay/local-output/task5-validation/dots-report/report.html
```

```bash
python3 replay/sweep.py replay/local-output/task5-validation/line-frames --polarities dark bright --roi-tops 0.35 --contrast-deltas 18
```

```text
rank polarity roi_top contrast detection ambiguity score errors
   1     dark    0.35     18.0     1.000     0.000 1.000      0
   2   bright    0.35     18.0     0.000     0.000 0.000      0
Recommendation only: score = detection * (1 - ambiguity). Detection is not accuracy.
Inspect thumbnails and negative scenes; no flight-time configuration written.
```

## Files changed

All are new:

- `replay/__init__.py`, `replay/frames.py`: package and portable bounded packet I/O.
- `replay/export_bag.py`: guarded, read-only rosbag2 reader and associations.
- `replay/run.py`, `replay/html_report.py`: offline evaluation, JSON and embedded HTML.
- `replay/sweep.py`: grid ranking, stdout only, no configuration writes.
- `replay/README.md`, `replay/HANDOFF.md`: usage, schema, limits and this evidence.
- `replay/.gitignore`: excludes local generated validation outputs.
- `tests/test_replay_pipeline.py`: 19 headless cases, no ROS required.

No changes to `vision/`, `nav/`, `simtest/`, `course/`, or `src/`. No simulator run,
GPU, flight, arming, publisher, credential access or deletion. Push receipt/commit
identity is supplied in the Router handoff after `git push -u origin replay/frames`.
