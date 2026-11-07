# Attitude-aware wall sense — task card 4

Branch: `vision/attitude-level`, based on `vision-nav` at `6aece6b`.
Destination: `Cyberchopin/dronehacks-autonomy-2026` only. No PR or merge.

## Part A: course work already saved

At inspection the working tree was clean on `course/layout-map`, not carrying untracked
course files. The requested outputs had already been committed in `a9cf7dd` and were
on `origin/course/layout-map` at `6a8af0de74a0a96404e12453ca09f8aafb23b72b`.
The GitHub connector independently verified that remote branch SHA. No duplicate course
commit or rewrite was made.

Ran `git checkout vision-nav`, then `git status --short --branch`: clean on `vision-nav`.
`git ls-files course` showed the nine original extraction/plot files already in that
branch's history; those were preserved. The new `floor_markings`, `passages`, `nav_grid`,
`route_prior`, and `mesh_geometry` modules were verified present on the course branch
and absent from `vision-nav`. Then ran `git checkout -b vision/attitude-level`.
No course files were changed in Part B. Gate B remains a candidate with `status: UNKNOWN`.

Router-confirmed appearance is black tape on orange tarp. Rectangular zone borders
and the route guideline are separate marking classes, recorded in `vision/README.md`.
No coordinates or gate identity were inferred from that appearance statement.

## Change and evidence

Optical rays can now be rotated into gravity-level body FLU before azimuth/elevation
selection. Optional camera height removes floor returns. Missing returns remain UNKNOWN.
Legacy mode keeps its calculation and adds `leveled: false`. Rotation, height and margin
validation rejects malformed values. The node reads PX4 attitude and optional valid height,
checks freshness, strips yaw, and composes TF. Its only publisher remains observer JSON.

Deterministic CPU renderer: camera at 0.8 m, wall plane 5 m ahead, no noise/dropout.

| Camera pose | Legacy centre range | Leveled + height centre range |
| --- | ---: | ---: |
| Level | 3.358 m | 5.002 m |
| 10° down | 2.001 m | 5.002 m |

Pitch match error: **0.000 m at the JSON's 0.001 m precision**. A 10° roll keeps all
sectors at or above 5 m, within 0.03 m of the level result. These are synthetic pinhole
rendering checks, not simulator or flight evidence.

Reproduce the range report from the repository root:

```bash
python3 - <<'PY'
import runpy
ns = runpy.run_path('tests/test_vision_forward_sectors_level.py')
forward, scene, centre = ns['forward_sectors'], ns['scene'], ns['centre']
args, rotation = scene()
before = centre(forward(*args))
level = centre(forward(*args, R_level_cam=rotation, camera_height_m=0.8))
args, rotation = scene(pitch=10)
pitched_old = centre(forward(*args))
pitched = centre(forward(*args, R_level_cam=rotation, camera_height_m=0.8))
print(f'level camera: legacy={before:.3f} m, leveled+height={level:.3f} m')
print(f'pitched 10 deg: legacy={pitched_old:.3f} m, leveled+height={pitched:.3f} m')
print(f'pitched match error={abs(pitched-level):.3f} m (JSON precision: 0.001 m)')
PY
```

Exact output:

```text
level camera: legacy=3.358 m, leveled+height=5.002 m
pitched 10 deg: legacy=2.001 m, leveled+height=5.002 m
pitched match error=0.000 m (JSON precision: 0.001 m)
```

## Environment and checks

All commands below ran from `/home/shiyue1128/dronehacks-autonomy-2026`.

```bash
uname -m
sha256sum /mnt/c/Users/wangs/Downloads/ruff-0.14.3-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
```

```text
x86_64
0e2f8a0bbcffcfd895df39c9a4ecd59bb80dca03dc43f7fb63e647ed176b741e  /mnt/c/Users/wangs/Downloads/ruff-0.14.3-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
```

The first `python3 -m pip install --no-index --no-deps <wheel path above>` exited 1
with `error: externally-managed-environment`. Retried as authorized:

