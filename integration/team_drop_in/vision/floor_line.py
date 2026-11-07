"""Floor guide line from one MONOCHROME camera image. PURE (numpy + OpenCV), no ROS import.

Why mono: in the lab only /stereo/left/image, /stereo/right/image and depth reach ROS; the RGB
view is a browser preview. The maze route is marked by a line on the floor, which a forward
camera sees in the lower part of its image.

Algorithm (adapted from Cyberchopin/dronehacks-autonomy-2026 src/aegisland/course_perception.py
`_line` / `_line_geometry` @01d9ded, which already ran on grey images): threshold pixels brighter
(or darker) than the floor-region median, keep connected components with stripe-like geometry,
fit a straight centre line, reject branched / cropped / wall-edge / competing candidates, and retry
once with CLAHE when the frame is dark (kept only if the retry clearly helps).

Output is IMAGE-SPACE evidence (normalised coordinates, image-plane lean). It is not a metric
position or heading: turning it into body-frame geometry needs CameraInfo, TF and height, and the
floor line's identity is unverified. control_output is always "DISABLED".
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

SCHEMA = "vision.floor_line/1"


@dataclass(frozen=True)
class LineConfig:
    """Thresholds copied from the prototype's CourseConfig (synthetic-tuned, NOT sim-tuned)."""

    polarity: str = "bright"  # floor line brighter than the floor; "dark" for dark paint/tape
    roi_top: float = 0.35  # only rows below this image fraction are searched (floor region)
    contrast_delta: float = 18.0
    contrast_full_scale: float = 80.0
    min_area_fraction: float = 0.001
    max_area_fraction: float = 0.18
    max_width_fraction: float = 0.20
    max_wide_row_fraction: float = 0.25
    max_split_row_fraction: float = 0.10
    min_row_coverage: float = 0.70
    bottom_margin_fraction: float = 0.08
    side_margin_fraction: float = 0.01
    max_above_roi_fraction: float = 0.50
    max_fit_rms_fraction: float = 0.012
    max_fit_error_fraction: float = 0.035
    max_width_cv: float = 0.40
    fit_width_multiplier: float = 1.8
    min_geometry_rows: int = 8
    confidence_min: float = 0.55
    competitor_ratio: float = 0.85
    samples: int = 12
    low_light_mean: float = 40.0
    low_light_dark_pixel: int = 12
    low_light_dark_fraction: float = 0.75
    clahe_clip_limit: float = 2.2
    clahe_tiles: int = 8
    recovery_min_contrast_gain: float = 5.0
    recovery_min_line_gain: float = 0.05

    def __post_init__(self):
        if self.polarity not in {"bright", "dark"}:
            raise ValueError("polarity must be bright or dark")
        if not 0 < self.roi_top < 1:
            raise ValueError("roi_top must be in (0, 1)")
        if not 0 < self.confidence_min <= 1:
            raise ValueError("confidence_min must be in (0, 1]")


def _cv2():
    try:
        import cv2
    except ImportError as e:  # explicit: the companion image may not ship OpenCV
        raise RuntimeError("vision.floor_line needs OpenCV (python3 -c 'import cv2')") from e
    return cv2


