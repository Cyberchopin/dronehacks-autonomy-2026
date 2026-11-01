import cv2
import numpy as np

from aegisland.perception_quality import (
    PerceptionFailureType,
    PerceptionQualityMonitor,
)


def textured_frame() -> np.ndarray:
    rng = np.random.default_rng(7)

    return rng.integers(
        25,
        230,
        size=(240, 320),
        dtype=np.uint8,
    )


def analyze(
    frame: np.ndarray,
    *,
    has_reference: bool = False,
    match_count: int = 0,
    inlier_ratio: float = 0.0,
    compensation_used: bool = False,
):
    return PerceptionQualityMonitor().analyze(
        frame,
        has_reference=has_reference,
        match_count=match_count,
        inlier_ratio=inlier_ratio,
        compensation_used=compensation_used,
    )


def test_healthy_textured_frame() -> None:
    result = analyze(
        textured_frame()
    )

    assert (
        result.failure_type
        == PerceptionFailureType.HEALTHY
    )

    assert result.quality_score > 0.6
    assert result.feature_count > 40


def test_overexposure_is_semantically_detected() -> None:
    frame = np.full(
        (240, 320),
        252,
        dtype=np.uint8,
    )

    result = analyze(frame)

    assert (
        result.failure_type
        == PerceptionFailureType.OVEREXPOSED
    )

    assert result.quality_score <= 0.25


def test_underexposure_is_semantically_detected() -> None:
    frame = np.zeros(
        (240, 320),
        dtype=np.uint8,
    )

    result = analyze(frame)

    assert (
        result.failure_type
        == PerceptionFailureType.UNDEREXPOSED
    )

    assert result.quality_score <= 0.25


def test_texture_degenerate_wall_is_detected() -> None:
    frame = np.full(
        (240, 320),
        128,
        dtype=np.uint8,
    )

    result = analyze(frame)

    assert (
        result.failure_type
        == PerceptionFailureType.TEXTURE_DEGENERATE
    )


def test_blur_is_detected() -> None:
    frame = textured_frame()

    blurred = cv2.GaussianBlur(
        frame,
        (41, 41),
        0,
    )

    result = analyze(blurred)

    assert (
        result.failure_type
        == PerceptionFailureType.BLURRED
    )


def test_large_occlusion_is_detected() -> None:
    frame = textured_frame()

    width = frame.shape[1]

    start = int(width * 0.15)
    end = int(width * 0.85)

    frame[:, start:end] = 0

    result = analyze(frame)

    assert (
        result.failure_type
        == PerceptionFailureType.OCCLUSION_SUSPECTED
    )


def test_geometry_failure_is_distinguished_from_bad_image() -> None:
    frame = textured_frame()

    result = analyze(
        frame,
        has_reference=True,
        match_count=0,
        inlier_ratio=0.0,
        compensation_used=False,
    )

    assert (
        result.failure_type
        == PerceptionFailureType.GEOMETRY_UNSTABLE
    )

    assert result.feature_count > 40
