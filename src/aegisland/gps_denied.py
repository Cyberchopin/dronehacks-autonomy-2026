from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class RelativePose2D:
    x: float
    y: float
    vx: float
    vy: float
    confidence: float
    valid: bool


class VisualDeadReckoner:
    """
    Lightweight GPS-denied relative-motion estimator.

    It converts frame-to-frame homography motion into an accumulated
    normalized local pose.

    IMPORTANT:
    - x/y are NOT meters.
    - This is NOT full VIO or SLAM.
    - It is a visual dead-reckoning prototype.
    """

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.30,
        confidence_decay: float = 0.85,
    ) -> None:
        self.minimum_confidence = minimum_confidence
        self.confidence_decay = confidence_decay

        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.confidence = 0.0

    def update(
        self,
        *,
        homography: Any | None,
        image_shape: tuple[int, int],
        inlier_ratio: float,
    ) -> RelativePose2D:
        if (
            homography is None
            or inlier_ratio < self.minimum_confidence
        ):
            self.vx = 0.0
            self.vy = 0.0
            self.confidence *= self.confidence_decay

            return self.current()

        height, width = image_shape

        center = np.array(
            [
                width / 2.0,
                height / 2.0,
                1.0,
            ],
            dtype=np.float64,
        )

        warped = homography @ center

        if abs(float(warped[2])) < 1e-9:
            self.confidence *= self.confidence_decay
            return self.current()

        warped = warped / warped[2]

        image_dx = float(
            warped[0] - center[0]
        )
        image_dy = float(
            warped[1] - center[1]
        )

        # Homography describes image motion.
        # Approximate camera motion points in the opposite direction.
        self.vx = -image_dx / max(float(width), 1.0)
        self.vy = -image_dy / max(float(height), 1.0)

        self.x += self.vx
        self.y += self.vy

        self.confidence = max(
            0.0,
            min(1.0, float(inlier_ratio)),
        )

        return self.current()

    def current(self) -> RelativePose2D:
        return RelativePose2D(
            x=self.x,
            y=self.y,
            vx=self.vx,
            vy=self.vy,
            confidence=self.confidence,
            valid=self.confidence >= self.minimum_confidence,
        )