def decode_mono(
    encoding: str, height: int, width: int, step: int, data: bytes, is_bigendian: bool = False
) -> np.ndarray:
    """sensor_msgs/Image -> uint8 grey. Accepts mono8, mono16 (scaled to 8 bit) and, for hardware
    drivers that publish colour, rgb8/bgr8 (converted to grey). Depth encodings are refused."""
    enc = encoding.lower()
    channels, base = {"mono8": (1, "u1"), "8uc1": (1, "u1"), "mono16": (1, "u2"),
                      "rgb8": (3, "u1"), "bgr8": (3, "u1")}.get(enc, (0, ""))
    if not channels:
        raise ValueError(f"unsupported image encoding {encoding!r} (need mono8/mono16/rgb8/bgr8)")
    dt = np.dtype((">" if is_bigendian else "<") + base)
    if not (0 < height <= 4096 and 0 < width <= 4096):
        raise ValueError(f"invalid image size {width}x{height}")
    if step < width * channels * dt.itemsize or len(data) != step * height:
        raise ValueError(f"buffer is {len(data)} bytes, expected step*height = {step}*{height}")
    shape = (height, width, channels) if channels > 1 else (height, width)
    strides = (step, channels * dt.itemsize, dt.itemsize) if channels > 1 else (step, dt.itemsize)
    image = np.ndarray(shape, dtype=dt, buffer=bytes(data), strides=strides)
    if base == "u2":
        return (image.astype(np.uint32) >> 8).astype(np.uint8)
    if channels == 3:
        rgb = image.astype(np.float32)
        if enc == "bgr8":
            rgb = rgb[..., ::-1]
        return np.clip(rgb @ np.array([0.299, 0.587, 0.114], np.float32) + 0.5, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(image, dtype=np.uint8)


def _contrast_mask(gray, polarity, delta):
    median = float(np.median(gray))
    selected = (gray.astype(float) - median) * (1 if polarity == "bright" else -1)
    return np.uint8(selected >= delta) * 255


def _line_geometry(gray, component, rows, widths, top, c: LineConfig):
    """Conservative near-field stripe consistency; it cannot establish ground semantics."""
    h, w = gray.shape
    fit_rows = rows[
        (widths[rows] / w <= c.max_width_fraction)
        & (widths[rows] <= np.median(widths[rows]) * c.fit_width_multiplier)
    ]
    centers = np.array([np.flatnonzero(component[y]).mean() for y in fit_rows]) / w
    yy = (fit_rows + top) / h
    coefficients = np.polyfit(yy, centers, 1)
    errors = np.abs(centers - np.polyval(coefficients, yy))
    rms, maximum = float(np.sqrt(np.mean(errors**2))), float(errors.max())
    width_cv = float(np.std(widths[fit_rows]) / np.mean(widths[fit_rows]))
    _, xs = np.nonzero(component)
    side_margin = min(int(xs.min()), w - 1 - int(xs.max())) / w
    bottom_distance = (h - 1 - (int(rows[-1]) + top)) / h
    # Reject thin wall highlights: does the fitted stripe keep standing out from its OWN row
    # neighbours above the floor region? (The prototype compared against the floor median, which
    # rejected every real line whenever the walls were simply brighter than the floor.)
    above_y = np.arange(top)
    above_x = np.clip(np.rint(np.polyval(coefficients, above_y / h) * w).astype(int), 0, w - 1)
    sign = 1 if c.polarity == "bright" else -1
    gap = max(6, int(3 * np.median(widths[fit_rows])))
    left = gray[above_y, np.clip(above_x - gap, 0, w - 1)].astype(float)
    right = gray[above_y, np.clip(above_x + gap, 0, w - 1)].astype(float)
    above_signal = (gray[above_y, above_x].astype(float) - np.maximum(left, right) * (sign > 0)
                    - np.minimum(left, right) * (sign < 0)) * sign
    above_fraction = float(np.mean(above_signal >= c.contrast_delta)) if top else 0.0
    geometry = {
        "fit_row_coverage": len(fit_rows) / component.shape[0],
        "fit_rms_fraction": rms,
        "fit_max_error_fraction": maximum,
        "width_cv": width_cv,
        "bottom_distance_fraction": bottom_distance,
        "side_margin_fraction": side_margin,
        "above_roi_continuation_fraction": above_fraction,
        # x = a*y + b in normalised image coordinates (x right, y down)
        "fit_slope": float(coefficients[0]),
        "fit_intercept": float(coefficients[1]),
    }
    reasons = []
    if geometry["fit_row_coverage"] < c.min_row_coverage:
        reasons.append("line_fit_support_insufficient")
    if rms > c.max_fit_rms_fraction or maximum > c.max_fit_error_fraction:
        reasons.append("line_shape_inconsistent")
    if width_cv > c.max_width_cv:
        reasons.append("line_width_inconsistent")
    if bottom_distance > c.bottom_margin_fraction:
        reasons.append("line_near_field_unsupported")
    if side_margin <= c.side_margin_fraction:
        reasons.append("line_cropped_at_side")
    if above_fraction > c.max_above_roi_fraction:
        reasons.append("line_wall_edge_ambiguous")
    return geometry, reasons, fit_rows


def _line(gray, c: LineConfig) -> dict:
    cv2 = _cv2()
    top = int(gray.shape[0] * c.roi_top)
    roi = gray[top:]
    mask = _contrast_mask(roi, c.polarity, c.contrast_delta)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates, rejected, rejected_geometry = [], [], False
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA]) / roi.size
        if not c.min_area_fraction <= area <= c.max_area_fraction:
            continue
        component = labels == label
        widths = component.sum(axis=1)
        rows = np.flatnonzero(widths)
        splits = np.sum(np.diff(component.astype(np.int8), axis=1) == 1, axis=1)
        splits += component[:, 0]
        split_fraction = float(np.mean(splits[rows] > 1))
        coverage = len(rows) / roi.shape[0]
        median_width = float(np.median(widths[rows])) / roi.shape[1]
        wide_fraction = float(np.mean(widths[rows] / roi.shape[1] > c.max_width_fraction))
        contrast = abs(float(roi[component].mean()) - float(np.median(roi)))
        confidence = coverage * min(1.0, contrast / c.contrast_full_scale)
        if (
            median_width > c.max_width_fraction
            or wide_fraction > c.max_wide_row_fraction
            or split_fraction > c.max_split_row_fraction
            or coverage < c.min_row_coverage
            or len(rows) < c.min_geometry_rows
        ):
            rejected_geometry = True
            continue
        geometry, reasons, fit_rows = _line_geometry(gray, component, rows, widths, top, c)
        geometric_confidence = confidence * max(0.0, 1 - geometry["fit_rms_fraction"] / c.max_fit_rms_fraction)
        sampled = fit_rows[np.linspace(0, len(fit_rows) - 1, c.samples).astype(int)]
        points = [
            [float(np.flatnonzero(component[y]).mean()) / gray.shape[1], float(y + top) / gray.shape[0]]
            for y in sampled
        ]
        candidate = {
            "candidate_confidence": confidence,
            "confidence": geometric_confidence if not reasons else 0.0,
            "geometry": geometry,
            "geometry_reasons": reasons,
            "row_coverage": coverage,
            "contrast": contrast,
            "points_normalized": points,
        }
        (rejected if reasons else candidates).append(candidate)
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    empty = {"confidence": 0.0, "candidate_confidence": 0.0, "geometry": None, "geometry_reasons": [],
             "row_coverage": 0.0, "contrast": 0.0, "points_normalized": []}
    best = candidates[0] if candidates else (
        max(rejected, key=lambda item: item["candidate_confidence"]) if rejected else empty)
    ambiguous = len(candidates) > 1 and candidates[1]["confidence"] >= best["confidence"] * c.competitor_ratio
    geometric_ambiguity = bool(best["geometry_reasons"])
    detected = best["confidence"] >= c.confidence_min and not ambiguous
    if ambiguous:
        reasons = ["competing_lines"]
    elif detected:
        reasons = []
    elif geometric_ambiguity:
        reasons = best["geometry_reasons"]
    elif rejected_geometry:
        reasons = ["branched_or_insufficient_geometry"]
    else:
        reasons = ["insufficient_line_support"]
    return {
        **best,
        "confidence": 0.0 if ambiguous else best["confidence"],
        "points_normalized": best["points_normalized"] if detected else [],
        "detected": detected,
        "ambiguous": ambiguous or geometric_ambiguity,
        "status": "supported" if detected else "ambiguous" if ambiguous or geometric_ambiguity else "unknown",
        "candidate_count": len(candidates),
        "rejection_reasons": reasons,
    }


