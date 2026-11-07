"""Pure rotation helpers: PX4 Hamilton wxyz FRD->NED, ROS body FLU, optical RDF.

No yaw is retained in the gravity-level body frame. No ROS imports.
"""

from __future__ import annotations

import numpy as np


def rotation_matrix(value) -> np.ndarray:
    """Validate a finite, proper 3x3 rotation (reflections are not rotations)."""
    try:
        if np.iscomplexobj(value):
            raise ValueError("rotation must be real")
        rotation = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError("rotation must be a real numeric 3x3 matrix") from e
    if (
        rotation.shape != (3, 3)
        or not np.isfinite(rotation).all()
        or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0)
        or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6, rtol=0)
    ):
        raise ValueError("rotation must be finite, 3x3, orthonormal and have determinant +1")
    return rotation


def quaternion_rotation(q) -> np.ndarray:
    """Hamilton (w, x, y, z) quaternion to a rotation; normalise rounding error."""
    q = np.asarray(q, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all():
        raise ValueError("quaternion must have four finite wxyz entries")
    norm = np.linalg.norm(q)
    if not np.isfinite(norm) or norm < 1e-12:
        raise ValueError("quaternion must have a finite, nonzero norm")
    w, x, y, z = q / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def level_from_px4(q) -> np.ndarray:
    """Body FLU -> gravity-level FLU using only PX4 attitude roll/pitch.

    Strip NED yaw, then change both FRD axes to FLU. The base_link frame must
    be body FLU at the PX4 body reference; mounting rotation belongs in TF.
    """
    ned_from_frd = quaternion_rotation(q)
    horizontal = np.hypot(ned_from_frd[0, 0], ned_from_frd[1, 0])
    if horizontal < 1e-6:
        raise ValueError("level heading is undefined with vertical body forward axis")
    c, s = ned_from_frd[:2, 0] / horizontal
    remove_yaw = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
    frd_from_flu = np.diag([1.0, -1.0, -1.0])
    return frd_from_flu @ remove_yaw @ ned_from_frd @ frd_from_flu


def is_recent(sample_ns: int | None, now_ns: int, frame_ns: int, max_age_ms: float) -> bool:
    """Check local-clock age and image alignment; reject backward clock jumps."""
    if sample_ns is None:
        return False
    limit_ns = max_age_ms * 1e6
    return 0 <= now_ns - sample_ns <= limit_ns and abs(frame_ns - sample_ns) <= limit_ns
