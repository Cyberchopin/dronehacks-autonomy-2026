# Course layout worker handoff

Repository: `Cyberchopin/dronehacks-autonomy-2026`.
Branch: `course/layout-map`, based on `29c84bd`.
Working directory: `/home/shiyue1128/dronehacks-autonomy-2026`.

All implementation and derived files are under `course/`. No protected paths,
flight/simulator interfaces, run/recording data, or credentials were used.
The large source model remains outside the checkout. No PR, merge, or push was made.

## Result

- 33 source groups, with metre/XYZ/Z-up AABBs and explicitly defined AABB midpoints.
- 122 rows × 122 columns at 0.05 m/cell; origin approximately `[-3.05, -3.05]` m.
- 2,743 occupied cells; 23 groups contribute geometry, 10 floor/marking/roof groups are excluded from occupancy but retained as features.
- Independent parsing of raw group vertices confirmed all 33 bounds and centroids and the source SHA-256. All four grid edges are occupied by the side nets.
- 29 offline synthetic tests pass, including negative/outside queries, upper-edge rounding, rotated footprints, thin/vertical triangles, metadata conflicts, and deterministic CLI output.
- No feature coordinates are embedded in the extractor.

Changed files:

1. `course/extract_layout.py`
2. `course/layout.json`
3. `course/tests/test_extract_layout.py`
4. `course/README.md`
5. `course/HANDOFF.md`

## Setup

```text
$ git clone https://github.com/Cyberchopin/dronehacks-autonomy-2026
Cloning into 'dronehacks-autonomy-2026'...
$ cd /home/shiyue1128/dronehacks-autonomy-2026
$ git checkout -b course/layout-map
Switched to a new branch 'course/layout-map'
```

The local source directory was confirmed with `ls -l`. Its model files are
`dronehacks-course-v3.obj`, `dronehacks-course-v3.mtl`, and
`dronehacks-course-v3.step`.

System Python lacked NumPy/pytest/Ruff, so the checks reused an existing local
environment without modifying it. All generated test/cache files were directed
under `course/` (ignored by the repository's existing ignore rules).
The shell environment for the exact acceptance commands below was:

```bash
export PATH=/home/shiyue1128/aegisland-agentic-vision/.venv/bin:$PATH
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTEST_ADDOPTS='-o addopts= -o cache_dir=course/.pytest_cache --basetemp=course/.test-tmp/pytest-final'
export RUFF_CACHE_DIR=course/.ruff_cache
mkdir -p course/.test-tmp
```

```text
$ python3 --version
python3 -m pytest --version
ruff --version
Python 3.12.15
pytest 8.4.2
ruff 0.16.4
```

NumPy in that environment is 2.5.2.

## Acceptance commands and captured output

```text
$ python3 course/extract_layout.py "/mnt/c/Users/wangs/Downloads/Stanford-DroneHacks-迁移包/Stanford-DroneHacks-migration/dronehacks-course-v3-obj/dronehacks-course-v3.obj" --out course/layout.json
Wrote course/layout.json: 33 features
Grid: 122 rows x 122 columns; 0.05 m/cell; origin XY [-3.0500000000000003, -3.0500000000000003]
Occupied cells: 2743
Source SHA-256: e610bcf9666422e2a0a78cb46f542fc8c4d5a7ef9b15f6123f1abe40f5b8e9e1
Barrier 3 (cut to 55 in): UNKNOWN: axis intended by the cut label; use measured XYZ bounds, not the name.
Tube oval 58 x 72 x 60: UNKNOWN: dimension order in the name; use measured XYZ bounds.
C2a chicane wall (window): UNKNOWN: aperture bounds; this group's bounds describe the entire wall.
Approach ring (stage 4 line): UNKNOWN: stage label meaning; this floor ring is not checkpoint 4 (Gate B/window).
UNKNOWN semantic priors: gate_a, gate_b, window_aperture
```

Exit status: 0.

```text
$ python3 -m pytest -q course/tests/test_extract_layout.py
.............................                                            [100%]
29 passed in 0.69s
```

Exit status: 0.

```text
$ ruff check course && ruff format --check course
All checks passed!
4 files already formatted
```

Exit status: 0.

The Ruff output above is the final check, including this handoff document.

## UNKNOWN items and limitations

- Gate A and Gate B do not have explicit group names in the supplied v3. Their separate gate-plane/aperture coordinates remain UNKNOWN/null.
- `C2a chicane wall (window)`: whole-wall bounds are extracted; opening bounds and centroid remain UNKNOWN/null. The task's checkpoint 4 is Gate B / the window.
- `Approach ring (stage 4 line)`: a floor marking, not checkpoint 4; the stage label's meaning is UNKNOWN.
- `Barrier 3 (cut to 55 in)`: the name's intended axis is UNKNOWN. Measured X span is 1.397 m; measured Z span is 1.7272 m. The label is not used to infer height.
- `Tube oval 58 x 72 x 60`: the label's dimension order is UNKNOWN. Measured XYZ spans are preserved.
- Boulders measure about 0.4572 m across and 0.5334 m tall; the latter differs from treating “about 18 in” as height.
- Projection over all heights closes the tunnel/window footprints. This is a conservative 2-D obstacle prior, not an aperture/altitude clearance model or a route.
- Repository CI currently selects `src/` and top-level `tests/`, not `course/`. CI integration is left to the Router because workflow edits are outside this ownership.
- Ruff **0.16.4** passed. Compatibility with the repository's pinned Ruff **0.14.3** is **UNKNOWN**: downloading that version failed because package-host DNS was unavailable.

Exact pinned-version installation attempt (exit 2; no course data was fetched):

```text
$ mkdir -p course/.test-tmp/uv
$ TMPDIR=/home/shiyue1128/dronehacks-autonomy-2026/course/.test-tmp/uv UV_NO_CACHE=1 uv pip install --python /home/shiyue1128/aegisland-agentic-vision/.venv/bin/python --target course/.deps ruff==0.14.3
Using CPython 3.12.15 interpreter at: /home/shiyue1128/aegisland-agentic-vision/.venv/bin/python
error: Request failed after 3 retries in 4.2s
  cause: Failed to fetch: https://pypi.org/simple/ruff/
  cause: error sending request for url (https://pypi.org/simple/ruff/)
  cause: client error (Connect)
  cause: dns error
  cause: failed to lookup address information: Temporary failure in name resolution
```

Earlier local checks: the first pytest invocation had 28 setup errors because
the parent of the configured temporary directory did not exist; creating
`course/.test-tmp` resolved that setup failure. Initial Ruff findings (import
ordering and a redundant pair of `startswith` calls) were corrected. Review
then identified and fixed rounding at the final representable in-map point;
the regression test is included in the passing 29-test run.

See `README.md` for schema, regeneration, source credit, input restrictions,
and runtime loading. The published coordinates are preliminary and may change.
