from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any

from .domain import VisionEvidence, ZoneCandidate
from .gps_denied import VisualDeadReckoner
from .motion_compensation import CameraMotionCompensator
from .perception_quality import PerceptionQualityMonitor

try:
    import cv2
    import numpy as np
except ImportError:  # Allows policy-only tests without the vision extras installed.
    cv2 = None
    np = None


def require_opencv() -> None:
    if cv2 is None or np is None:
        raise RuntimeError("OpenCV 5 and NumPy are required. Run: pip install -e '.[dev]'")


def clahe_gray(gray: Any, *, clip_limit: float = 2.2, tiles: int = 8) -> Any:
    """Shared same-frame exposure retry; it makes no confidence/authority claim."""
    return cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tiles, tiles)).apply(gray)


@dataclass(frozen=True, slots=True)
class PerceptionConfig:
    grid_rows: int = 3
    grid_cols: int = 4
    maximum_width: int = 960
    flow_threshold: float = 1.8
    safe_zone_threshold: float = 0.64
    minimum_zone_area_ratio: float = 0.035


class OpenCVLandingPerception:
    """Multi-cue landing-zone perception built from OpenCV primitives.

    It combines Canny structure, Laplacian texture, dense Farneback optical flow,
    morphology, contour analysis and grid-based clearance. No score is presented
    as semantic certainty: it is a measurable safety heuristic for the prototype.
    """

    def __init__(self, config: PerceptionConfig | None = None) -> None:
        require_opencv()
        self.config = config or PerceptionConfig()
        self.previous_gray: Any | None = None
        self._active_reference_gray: Any | None = None
        self.motion_compensator = CameraMotionCompensator()
        self.visual_dead_reckoner = VisualDeadReckoner()
        self.perception_quality_monitor = PerceptionQualityMonitor()

    def observe(
        self,
        frame: Any,
        frame_index: int,
        *,
        active_perception: bool = False,
    ) -> tuple[VisionEvidence, Any]:
        started = time.perf_counter()
        frame = self._resize(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if active_perception:
            gray = clahe_gray(gray)

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 55, 145)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        texture = cv2.convertScaleAbs(cv2.Laplacian(blurred, cv2.CV_32F))
        reference_gray = self._active_reference_gray if active_perception else self.previous_gray
        motion_mask, motion_boxes, motion_metrics = self._motion(
            gray,
            reference_gray,
            update_visual_state=not active_perception,
        )

        perception_quality = (
            self.perception_quality_monitor.analyze(
                gray,
                has_reference=(
                    reference_gray is not None
                ),
                match_count=int(
                    motion_metrics["match_count"]
                ),
                inlier_ratio=float(
                    motion_metrics["inlier_ratio"]
                ),
                compensation_used=bool(
                    motion_metrics[
                        "compensation_used"
                    ]
                ),
            )
        )

        candidates = self._score_grid(gray, edges, texture, motion_mask, motion_boxes)
        lower = slice(frame.shape[0] // 3, frame.shape[0])
        obstacle_risk = float(np.mean(edges[lower] > 0))
        motion_risk = float(np.mean(motion_mask[lower] > 0))

        contrast = float(np.std(gray))
        dynamic_range = float(np.percentile(gray, 95) - np.percentile(gray, 5))
        confidence = min(0.98, 0.34 + min(0.30, contrast / 180) + min(0.30, dynamic_range / 300))
        if active_perception:
            confidence = min(0.99, confidence + 0.06)

        payload = {
            "frame": frame_index,
            "confidence": round(confidence, 4),
            "obstacle": round(obstacle_risk, 4),
            "motion": round(motion_risk, 4),
            "zones": [(candidate.zone_id, round(candidate.score, 4)) for candidate in candidates],
        }
        evidence_id = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
        elapsed_ms = (time.perf_counter() - started) * 1000
        notes = (
            "CLAHE active-perception retry applied." if active_perception else "Base exposure pass.",
            f"Detected {len(motion_boxes)} moving regions.",
        )
        motion_object_center = None

        if motion_boxes:
            dominant_box = max(
                motion_boxes,
                key=lambda box: box[2] * box[3],
            )

            box_x, box_y, box_w, box_h = dominant_box

            motion_object_center = (
                box_x + box_w / 2.0,
                box_y + box_h / 2.0,
            )

        evidence = VisionEvidence(
            evidence_id=evidence_id,
            frame_index=frame_index,
            confidence=round(confidence, 4),
            obstacle_risk=round(min(1.0, obstacle_risk * 4.5), 4),
            motion_risk=round(min(1.0, motion_risk * 5.5), 4),
            candidates=tuple(candidates),
            active_perception_used=active_perception,
            processing_ms=round(elapsed_ms, 3),
            camera_compensation_used=bool(
                motion_metrics["compensation_used"]
            ),
            camera_match_count=int(
                motion_metrics["match_count"]
            ),
            camera_inlier_count=int(
                motion_metrics["inlier_count"]
            ),
            camera_inlier_ratio=float(
                motion_metrics["inlier_ratio"]
            ),
            raw_motion_risk=float(
                motion_metrics["raw_motion_risk"]
            ),
            motion_suppression_ratio=float(
                motion_metrics["suppression_ratio"]
            ),
            motion_object_center=motion_object_center,
            visual_localization_valid=bool(
                motion_metrics.get(
                    "visual_localization_valid",
                    False,
                )
            ),
            visual_localization_confidence=float(
                motion_metrics.get(
                    "visual_localization_confidence",
                    0.0,
                )
            ),
            visual_relative_x=float(
                motion_metrics.get("visual_relative_x", 0.0)
            ),
            visual_relative_y=float(
                motion_metrics.get("visual_relative_y", 0.0)
            ),
            visual_velocity_x=float(
                motion_metrics.get("visual_velocity_x", 0.0)
            ),
            visual_velocity_y=float(
                motion_metrics.get("visual_velocity_y", 0.0)
            ),

            perception_quality_score=(
                perception_quality.quality_score
            ),
            perception_failure_type=(
                perception_quality.failure_type.value
            ),

            perception_mean_brightness=(
                perception_quality.mean_brightness
            ),
            perception_bright_ratio=(
                perception_quality.bright_ratio
            ),
            perception_dark_ratio=(
                perception_quality.dark_ratio
            ),
            perception_sharpness=(
                perception_quality.sharpness
            ),
            perception_entropy_bits=(
                perception_quality.entropy_bits
            ),
            perception_feature_count=(
                perception_quality.feature_count
            ),
            perception_largest_dark_region_ratio=(
                perception_quality
                .largest_dark_region_ratio
            ),
            perception_geometry_score=(
                perception_quality.geometry_score
            ),
            perception_failure_reasons=(
                perception_quality.reasons
            ),

            notes=notes + (
                (
                    "Perception self-diagnosis: "
                    f"{perception_quality.failure_type.value}; "
                    f"quality="
                    f"{perception_quality.quality_score:.2f}."
                ),
            ),
        )
        annotated = self._annotate(frame.copy(), evidence, motion_boxes)
        if not active_perception:
            # Keep the pre-frame reference for a same-frame active-perception retry.
            # Otherwise CLAHE's brightness change can be mistaken for physical motion.
            self._active_reference_gray = self.previous_gray
            self.previous_gray = gray
        return evidence, annotated

    def enhance_for_active_perception(self, frame: Any) -> Any:
        """Expose an explicit tool step so traces show why a second look happened."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        light, channel_a, channel_b = cv2.split(lab)
        light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
        return cv2.cvtColor(cv2.merge((light, channel_a, channel_b)), cv2.COLOR_LAB2BGR)

    def _resize(self, frame: Any) -> Any:
        height, width = frame.shape[:2]
        if width <= self.config.maximum_width:
            return frame
        ratio = self.config.maximum_width / width
        return cv2.resize(frame, (self.config.maximum_width, int(height * ratio)))

    def _motion(
        self,
        gray: Any,
        reference_gray: Any | None,
        *,
        update_visual_state: bool = True,
    ) -> tuple[
        Any,
        list[tuple[int, int, int, int]],
        dict[str, float | int | bool],
    ]:
        if reference_gray is None or reference_gray.shape != gray.shape:
            return (
                np.zeros_like(gray),
                [],
                {
                    "compensation_used": False,
                    "match_count": 0,
                    "inlier_count": 0,
                    "inlier_ratio": 0.0,
                    "raw_motion_risk": 0.0,
                    "suppression_ratio": 0.0,
                },
            )

        raw_flow = cv2.calcOpticalFlowFarneback(
            reference_gray,
            gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=17,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )

        raw_magnitude, _ = cv2.cartToPolar(
            raw_flow[..., 0],
            raw_flow[..., 1],
        )

        compensation = self.motion_compensator.compensate(
            reference_gray,
            gray,
        )

        if update_visual_state:
            visual_pose = self.visual_dead_reckoner.update(
                homography=(
                    compensation.homography
                    if compensation.success
                    else None
                ),
                image_shape=gray.shape,
                inlier_ratio=compensation.inlier_ratio,
            )
        else:
            # Active-perception is a second interpretation of the same
            # physical frame. It must not integrate or decay localization
            # state a second time.
            visual_pose = self.visual_dead_reckoner.current()

        aligned_reference = (
            compensation.aligned_previous
            if compensation.success
            else reference_gray
        )

        flow = cv2.calcOpticalFlowFarneback(
            aligned_reference,
            gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=17,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )

        magnitude, _ = cv2.cartToPolar(
            flow[..., 0],
            flow[..., 1],
        )

        raw_mean = float(np.mean(raw_magnitude))
        compensated_mean = float(np.mean(magnitude))

        suppression_ratio = (
            1.0 - compensated_mean / raw_mean
            if raw_mean > 1e-6
            else 0.0
        )

        suppression_ratio = max(
            0.0,
            min(1.0, suppression_ratio),
        )

        mask = np.uint8(
            magnitude > self.config.flow_threshold
        ) * 255

        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (7, 7),
        )

        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            kernel,
        )

        mask = cv2.dilate(
            mask,
            kernel,
            iterations=2,
        )

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        minimum_area = gray.size * 0.0015

        boxes = [
            cv2.boundingRect(contour)
            for contour in contours
            if cv2.contourArea(contour) >= minimum_area
        ]

        metrics = {
            "compensation_used": compensation.success,
            "match_count": compensation.match_count,
            "inlier_count": compensation.inlier_count,
            "inlier_ratio": round(compensation.inlier_ratio, 4),
            "raw_motion_risk": round(raw_mean, 4),
            "suppression_ratio": round(suppression_ratio, 4),
            "visual_localization_valid": visual_pose.valid,
            "visual_localization_confidence": round(
                visual_pose.confidence,
                4,
            ),
            "visual_relative_x": round(visual_pose.x, 6),
            "visual_relative_y": round(visual_pose.y, 6),
            "visual_velocity_x": round(visual_pose.vx, 6),
            "visual_velocity_y": round(visual_pose.vy, 6),
        }

        return mask, boxes, metrics

    def _score_grid(
        self,
        gray: Any,
        edges: Any,
        texture: Any,
        motion: Any,
        motion_boxes: list[tuple[int, int, int, int]],
    ) -> list[ZoneCandidate]:
        height, width = edges.shape
        cell_h = height // self.config.grid_rows
        cell_w = width // self.config.grid_cols
        candidates: list[ZoneCandidate] = []
        image_diag = math.hypot(width, height)
        # Relative darkness is an appearance anomaly cue, not an object identity.
        # The median-relative threshold remains usable after a global light drop.
        relative_threshold = max(8.0, float(np.median(gray)) * 0.76)
        appearance_mask = np.uint8(gray < relative_threshold) * 255
        appearance_mask = cv2.morphologyEx(
            appearance_mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        )

        for row in range(1, self.config.grid_rows):  # Ignore the horizon/top third.
            for col in range(self.config.grid_cols):
                margin_x, margin_y = int(cell_w * 0.09), int(cell_h * 0.09)
                x = col * cell_w + margin_x
                y = row * cell_h + margin_y
                w = cell_w - 2 * margin_x
                h = cell_h - 2 * margin_y
                roi_edges = edges[y : y + h, x : x + w]
                roi_texture = texture[y : y + h, x : x + w]
                roi_motion = motion[y : y + h, x : x + w]
                roi_appearance = appearance_mask[y : y + h, x : x + w]

                edge_density = float(np.mean(roi_edges > 0))
                motion_occupancy = float(np.mean(roi_motion > 0))
                texture_risk = min(1.0, float(np.mean(roi_texture)) / 55.0)
                appearance_occupancy = float(np.mean(roi_appearance > 0))

                center = (x + w / 2, y + h / 2)
                if motion_boxes:
                    distances = []
                    for bx, by, bw, bh in motion_boxes:
                        box_center = (bx + bw / 2, by + bh / 2)
                        distances.append(math.dist(center, box_center) / image_diag)
                    clearance = min(1.0, min(distances) * 3.0)
                else:
                    clearance = 1.0

                score = (
                    0.22 * (1.0 - min(1.0, edge_density * 4.0))
                    + 0.28 * (1.0 - min(1.0, motion_occupancy * 5.0))
                    + 0.12 * (1.0 - texture_risk)
                    + 0.22 * (1.0 - min(1.0, appearance_occupancy * 4.0))
                    + 0.16 * clearance
                )
                safe = (
                    score >= self.config.safe_zone_threshold
                    and edge_density < 0.16
                    and motion_occupancy < 0.10
                    and appearance_occupancy < 0.08
                    and clearance >= 0.48
                )
                candidates.append(
                    ZoneCandidate(
                        zone_id=f"Z{row}-{col}",
                        bbox_xywh=(x, y, w, h),
                        score=round(score, 4),
                        edge_density=round(edge_density, 4),
                        motion_occupancy=round(motion_occupancy, 4),
                        texture_risk=round(texture_risk, 4),
                        appearance_occupancy=round(appearance_occupancy, 4),
                        clearance=round(clearance, 4),
                        safe=safe,
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)

    @staticmethod
    def _annotate(frame: Any, evidence: VisionEvidence, boxes: list[tuple[int, int, int, int]]) -> Any:
        best_id = evidence.best_zone.zone_id if evidence.best_zone else None
        for candidate in evidence.candidates:
            x, y, w, h = candidate.bbox_xywh
            color = (50, 220, 110) if candidate.safe else (60, 170, 245)
            thickness = 3 if candidate.zone_id == best_id else 1
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness)
            cv2.putText(
                frame,
                f"{candidate.zone_id} {candidate.score:.2f}",
                (x + 5, y + 19),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2.LINE_AA,
            )
        for x, y, w, h in boxes:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (55, 55, 255), 2)
            cv2.putText(frame, "MOTION", (x, max(18, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (55, 55, 255), 2)
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 42), (10, 16, 25), -1)
        cv2.putText(
            frame,
            f"VISION conf={evidence.confidence:.2f} obstacle={evidence.obstacle_risk:.2f} motion={evidence.motion_risk:.2f}",
            (15, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.61,
            (235, 240, 247),
            1,
            cv2.LINE_AA,
        )
        return frame
