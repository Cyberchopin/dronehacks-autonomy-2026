# Published course layout priors

map from the published layout (rule 6.4); feature priors, not a hard-coded route; coordinates are preliminary and may change.

`extract_layout.py` reads the current published OBJ and returns or writes named
feature bounds, AABB midpoints, and a coarse XY obstacle grid. There are no flight
waypoints, timings, traversal order, flight interfaces, or simulator imports.
Extraction dependencies are Python 3.11+ and NumPy. The PNG renderer additionally
requires Matplotlib; tests require pytest and, for plotting tests, Matplotlib.

The source is the **published DroneHacks 2026 course model, v3**,
`dronehacks-course-v3.obj`, distributed with its MTL, STEP, and `README.txt`.
Credit for the layout belongs to the published course model's authors. The OBJ
header identifies an Onshape/PTC export; the accompanying README specifies
metres, Z-up, and the floor-centre origin. The local STEP declares metre units
and corroborates the piece names. The extractor uses the OBJ geometry only;
it does not read MTL, STEP, external references, network sources, runs, or recordings.
The source model is not included in this repository.

## Regenerate and load

From the repository root, pass the path to the current published OBJ:

```bash
python3 course/extract_layout.py /path/to/dronehacks-course-v3.obj --out course/layout.json
python3 course/extract_layout.py /path/to/dronehacks-course-v3.obj --cell-size 0.1 --out course/layout.json
```

The default cell size is **0.05 m**. Output is deterministic, with the source
basename and SHA-256 of the exact parsed bytes in its header. No absolute host
path or timestamp is stored. Regenerate after every model revision.

For runtime use, load the model rather than assuming this checked-in JSON is current:

```python
from course.extract_layout import OutOfMapError, extract_layout, query_occupancy

layout = extract_layout(model_path, resolution=0.05)
try:
    occupied = query_occupancy(layout, x, y)  # 0 or 1
except OutOfMapError:
    occupied = None  # Explicitly unknown; the caller chooses its handling.
```

The caller supplies `model_path`, `x`, and `y`. Import from the repository root or
put the repository root on Python's import path; the existing `src/` package
configuration does not install `course/`. A separate consumer can parse the JSON
with `json.load`, then use the same query functions. Source updates always require
re-extraction; the JSON is a snapshot, not an automatic model update mechanism.

## Schema (version 1)

| Field | Meaning |
| --- | --- |
| `header` | Source filename/SHA-256, metre/Z-up frame contract, provenance, centroid definition |
| `model_bounds.min`, `.max` | Bounds of every source vertex, in `[x, y, z]` metres |
| `feature_count` | Number of named OBJ `g` groups |
| `features[group_name].bounds.min`, `.max` | Group-local XYZ vertex bounds; rotation is retained in the mesh, but these bounds are axis-aligned |
| `features[group_name].centroid` | `(min + max) / 2`; **AABB midpoint**, not a volume centroid or an aperture/flight target |
| `vertex_count`, `triangle_count` | Source geometry counts per group |
| `kind`, `include_in_occupancy`, `reason` | Name-derived semantic label, occupancy decision, and explanation |
| `projection_method`, `flags` | Triangle projection, conservative AABB fallback, or exclusion; explicit UNKNOWN annotations |
| `semantic_priors` | Unresolved gate and window-aperture identities, null coordinates, and references to candidate wall groups |
| `occupancy.origin_xy` | Lower-left corner of cell `[0][0]`, aligned down to resolution from the model's minimum XY |
| `occupancy.resolution_m` | Square cell width in metres |
| `occupancy.shape_yx` | `[number_of_rows, number_of_columns]` |
| `occupancy.cells` | Nested integer array indexed `[row_y][column_x]`; +Y increases row, +X increases column |
| `occupancy.extent_max_xy` | Exclusive upper XY extent, including grid padding |
| `occupancy.occupied_cell_count` | Number of cells containing projected geometry |

Cell centres are `origin_xy + resolution_m * [column + 0.5, row + 0.5]`.
Coordinates are not scaled, recentered, or reordered. Minimum map boundaries are
included; maximum boundaries are excluded. `world_to_cell` and `query_occupancy`
raise `OutOfMapError` outside these bounds, and `ValueError` for nonfinite queries.
They do not wrap negative indices or silently treat outside space as free.

## Projection and limits

The grid marks every cell intersecting an included mesh triangle's XY projection,
including thin or vertical surfaces and intersections away from cell centres.
This preserves rotated-wall footprints instead of filling their whole AABBs.
Cells touching geometry at a boundary may both be occupied. It is a conservative
discretisation without vehicle-radius inflation. `0` means no included geometry
projects there; it does not establish collision-free flight or usable clearance.

Walls, barriers, maze dividers, boulders, tunnel supports, tunnel shell, and side
nets contribute to occupancy. The floor, overhead roof net, and floor markings
remain in `features` but do not occupy the entire map. Named pads/markings must
lie within `--surface-tolerance` metres of source Z=0 (default 0.01 m) to be
excluded. A label that conflicts with this check becomes UNKNOWN and remains an
obstacle. Unrecognised groups are also conservatively included. An obstacle with
vertices but no faces uses its XY AABB and receives an explicit UNKNOWN flag.

