"""
Device-independent obstacle input: depth image -> nearest obstacle per azimuth sector.

Input: a metric depth image (z along the optical axis, metres), a validity mask,
the capture timestamp and pinhole intrinsics of the depth image. This matches an
OAK StereoDepth `depth` frame (uint16 mm -> metres, 0 = invalid) aligned to the
rectified left camera, and also a host-side SGBM stand-in.

Output: per sector the nearest range (robust low percentile of valid ranges),
the valid-pixel fraction, a validity verdict with a reason, and the data age.
It is a perception verdict only: no velocity, attitude or other control quantity
is produced, and nothing is sent anywhere (CONTROL OUTPUT = DISABLED).

Range is the Euclidean distance along each pixel's ray (not z), so a sector at
the image edge is not reported as farther than it is.
"""

from __future__ import annotations

import functools
import itertools
import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class SectorConfig:
    sectors: int = 7
    horizontal_fov_deg: float | None = None  # None = full image width
    vertical_band_deg: float = 15.0  # +- around the optical axis
    min_range_m: float = 0.2  # below: unreliable (stereo blind zone), not "an obstacle"
    max_range_m: float = 10.0
    percentile: float = 5.0  # robust "nearest": ignores isolated speckle
    min_valid_fraction: float = 0.2
    min_valid_pixels: int = 50
    max_age_ms: float = 200.0


@dataclass(frozen=True)
class SectorResult:
    azimuth_deg: tuple[float, float]  # left edge, right edge; +right (FRD-like)
    nearest_m: float | None
    valid_fraction: float
    valid: bool
    reason: str


@dataclass(frozen=True)
class ObstacleReport:
    timestamp_ns: int
    age_ms: float
    fresh: bool
    frame_valid_fraction: float
    sectors: tuple[SectorResult, ...]
    control_output: str = "DISABLED"

    @property
    def nearest_m(self) -> float | None:
        values = [s.nearest_m for s in self.sectors if s.valid and s.nearest_m is not None]
        return min(values) if values else None


@functools.lru_cache(maxsize=8)
def _azimuth_elevation(shape, intrinsics: Intrinsics) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-pixel ray angles; cached because shape and intrinsics are fixed per camera."""
    height, width = shape
    u = (np.arange(width) - intrinsics.cx) / intrinsics.fx
    v = (np.arange(height) - intrinsics.cy) / intrinsics.fy
    x, y = np.meshgrid(u, v)
    azimuth = np.degrees(np.arctan2(x, 1.0))
    elevation = np.degrees(np.arctan2(-y, np.sqrt(1.0 + x * x)))
    ray_scale = np.sqrt(1.0 + x * x + y * y)  # range = z * ray_scale
    for array in (azimuth, elevation, ray_scale):
        array.flags.writeable = False  # shared cache entries must not be mutated
    return azimuth, elevation, ray_scale


def sector_report(
    depth_m: np.ndarray,
    valid: np.ndarray,
    timestamp_ns: int,
    intrinsics: Intrinsics,
    *,
    now_ns: int,
    config: SectorConfig | None = None,
) -> ObstacleReport:
    config = config or SectorConfig()
    if depth_m.ndim != 2 or valid.shape != depth_m.shape:
        raise ValueError("depth and valid mask must be 2-D with the same shape")
    if valid.dtype != bool:
        raise ValueError("valid mask must be boolean")
    azimuth, elevation, ray_scale = _azimuth_elevation(tuple(depth_m.shape), intrinsics)
    with np.errstate(invalid="ignore"):
        ranges = depth_m * ray_scale
    usable = valid & np.isfinite(ranges) & (depth_m > 0)
    band = np.abs(elevation) <= config.vertical_band_deg
    half = (config.horizontal_fov_deg / 2 if config.horizontal_fov_deg is not None
            else float(min(abs(azimuth[0, 0]), abs(azimuth[0, -1]))))
    edges = np.linspace(-half, half, config.sectors + 1)
    results = []
    for left, right in itertools.pairwise(edges):
        cell = band & (azimuth >= left) & (azimuth < right)
        total = int(cell.sum())
        good = cell & usable & (ranges >= config.min_range_m)
        too_close = int((cell & usable & (ranges < config.min_range_m)).sum())
        fraction = float(good.sum()) / total if total else 0.0
        if total == 0:
            results.append(SectorResult((left, right), None, 0.0, False, "no pixels"))
            continue
        if too_close > config.min_valid_pixels:
            # Something is inside the blind zone: not measurable, but not "free" either.
            results.append(SectorResult((left, right), None, fraction, False,
                                        "returns inside min range (blind zone)"))
            continue
        if good.sum() < config.min_valid_pixels or fraction < config.min_valid_fraction:
            results.append(SectorResult((left, right), None, fraction, False,
                                        "too few valid depth pixels"))
            continue
        nearest = float(np.percentile(ranges[good], config.percentile))
        if nearest > config.max_range_m:
            results.append(SectorResult((left, right), None, fraction, True,
                                        f"clear to max range {config.max_range_m} m"))
            continue
        results.append(SectorResult((left, right), nearest, fraction, True, "ok"))
    age_ms = (now_ns - timestamp_ns) / 1e6
    in_band = band & (np.abs(azimuth) <= half)
    frame_fraction = float((usable & in_band).sum()) / max(1, int(in_band.sum()))
    return ObstacleReport(timestamp_ns, age_ms, 0 <= age_ms <= config.max_age_ms, frame_fraction,
                          tuple(results))


def depth_from_oak_mm(depth_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OAK StereoDepth uint16 millimetres (0 = invalid) -> (metres, valid mask)."""
    if depth_mm.dtype != np.uint16:
        raise ValueError("OAK depth is uint16 millimetres")
    return depth_mm.astype(np.float32) / 1000.0, depth_mm > 0


def depth_from_disparity(disparity_px: np.ndarray, focal_px: float, baseline_m: float,
                         min_disparity_px: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Disparity (px, float) -> (z metres, valid mask); invalid where disparity is too small."""
    valid = np.isfinite(disparity_px) & (disparity_px >= min_disparity_px)
    depth = np.zeros(disparity_px.shape, np.float32)
    depth[valid] = focal_px * baseline_m / disparity_px[valid]
    return depth, valid


def min_depth_m(focal_px: float, baseline_m: float, max_disparity_px: float) -> float:
    """Closest measurable depth for a stereo matcher's disparity search range."""
    return focal_px * baseline_m / max_disparity_px if max_disparity_px > 0 else math.inf
