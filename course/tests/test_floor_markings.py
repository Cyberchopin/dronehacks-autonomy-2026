import numpy as np
import pytest

from course.floor_markings import extract_markings
from course.tests.mesh_fixtures import circle_mark, rectangle, slab


def test_l_strip_centreline_is_mesh_derived_and_oriented_by_launch():
    polygon = np.array([[0, 0], [2, 0], [2, 0.2], [0.2, 0.2], [0.2, 2], [0, 2]])
    angle = 0.37
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    shift = np.array([3, -1])
    centreline = np.array([[2, 0.1], [0.1, 0.1], [0.1, 2]]) @ rotation.T + shift
    groups = {
        "Guideline": slab(polygon @ rotation.T + shift),
        "Launch mark": circle_mark(0.04, centreline[0]),
    }
    result = extract_markings(groups, {})
    stroke = result["features"]["Guideline"]["strokes"][0]
    np.testing.assert_allclose(stroke["polyline_xy"], centreline, atol=1e-8)
    assert stroke["width_m"] == pytest.approx(0.2)
    assert stroke["fit_rms_m"] < 1e-8
    assert stroke["direction_status"] == "INFERRED_FROM_LAUNCH"


def test_disjoint_strokes_are_not_joined_or_ordered():
    strokes = np.r_[slab(rectangle(0, 0, 2, 0.1)), slab(rectangle(3, 1, 4, 1.1))]
    result = extract_markings({"Guideline": strokes}, {})["features"]["Guideline"]
    assert result["stroke_order_status"] == "UNKNOWN"
    assert len(result["strokes"]) == 2
    assert all(len(stroke["polyline_xy"]) == 2 for stroke in result["strokes"])
    assert all(stroke["direction_status"] == "UNKNOWN" for stroke in result["strokes"])


def test_ring_and_launch_circle_fits_include_real_inner_and_outer_edges():
    groups = {
        "Landing pad ring": circle_mark(0.6, (2, -1), inner=0.5),
        "Launch mark": circle_mark(0.1, (-1, 3)),
    }
    result = extract_markings(groups, {})["features"]
    ring = result["Landing pad ring"]
    np.testing.assert_allclose(ring["centre_xy"], [2, -1], atol=1e-10)
    assert ring["radius_m"] == pytest.approx(0.55)
    assert ring["inner_radius_m"] == pytest.approx(0.5)
    assert ring["outer_radius_m"] == pytest.approx(0.6)
    assert ring["fit_rms_m"] < 1e-10
    assert ring["boundary_fits"][0]["chord_midpoint_max_error_m"] > 0
    np.testing.assert_allclose(result["Launch mark"]["centre_xy"], [-1, 3], atol=1e-10)


def test_non_circular_marking_does_not_get_an_invented_radius():
    # Dense elongated ellipse cannot pass merely because four rectangle corners are concyclic.
    theta = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    ellipse = np.column_stack((2 * np.cos(theta), np.sin(theta)))
    result = extract_markings({"Launch mark": slab(ellipse)}, {})["features"]["Launch mark"]
    assert result["status"] == "UNKNOWN"
    assert "radius_m" not in result


def test_concyclic_square_corners_do_not_establish_a_circle():
    result = extract_markings({"Launch mark": slab(rectangle(-1, -1, 1, 1))}, {})
    assert result["features"]["Launch mark"]["status"] == "UNKNOWN"