```bash
python3 -m pip install --no-index --no-deps --break-system-packages /mnt/c/Users/wangs/Downloads/ruff-0.14.3-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl && ruff --version
```

```text
Defaulting to user installation because normal site-packages is not writeable
Processing /mnt/c/Users/wangs/Downloads/ruff-0.14.3-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
Installing collected packages: ruff
Successfully installed ruff-0.14.3
ruff 0.14.3
```

Ruff 0.14.3 initially reported three pre-existing test files requiring formatting.
Formatted only those and changed Python files from the repository root. AST comparison
against `HEAD` verified no assertion/code change in those existing tests. `src/` is untouched.

Required pre-push command (exit 0):

```bash
ruff check src tests && ruff format --check src tests && pytest -q && git diff --check
```

Exact combined output (`git diff --check` emitted nothing):

```text
All checks passed!
56 files already formatted
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 43%]
........................................................................ [ 57%]
........................................................................ [ 72%]
........................................................................ [ 86%]
...................................................................      [100%]
```

`pytest --collect-only -q -o addopts=''` confirmed `499 tests collected in 0.27s`.
Python 3.14.4, NumPy 2.5.4, pytest 9.2.0 are installed here; Ruff is pinned exactly.
The local pytest version differs from the project's dev constraint (>=8.4,<9);
the run above is local validation, not a claim that hosted CI has run.

Additional offline checks:

```bash
ruff check vision/attitude.py vision/depth_sectors.py vision/forward_sectors.py vision/node.py tests/test_vision_forward_sectors_level.py
ruff format --check vision/attitude.py vision/depth_sectors.py vision/forward_sectors.py vision/node.py
python3 -m pytest -q -o addopts='' tests/test_vision_forward_sectors_level.py tests/test_vision_forward_sectors.py simtest/tests/test_course_render.py
```

```text
All checks passed!
4 files already formatted
....................................................................     [100%]
68 passed in 3.09s
```

## Files changed

- `vision/attitude.py`: pure quaternion, frame and freshness helpers (new).
- `vision/depth_sectors.py`: optional level geometry and floor mask.
- `vision/forward_sectors.py`: optional inputs and `leveled` field.
- `vision/node.py`: read-only PX4 subscriptions, TF composition, guarded fallback.
- `vision/README.md`: inputs, frames, limits, definition provenance and tape classes.
- `vision/ATTITUDE_LEVEL_HANDOFF.md`: this record (new).
- `tests/test_vision_forward_sectors_level.py`: renderer, validation and callback tests (new).
- `tests/test_nav_line_follow.py`, `tests/test_vision_floor_line.py`,
  `tests/test_vision_forward_sectors.py`: Ruff 0.14.3 formatting only.

No modifications to `course/`, `src/`, `nav/`, `replay/` or `simtest/`.

## Remaining UNKNOWNs

- Node wiring is **untested against ROS**. No installed ROS/PX4 definitions were found.
  Official PX4 source verified field names and FRD→NED Hamilton wxyz conventions; source
  URLs and blob IDs are in README. Runtime requires attitude version 0 and position
  version 1 with the expected fields. Installed schema compatibility remains UNKNOWN.
- Transport latency, sensor/ROS clock alignment, and real camera/body/height-reference
  calibration are UNKNOWN. Freshness uses reception time adjusted by PX4 sample delay.
  See README for limitations and timestamp-reset behavior.
- Actual sensor accuracy, real floor planarity and hardware performance are UNKNOWN.
  Floor suppression requires a valid camera height and removes points below the margin,
  including low obstacles. No simulator, GPU, flight or arming was used.
- Course Gate B identity remains UNKNOWN; the saved course branch retains that status.

## Delivery

`git ls-remote --heads origin course/layout-map vision/attitude-level` exited 128:

```text
fatal: unable to access 'https://github.com/Cyberchopin/dronehacks-autonomy-2026/': Could not resolve host: github.com
```

Shell push outcome and final branch identity are reported in the Router handoff.
