"""Offline image/depth evidence only. No planner, command, transport or hardware adapter.

All distances are camera-frame metres. Scores are heuristics, never calibrated
probabilities. Checkpoint names are intentionally absent from the inference logic.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .course_config import CourseConfig
from .depth_sectors import Intrinsics, ObstacleReport, sector_report
from .domain import ZoneCandidate, jsonable
from .perception import clahe_gray
from .stage_timing import Collector


@dataclass(frozen=True)
class OfflineFrame:
    image: np.ndarray
    frame_index: int
    timestamp_ns: int
    evaluated_at_ns: int
    source_id: str
    source_type: str = "synthetic"  # Only synthetic / recording are accepted.
    camera_view: str = "forward"  # A declaration, not an attitude estimate.
    depth_m: np.ndarray | None = None
    depth_valid: np.ndarray | None = None
    depth_timestamp_ns: int | None = None
    intrinsics: Intrinsics | None = None
    calibration_id: str | None = None

    def validate(self) -> None:
        if self.source_type not in {"synthetic", "recording"} or not self.source_id.strip():
            raise ValueError("only identified synthetic or recording sources are accepted")
        if self.camera_view not in {"forward", "downward"}:
            raise ValueError("camera_view must be forward or downward")
        if (
            self.image.dtype != np.uint8
            or self.image.ndim != 3
            or self.image.shape[2] != 3
            or min(self.image.shape[:2]) < 2
        ):
            raise ValueError("image must be nonempty BGR uint8")
        if any(
            type(x) is not int or x < 0
            for x in (self.frame_index, self.timestamp_ns, self.evaluated_at_ns)
        ):
            raise ValueError("frame index and timestamps must be nonnegative integers")
        associated = (
            self.depth_valid,
            self.depth_timestamp_ns,
            self.intrinsics,
            self.calibration_id,
        )
        if self.depth_m is None:
            if any(x is not None for x in associated):
                raise ValueError("depth metadata without depth")
            return
        if any(x is None for x in associated):
            raise ValueError("aligned depth requires mask, timestamp, intrinsics, calibration_id")
        if (
            self.depth_m.shape != self.image.shape[:2]
            or self.depth_valid.shape != self.depth_m.shape
            or self.depth_valid.dtype != bool
            or self.depth_m.dtype.kind != "f"
        ):
            raise ValueError("depth must be aligned float metres with a boolean validity mask")
        if type(self.depth_timestamp_ns) is not int or self.depth_timestamp_ns < 0:
            raise ValueError("depth timestamp must be a nonnegative integer")
        k = self.intrinsics
        h, w = self.image.shape[:2]
        if (
            not self.calibration_id.strip()
            or not all(math.isfinite(x) for x in (k.fx, k.fy, k.cx, k.cy))
            or min(k.fx, k.fy) <= 0
            or not 0 <= k.cx < w
            or not 0 <= k.cy < h
        ):
            raise ValueError("invalid aligned-image intrinsics/calibration_id")


def _box_normalized(box, shape):
    x, y, w, h = box
    return [x / shape[1], y / shape[0], w / shape[1], h / shape[0]]


def _iou(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    overlap = max(0, right - x) * max(0, bottom - y)
    return overlap / (a[2] * a[3] + b[2] * b[3] - overlap)


class CoursePerception:
    def __init__(self, config: CourseConfig | None = None):
        self.config = config or CourseConfig()

    def observe(self, sample: OfflineFrame) -> dict:
        started = time.perf_counter()
        spans = Collector()
        spans.call("input.validate", sample.validate)
        c = self.config
        gray = spans.call("preprocess.gray", cv2.cvtColor, sample.image, cv2.COLOR_BGR2GRAY)
        raw_line = spans.call("line.raw", self._line, gray)
        low_light = (
            float(gray.mean()) < c.low_light_mean
            or float(np.mean(gray <= c.low_light_dark_pixel)) >= c.low_light_dark_fraction
        )
        raw_contrast = float(np.std(gray))
        enhanced = gray
        recovered_line = raw_line
        if low_light:
            enhanced = spans.call(
                "retry.clahe", clahe_gray, gray, clip_limit=c.clahe_clip_limit, tiles=c.clahe_tiles
            )
            recovered_line = spans.call("line.retry", self._line, enhanced)
        gain = float(np.std(enhanced)) - raw_contrast
        line_gain = recovered_line["confidence"] - raw_line["confidence"]
        recovered = (
            low_light
            and gain >= c.recovery_min_contrast_gain
            and line_gain >= c.recovery_min_line_gain
            and recovered_line["detected"]
        )
        # No automatic confidence bonus for invoking CLAHE. Unsuccessful retry is discarded.
        line = recovered_line if recovered else raw_line
        depth, depth_report = spans.call("depth.evidence", self._depth, sample)
        openings = spans.call("opening.rois", self._openings, gray, sample, depth)
        clearance = spans.call(
            "clearance.forward",
            self._clearance,
            sample,
            depth,
            (0, 0, gray.shape[1], gray.shape[0]),
        )
        landing = spans.call("landing.ring", self._landing, gray, sample, depth)
        if low_light:
            landing["descent_geometry_suitable"] = False
            landing["rejection_reasons"].append("low_light_raw_evidence")
        if low_light or not depth["valid"]:
            state = "degraded"
        elif landing["detected"]:
            state = "pad_candidate"
        elif openings:
            state = "opening_candidate"
        elif line["detected"]:
            state = "line_supported"
        else:
            state = "unobservable"
        digest = hashlib.sha256()
        for array in (sample.image, sample.depth_m, sample.depth_valid):
            if array is not None:
                digest.update(str((array.shape, str(array.dtype))).encode())
                digest.update(array.tobytes())
        evidence = {
            "schema": "aegisland.course-perception.v2",
            "frame_index": sample.frame_index,
            "timestamp_ns": sample.timestamp_ns,
            "evaluated_at_ns": sample.evaluated_at_ns,
            "source": {
                "type": sample.source_type,
                "id": sample.source_id,
                "input_sha256": digest.hexdigest(),
                "camera_view": sample.camera_view,
                "calibration_id": sample.calibration_id,
            },
            "configuration": c.snapshot(),
            "state": state,
            "line": line,
            "openings": openings,
            "clearance": clearance,
            "landing": landing,
            "low_light": {
                "detected": low_light,
                "raw_mean": float(gray.mean()),
                "raw_dark_fraction": float(np.mean(gray <= c.low_light_dark_pixel)),
                "retry_applied": low_light,
                "raw_contrast_std": raw_contrast,
                "retry_contrast_std": float(np.std(enhanced)),
                "contrast_gain": gain,
                "raw_line_confidence": raw_line["confidence"],
                "retry_line_confidence": recovered_line["confidence"],
                "line_confidence_gain": line_gain,
                "line_recovered": recovered,
                "authority_change": "NONE",
            },
            "depth": depth,
            "depth_sector_report": jsonable(depth_report),
            "stage_ms": {row["stage"]: row["inclusive_ns"] / 1e6 for row in spans.rows},
            "control_output": "DISABLED",
            "command_executed": False,
            "executed": False,
            "authority_change": "NONE",
            "capabilities": {
                "window_navigation": "unimplemented",
                "return_navigation": "unimplemented",
                "metric_vio_slam": "not_provided",
            },
            "advisory_only": True,
        }
        evidence["processing_ms"] = (time.perf_counter() - started) * 1000
        return evidence

    def _contrast_mask(self, gray, polarity):
        c = self.config
        median = float(np.median(gray))
        selected = (gray.astype(float) - median) * (1 if polarity == "bright" else -1)
        return np.uint8(selected >= c.contrast_delta) * 255

    def _line(self, gray):
        c = self.config
        top = int(gray.shape[0] * c.line_roi_top)
        roi = gray[top:]
        mask = self._contrast_mask(roi, c.line_polarity)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        candidates = []
        rejected = []
        rejected_geometry = False
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA]) / roi.size
            if not c.line_min_area_fraction <= area <= c.line_max_area_fraction:
                continue
            component = labels == label
            widths = component.sum(axis=1)
            rows = np.flatnonzero(widths)
            splits = np.sum(np.diff(component.astype(np.int8), axis=1) == 1, axis=1)
            splits += component[:, 0]
            split_fraction = float(np.mean(splits[rows] > 1))
            coverage = len(rows) / roi.shape[0]
            median_width = float(np.median(widths[rows])) / roi.shape[1]
            wide_fraction = float(np.mean(widths[rows] / roi.shape[1] > c.line_max_width_fraction))
            contrast = abs(float(roi[component].mean()) - float(np.median(roi)))
            confidence = coverage * min(1.0, contrast / c.contrast_full_scale)
            if (
                median_width > c.line_max_width_fraction
                or wide_fraction > c.line_max_wide_row_fraction
                or split_fraction > c.line_max_split_row_fraction
                or coverage < c.line_min_row_coverage
                or len(rows) < c.line_min_geometry_rows
            ):
                rejected_geometry = True
                continue
            geometry, geometry_reasons, fit_rows = self._line_geometry(
                gray, component, rows, widths, top
            )
            geometric_confidence = confidence * max(
                0.0, 1 - geometry["fit_rms_fraction"] / c.line_max_fit_rms_fraction
            )
            sampled = fit_rows[np.linspace(0, len(fit_rows) - 1, c.line_samples).astype(int)]
            points = [
                [
                    float(np.flatnonzero(component[y]).mean()) / gray.shape[1],
                    float(y + top) / gray.shape[0],
                ]
                for y in sampled
            ]
            candidate = {
                "candidate_confidence": confidence,
                "confidence": geometric_confidence if not geometry_reasons else 0.0,
                "geometry": geometry,
                "geometry_reasons": geometry_reasons,
                "row_coverage": coverage,
                "median_width_fraction": median_width,
                "wide_row_fraction": wide_fraction,
                "split_row_fraction": split_fraction,
                "contrast": contrast,
                "points_normalized": points,
            }
            if geometry_reasons:
                rejected.append(candidate)
            else:
                candidates.append(candidate)
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        best = (
            candidates[0]
            if candidates
            else max(rejected, key=lambda item: item["candidate_confidence"])
            if rejected
            else {
                "confidence": 0.0,
                "candidate_confidence": 0.0,
                "geometry": None,
                "geometry_reasons": [],
                "row_coverage": 0.0,
                "median_width_fraction": 0.0,
                "wide_row_fraction": 0.0,
                "contrast": 0.0,
                "points_normalized": [],
            }
        )
        ambiguous = (
            len(candidates) > 1
            and candidates[1]["confidence"] >= best["confidence"] * c.line_competitor_ratio
        )
        geometric_ambiguity = bool(best["geometry_reasons"])
        detected = best["confidence"] >= c.line_confidence_min and not ambiguous
        return {
            **best,
            "confidence": 0.0 if ambiguous else best["confidence"],
            "points_normalized": best["points_normalized"] if detected else [],
            "coordinate_unit": "normalized_image",
            "semantic_identity": "unverified",
            "detected": detected,
            "geometry_consistent": best["geometry"] is not None and not geometric_ambiguity,
            "ambiguous": ambiguous or geometric_ambiguity,
            "status": "supported"
            if detected
            else "ambiguous"
            if ambiguous or geometric_ambiguity
            else "unknown",
            "candidate_count": len(candidates),
            "rejection_reasons": ["competing_lines"]
            if ambiguous
            else (
                []
                if detected
                else best["geometry_reasons"]
                if geometric_ambiguity
                else ["branched_or_insufficient_geometry"]
                if rejected_geometry
                else ["insufficient_line_support"]
            ),
        }

    def _line_geometry(self, gray, component, rows, widths, top):
        """Conservative near-field stripe consistency; it cannot establish ground semantics."""
        c = self.config
        h, w = gray.shape
        fit_rows = rows[
            (widths[rows] / w <= c.line_max_width_fraction)
            & (widths[rows] <= np.median(widths[rows]) * c.line_fit_width_multiplier)
        ]
        # Prior coverage/split gates guarantee enough rows for a non-degenerate fit.
        centers = np.array([np.flatnonzero(component[y]).mean() for y in fit_rows]) / w
        yy = (fit_rows + top) / h
        coefficients = np.polyfit(yy, centers, 1)
        errors = np.abs(centers - np.polyval(coefficients, yy))
        rms, maximum = float(np.sqrt(np.mean(errors**2))), float(errors.max())
        width_cv = float(np.std(widths[fit_rows]) / np.mean(widths[fit_rows]))
        _, xs = np.nonzero(component)
        side_margin = min(int(xs.min()), w - 1 - int(xs.max())) / w
        bottom_distance = (h - 1 - (int(rows[-1]) + top)) / h
        # Reject thin wall highlights continuing well above the configured floor ROI.
        above_y = np.arange(top)
        above_x = np.clip(np.rint(np.polyval(coefficients, above_y / h) * w).astype(int), 0, w - 1)
        sign = 1 if c.line_polarity == "bright" else -1
        above_signal = (gray[above_y, above_x].astype(float) - float(np.median(gray[top:]))) * sign
        above_fraction = float(np.mean(above_signal >= c.contrast_delta)) if top else 0.0
        geometry = {
            "fit_row_coverage": len(fit_rows) / component.shape[0],
            "fit_rms_fraction": rms,
            "fit_max_error_fraction": maximum,
            "width_cv": width_cv,
            "bottom_distance_fraction": bottom_distance,
            "side_margin_fraction": side_margin,
            "above_roi_continuation_fraction": above_fraction,
        }
        reasons = []
        if geometry["fit_row_coverage"] < c.line_min_row_coverage:
            reasons.append("line_fit_support_insufficient")
        if rms > c.line_max_fit_rms_fraction or maximum > c.line_max_fit_error_fraction:
            reasons.append("line_shape_inconsistent")
        if width_cv > c.line_max_width_cv:
            reasons.append("line_width_inconsistent")
        if bottom_distance > c.line_bottom_margin_fraction:
            reasons.append("line_near_field_unsupported")
        if side_margin <= c.line_side_margin_fraction:
            reasons.append("line_cropped_at_side")
        if above_fraction > c.line_max_above_roi_fraction:
            reasons.append("line_wall_edge_ambiguous")
        return geometry, reasons, fit_rows

    def _depth(self, sample) -> tuple[dict, ObstacleReport | None]:
        c = self.config
        image_age = (sample.evaluated_at_ns - sample.timestamp_ns) / 1e6
        reasons = []
        if not 0 <= image_age <= c.depth.max_age_ms:
            reasons.append("image_stale_or_future")
        if sample.depth_m is None:
            return {
                "valid": False,
                "image_age_ms": image_age,
                "valid_fraction": 0.0,
                "rejection_reasons": reasons + ["depth_missing"],
            }, None
        report = sector_report(
            sample.depth_m,
            sample.depth_valid,
            sample.depth_timestamp_ns,
            sample.intrinsics,
            now_ns=sample.evaluated_at_ns,
            config=c.depth,
        )
        skew = abs(sample.timestamp_ns - sample.depth_timestamp_ns) / 1e6
        if not report.fresh:
            reasons.append("depth_stale_or_future")
        if skew > c.depth_sync_max_ms:
            reasons.append("image_depth_unsynchronized")
        if not all(s.valid for s in report.sectors):
            reasons.append("depth_sector_degraded")
        return {
            "valid": not reasons,
            "image_age_ms": image_age,
            "age_ms": report.age_ms,
            "sync_skew_ms": skew,
            "valid_fraction": report.frame_valid_fraction,
            "rejection_reasons": reasons,
        }, report

    def _local_depth(self, sample, depth, mask):
        c = self.config
        reasons = list(depth["rejection_reasons"])
        if sample.depth_m is None:
            return None, 0.0, reasons
        z = sample.depth_m
        good = sample.depth_valid & np.isfinite(z) & (z >= c.depth.min_range_m)
        # Beyond configured range is unknown here (stricter than sector-report saturation).
        good &= z <= c.depth.max_range_m
        fraction = float(np.sum(good & mask)) / max(1, int(mask.sum()))
        if np.sum(good & mask) < c.local_depth_min_pixels or fraction < c.local_depth_min_fraction:
            reasons.append("local_depth_insufficient")
        if np.any(mask & sample.depth_valid & np.isfinite(z) & (z > 0) & (z < c.depth.min_range_m)):
            reasons.append("local_depth_blind_zone")
        return good & mask, fraction, reasons

    def _clearance(self, sample, depth, box):
        c = self.config
        x, y, w, h = box
        mx, my = int(w * c.roi_inset_fraction), int(h * c.roi_inset_fraction)
        mask = np.zeros(sample.image.shape[:2], bool)
        mask[y + my : y + h - my, x + mx : x + w - mx] = True
        good, fraction, reasons = self._local_depth(sample, depth, mask)
        result = {
            "scope": "local_camera_z_probe_plane",
            "supported_meaning": "observed_local_plane_width_only",
            "supported": False,
            "local_plane_supported": False,
            "full_3d_traversability": "UNKNOWN",
            "supports_3d_traversal": False,
            "authority_change": "NONE",
            "executed": False,
            "unassessed": [
                "outside_sampled_roi",
                "beyond_probe_plane",
                "occluded_volume",
                "swept_vehicle_volume",
                "dynamic_obstacles",
            ],
            "bbox_xywh": list(box),
            "bbox_normalized": _box_normalized(box, sample.image.shape),
            "sampled_bbox_normalized": _box_normalized(
                (x + mx, y + my, w - 2 * mx, h - 2 * my), sample.image.shape
            ),
            "valid_fraction": fraction,
            "probe_z_m": c.corridor_probe_m,
            "required_width_m": c.envelope_width_m + 2 * c.clearance_margin_m,
            "width_at_probe_m": None,
            "nearest_z_m": None,
            "free_column_span_normalized": None,
            "rgb_depth_consistency": "unverified",
            "rejection_reasons": reasons,
        }
        if sample.camera_view != "forward":
            reasons.append("camera_view_not_forward")
        if good is None:
            return result
        if not reasons and self._rgb_depth_conflict(sample, mask, good):
            # A compact visual structure against flat far depth might be paint OR a
            # mismatched/failed depth return. Neither interpretation licenses traversal.
            reasons.append("rgb_depth_conflict_suspected")
            result["rgb_depth_consistency"] = "ambiguous"
        if np.any(good):
            result["nearest_z_m"] = float(np.min(sample.depth_m[good]))
        # No unknown/near pixel is allowed to create a free column. No percentile can erase an obstacle.
        inner = np.s_[y + my : y + h - my, x + mx : x + w - mx]
        known = good[inner]
        z = sample.depth_m[inner]
        free_columns = np.mean(known, axis=0) >= c.local_depth_min_fraction
        free_columns &= ~np.any(~known | (z < c.corridor_probe_m), axis=0)
        longest = run = end = 0
        for column, free in enumerate(free_columns):
            run = run + 1 if free else 0
            if run > longest:
                longest, end = run, column + 1
        width = longest * c.corridor_probe_m / sample.intrinsics.fx
        # With untrusted timestamps/depth, numeric width is withheld rather than labelled free.
        if not reasons:
            result["width_at_probe_m"] = width
            result["free_column_span_normalized"] = [
                (x + mx + end - longest) / sample.image.shape[1],
                (x + mx + end) / sample.image.shape[1],
            ]
            if width < result["required_width_m"]:
                reasons.append("insufficient_observed_clearance")
        result["supported"] = not reasons
        result["local_plane_supported"] = result["supported"]
        return result

    def _rgb_depth_conflict(self, sample, mask, good):
        c = self.config
        gray = cv2.cvtColor(sample.image, cv2.COLOR_BGR2GRAY)
        contrast_mask = np.abs(gray.astype(float) - float(np.median(gray))) >= c.contrast_delta
        foreground = contrast_mask & mask
        count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(foreground))
        yy, xx = np.nonzero(mask)
        roi_w, roi_h = int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1)
        for label in range(1, count):
            _, _, w, h, area = stats[label]
            if (
                area / mask.sum() < c.rgb_conflict_min_area_fraction
                or min(w / roi_w, h / roi_h) < c.rgb_conflict_min_extent_fraction
                or area / (w * h) < c.rgb_conflict_min_fill_fraction
            ):
                continue
            inside = good & (labels == label)
            # A candidate ROI entirely inside a visual blocker must not erase its
            # surrounding context and become a new apparently clear aperture.
            outside = (
                sample.depth_valid
                & np.isfinite(sample.depth_m)
                & (sample.depth_m >= c.depth.min_range_m)
                & (sample.depth_m <= c.depth.max_range_m)
                & ~contrast_mask
            )
            if inside.sum() < c.local_depth_min_pixels or outside.sum() < c.local_depth_min_pixels:
                continue
            inside_z = float(np.median(sample.depth_m[inside]))
            outside_z = float(np.median(sample.depth_m[outside]))
            if (
                min(inside_z, outside_z) >= c.corridor_probe_m
                and abs(inside_z - outside_z) <= c.rgb_conflict_depth_delta_m
            ):
                return True
        return False

    def _openings(self, gray, sample, depth):
        c = self.config
        edges = cv2.Canny(gray, c.canny_low, c.canny_high)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            area = cv2.contourArea(contour)
            if not c.opening_min_area_fraction <= area / gray.size <= c.opening_max_area_fraction:
                continue
            polygon = cv2.approxPolyDP(
                contour, c.contour_epsilon_fraction * cv2.arcLength(contour, True), True
            )
            x, y, w, h = cv2.boundingRect(contour)
            if (
                len(polygon) != 4
                or not cv2.isContourConvex(polygon)
                or not c.opening_min_aspect <= w / h <= c.opening_max_aspect
                or area / (w * h) < c.opening_min_rectangularity
                or x == 0
                or y == 0
                or x + w >= gray.shape[1]
                or y + h >= gray.shape[0]
            ):
                continue
            if any(_iou((x, y, w, h), b[0]) >= c.candidate_nms_iou for b in boxes):
                continue
            boxes.append(((x, y, w, h), float(area / (w * h))))
            if len(boxes) >= c.candidate_limit:
                break
        results = [
            {
                "kind": "rectangular_opening_candidate",
                "bbox_xywh": list(box),
                "bbox_normalized": _box_normalized(box, gray.shape),
                "confidence": score,
                "exit_identity": "unverified",
                "clearance": self._clearance(sample, depth, box),
            }
            for box, score in boxes
        ]
        for opening in results:
            local = opening["clearance"]
            opening["rgb_depth_consistency"] = (
                "ambiguous"
                if local["rgb_depth_consistency"] == "ambiguous"
                else "visual_aperture_not_confirmed_by_depth"
                if "insufficient_observed_clearance" in local["rejection_reasons"]
                else "unverified"
            )
        return results

    def _landing(self, gray, sample, depth):
        c = self.config
        # Both contrast polarities permit bright paint on dark ground and its inverse.
        rings = []
        for polarity in ("bright", "dark"):
            contours, hierarchy = cv2.findContours(
                self._contrast_mask(gray, polarity), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
            )
            if hierarchy is None:
                continue
            for idx, contour in enumerate(contours):
                area, perimeter = cv2.contourArea(contour), cv2.arcLength(contour, True)
                if (
                    not c.ring_min_area_fraction <= area / gray.size <= c.ring_max_area_fraction
                    or perimeter == 0
                    or len(contour) < 5
                ):
                    continue
                circularity = 4 * math.pi * area / perimeter**2
                center, axes, _ = cv2.fitEllipse(contour)
                axis_ratio = min(axes) / max(axes)
                if circularity < c.ring_min_circularity or axis_ratio < c.ring_min_axis_ratio:
                    continue
                child = int(hierarchy[0, idx, 2])
                while child >= 0:
                    hole = contours[child]
                    hole_ratio = cv2.contourArea(hole) / area
                    moments = cv2.moments(hole)
                    if moments["m00"]:
                        hole_center = (
                            moments["m10"] / moments["m00"],
                            moments["m01"] / moments["m00"],
                        )
                        offset = math.dist(center, hole_center) / max(axes)
                        if (
                            c.ring_min_hole_ratio <= hole_ratio <= c.ring_max_hole_ratio
                            and offset <= c.ring_max_center_offset
                        ):
                            rings.append(
                                (
                                    circularity * axis_ratio,
                                    contour,
                                    hole,
                                    circularity,
                                    axis_ratio,
                                    hole_ratio,
                                )
                            )
                    child = int(hierarchy[0, child, 0])
        if not rings:
            return {
                "detected": False,
                "confidence": 0.0,
                "candidate": None,
                "descent_geometry_suitable": False,
                "rejection_reasons": ["no_outer_ring"],
            }
        rings.sort(key=lambda ring: ring[0], reverse=True)
        score, contour, hole, circularity, axis_ratio, hole_ratio = rings[0]
        box = cv2.boundingRect(contour)
        x, y, w, h = box
        mask = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(mask, [hole], -1, 1, cv2.FILLED)
        good, fraction, reasons = self._local_depth(sample, depth, mask.astype(bool))
        if sample.camera_view != "downward":
            reasons.append("camera_view_not_downward")
        border = c.ring_border_fraction * min(gray.shape)
        if min(x, y, gray.shape[1] - x - w, gray.shape[0] - y - h) < border:
            reasons.append("ring_clipped_or_near_border")
        # Multiple spatially distinct pads cannot be silently resolved by contour ordering.
        if any(_iou(box, cv2.boundingRect(ring[1])) < c.candidate_nms_iou for ring in rings[1:]):
            reasons.append("competing_outer_rings")
        plane = None
        confidence = min(1.0, score)
        footprint_diameter = None
        if good is not None and np.sum(good) >= c.local_depth_min_pixels:
            plane = self._plane(sample, good)
            _, _, hole_w, hole_h = cv2.boundingRect(hole)
            footprint_diameter = (
                min(hole_w / sample.intrinsics.fx, hole_h / sample.intrinsics.fy) * plane["min_z_m"]
            )
            if footprint_diameter < c.envelope_width_m + 2 * c.clearance_margin_m:
                reasons.append("landing_footprint_too_small")
            confidence *= fraction
            if not c.landing_min_z_m <= plane["min_z_m"] <= plane["max_z_m"] <= c.landing_max_z_m:
                reasons.append("landing_depth_out_of_range")
            if plane["max_residual_m"] > c.plane_max_residual_m:
                reasons.append("landing_surface_not_planar")
            if not plane["rank_sufficient"]:
                reasons.append("landing_surface_rank_deficient")
            if plane["tilt_to_optical_axis_deg"] > c.plane_max_tilt_deg:
                reasons.append("landing_surface_tilted")
        if confidence < c.landing_confidence_min:
            reasons.append("ring_confidence_low")
        # Reuse the existing candidate ROI schema. Unknown dynamic/semantic cues remain
        # pessimistic and `safe` remains False: geometric suitability is a separate advisory.
        candidate = ZoneCandidate(
            zone_id="outer-ring",
            bbox_xywh=box,
            score=confidence,
            edge_density=float(
                np.mean(cv2.Canny(gray, c.canny_low, c.canny_high)[y : y + h, x : x + w] > 0)
            ),
            motion_occupancy=1.0,
            texture_risk=1.0,
            appearance_occupancy=1.0,
            clearance=0.0,
            safe=False,
        )
        return {
            "detected": True,
            "confidence": confidence,
            "candidate": jsonable(candidate),
            "bbox_normalized": _box_normalized(box, gray.shape),
            "circularity": circularity,
            "axis_ratio": axis_ratio,
            "hole_ratio": hole_ratio,
            "valid_depth_fraction": fraction,
            "plane": plane,
            "inner_diameter_proxy_m": footprint_diameter,
            "descent_geometry_suitable": not reasons,
            "rejection_reasons": reasons,
            "unassessed": [
                "motion",
                "semantic_pad_identity",
                "gravity_alignment",
                "full_3d_vehicle_footprint",
                "touchdown_dynamics",
            ],
        }

    def _plane(self, sample, good):
        c = self.config
        yy, xx = np.nonzero(good)
        # Bound SVD cost; extrema/residuals are checked on every valid pixel below.
        z = sample.depth_m[good].astype(float)
        k = sample.intrinsics
        points = np.column_stack(((xx - k.cx) * z / k.fx, (yy - k.cy) * z / k.fy, z))
        chosen = points[
            np.linspace(0, len(points) - 1, min(c.plane_max_samples, len(points))).astype(int)
        ]
        center = chosen.mean(axis=0)
        _, singular, axes = np.linalg.svd(chosen - center, full_matrices=False)
        normal = axes[-1]
        residual = np.abs((points - center) @ normal)
        # Rank < 2 cannot define a surface plane.
        max_residual = float(residual.max())
        return {
            "max_residual_m": max_residual,
            "rank_sufficient": bool(singular[1] > np.finfo(float).eps),
            "tilt_to_optical_axis_deg": math.degrees(math.acos(min(1.0, abs(normal[2])))),
            "min_z_m": float(z.min()),
            "max_z_m": float(z.max()),
            "point_count": len(points),
        }
