"""Central, uncalibrated offline prototype parameters; no course coordinates."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

from .depth_sectors import SectorConfig


@dataclass(frozen=True)
class CourseConfig:
    # Provenance is deliberately a calibration claim, not a competition safety limit.
    provenance: str = "synthetic-v2-adversarial; engineering heuristics; no field calibration"
    schema_version: int = 2
    line_polarity: str = "bright"
    line_roi_top: float = 0.35
    contrast_delta: float = 18.0
    contrast_full_scale: float = 80.0
    line_min_area_fraction: float = 0.001
    line_max_area_fraction: float = 0.18
    line_max_width_fraction: float = 0.20
    line_max_wide_row_fraction: float = 0.25
    line_max_split_row_fraction: float = 0.10
    line_min_row_coverage: float = 0.70
    line_bottom_margin_fraction: float = 0.08
    line_side_margin_fraction: float = 0.01
    line_max_above_roi_fraction: float = 0.50
    line_max_fit_rms_fraction: float = 0.012
    line_max_fit_error_fraction: float = 0.035
    line_max_width_cv: float = 0.40
    line_fit_width_multiplier: float = 1.8
    line_min_geometry_rows: int = 8
    line_confidence_min: float = 0.55
    line_competitor_ratio: float = 0.85
    line_samples: int = 12
    low_light_mean: float = 40.0
    low_light_dark_pixel: int = 12
    low_light_dark_fraction: float = 0.75
    clahe_clip_limit: float = 2.2
    clahe_tiles: int = 8
    recovery_min_contrast_gain: float = 5.0
    recovery_min_line_gain: float = 0.05
    canny_low: float = 40.0
    canny_high: float = 120.0
    contour_epsilon_fraction: float = 0.025
    opening_min_area_fraction: float = 0.025
    opening_max_area_fraction: float = 0.80
    opening_min_aspect: float = 0.4
    opening_max_aspect: float = 2.5
    opening_min_rectangularity: float = 0.85
    roi_inset_fraction: float = 0.12
    candidate_nms_iou: float = 0.60
    candidate_limit: int = 8
    depth_sync_max_ms: float = 25.0
    # SectorConfig is the existing AegisLand depth-evidence configuration.
    depth: SectorConfig = field(default_factory=SectorConfig)
    local_depth_min_fraction: float = 0.90
    local_depth_min_pixels: int = 50
    corridor_probe_m: float = 2.0
    envelope_width_m: float = 0.35
    clearance_margin_m: float = 0.15
    rgb_conflict_min_area_fraction: float = 0.02
    rgb_conflict_min_extent_fraction: float = 0.15
    rgb_conflict_min_fill_fraction: float = 0.65
    rgb_conflict_depth_delta_m: float = 0.08
    ring_min_area_fraction: float = 0.015
    ring_max_area_fraction: float = 0.65
    ring_min_circularity: float = 0.84
    ring_min_axis_ratio: float = 0.65
    ring_min_hole_ratio: float = 0.30
    ring_max_hole_ratio: float = 0.90
    ring_max_center_offset: float = 0.10
    ring_border_fraction: float = 0.01
    landing_confidence_min: float = 0.65
    landing_min_z_m: float = 0.4
    landing_max_z_m: float = 4.0
    plane_max_residual_m: float = 0.04
    plane_max_tilt_deg: float = 15.0
    plane_max_samples: int = 2000

    def __post_init__(self) -> None:
        if not self.provenance.strip():
            raise ValueError("configuration provenance is required")
        if self.line_polarity not in {"bright", "dark"}:
            raise ValueError("line_polarity must be bright or dark")
        for name, value in asdict(self).items():
            if isinstance(value, (int, float)) and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
            if (
                any(token in name for token in ("fraction", "ratio", "confidence", "iou"))
                and isinstance(value, (int, float))
                and value > 1
            ):
                raise ValueError(f"{name} must be <= 1")
        if not 0 < self.line_roi_top < 1:
            raise ValueError("line_roi_top must be in (0, 1)")
        for name in (
            "line_samples",
            "line_min_geometry_rows",
            "clahe_tiles",
            "candidate_limit",
            "local_depth_min_pixels",
            "plane_max_samples",
            "schema_version",
            "low_light_dark_pixel",
        ):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        for low, high in (
            (self.canny_low, self.canny_high),
            (self.line_min_area_fraction, self.line_max_area_fraction),
            (self.opening_min_area_fraction, self.opening_max_area_fraction),
            (self.opening_min_aspect, self.opening_max_aspect),
            (self.ring_min_area_fraction, self.ring_max_area_fraction),
            (self.ring_min_hole_ratio, self.ring_max_hole_ratio),
            (self.landing_min_z_m, self.landing_max_z_m),
        ):
            if low >= high:
                raise ValueError("configuration lower bound must be below upper bound")
        if self.roi_inset_fraction >= 0.5 or self.ring_border_fraction >= 0.5:
            raise ValueError("ROI inset/border fraction must be below 0.5")
        if self.plane_max_samples < 3:
            raise ValueError("plane_max_samples must be >= 3")
        if self.line_fit_width_multiplier < 1 or self.line_min_geometry_rows < 4:
            raise ValueError("line geometry requires width multiplier >= 1 and at least 4 rows")
        d = self.depth
        if (
            type(d.sectors) is not int
            or d.sectors < 1
            or d.min_valid_pixels < 1
            or not 0 < d.min_valid_fraction <= 1
            or not 0 <= d.percentile <= 100
            or not 0 < d.min_range_m < self.corridor_probe_m <= d.max_range_m
            or not 0 < d.vertical_band_deg < 90
            or d.max_age_ms <= 0
        ):
            raise ValueError("invalid depth sector configuration")
        if any(not math.isfinite(v) for v in asdict(d).values() if v is not None):
            raise ValueError("depth sector configuration must be finite")
        if d.horizontal_fov_deg is not None and not 0 < d.horizontal_fov_deg < 180:
            raise ValueError("horizontal_fov_deg must be in (0, 180)")

    def snapshot(self) -> dict:
        values = asdict(self)
        encoded = json.dumps(values, sort_keys=True, allow_nan=False).encode()
        return {"sha256": hashlib.sha256(encoded).hexdigest(), "values": values}