def detect_floor_line(gray: np.ndarray, config: LineConfig | None = None) -> dict:
    """Grey uint8 image -> line evidence dict (no timestamps; see floor_line_message)."""
    c = config or LineConfig()
    if gray.dtype != np.uint8 or gray.ndim != 2 or min(gray.shape) < 16:
        raise ValueError("need a 2-D uint8 grey image of at least 16x16")
    raw = _line(gray, c)
    dark_fraction = float(np.mean(gray <= c.low_light_dark_pixel))
    low_light = float(gray.mean()) < c.low_light_mean or dark_fraction >= c.low_light_dark_fraction
    retry, gain = raw, 0.0
    if low_light:
        enhanced = _cv2().createCLAHE(clipLimit=c.clahe_clip_limit,
                                      tileGridSize=(c.clahe_tiles, c.clahe_tiles)).apply(gray)
        retry = _line(enhanced, c)
        gain = float(np.std(enhanced)) - float(np.std(gray))
    recovered = (low_light and gain >= c.recovery_min_contrast_gain and retry["detected"]
                 and retry["confidence"] - raw["confidence"] >= c.recovery_min_line_gain)
    line = retry if recovered else raw  # no confidence bonus for merely trying CLAHE

    out = {
        "detected": bool(line["detected"]),
        "status": line["status"],
        "confidence": round(float(line["confidence"]), 3),
        "rejection_reasons": list(line["rejection_reasons"]),
        "candidate_count": int(line["candidate_count"]),
        "points_normalized": [[round(x, 4), round(y, 4)] for x, y in line["points_normalized"]],
        "bottom_offset": None,
        "image_lean_deg": None,
        "low_light": {"detected": bool(low_light), "mean": round(float(gray.mean()), 1),
                      "dark_fraction": round(dark_fraction, 3), "line_recovered": bool(recovered)},
        "coordinate_unit": "normalized_image",
        "semantic_identity": "unverified",
        "control_output": "DISABLED",
    }
    if line["detected"]:
        g = line["geometry"]
        h, w = gray.shape
        # where the fitted line meets the bottom row: -1 = left edge, 0 = centre, +1 = right edge
        out["bottom_offset"] = round(2.0 * (g["fit_slope"] * 1.0 + g["fit_intercept"]) - 1.0, 4)
        # image-plane lean of the line going UP the image (away from the camera), + = leans right.
        # Pixel units, so it is an image angle, not a ground heading.
        out["image_lean_deg"] = round(math.degrees(math.atan2(-g["fit_slope"] * w, h)), 2)
    return out


def floor_line_message(
    encoding: str, height: int, width: int, step: int, data: bytes, stamp_ns: int, now_ns: int,
    frame_id: str = "", config: LineConfig | None = None, is_bigendian: bool = False,
    max_age_ms: float = 200.0,
) -> dict:
    """One sensor_msgs/Image -> JSON-ready dict for /vision/floor_line."""
    gray = decode_mono(encoding, height, width, step, data, is_bigendian)
    doc = detect_floor_line(gray, config)
    age_ms = (int(now_ns) - int(stamp_ns)) / 1e6
    return {"schema": SCHEMA, "frame_id": frame_id, "stamp_ns": int(stamp_ns), "age_ms": round(age_ms, 1),
            "fresh": bool(0 <= age_ms <= max_age_ms), **doc}


def config_snapshot(config: LineConfig | None = None) -> dict:
    return asdict(config or LineConfig())
