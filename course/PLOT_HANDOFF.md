# Course visualization worker handoff

Repository: `Cyberchopin/dronehacks-autonomy-2026`.
Branch: `course/layout-map`, continuing from `e884f9c`.
Working directory: `/home/shiyue1128/dronehacks-autonomy-2026`.

The PNG renders the committed JSON; the source OBJ and existing JSON were not
modified. All task changes are under `course/`. No protected paths, simulator,
flight interfaces, GPU, run/recording data, or credentials were used. The only
network operations were Git operations against the user's repository.

## Files changed

- `course/plot_layout.py` — headless Agg renderer and coverage report.
- `course/layout.png` — regenerable map for inspection and presentation.
- `course/tests/test_plot_layout.py` — offline synthetic JSON/PNG tests.
- `course/README.md` — plotting usage, dependencies, and interpretation.
- `course/PLOT_HANDOFF.md` — this command/output record.

## Coverage and interpretation

Every one of the 33 features has an XY bounding rectangle, a map ID, and a full
name in the feature key. All seven UNKNOWN records are shown: four flagged
feature bounds have orange dashed outlines and question marks; three unlocated
semantic priors are listed in the UNKNOWN register without invented positions.
The output was visually inspected for readable labels, legend, source SHA-256,
scale bar, occupancy orientation, and the complete feature/UNKNOWN keys.

The background uses the JSON's 122 × 122 occupancy array, origin approximately
`[-3.05, -3.05]` m, and 0.05 m resolution. X increases right, Y increases up.
The scale bar is 1 m, computed from the map extent and rendered at the actual
map scale. The source SHA-256 is printed in full and embedded in PNG metadata.

Outlines are the JSON's **AABBs**, not reconstructed mesh outlines. This is
particularly relevant to rotated walls and pad/approach rings. Coincident
bounds can overlap; every feature still has its own label and key entry.
The occupancy projection spans all heights, so tunnel/window passage clearance
is not established by this 2-D image.

## Existing branch push

The branch was already pushed by the prior task. The requested command was
run again after confirming the push remote was the user's repository:

```text
$ git remote get-url --push origin
https://github.com/Cyberchopin/dronehacks-autonomy-2026
$ git push -u origin course/layout-map
Everything up-to-date
branch 'course/layout-map' set up to track 'origin/course/layout-map'.
```

The visualization changes are committed and pushed on that same branch;
the resulting commit and push outcome are reported in the final reply.
No PR or merge is requested or performed, and no team-repository remote is used.

## Local environment

Rendering used an existing Python 3.14.4 environment with NumPy 2.5.4 and
Matplotlib 3.11.2. Pytest 8.4.2 and its missing pure-Python dependencies were
reused from an existing local environment via symlinks under ignored
`course/.deps/`. No package download or environment outside `course/` was needed.
Ruff 0.16.4 was reused from the existing local executable. Compatibility with
the repository's pinned Ruff 0.14.3 remains **UNKNOWN**, as recorded in the
earlier extraction handoff.

These environment settings kept generated caches and test fixtures under
`course/` and made the commands below reproducible on this machine:

```bash
export PATH=/home/shiyue1128/sasenv/bin:/home/shiyue1128/aegisland-agentic-vision/.venv/bin:$PATH
export PYTHONPATH=/home/shiyue1128/dronehacks-autonomy-2026/course/.deps
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR=/home/shiyue1128/dronehacks-autonomy-2026/course/.test-tmp/matplotlib
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTEST_ADDOPTS='-o addopts= -o cache_dir=course/.pytest_cache --basetemp=course/.test-tmp/plot-pytest-2'
export RUFF_CACHE_DIR=course/.ruff_cache
```

Use a fresh `--basetemp` on subsequent runs. On another machine, use a Python
environment with NumPy, Matplotlib, pytest, and Ruff installed normally.

## Acceptance commands

```text
$ python3 course/plot_layout.py course/layout.json --out course/layout.png
Wrote course/layout.png: 3960 x 2160 pixels; 610691 bytes
Features: 33/33 outlined and labelled
UNKNOWN: 7 records shown; 4 flagged feature bounds; 3 unlocated priors listed without coordinates
Scale bar: 1 m; axes: X right, Y up, Z-up top-down
```

Exit status: 0.

```text
$ python3 -m pytest -q course/tests/
................................                                         [100%]
32 passed in 2.40s
```

Exit status: 0.

```text
$ ruff check course && ruff format --check course
All checks passed!
7 files already formatted
```

Exit status: 0.

PNG: **3960 × 2160 pixels**, **610,691 bytes**. All 33 features and all 7 UNKNOWN
records are represented, as described above. The renderer was run again after
the code cleanup and produced the same byte count. The tests exercise the Agg
backend, a synthetic PNG, grid orientation/extent, every feature outline and
label, UNKNOWN coverage without added coordinates, and scale-bar calibration.

## Remaining UNKNOWN items

- `gate_a`, `gate_b`, and `window_aperture`: coordinates remain UNKNOWN / UNLOCATED.
- `C2a chicane wall (window)`: only whole-wall bounds are established here.
- `Approach ring (stage 4 line)`: the stage-label meaning remains UNKNOWN; it is not checkpoint 4.
- `Barrier 3 (cut to 55 in)`: the label's intended dimension axis remains UNKNOWN.
- `Tube oval 58 x 72 x 60`: dimension order in its label remains UNKNOWN.
- The current repository CI does not select `course/` and does not declare Matplotlib. The requested checks were run directly; CI/package edits are outside this task's ownership.

Initial setup required adding pytest's `py.py` compatibility shim to the local
dependency links after a missing-module error. Initial Ruff findings (import
order and a nested conditional) were corrected before the passing test run.
