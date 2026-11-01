"""Deterministic offline fixtures. Drawing coordinates describe data, never detector rules."""

from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from .course_perception import OfflineFrame
from .depth_sectors import Intrinsics


def synthetic_frame(
    kind: str, *, width: int = 320, height: int = 240, offset: float = 0.0, scale: float = 1.0
) -> OfflineFrame:
    image = np.full((height, width, 3), 65, np.uint8)
    depth = np.full((height, width), 3.0, np.float32)
    valid = np.ones(depth.shape, bool)
    x = int(width * (0.5 + offset))
    thickness = max(2, int(width * 0.025 * scale))
    radius = max(4, int(min(width, height) * 0.23 * scale))
    view = "forward"
    if kind in {
        "line",
        "maze",
        "dim_line",
        "dim_recoverable",
        "parallel_lines",
        "branch",
        "broken_line",
        "dark_line",
    }:
        color = (245, 245, 245)
        if kind == "dark_line":
            image[:] = 210
            color = (5, 5, 5)
        if kind == "dim_line":
            image[:] = 3
            color = (7, 7, 7)
        if kind == "dim_recoverable":
            rng = np.random.default_rng(41)
            gray = rng.integers(5, 20, (height, width), dtype=np.uint8)
            image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            color = (50, 50, 50)
        cv2.line(image, (x, height - 1), (x, int(height * 0.35)), color, thickness)
        if kind == "maze":
            cv2.line(
                image,
                (x, int(height * 0.35)),
                (int(width * 0.20), int(height * 0.35)),
                color,
                thickness,
            )
        if kind == "parallel_lines":
            cv2.line(
                image,
                (int(width * 0.2), height - 1),
                (int(width * 0.2), int(height * 0.35)),
                color,
                thickness,
            )
        if kind == "branch":
            cv2.line(
                image,
                (x, int(height * 0.7)),
                (int(width * 0.1), int(height * 0.35)),
                color,
                thickness,
            )
        if kind == "broken_line":
            image[int(height * 0.4) : int(height * 0.85)] = 65
    elif kind in {"opening", "blocked_opening", "unknown_opening", "narrow_gap", "chicane"}:
        cv2.rectangle(
            image,
            (int(width * 0.20), int(height * 0.15)),
            (int(width * 0.80), int(height * 0.85)),
            (245, 245, 245),
            thickness,
        )
        if kind == "blocked_opening":
            depth[:] = 0.8
        if kind == "unknown_opening":
            valid[
                int(height * 0.35) : int(height * 0.65), int(width * 0.35) : int(width * 0.65)
            ] = False
        if kind in {"narrow_gap", "chicane"}:
            depth[:] = 0.8
            left, right = (0.45, 0.55) if kind == "narrow_gap" else (0.28, 0.65)
            depth[:, int(width * left) : int(width * right)] = 3.0
    elif kind in {
        "pad",
        "solid_disk",
        "ellipse",
        "clipped_pad",
        "intruded_pad",
        "tilted_pad",
        "dark_pad",
        "two_pads",
    }:
        view = "downward"
        depth[:] = 1.5
        center = (x, height // 2)
        if kind == "dark_pad":
            image[:] = 210
        color = (5, 5, 5) if kind == "dark_pad" else (245, 245, 245)
        if kind == "clipped_pad":
            center = (radius // 2, height // 2)
        if kind == "ellipse":
            cv2.ellipse(image, center, (radius, radius // 3), 0, 0, 360, color, thickness)
        elif kind == "two_pads":
            for px in (int(width * 0.23), int(width * 0.77)):
                cv2.circle(image, (px, height // 2), radius, color, thickness)
        else:
            cv2.circle(image, center, radius, color, -1 if kind == "solid_disk" else thickness)
        if kind == "intruded_pad":
            depth[height // 2 - 5 : height // 2 + 5, x - 5 : x + 5] = 0.65
        if kind == "tilted_pad":
            u = (np.arange(width) - (width - 1) / 2) / (width * 0.70)
            depth[:] = 1.5 / (1 - u * np.tan(np.deg2rad(30)))
    elif kind == "blackout":
        image[:] = 0
        valid[:] = False
    elif kind != "blank":
        raise ValueError(f"unknown synthetic fixture: {kind}")
    return OfflineFrame(
        image=image,
        frame_index=0,
        timestamp_ns=1_000_000_000,
        evaluated_at_ns=1_020_000_000,
        source_id=f"synthetic:{kind}",
        camera_view=view,
        depth_m=depth,
        depth_valid=valid,
        depth_timestamp_ns=1_000_000_000,
        intrinsics=Intrinsics(width * 0.70, width * 0.70, (width - 1) / 2, (height - 1) / 2),
        calibration_id="synthetic-pinhole-v1",
    )


def suite() -> list[OfflineFrame]:
    kinds = (
        "line",
        "maze",
        "opening",
        "dim_recoverable",
        "dim_line",
        "blackout",
        "chicane",
        "narrow_gap",
        "blocked_opening",
        "unknown_opening",
        "pad",
        "intruded_pad",
        "solid_disk",
        "ellipse",
        "parallel_lines",
        "branch",
        "broken_line",
        "blank",
        "tilted_pad",
        "clipped_pad",
        "dark_pad",
        "two_pads",
    )
    samples = [synthetic_frame(kind) for kind in kinds]
    base = synthetic_frame("line")
    samples.extend(
        [
            replace(base, source_id="synthetic:stale_depth", depth_timestamp_ns=700_000_000),
            replace(
                base, source_id="synthetic:unsynchronized_depth", depth_timestamp_ns=950_000_000
            ),
            replace(
                base,
                source_id="synthetic:missing_depth",
                depth_m=None,
                depth_valid=None,
                depth_timestamp_ns=None,
                intrinsics=None,
                calibration_id=None,
            ),
            replace(
                base, source_id="synthetic:blind_zone", depth_m=np.full_like(base.depth_m, 0.1)
            ),
        ]
    )
    return [replace(sample, frame_index=index) for index, sample in enumerate(samples)]


def adversarial_frame(
    kind: str, *, width: int = 320, height: int = 240, offset: float = 0.0, scale: float = 1.0
) -> OfflineFrame:
    """Counterexamples and positive controls; drawing geometry is not inference logic."""
    base = synthetic_frame("blank", width=width, height=height)
    image, depth = base.image.copy(), base.depth_m.copy()
    x = int(width * (0.5 + offset))
    thickness = max(2, int(width * 0.025 * scale))
    if kind in {"partial_ring", "curved_shadow"}:
        image[:] = 180 if kind == "curved_shadow" else 65
        color = (15, 15, 15) if kind == "curved_shadow" else (245, 245, 245)
        center = (int(width * (0.08 + offset)), int(height * 0.72))
        radius = int(min(width, height) * 0.48 * scale)
        cv2.ellipse(image, center, (radius, radius), 0, -90, 90, color, thickness)
    elif kind == "wall_edge":
        # A thin wall slab can occupy less than the old maximum line-area gate.
        image[:, : max(2, int(width * 0.10 * scale))] = 245
    elif kind == "wall_highlight":
        cv2.line(image, (x, 0), (x, height - 1), (245, 245, 245), thickness)
    elif kind == "short_fragment":
        cv2.line(image, (x, int(height * 0.70)), (x, height - 1), (245, 245, 245), thickness)
    elif kind == "slanted_line":
        cv2.line(
            image,
            (x, height - 1),
            (int(width * (0.35 + offset)), int(height * 0.35)),
            (245, 245, 245),
            thickness,
        )
    elif kind == "rgb_blocker_depth_far":
        image = synthetic_frame("opening", width=width, height=height).image.copy()
        cv2.rectangle(
            image,
            (int(width * 0.35), int(height * 0.32)),
            (int(width * 0.65), int(height * 0.68)),
            (5, 5, 5),
            cv2.FILLED,
        )
    elif kind == "rgb_opening_depth_wall":
        image = synthetic_frame("opening", width=width, height=height).image.copy()
        depth[:] = 0.8
    elif kind == "outside_roi_obstacle":
        depth[: max(1, int(height * 0.08))] = 0.5
    elif kind == "beyond_probe_obstacle":
        depth[int(height * 0.3) : int(height * 0.7), int(width * 0.3) : int(width * 0.7)] = 2.5
    else:
        raise ValueError(f"unknown adversarial fixture: {kind}")
    return replace(base, image=image, depth_m=depth, source_id=f"synthetic:adversarial:{kind}")


def adversarial_suite() -> list[OfflineFrame]:
    kinds = (
        "partial_ring",
        "curved_shadow",
        "wall_edge",
        "wall_highlight",
        "short_fragment",
        "slanted_line",
        "rgb_blocker_depth_far",
        "rgb_opening_depth_wall",
        "outside_roi_obstacle",
        "beyond_probe_obstacle",
    )
    return [replace(adversarial_frame(kind), frame_index=index) for index, kind in enumerate(kinds)]
