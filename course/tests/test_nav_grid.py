import pytest

from course.extract_layout import extract_layout, query_occupancy, world_to_cell
from course.mesh_geometry import load_mesh
from course.nav_grid import build_nav_grid
from course.tests.mesh_fixtures import rectangle, slab, tube_mesh, window_mesh, write_mesh


def test_window_is_open_at_valid_heights_but_not_through_the_whole_band(tmp_path):
    source = write_mesh(tmp_path / "window.obj", {"Wall with window": window_mesh()})
    old = extract_layout(source)
    nav = build_nav_grid(*load_mesh(source), old, z_min=0.4, z_max=1.6, z_step=0.2, height=0.8)
    assert query_occupancy(old, 0, 0.05) == 1
    assert query_occupancy(nav, 0, 0.05) == 0
    assert query_occupancy(nav, 0.8, 0.05) == 1
    row, column = world_to_cell(nav, 0, 0.05)
    lower = nav["sample_heights_m"].index(0.8)
    upper = nav["sample_heights_m"].index(1.6)
    assert nav["free_height_masks"][row][column] & (1 << lower)
    assert not nav["free_height_masks"][row][column] & (1 << upper)
    assert nav["layers"][upper]["cells"][row][column] == 1
    assert nav["occupancy"]["origin_xy"] == old["occupancy"]["origin_xy"]
    assert nav["occupancy"]["resolution_m"] == old["occupancy"]["resolution_m"]
    assert len(nav["unknowns"]) == 2  # No geometry fallback; only declared clearance limits.


def test_tube_interior_is_free_and_solid_wall_interior_is_filled(tmp_path):
    source = write_mesh(
        tmp_path / "tube.obj",
        {"Tube oval": tube_mesh(), "Solid wall": slab(rectangle(-1, 1.5, -0.2, 2.8), z1=2)},
    )
    old = extract_layout(source)
    nav = build_nav_grid(*load_mesh(source), old, z_min=1, z_max=1, height=1)
    assert query_occupancy(old, 1, 2.4) == 1
    assert query_occupancy(nav, 1, 2.4) == 0
    assert query_occupancy(nav, 1.55, 2.4) == 1
    # A surface-only rasteriser would incorrectly leave this thick solid's centre free.
    assert query_occupancy(nav, -0.6, 2.1) == 1
    assert not nav["unknowns"][:-2]


def test_reference_source_mismatch_is_rejected(tmp_path):
    source = write_mesh(tmp_path / "tiny.obj", {"Wall": slab(rectangle(0, 0, 1, 0.1), z1=2)})
    old = extract_layout(source)
    old["header"]["source_sha256"] = "different"
    with pytest.raises(ValueError, match="SHA-256"):
        build_nav_grid(*load_mesh(source), old)


def test_invalid_band_fails_before_any_geometry():
    with pytest.raises(ValueError, match="height band"):
        build_nav_grid({}, {}, {}, z_min=2, z_max=1)