**This projects all heights.** The tube roof and wall above/below the window
therefore occupy their footprints. A 2-D projection cannot describe passage
through these openings or ceiling clearance. Use the full geometry and other
perception for those decisions; neither a group centroid nor a free grid cell
is a flight waypoint.

The parser deliberately follows the published Onshape dialect: the complete
`g` label, including spaces, identifies one feature; its following `v` lines
belong to that feature. `o` surface records do not split features. Repeated
group labels merge. Triangular faces support global positive or relative
negative vertex indices and slash-separated texture/normal fields. Invalid
indices, ungrouped vertices, cross-group references, empty groups, non-triangular
faces, and nonfinite coordinates fail explicitly. General OBJ files with one
global vertex block before their groups must be converted to this dialect.
Declared incompatible units or X/Y-up comments are rejected; absent metadata
cannot prove units or axes, so metre/Z-up remains the input contract. There is
a 4,000,000-cell allocation limit.

## Verified v3 geometry and UNKNOWN items

The supplied v3 has 33 named groups. Geometry gives a 6.096 m square floor,
wall Z extents of 1.7272 m, and 0.1016 m thickness for axis-aligned walls.
Rotated walls' XY AABB spans are not their local thickness or length.
The boulders are approximately 0.4572 m across but **0.5334 m tall** in this model.
The largest landing-pad ring spans approximately 1.524 m. These observations
describe this source only; none are baked into the extraction code.

- **Gate A / Gate B:** no groups explicitly have these names in v3. Their
  separate gate planes/aperture coordinates remain **UNKNOWN**. The task's
  checkpoint description identifies checkpoint 4 as Gate B / the window.
- **`C2a chicane wall (window)`:** the model contains the wall and opening, but
  its group bounds describe the entire wall. The extractor does not infer an
  aperture from its name; aperture bounds and centroid remain **UNKNOWN**.
- **`Approach ring (stage 4 line)`:** a thin floor ring, **not checkpoint 4**.
  The meaning of the stage label is **UNKNOWN**. It remains a marking prior.
- **`Barrier 3 (cut to 55 in)`:** the label does not specify an axis. The measured
  X span is 1.397 m (55 in), while its height is 1.7272 m (68 in).
  The label's intended axis remains flagged **UNKNOWN**, rather than treating
  55 in as the height.
- **`Tube oval 58 x 72 x 60`:** dimension order in the name is **UNKNOWN**.
  Measured XYZ spans are approximately `[1.47304, 1.524, 1.8288]` m.

Landing-pad rings, cross, launch mark, guideline, boulders, supports, maze walls,
barriers, and net pieces are all available under their original group names.
No group is silently dropped or assigned a checkpoint based on a suggestive label.

## Top-down PNG

```bash
python3 course/plot_layout.py course/layout.json --out course/layout.png
```

`plot_layout.py` uses Matplotlib's headless **Agg** backend. Install Matplotlib
in the environment used to run this command and the full `course/tests/` suite;
it is not currently declared by the repository's top-level package configuration.
The renderer reads only the supplied JSON and writes the PNG. `--dpi` controls
output resolution (default 180; accepted range 40–600).

The image includes the full source filename and SHA-256, a metre scale bar,
and the occupancy array with X increasing right and Y increasing up. Its real
origin, resolution, and row/column shape come from the JSON. Every named feature
has a numbered label on the map and its full name in the feature key. The IDs
index source groups; they do not prescribe a route.

**Feature outlines are XY AABBs**, because the JSON does not store individual
mesh outlines. This includes the rectangular bounds of rings and rotated walls;
the more detailed obstacle footprints are visible in the occupancy background.
Coincident bounds can overlap. Excluded floor/marking/roof groups use dotted
outlines. A feature carrying an UNKNOWN flag uses an orange dashed outline and
a question mark; the complete issue appears in the UNKNOWN register.

Unlocated semantic priors such as gate/window apertures appear **only in that
register**, explicitly marked UNKNOWN / UNLOCATED. They receive no guessed map
position. The v3 render contains all **33 feature bounds and labels** and all
**7 UNKNOWN records**: 4 flagged features and 3 unlocated semantic priors.
The CLI reports these counts and the PNG's pixel dimensions and byte size.
`build_figure(layout)` also returns the coverage report for programmatic use.

The committed image is a presentation/checking artifact of the committed JSON.
After updating the model, regenerate the JSON first, then regenerate the image.

## Offline checks

```bash
python3 -m pytest -q course/tests/
ruff check course && ruff format --check course
```

Tests construct tiny OBJs locally and require neither the large published model
nor network access. For ownership-isolated test runs, first run
`mkdir -p course/.test-tmp`, then set `PYTHONDONTWRITEBYTECODE=1`,
`PYTEST_ADDOPTS="-o cache_dir=course/.pytest_cache --basetemp=course/.test-tmp/pytest"`,
`RUFF_CACHE_DIR=course/.ruff_cache`, and
`MPLCONFIGDIR="$PWD/course/.test-tmp/matplotlib"`; use a fresh `--basetemp` for each run.
The current repository workflow checks `src/` and top-level `tests/` explicitly;
it does not yet select `course/`. The commands above verify this directory
without changing that workflow outside this task's ownership.
