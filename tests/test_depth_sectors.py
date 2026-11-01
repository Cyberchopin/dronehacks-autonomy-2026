import numpy as np
import pytest

from aegisland.depth_sectors import (
    Intrinsics,
    SectorConfig,
    depth_from_disparity,
    depth_from_oak_mm,
    min_depth_m,
    sector_report,
)

K = Intrinsics(fx=200.0, fy=200.0, cx=159.5, cy=99.5)
SHAPE = (200, 320)


def wall(distance: float) -> tuple[np.ndarray, np.ndarray]:
    return np.full(SHAPE, distance, np.float32), np.ones(SHAPE, bool)


def test_flat_wall_gives_ray_ranges_and_center_sector_at_wall_distance() -> None:
    depth, valid = wall(3.0)
    report = sector_report(depth, valid, 1_000, K, now_ns=1_000 + 20_000_000,
                           config=SectorConfig(sectors=5))
    center = report.sectors[2]
    assert center.valid and center.reason == "ok"
    assert center.nearest_m == pytest.approx(3.0, abs=0.01)
    # Edge sectors see the same wall at a slant: farther along the ray.
    assert report.sectors[0].nearest_m > center.nearest_m
    assert report.age_ms == pytest.approx(20.0) and report.fresh
    assert report.control_output == "DISABLED"


def test_obstacle_in_one_sector_is_reported_only_there() -> None:
    depth, valid = wall(6.0)
    depth[80:120, 250:290] = 1.2  # box on the right
    report = sector_report(depth, valid, 0, K, now_ns=0, config=SectorConfig(sectors=5))
    nearest = [s.nearest_m for s in report.sectors]
    # z = 1.2 m at ~24-31 deg off axis: range along the ray = z * |ray| ~ 1.32-1.40 m
    assert 1.30 <= nearest[4] <= 1.40
    assert all(n > 5.9 for n in nearest[:3])
    assert report.nearest_m == nearest[4]


def test_invalid_blind_zone_and_stale_data_are_not_reported_as_free() -> None:
    depth, valid = wall(3.0)
    valid[:, :160] = False  # left half has no depth
    depth[:, 200:240] = 0.1  # something inside the blind zone
    report = sector_report(depth, valid, 0, K, now_ns=500_000_000,
                           config=SectorConfig(sectors=4, min_range_m=0.3))
    assert report.sectors[0].valid is False
    assert report.sectors[0].reason == "too few valid depth pixels"
    assert report.sectors[2].valid is False
    assert "blind zone" in report.sectors[2].reason
    assert report.fresh is False  # 500 ms old > 200 ms


def test_far_scene_is_clear_to_max_range_and_inputs_are_validated() -> None:
    depth, valid = wall(50.0)
    report = sector_report(depth, valid, 0, K, now_ns=0, config=SectorConfig(max_range_m=10.0))
    assert all(s.valid and s.nearest_m is None and s.reason.startswith("clear") for s in
               report.sectors)
    with pytest.raises(ValueError, match="boolean"):
        sector_report(depth, valid.astype(np.uint8), 0, K, now_ns=0)


def test_conversions_and_min_depth() -> None:
    depth, valid = depth_from_oak_mm(np.array([[0, 1500]], np.uint16))
    assert valid.tolist() == [[False, True]] and depth[0, 1] == pytest.approx(1.5)
    z, ok = depth_from_disparity(np.array([[0.1, 10.0]]), focal_px=400.0, baseline_m=0.075)
    assert ok.tolist() == [[False, True]] and z[0, 1] == pytest.approx(3.0)
    # Luxonis docs example: OAK-D 800P, f = 882.5 px, B = 7.5 cm, 95 px -> ~0.70 m
    assert min_depth_m(882.5, 0.075, 95) == pytest.approx(0.6967, abs=1e-3)
