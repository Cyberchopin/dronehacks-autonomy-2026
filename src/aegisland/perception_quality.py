from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np


class PerceptionFailureType(StrEnum):
    HEALTHY = "healthy"
    OVEREXPOSED = "overexposed"
    UNDEREXPOSED = "underexposed"
    BLURRED = "blurred"
    TEXTURE_DEGENERATE = "texture_degenerate"
    OCCLUSION_SUSPECTED = "occlusion_suspected"
    GEOMETRY_UNSTABLE = "geometry_unstable"


@dataclass(frozen=True, slots=True)
class PerceptionQualityResult:
    failure_type: PerceptionFailureType
    quality_score: float

    mean_brightness: float
    bright_ratio: float
    dark_ratio: float
    sharpness: float
    entropy_bits: float

    feature_count: int
    largest_dark_region_ratio: float

    geometry_score: float
    reasons: tuple[str, ...]


class PerceptionQualityMonitor:
    """
    Stateless semantic self-diagnosis for visual perception.

    The monitor does not decide flight actions. It explains whether the
    current image/geometry is trustworthy and why it may be degrading.

    Thresholds are prototype heuristics and must be calibrated through
    deterministic fault benchmarks before being treated as safety limits.
    """

    def __init__(
        self,
        *,
        bright_pixel_threshold: int = 245,
        dark_pixel_threshold: int = 12,
        overexposure_ratio: float = 0.65,
        underexposure_ratio: float = 0.75,
        blur_sharpness_gate: float = 18.0,
        texture_entropy_gate: float = 2.0,
        texture_feature_gate: int = 20,
        geometry_match_gate: int = 20,
        geometry_inlier_gate: float = 0.30,
        max_features: int = 500,
    ) -> None:
        self.bright_pixel_threshold = bright_pixel_threshold
        self.dark_pixel_threshold = dark_pixel_threshold

        self.overexposure_ratio = overexposure_ratio
        self.underexposure_ratio = underexposure_ratio

        self.blur_sharpness_gate = blur_sharpness_gate

        self.texture_entropy_gate = texture_entropy_gate
        self.texture_feature_gate = texture_feature_gate

        self.geometry_match_gate = geometry_match_gate
        self.geometry_inlier_gate = geometry_inlier_gate

        self.orb = cv2.ORB_create(
            nfeatures=max_features,
        )

    def analyze(
        self,
        gray: np.ndarray,
        *,
        has_reference: bool,
        match_count: int,
        inlier_ratio: float,
        compensation_used: bool,
    ) -> PerceptionQualityResult:
        if gray is None or gray.size == 0:
            raise ValueError(
                "gray must be a non-empty image"
            )

        if gray.ndim == 3:
            gray = cv2.cvtColor(
                gray,
                cv2.COLOR_BGR2GRAY,
            )

        mean_brightness = float(
            np.mean(gray)
        )

        bright_ratio = float(
            np.mean(
                gray >= self.bright_pixel_threshold
            )
        )

        dark_mask = np.uint8(
            gray <= self.dark_pixel_threshold
        ) * 255

        dark_ratio = float(
            np.mean(dark_mask > 0)
        )

        sharpness = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F,
            ).var()
        )

        entropy_bits = self._entropy(gray)

        keypoints = self.orb.detect(
            gray,
            None,
        )

        feature_count = len(keypoints)

        largest_dark_region_ratio = (
            self._largest_region_ratio(
                dark_mask
            )
        )

        image_score = self._image_score(
            bright_ratio=bright_ratio,
            dark_ratio=dark_ratio,
            sharpness=sharpness,
            entropy_bits=entropy_bits,
            feature_count=feature_count,
        )

        geometry_score = self._geometry_score(
            has_reference=has_reference,
            match_count=match_count,
            inlier_ratio=inlier_ratio,
        )

        if has_reference:
            quality_score = (
                0.70 * image_score
                + 0.30 * geometry_score
            )
        else:
            quality_score = image_score

        failure_type, reasons = self._classify(
            mean_brightness=mean_brightness,
            bright_ratio=bright_ratio,
            dark_ratio=dark_ratio,
            sharpness=sharpness,
            entropy_bits=entropy_bits,
            feature_count=feature_count,
            largest_dark_region_ratio=(
                largest_dark_region_ratio
            ),
            has_reference=has_reference,
            match_count=match_count,
            inlier_ratio=inlier_ratio,
            compensation_used=compensation_used,
        )

        # Semantic states also provide a conservative upper bound.
        caps = {
            PerceptionFailureType.OVEREXPOSED: 0.25,
            PerceptionFailureType.UNDEREXPOSED: 0.25,
            PerceptionFailureType.BLURRED: 0.45,
            PerceptionFailureType.TEXTURE_DEGENERATE: 0.35,
            PerceptionFailureType.OCCLUSION_SUSPECTED: 0.40,
            PerceptionFailureType.GEOMETRY_UNSTABLE: 0.50,
        }

        cap = caps.get(failure_type)

        if cap is not None:
            quality_score = min(
                quality_score,
                cap,
            )

        return PerceptionQualityResult(
            failure_type=failure_type,
            quality_score=round(
                self._clamp(quality_score),
                4,
            ),
            mean_brightness=round(
                mean_brightness,
                3,
            ),
            bright_ratio=round(
                bright_ratio,
                4,
            ),
            dark_ratio=round(
                dark_ratio,
                4,
            ),
            sharpness=round(
                sharpness,
                3,
            ),
            entropy_bits=round(
                entropy_bits,
                4,
            ),
            feature_count=feature_count,
            largest_dark_region_ratio=round(
                largest_dark_region_ratio,
                4,
            ),
            geometry_score=round(
                geometry_score,
                4,
            ),
            reasons=tuple(reasons),
        )

    def _classify(
        self,
        *,
        mean_brightness: float,
        bright_ratio: float,
        dark_ratio: float,
        sharpness: float,
        entropy_bits: float,
        feature_count: int,
        largest_dark_region_ratio: float,
        has_reference: bool,
        match_count: int,
        inlier_ratio: float,
        compensation_used: bool,
    ) -> tuple[
        PerceptionFailureType,
        list[str],
    ]:
        if (
            bright_ratio >= self.overexposure_ratio
            or mean_brightness >= 240.0
        ):
            return (
                PerceptionFailureType.OVEREXPOSED,
                [
                    "Large image regions are near sensor saturation.",
                ],
            )

        if (
            dark_ratio >= self.underexposure_ratio
            or mean_brightness <= 15.0
        ):
            return (
                PerceptionFailureType.UNDEREXPOSED,
                [
                    "Most image information is near the dark floor.",
                ],
            )

        if (
            0.20
            <= largest_dark_region_ratio
            <= 0.90
            and dark_ratio >= 0.18
            and mean_brightness > 15.0
        ):
            return (
                PerceptionFailureType.OCCLUSION_SUSPECTED,
                [
                    "A large spatially connected dark region blocks visual information.",
                ],
            )

        if (
            entropy_bits < self.texture_entropy_gate
            and feature_count
            < self.texture_feature_gate
        ):
            return (
                PerceptionFailureType.TEXTURE_DEGENERATE,
                [
                    "The frame contains too little visual information for robust feature geometry.",
                ],
            )

        if (
            sharpness < self.blur_sharpness_gate
            and entropy_bits
            >= self.texture_entropy_gate
        ):
            return (
                PerceptionFailureType.BLURRED,
                [
                    "High-frequency spatial detail collapsed while image information remains present.",
                ],
            )

        if (
            has_reference
            and not compensation_used
            and feature_count >= 40
            and (
                match_count
                < self.geometry_match_gate
                or inlier_ratio
                < self.geometry_inlier_gate
            )
        ):
            return (
                PerceptionFailureType.GEOMETRY_UNSTABLE,
                [
                    "Image appearance remains informative but geometric correspondence is unreliable.",
                ],
            )

        return (
            PerceptionFailureType.HEALTHY,
            [
                "Image statistics and geometric evidence remain usable.",
            ],
        )

    @staticmethod
    def _entropy(
        gray: np.ndarray,
    ) -> float:
        histogram = cv2.calcHist(
            [gray],
            [0],
            None,
            [256],
            [0, 256],
        ).ravel()

        total = float(histogram.sum())

        if total <= 0.0:
            return 0.0

        probabilities = (
            histogram[histogram > 0]
            / total
        )

        return float(
            -np.sum(
                probabilities
                * np.log2(probabilities)
            )
        )

    @staticmethod
    def _largest_region_ratio(
        binary_mask: np.ndarray,
    ) -> float:
        contours, _ = cv2.findContours(
            binary_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        if not contours:
            return 0.0

        largest = max(
            cv2.contourArea(contour)
            for contour in contours
        )

        return float(
            largest
            / max(1, binary_mask.size)
        )

    @staticmethod
    def _image_score(
        *,
        bright_ratio: float,
        dark_ratio: float,
        sharpness: float,
        entropy_bits: float,
        feature_count: int,
    ) -> float:
        exposure_score = max(
            0.0,
            1.0 - max(
                bright_ratio,
                dark_ratio,
            ),
        )

        sharpness_score = min(
            1.0,
            sharpness / 150.0,
        )

        entropy_score = min(
            1.0,
            entropy_bits / 6.0,
        )

        feature_score = min(
            1.0,
            feature_count / 250.0,
        )

        return (
            0.30 * exposure_score
            + 0.25 * sharpness_score
            + 0.20 * entropy_score
            + 0.25 * feature_score
        )

    @staticmethod
    def _geometry_score(
        *,
        has_reference: bool,
        match_count: int,
        inlier_ratio: float,
    ) -> float:
        if not has_reference:
            return 1.0

        match_score = min(
            1.0,
            max(0.0, match_count / 60.0),
        )

        inlier_score = min(
            1.0,
            max(0.0, inlier_ratio / 0.70),
        )

        return (
            0.45 * match_score
            + 0.55 * inlier_score
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(
            0.0,
            min(1.0, float(value)),
        )
