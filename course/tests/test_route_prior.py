from itertools import pairwise

import numpy as np
import pytest

from course.route_prior import build_route_prior, line_clear, plan_corridor


def grid():
    cells = np.zeros((20, 40), dtype=int)
    cells[0] = cells[-1] = 1
    cells[:, 0] = cells[:, -1] = 1
    # A wall with a central gap makes the route obey geometry.
    cells[1:8, 20] = 1
    cells[12:-1, 20] = 1
    return {
        "origin_xy": [-1, -1],
        "resolution_m": 0.1,
        "shape_yx": [20, 40],
        "extent_max_xy": [3, 1],
        "cells": cells.tolist(),
    }


def test_route_obeys_ordered_finite_crossings_and_keeps_simplification_clear():
    reference = grid()
    checkpoints = [
        {
            "number": i + 1,
            "name": f"stage {i + 1}",
            "portals": [{"line_xy": [[x, -0.15], [x, 0.15]], "normal_xy": [1, 0]}],
        }
        for i, x in enumerate([-0.2, 0.5, 1.05, 1.8])
    ]
    checkpoints.append({"number": 5, "name": "containment goal", "target_xy": [2.4, 0.1]})
    result = plan_corridor(reference, [-0.6, 0.1], checkpoints)
    assert result["status"] == "GEOMETRIC_SEED"
    assert [item["number"] for item in result["checkpoints"]] == [1, 2, 3, 4, 5]
    indexes = []
    for checkpoint in result["checkpoints"][:4]:
        crossing = checkpoint["crossings"][0]
        indexes.append(crossing["polyline_indices"][0])
        point = crossing["intersection_xy"]
        assert abs(point[1]) <= 0.15
        assert "UNKNOWN" in crossing["whole_drone_status"]
    assert indexes == sorted(indexes)
    points = np.floor((np.array(result["corridor_polyline_xy"]) - [-1, -1]) / 0.1).astype(int)[
        :, ::-1
    ]
    mask = np.asarray(reference["cells"], dtype=bool)
    assert all(line_clear(mask, tuple(a), tuple(b)) for a, b in pairwise(points))


def test_blocked_crossing_is_not_routed_around_and_claimed_complete():
    reference = grid()
    reference["cells"][10][20] = 1
    portal = {
        "number": 1,
        "portals": [{"line_xy": [[1.05, -0.15], [1.05, 0.15]], "normal_xy": [1, 0]}],
    }
    with pytest.raises(ValueError, match="direct portal crossing"):
        plan_corridor(reference, [-0.6, 0.1], [portal])


def test_diagonal_corner_touch_is_not_clear():
    mask = np.array([[False, True], [True, False]])
    assert not line_clear(mask, (0, 0), (1, 1))


def test_inconsistent_prior_sources_fail_explicitly():
    with pytest.raises(ValueError, match="SHA-256"):
        build_route_prior(
            {"header": {"source_sha256": "a"}},
            {"header": {"source_sha256": "b"}},
            {"header": {"source_sha256": "a"}},
        )
