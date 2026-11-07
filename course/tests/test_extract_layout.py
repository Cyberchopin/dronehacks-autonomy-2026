"""Offline synthetic geometry only; no published model or run data required."""

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from course.extract_layout import OutOfMapError, extract_layout, query_occupancy, world_to_cell


def write_obj(tmp_path, text):
    path = tmp_path / "synthetic.obj"
    path.write_text(text, encoding="utf-8")
    return path


def test_group_bounds_keep_metres_z_up_and_full_names(tmp_path):
    source = """# Units = meters; Z-up
g Rotated wall with spaces
v 1 -2 0.25
v 3 -1 1.75
o separate_surface_not_a_feature
v 3 -1 0.25
vn 99 99 99
g Launch mark
v -1 0.2 0.001
v -0.8 0.4 0.002
g Rotated wall with spaces
v 2 -1.5 0.5
"""
    path = write_obj(tmp_path, source)
    layout = extract_layout(path)
    assert layout["feature_count"] == 2
    wall = layout["features"]["Rotated wall with spaces"]
    assert wall["bounds"] == {"min": [1, -2, 0.25], "max": [3, -1, 1.75]}
    assert wall["centroid"] == [2, -1.5, 1]
    assert wall["vertex_count"] == 4
    assert layout["header"]["units"] == "metres"
    assert layout["header"]["axes"]["up"] == "+Z"
    assert layout["header"]["source_file"] == "synthetic.obj"
    assert layout["header"]["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not layout["features"]["Launch mark"]["include_in_occupancy"]
    # Loading the model again must use the new coordinates, not cached priors.
    path.write_text(source.replace("v 3 -1 1.75", "v 4 -1 2.25"), encoding="utf-8")
    updated = extract_layout(path)
    assert updated["features"]["Rotated wall with spaces"]["bounds"]["max"] == [4, -1, 2.25]
    assert updated["header"]["source_sha256"] != layout["header"]["source_sha256"]


@pytest.fixture
def small_layout(tmp_path):
    path = write_obj(
        tmp_path,
        """g Floor
v -0.52 -0.27 -0.02
v 0.76 0.51 0
g Wall
v -0.12 -0.02 0
v 0.12 0.02 1.7
""",
    )
    return extract_layout(path, resolution=0.25)


def test_grid_origin_resolution_indexing_and_round_trip(small_layout):
    layout = json.loads(json.dumps(small_layout, allow_nan=False))
    grid = layout["occupancy"]
    assert grid["origin_xy"] == [-0.75, -0.5]
    assert grid["resolution_m"] == 0.25
    assert grid["shape_yx"] == [5, 7]
    assert grid["extent_max_xy"] == [1.0, 0.75]
    assert np.asarray(grid["cells"]).shape == (5, 7)
    assert world_to_cell(layout, -0.625, -0.375) == (0, 0)
    assert world_to_cell(layout, 0.125, 0.125) == (2, 3)
    assert query_occupancy(layout, 0, 0) == 1
    assert query_occupancy(layout, -0.625, -0.375) == 0
    assert query_occupancy(layout, -0.75, -0.5) == 0
    assert layout["features"]["Wall"]["projection_method"] == "aabb_fallback"


@pytest.mark.parametrize("point", [(-0.750001, 0), (0, -0.500001), (1, 0), (0, 0.75), (1e6, 1e6)])
def test_out_of_map_is_explicit(small_layout, point):
    with pytest.raises(OutOfMapError, match="outside"):
        query_occupancy(small_layout, *point)


def test_last_representable_in_map_position_is_inside(small_layout):
    max_x, max_y = small_layout["occupancy"]["extent_max_xy"]
    point = (math.nextafter(max_x, -math.inf), math.nextafter(max_y, -math.inf))
    assert world_to_cell(small_layout, *point) == (4, 6)
    assert query_occupancy(small_layout, *point) == 0


@pytest.mark.parametrize("point", [(math.nan, 0), (0, math.inf), (-math.inf, 0)])
def test_nonfinite_query_rejected(small_layout, point):
    with pytest.raises(ValueError, match="finite"):
        query_occupancy(small_layout, *point)


def test_rotated_mesh_uses_footprint_not_axis_aligned_box(tmp_path):
    path = write_obj(
        tmp_path,
        """g Floor
v -0.2 -0.2 -0.01
v 1.2 1.2 0
g Rotated wall
v 0 0 1.7
v 1 1 1.7
v 1 0.9 1.7
v 0 -0.1 1.7
f 3 4 5
f -4 -2 -1
""",
    )
    layout = extract_layout(path, resolution=0.05)
    assert query_occupancy(layout, 0.52, 0.47) == 1
    # This point lies inside the wall AABB but outside its rotated footprint.
    assert query_occupancy(layout, 0.12, 0.82) == 0
    assert layout["features"]["Rotated wall"]["triangle_count"] == 2


def test_projection_catches_subcell_obstacles_and_vertical_faces(tmp_path):
    path = write_obj(
        tmp_path,
        """g Floor
v 0 0 -0.01
v 1 1 0
g Small obstacle
v 0.011 0.011 0.5
v 0.019 0.011 0.5
v 0.011 0.019 0.5
f 3/1/1 4/1/1 5/1/1
g Vertical wall
v 0.3 0.3 0
v 0.3 0.8 0
v 0.3 0.3 1.7
f 6//1 7//1 8//1
""",
    )
    layout = extract_layout(path, resolution=0.1)
    assert query_occupancy(layout, 0.05, 0.05) == 1
    assert query_occupancy(layout, 0.25, 0.55) == 1
    assert query_occupancy(layout, 0.55, 0.55) == 0
    assert layout["features"]["Small obstacle"]["kind"] == "UNKNOWN"


def test_exclusions_require_matching_geometry_and_ambiguities_stay_unknown(tmp_path):
    path = write_obj(
        tmp_path,
        """g Floor
v -1 -1 -0.01
v 1 1 0
g Net roof
v -1 -1 3
v 1 1 3.001
g Approach ring (stage 4 line)
v -0.9 -0.9 0
v 0.9 0.9 0.001
g C2a chicane wall (window)
v -0.1 -0.1 0
v 0.1 0.1 1.7
g Launch mark suspended above floor
v 0.5 0.5 2
v 0.6 0.6 2.001
""",
    )
    layout = extract_layout(path)
    assert query_occupancy(layout, -0.5, -0.5) == 0
    assert query_occupancy(layout, 0.55, 0.55) == 1
    assert query_occupancy(layout, 0, 0) == 1
    assert layout["features"]["Launch mark suspended above floor"]["kind"] == "UNKNOWN"
    assert layout["semantic_priors"]["gate_a"]["status"] == "UNKNOWN"
    assert layout["semantic_priors"]["gate_b"]["bounds"] is None
    assert layout["semantic_priors"]["window_aperture"]["centroid"] is None
    assert layout["semantic_priors"]["gate_b"]["window_wall_groups"] == [
        "C2a chicane wall (window)"
    ]
    assert "not checkpoint 4" in layout["features"]["Approach ring (stage 4 line)"]["flags"][0]


@pytest.mark.parametrize("resolution", [0, -1, math.nan, math.inf])
def test_invalid_resolution_is_rejected(tmp_path, resolution):
    path = write_obj(tmp_path, "g Wall\nv 0 0 0\nv 1 1 1\n")
    with pytest.raises(ValueError, match="resolution"):
        extract_layout(path, resolution)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("# Units = millimeters\ng Wall\nv 1 2 3\n", "expected metres"),
        ("# Y-up\ng Wall\nv 1 2 3\n", "expected Z-up"),
        ("g Wall\nv nan 0 0\n", "finite"),
        ("v 0 0 0\n", "named g"),
        ("g Wall\nv 0 0 0\nf 1 2 3\n", "undeclared vertex"),
        ("g Wall\nv 0 0 0\nf 0 1 1\n", "one-based"),
        ("g Wall\nv 0 0 0\ng Other\nv 1 1 1\nf 1 2 2\n", "another group"),
        ("g Wall\nv 0 0 0\ng Empty\n", "no local v"),
        ("# empty\n", "no grouped vertices"),
        ("g Wall\nv 0 0 0\nf 1 1 1 1\n", "triangulate"),
    ],
)
def test_incompatible_or_malformed_input_fails_explicitly(tmp_path, source, message):
    with pytest.raises(ValueError, match=message):
        extract_layout(write_obj(tmp_path, source))


def test_cli_writes_deterministic_json(tmp_path):
    path = write_obj(tmp_path, "g Boulder\nv -0.2 -0.2 0\nv 0.2 0.2 0.5\n")
    output = tmp_path / "layout.json"
    script = Path(__file__).resolve().parents[1] / "extract_layout.py"
    command = [sys.executable, str(script), str(path), "--out", str(output), "--cell-size", "0.1"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    assert "1 features" in completed.stdout
    assert completed.stderr == ""
    before = output.read_bytes()
    assert json.loads(before) == extract_layout(path, resolution=0.1)
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert output.read_bytes() == before
