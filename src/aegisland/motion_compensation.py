from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

# Two entries keep both the base frame and an active-perception retry frame.
FEATURE_CACHE_SIZE = 2


def require_opencv() -> None:
    if cv2 is None or np is None:
        raise RuntimeError(
            "OpenCV and NumPy are required. Run: pip install -e '.[dev]'"
        )


@dataclass(frozen=True, slots=True)
class MotionCompensationResult:
    aligned_previous: Any
    homography: Any | None
    match_count: int
    inlier_count: int
    inlier_ratio: float
    success: bool


class CameraMotionCompensator:
    """Estimate camera motion with ORB + RANSAC homography."""

    def __init__(
        self,
        *,
        max_features: int = 1200,
        minimum_matches: int = 20,
        minimum_inliers: int = 12,
        minimum_inlier_ratio: float = 0.30,
        maximum_corner_displacement_ratio: float = 0.35,
        enabled: bool = True,
    ) -> None:
        require_opencv()

        self.max_features = max_features
        self.minimum_matches = minimum_matches
        self.minimum_inliers = minimum_inliers
        self.minimum_inlier_ratio = minimum_inlier_ratio
        self.maximum_corner_displacement_ratio = maximum_corner_displacement_ratio
        self.enabled = enabled

        self.orb = cv2.ORB_create(
            nfeatures=max_features,
        )

        self.matcher = cv2.BFMatcher(
            cv2.NORM_HAMMING,
            crossCheck=False,
        )

        # The previous frame of call N is usually the current frame of call N-1.
        # ORB is deterministic, so features are reused only for byte-identical
        # images (a private copy is compared, so caller mutation cannot leak in).
        self._feature_cache: list[tuple[Any, Any, Any]] = []

    def _features(self, gray: Any) -> tuple[Any, Any]:
        for cached_gray, keypoints, descriptors in self._feature_cache:
            if (
                cached_gray.shape == gray.shape
                and cached_gray.dtype == gray.dtype
                and np.array_equal(cached_gray, gray)
            ):
                return keypoints, descriptors

        keypoints, descriptors = self.orb.detectAndCompute(gray, None)
        self._feature_cache = [
            (np.array(gray, copy=True), keypoints, descriptors),
            *self._feature_cache,
        ][:FEATURE_CACHE_SIZE]
        return keypoints, descriptors

    def compensate(
        self,
        previous_gray: Any,
        current_gray: Any,
    ) -> MotionCompensationResult:
        if not self.enabled:
            return self._failure(previous_gray)
        if previous_gray is None:
            return MotionCompensationResult(
                aligned_previous=current_gray,
                homography=None,
                match_count=0,
                inlier_count=0,
                inlier_ratio=0.0,
                success=False,
            )

        if previous_gray.shape != current_gray.shape:
            return MotionCompensationResult(
                aligned_previous=previous_gray,
                homography=None,
                match_count=0,
                inlier_count=0,
                inlier_ratio=0.0,
                success=False,
            )

        prev_keypoints, prev_descriptors = self._features(previous_gray)
        curr_keypoints, curr_descriptors = self._features(current_gray)

        if prev_descriptors is None or curr_descriptors is None:
            return self._failure(previous_gray)

        knn_matches = self.matcher.knnMatch(
            prev_descriptors,
            curr_descriptors,
            k=2,
        )

        matches = []

        for pair in knn_matches:
            if len(pair) < 2:
                continue

            best, second_best = pair

            if best.distance < 0.75 * second_best.distance:
                matches.append(best)

        matches = sorted(
            matches,
            key=lambda match: match.distance,
        )

        if len(matches) < self.minimum_matches:
            return MotionCompensationResult(
                aligned_previous=previous_gray,
                homography=None,
                match_count=len(matches),
                inlier_count=0,
                inlier_ratio=0.0,
                success=False,
            )

        source_points = np.float32(
            [
                prev_keypoints[match.queryIdx].pt
                for match in matches
            ]
        ).reshape(-1, 1, 2)

        destination_points = np.float32(
            [
                curr_keypoints[match.trainIdx].pt
                for match in matches
            ]
        ).reshape(-1, 1, 2)

        homography, mask = cv2.findHomography(
            source_points,
            destination_points,
            cv2.RANSAC,
            3.0,
        )

        if homography is None or mask is None:
            return MotionCompensationResult(
                aligned_previous=previous_gray,
                homography=None,
                match_count=len(matches),
                inlier_count=0,
                inlier_ratio=0.0,
                success=False,
            )

        inlier_count = int(mask.ravel().sum())
        inlier_ratio = inlier_count / max(1, len(matches))

        if (
            inlier_count < self.minimum_inliers
            or inlier_ratio < self.minimum_inlier_ratio
            or not self._homography_is_sane(
                homography,
                current_gray.shape,
            )
        ):
            return MotionCompensationResult(
                aligned_previous=previous_gray,
                homography=homography,
                match_count=len(matches),
                inlier_count=inlier_count,
                inlier_ratio=inlier_count / max(1, len(matches)),
                success=False,
            )

        height, width = current_gray.shape

        aligned_previous = cv2.warpPerspective(
            previous_gray,
            homography,
            (width, height),
        )

        return MotionCompensationResult(
            aligned_previous=aligned_previous,
            homography=homography,
            match_count=len(matches),
            inlier_count=inlier_count,
            inlier_ratio=inlier_count / max(1, len(matches)),
            success=True,
        )

    def _homography_is_sane(
        self,
        homography: Any,
        image_shape: tuple[int, int],
    ) -> bool:
        if homography is None:
            return False

        if not np.isfinite(homography).all():
            return False

        height, width = image_shape

        corners = np.float32(
            [
                [0, 0],
                [width - 1, 0],
                [width - 1, height - 1],
                [0, height - 1],
            ]
        ).reshape(-1, 1, 2)

        warped_corners = cv2.perspectiveTransform(
            corners,
            homography,
        )

        displacement = np.linalg.norm(
            warped_corners.reshape(-1, 2)
            - corners.reshape(-1, 2),
            axis=1,
        )

        image_diagonal = float(
            np.hypot(width, height)
        )

        maximum_allowed = (
            image_diagonal
            * self.maximum_corner_displacement_ratio
        )

        return bool(
            np.max(displacement) <= maximum_allowed
        )

    def _failure(self, previous_gray: Any) -> MotionCompensationResult:
        return MotionCompensationResult(
            aligned_previous=previous_gray,
            homography=None,
            match_count=0,
            inlier_count=0,
            inlier_ratio=0.0,
            success=False,
        )
