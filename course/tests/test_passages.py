import numpy as np
import pytest

from course.passages import (
    extract_passages,
    extract_tunnel,
    extract_window,
    gap_between_edges,
    wall_geometry,
)
from course.tests.mesh_fixtures import rectangle, slab, tube_mesh, window_mesh


def test_window_hole_in_rotated_wall_has_inner_dimensions_and_sill():
    angle = 0.41
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
    )
    translation = np.array([2, -3, 0.2])
    triangles = window_mesh() @ rotation.T + translation
    result = extract_window(triangles)
    np.testing.assert_allclose(
        result["centre_xyz"], np.array([0, 0.05, 0.8]) @ rotation.T + translation, atol=1e-8
    )
    assert result["width_m"] == pytest.approx(0.8)
    assert result["height_m"] == pytest.approx(1.0)
    assert result["sill_height_m"] == pytest.approx(0.5)
    assert result["wall_thickness_m"] == pytest.approx(0.1)


def test_short_tube_uses_inner_caps_not_outer_box_or_longest_axis():
    result = extract_tunnel(tube_mesh(), approach_xy=[1, 0])
    assert result["inner_width_m"] == pytest.approx(1.0)
    assert result["inner_height_m"] == pytest.approx(1.4)
    np.testing.assert_allclose(result["entry_centre_xyz"], [1, 2, 1], atol=1e-8)
    np.testing.assert_allclose(result["exit_centre_xyz"], [1, 2.8, 1], atol=1e-8)
    np.testing.assert_allclose(result["passage_axis"], [0, 1, 0], atol=1e-8)
    assert extract_tunnel(tube_mesh())["direction_status"] == "UNKNOWN"


def test_solid_wall_has_no_window_hole():
    with pytest.raises(ValueError, match="enclosed hole"):
        extract_window(slab(rectangle(-1, 0, 1, 0.1), z1=2))


def test_gap_is_bounded_by_measured_wall_ends():
    left = wall_geometry(slab(rectangle(-2, -0.1, -0.5, 0.1), z1=1.5))
    right = wall_geometry(slab(rectangle(0.5, -0.1, 2, 0.1), z1=1.5))
    result = gap_between_edges(left["ends"][1], right["ends"][0])
    np.testing.assert_allclose(result["centre_xy"], [0, 0], atol=1e-10)
    np.testing.assert_allclose(result["crossing_line_xy"], [[-0.5, 0], [0.5, 0]], atol=1e-10)
    assert result["width_m"] == pytest.approx(1)
    assert result["height_status"] == "UNKNOWN"
    assert result["official_scoring_line_status"] == "UNKNOWN"


def test_crossing_edges_do_not_create_a_false_gap():
    with pytest.raises(ValueError, match="edges touch"):
        gap_between_edges([[-1, 0], [1, 0]], [[0, -1], [0, 1]])


def test_gate_b_identity_is_not_guessed_from_neighbouring_wall_names():
    groups = {
        "A approach wall": slab(rectangle(-0.1, 0, 0.1, 2), z1=1.5),
        "C chicane wall": slab(rectangle(0.9, -2, 1.1, -0.5), z1=1.5),
    }
    unresolved = extract_passages(groups, {})["passages"]["gate_b"]
    assert unresolved["status"] == "UNKNOWN"
    assert unresolved["candidate"]["width_m"] == pytest.approx(np.hypot(0.8, 0.5))
    confirmed = extract_passages(groups, {}, gate_b_groups=list(groups))["passages"]["gate_b"]
    assert confirmed["status"] == "RESOLVED"
    assert confirmed["centre_xy"] == unresolved["candidate"]["centre_xy"]
