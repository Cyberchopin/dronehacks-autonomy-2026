"""simtest.course_render: box-world depth/mono rendering, checked against vision/forward_sectors.
Synthetic worlds only (no dependency on course/layout.json). Confirms depth geometry/units and that
the real detector reads the rendered scene sensibly. Not the DroneHacks sim; coarse box world."""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simtest.course_render import (Camera, RenderConfig, World, depth_message_bytes,  # noqa: E402
                                   render, world_from_layout)
from vision.forward_sectors import forward_sectors  # noqa: E402

CFG = RenderConfig(noise_m=0.0, mono_noise=0.0)


def wall_box(x0, x1=None, y=(-2.0, 2.0), z=(0.0, 1.7)):
    x1 = x0 + 0.1 if x1 is None else x1
    return [[x0, y[0], z[0]], [x1, y[1], z[1]]]


def sectors(world, cam, cfg=CFG):
    dz, valid, mono, (fx, fy, cx, cy) = render(world, cam, cfg)
    doc = forward_sectors("32FC1", cfg.height, cfg.width, cfg.width * 4,
                          depth_message_bytes(dz), [fx, 0, cx, 0, fy, cy, 0, 0, 1], 1000, 1000)
    return dz, valid, mono, doc


def test_wall_ahead_reads_its_distance_centre_nearest():
    world = World(boxes=np.array([wall_box(3.0)]), box_kind=["wall"])
    cam = Camera(pos=(0.0, 0.0, 0.8), yaw_deg=0.0, pitch_deg=0.0, hfov_deg=71.5)
    dz, valid, mono, doc = sectors(world, cam)
    assert doc["sectors"][3]["nearest_m"] == pytest.approx(3.0, abs=0.05)
    # range is along the ray: edge sectors see the same plane farther, never nearer
    assert doc["sectors"][0]["nearest_m"] > doc["sectors"][3]["nearest_m"]
    assert doc["nearest_m"] == pytest.approx(3.0, abs=0.05)


def test_distance_scales_with_wall_position():
    # distances where the wall is nearer than the floor the level camera also sees (floor enters the
    # lower band at ~0.8/sin(15 deg) ~= 3.1 m), so the wall is the nearest return
    for d in (1.5, 2.0, 2.8):
        world = World(boxes=np.array([wall_box(d)]), box_kind=["wall"])
        cam = Camera(pos=(0.0, 0.0, 0.8), yaw_deg=0.0, pitch_deg=0.0)
        _, _, _, doc = sectors(world, cam)
        assert doc["sectors"][3]["nearest_m"] == pytest.approx(d, abs=0.06)


def test_level_camera_sees_the_floor_as_nearest_in_the_lower_band():
    # documents a real limitation: standalone forward_sectors does NOT level by attitude, so a level
    # camera reports the floor as an obstacle. A far wall (5 m) is hidden behind the ~3 m floor hit.
    world = World(boxes=np.array([wall_box(5.0)]), box_kind=["wall"])
    cam = Camera(pos=(0.0, 0.0, 0.8), yaw_deg=0.0, pitch_deg=0.0)
    _, _, _, doc = sectors(world, cam)
    assert doc["nearest_m"] is not None and 2.5 < doc["nearest_m"] < 3.6   # the floor, not the wall


def test_obstacle_on_one_side_only():
    # a short wall block to the right of the optical axis (world +y is left when facing +x)
    world = World(boxes=np.array([[[1.0, -2.5, 0.0], [1.2, -0.5, 1.7]]]), box_kind=["wall"])
    cam = Camera(pos=(0.0, 0.0, 0.8), yaw_deg=0.0, pitch_deg=0.0)
    _, _, _, doc = sectors(world, cam)
    left, right = doc["sectors"][0], doc["sectors"][-1]
    assert right["nearest_m"] is not None and right["nearest_m"] < 1.6
    assert left["nearest_m"] is None or left["nearest_m"] > 2.5


def test_open_scene_pitched_up_has_no_returns():
    # no boxes and the camera pitched up so the band clears the floor: nothing in front
    world = World(boxes=np.zeros((0, 2, 3)), box_kind=[])
    cam = Camera(pos=(0.0, 0.0, 0.8), yaw_deg=0.0, pitch_deg=-30.0)
    dz, valid, mono, doc = sectors(world, cam)
    assert doc["nearest_m"] is None            # clear sky above the walls: no return


def test_floor_is_seen_when_pitched_down():
    world = World(boxes=np.zeros((0, 2, 3)), box_kind=[])
    cam = Camera(pos=(0.0, 0.0, 1.0), yaw_deg=0.0, pitch_deg=45.0)
    dz, valid, mono, doc = sectors(world, cam)
    assert valid.mean() > 0.3                   # the floor fills much of a steeply-down view
    # a 45-deg-down ray from 1 m hits the floor at ~1.41 m range near the image centre
    assert 1.0 < np.nanmedian(dz) < 3.0


def test_dropout_and_noise_are_deterministic_with_seed():
    world = World(boxes=np.array([wall_box(3.0)]), box_kind=["wall"])
    cam = Camera(pos=(0.0, 0.0, 0.8))
    cfg = RenderConfig(noise_m=0.02, dropout=0.1, seed=7)
    a = render(world, cam, cfg)[0]
    b = render(world, cam, cfg)[0]
    assert np.array_equal(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1))
    assert np.isnan(a).mean() > np.isnan(render(world, cam, RenderConfig(noise_m=0, dropout=0))[0]).mean()


def test_world_from_layout_parses_boxes_and_rings():
    layout = {
        "features": {
            "M1 maze divider": {"kind": "wall", "include_in_occupancy": True,
                                 "bounds": {"min": [0.0, 0.0, 0.0], "max": [0.1, 1.0, 1.7]}},
            "Landing pad ring r30": {"kind": "floor_marking", "include_in_occupancy": False,
                                      "bounds": {"min": [-2.8, -1.5, 0.0], "max": [-1.3, 0.0, 0.0]}},
            "Guideline (zone 1)": {"kind": "floor_marking", "include_in_occupancy": False,
                                    "bounds": {"min": [-2.5, 0.9, 0.0], "max": [0.3, 2.6, 0.0]}},
        }
    }
    w = world_from_layout(layout)
    assert w.boxes.shape == (1, 2, 3) and w.box_kind == ["wall"]   # divider only
    assert len(w.rings) == 1                                        # ring reconstructed as a circle
    cx, cy, r, _ = w.rings[0]
    assert cx == pytest.approx(-2.05, abs=0.01) and r == pytest.approx(0.75, abs=0.01)


def test_mono_frame_is_uint8_and_runs_through_floor_line():
    from vision.floor_line import floor_line_message
    world = World(boxes=np.array([wall_box(3.0)]), box_kind=["wall"])
    cam = Camera(pos=(0.0, 0.0, 0.8), pitch_deg=10.0)
    dz, valid, mono, K = render(world, cam, CFG)
    assert mono.dtype == np.uint8 and mono.shape == (CFG.height, CFG.width)
    doc = floor_line_message("mono8", CFG.height, CFG.width, CFG.width, mono.tobytes(), 1000, 1000)
    assert "detected" in doc and doc["control_output"] == "DISABLED"   # smoke: it runs on a real frame
