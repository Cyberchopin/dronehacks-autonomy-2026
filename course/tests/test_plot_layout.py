"""Headless plotting checks on tiny JSON fixtures, independent of the real map."""

import json
import struct
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pytest

from course.plot_layout import build_figure


@pytest.fixture
def tiny_layout():
    def feature(low, high, kind="wall", included=True, flags=()):
        return {
            "bounds": {"min": low, "max": high},
            "kind": kind,
            "include_in_occupancy": included,
            "flags": list(flags),
        }

    return {
        "header": {
            "source_file": "synthetic.obj",
            "source_sha256": "ab" * 32,
            "units": "metres",
            "axes": {"coordinate_order": "XYZ", "up": "+Z", "grid_plane": "XY"},
        },
        "features": {
            "Floor": feature([-0.6, 1.2, -0.01], [0, 1.6, 0], "floor", False),
            "Wall with window": feature(
                [-0.4, 1.3, 0], [-0.2, 1.5, 1], flags=["UNKNOWN: aperture coordinates."]
            ),
            "Launch mark": feature([-0.56, 1.25, 0], [-0.54, 1.27, 0.001], "floor_marking", False),
            "Unidentified piece": feature([-0.11, 1.45, 0], [-0.09, 1.55, 0.1], "UNKNOWN"),
        },
        "semantic_priors": {
            "gate": {
                "status": "UNKNOWN",
                "bounds": None,
                "centroid": None,
                "reason": "No position established.",
            }
        },
        "occupancy": {
            "origin_xy": [-0.6, 1.2],
            "resolution_m": 0.2,
            "shape_yx": [2, 3],
            "extent_max_xy": [0, 1.6],
            "cells": [[0, 1, 0], [1, 0, 1]],
        },
    }


def test_cli_writes_nonempty_png_headlessly(tmp_path, tiny_layout):
    source = tmp_path / "tiny.json"
    source.write_text(json.dumps(tiny_layout), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "tiny.png"
    script = Path(__file__).resolve().parents[1] / "plot_layout.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(source), "--out", str(output), "--dpi", "60"],
        check=True,
        capture_output=True,
        text=True,
    )
    png = output.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000
    assert struct.unpack(">II", png[16:24]) == (1320, 720)
    assert "Features: 4/4 outlined and labelled" in completed.stdout
    assert "UNKNOWN: 3 records shown" in completed.stdout
    assert "1 unlocated priors listed without coordinates" in completed.stdout
    assert completed.stderr == ""
    assert source.read_bytes() == original


def test_every_feature_and_unknown_is_visible_without_invented_coordinates(tiny_layout):
    figure, report = build_figure(tiny_layout, dpi=60)
    try:
        assert matplotlib.get_backend().lower() == "agg"
        ax = figure.axes[0]
        assert ax.images[0].origin == "lower"
        np.testing.assert_allclose(ax.images[0].get_extent(), [-0.6, 0, 1.2, 1.6], atol=1e-12)
        np.testing.assert_array_equal(ax.images[0].get_array(), [[0, 1, 0], [1, 0, 1]])
        assert ax.get_xlim()[0] < ax.get_xlim()[1]
        assert ax.get_ylim()[0] < ax.get_ylim()[1]
        assert {patch.get_gid() for patch in ax.patches} == {
            f"feature-bounds:{name}" for name in tiny_layout["features"]
        }
        assert {artist.get_gid() for artist in ax.texts} == {
            f"feature-label:{name}" for name in tiny_layout["features"]
        }
        texts = {artist.get_gid(): artist.get_text() for artist in figure.texts}
        for name in tiny_layout["features"]:
            assert name in texts[f"feature-key:{name}"]
        assert texts["unknown:1"].endswith("UNKNOWN: aperture coordinates.")
        assert "UNKNOWN" in texts["unknown:2"]
        assert "UNLOCATED" in texts["unknown:3"]
        assert report["feature_count"] == 4
        assert report["unknown_count"] == 3
        assert report["flagged_feature_count"] == 2
        assert report["unlocated_unknown_count"] == 1
        assert any("UNKNOWN" in label.get_text() for label in figure.legends[0].get_texts())
        assert "synthetic.obj" in figure._suptitle.get_text()
        assert any("ab" * 32 in text.get_text() for text in figure.texts)
        # The scale bar's physical screen width must match its stated metre length.
        bar = next(artist for artist in figure.artists if artist.get_gid() == "scale-bar")
        actual = np.diff(bar.get_xdata())[0] * figure.bbox.width
        points = ax.transData.transform([[0, 0], [report["scale_bar_m"], 0]])
        assert actual == pytest.approx(points[1, 0] - points[0, 0])
    finally:
        figure.clear()


def test_conflicting_grid_extent_is_rejected(tiny_layout):
    tiny_layout["occupancy"]["extent_max_xy"] = [100, 100]
    with pytest.raises(ValueError, match="extent conflicts"):
        build_figure(tiny_layout)
