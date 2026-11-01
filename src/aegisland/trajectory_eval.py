"""
Offline trajectory evaluation for GPS-denied localization benchmarks.

Metrics are only metric (meters) when BOTH the estimate and the ground truth
are metric. Sim(3) alignment hides scale error, so its ATE is labelled as
scale-corrected and must not be reported as metric localization accuracy.

This module is evaluation-only. Nothing here feeds the safety decision path.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MINIMUM_ALIGNMENT_PAIRS = 3
METRIC_UNIT = "m"
SCALE_CORRECTED_UNIT = "m (after scale correction; not a metric-scale result)"


@dataclass(frozen=True)
class Trajectory:
    timestamps_s: np.ndarray
    positions_m: np.ndarray
    quaternions_xyzw: np.ndarray

    def __post_init__(self) -> None:
        count = len(self.timestamps_s)
        if self.positions_m.shape != (count, 3):
            raise ValueError("positions_m must have shape (N, 3)")
        if self.quaternions_xyzw.shape != (count, 4):
            raise ValueError("quaternions_xyzw must have shape (N, 4)")
        for name in ("timestamps_s", "positions_m", "quaternions_xyzw"):
            if not np.all(np.isfinite(getattr(self, name))):
                raise ValueError(f"{name} must be finite")


def _normalized(quaternions: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError("zero-norm quaternion")
    return quaternions / norms


def quaternion_to_matrix(quaternion_xyzw: np.ndarray) -> np.ndarray:
    x, y, z, w = quaternion_xyzw / np.linalg.norm(quaternion_xyzw)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def load_tum(path: Path | str) -> Trajectory:
    """TUM format: `timestamp_s tx ty tz qx qy qz qw` per line, '#' comments."""
    rows = [
        [float(value) for value in line.split()]
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rows or any(len(row) != 8 for row in rows):
        raise ValueError(f"{path}: expected 8 columns per TUM row")
    data = np.array(rows, dtype=np.float64)
    return Trajectory(data[:, 0], data[:, 1:4], _normalized(data[:, 4:8]))


def write_tum(path: Path | str, trajectory: Trajectory) -> None:
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write("# timestamp_s tx_m ty_m tz_m qx qy qz qw\n")
        stream.writelines(
            f"{t:.9f} {p[0]:.9f} {p[1]:.9f} {p[2]:.9f} "
            f"{q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f}\n"
            for t, p, q in zip(
                trajectory.timestamps_s, trajectory.positions_m, trajectory.quaternions_xyzw
            )
        )


def load_euroc_groundtruth(path: Path | str) -> Trajectory:
    """EuRoC `state_groundtruth_estimate0/data.csv`: ns timestamp, p xyz [m], q wxyz."""
    timestamps, positions, quaternions = [], [], []
    with Path(path).open(encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 8:
                raise ValueError(f"{path}: expected at least 8 columns, got {len(row)}")
            # Integer nanoseconds -> seconds without float precision loss on the integer part.
            nanoseconds = int(row[0])
            timestamps.append(nanoseconds // 1_000_000_000 + (nanoseconds % 1_000_000_000) * 1e-9)
            positions.append([float(value) for value in row[1:4]])
            w, x, y, z = (float(value) for value in row[4:8])
            quaternions.append([x, y, z, w])
    if not timestamps:
        raise ValueError(f"{path}: no ground-truth rows")
    return Trajectory(
        np.array(timestamps), np.array(positions), _normalized(np.array(quaternions))
    )


def associate(
    query_timestamps_s: np.ndarray,
    reference_timestamps_s: np.ndarray,
    *,
    max_time_difference_s: float,
) -> list[tuple[int, int]]:
    """Nearest-timestamp pairs (query_index, reference_index) within tolerance."""
    for name, values in (("query", query_timestamps_s), ("reference", reference_timestamps_s)):
        if np.any(np.diff(values) < 0):
            raise ValueError(f"{name} timestamps must be sorted")
    if len(reference_timestamps_s) == 0:
        return []
    insertion = np.searchsorted(reference_timestamps_s, query_timestamps_s)
    pairs = []
    for query_index, position in enumerate(insertion):
        candidates = [c for c in (position - 1, position) if 0 <= c < len(reference_timestamps_s)]
        best = min(
            candidates,
            key=lambda c: abs(reference_timestamps_s[c] - query_timestamps_s[query_index]),
        )
        if abs(reference_timestamps_s[best] - query_timestamps_s[query_index]) <= (
            max_time_difference_s
        ):
            pairs.append((query_index, int(best)))
    return pairs


def umeyama_alignment(
    source: np.ndarray, target: np.ndarray, *, with_scale: bool
) -> tuple[np.ndarray, np.ndarray, float]:
    """Least-squares R, t, s minimizing ||target - (s R source + t)|| (Umeyama 1991)."""
    if source.shape != target.shape or source.shape[0] < MINIMUM_ALIGNMENT_PAIRS:
        raise ValueError("alignment needs matching (N>=3, 3) point sets")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = target_centered.T @ source_centered / len(source)
    u, singular_values, vt = np.linalg.svd(covariance)
    correction = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        correction[2, 2] = -1.0
    rotation = u @ correction @ vt
    scale = 1.0
    if with_scale:
        source_variance = float(np.mean(np.sum(source_centered**2, axis=1)))
        if source_variance < 1e-12:
            raise ValueError("degenerate source trajectory; cannot estimate scale")
        scale = float(np.trace(np.diag(singular_values) @ correction) / source_variance)
    translation = target_mean - scale * rotation @ source_mean
    return rotation, translation, scale


def _matched(
    estimate: Trajectory, ground_truth: Trajectory, max_time_difference_s: float
) -> list[tuple[int, int]]:
    pairs = associate(
        estimate.timestamps_s,
        ground_truth.timestamps_s,
        max_time_difference_s=max_time_difference_s,
    )
    if len(pairs) < MINIMUM_ALIGNMENT_PAIRS:
        raise ValueError(
            f"only {len(pairs)} timestamp pairs within {max_time_difference_s}s; "
            f"need {MINIMUM_ALIGNMENT_PAIRS}"
        )
    return pairs


def absolute_trajectory_error(
    estimate: Trajectory,
    ground_truth: Trajectory,
    *,
    max_time_difference_s: float,
    with_scale: bool = False,
) -> dict[str, float | int | str]:
    """Position ATE after SE(3) (default) or Sim(3) alignment of estimate onto ground truth."""
    pairs = _matched(estimate, ground_truth, max_time_difference_s)
    source = estimate.positions_m[[e for e, _ in pairs]]
    target = ground_truth.positions_m[[g for _, g in pairs]]
    rotation, translation, scale = umeyama_alignment(source, target, with_scale=with_scale)
    errors = np.linalg.norm(target - (scale * source @ rotation.T + translation), axis=1)
    return {
        "metric": "ate_position",
        "alignment": "sim3" if with_scale else "se3",
        "unit": SCALE_CORRECTED_UNIT if with_scale else METRIC_UNIT,
        "pairs": len(pairs),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "mean": float(np.mean(errors)),
        "median": float(np.median(errors)),
        "max": float(np.max(errors)),
        "scale": scale,
    }


def _pose_matrix(trajectory: Trajectory, index: int) -> np.ndarray:
    pose = np.eye(4)
    pose[:3, :3] = quaternion_to_matrix(trajectory.quaternions_xyzw[index])
    pose[:3, 3] = trajectory.positions_m[index]
    return pose


def relative_pose_error(
    estimate: Trajectory,
    ground_truth: Trajectory,
    *,
    delta_frames: int,
    max_time_difference_s: float,
) -> dict[str, float | int | str]:
    """RPE over a fixed number of matched estimate frames; independent of world alignment."""
    if delta_frames < 1:
        raise ValueError("delta_frames must be >= 1")
    pairs = _matched(estimate, ground_truth, max_time_difference_s)
    translation_errors, rotation_errors = [], []
    for (e0, g0), (e1, g1) in zip(pairs, pairs[delta_frames:]):
        estimate_delta = np.linalg.inv(_pose_matrix(estimate, e0)) @ _pose_matrix(estimate, e1)
        truth_delta = np.linalg.inv(_pose_matrix(ground_truth, g0)) @ _pose_matrix(
            ground_truth, g1
        )
        error = np.linalg.inv(truth_delta) @ estimate_delta
        translation_errors.append(float(np.linalg.norm(error[:3, 3])))
        cosine = (np.trace(error[:3, :3]) - 1.0) / 2.0
        rotation_errors.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    if not translation_errors:
        raise ValueError("not enough matched frames for the requested delta")
    translation = np.array(translation_errors)
    rotation = np.array(rotation_errors)
    return {
        "metric": "rpe",
        "delta_frames": delta_frames,
        "pairs": len(translation),
        "translation_unit": METRIC_UNIT,
        "rotation_unit": "deg",
        "translation_rmse_m": float(np.sqrt(np.mean(translation**2))),
        "translation_median_m": float(np.median(translation)),
        "rotation_rmse_deg": float(np.sqrt(np.mean(rotation**2))),
        "rotation_median_deg": float(np.median(rotation)),
    }
