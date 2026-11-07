"""Small, offline triangle-geometry utilities shared by course prior generators."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

if __package__:
    from .extract_layout import _parse_obj
else:
    from extract_layout import _parse_obj

NOTICE = (
    "Map-derived prior from the published layout (rule 6.4), not fixed flight waypoints or timings. "
    "Runtime must localise and react to live perception (generality, rule 9.5). "
    "Coordinates are preliminary and may change."
)


def load_mesh(path):
    path = Path(path)
    raw = path.read_bytes()
    vertices, groups = _parse_obj(raw)
    meshes = {}
    for name, group in groups.items():
        if not group.triangles:
            raise ValueError(f"{name!r}: real triangle faces are required")
        meshes[name] = vertices[np.asarray(group.triangles)]
    return meshes, {
        "schema_version": 1,
        "source_file": path.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "units": "metres",
        "axes": {"coordinate_order": "XYZ", "up": "+Z", "grid_plane": "XY"},
        "provenance": "Published OBJ triangle geometry only; no run or recording data.",
        "notice": NOTICE,
    }


def write_json(path, value):
    # Compact arrays keep sampled grids small; no timestamps or absolute input paths.
    Path(path).write_text(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")


def unknown(reason, **extra):
    return {"status": "UNKNOWN", "reason": str(reason), **extra}


def unique_points(triangles):
    return np.unique(np.asarray(triangles).reshape(-1, 3), axis=0)


def canonical(vector):
    vector = np.asarray(vector, dtype=float)
    vector = vector / np.linalg.norm(vector)
    nonzero = np.flatnonzero(np.abs(vector) > 1e-8)
    return vector if vector[nonzero[0]] > 0 else -vector


def _edge_graph(segments, tolerance=1e-5, boundary_only=False):
    points = defaultdict(list)
    counts = Counter()
    for first, second in segments:
        a = tuple(np.rint(first / tolerance).astype(np.int64))
        b = tuple(np.rint(second / tolerance).astype(np.int64))
        points[a].append(first)
        points[b].append(second)
        if a != b:
            counts[tuple(sorted((a, b)))] += 1
    if boundary_only and any(count > 2 for count in counts.values()):
        raise ValueError("non-manifold planar surface")
    edges = {edge for edge, count in counts.items() if not boundary_only or count == 1}
    positions = {key: np.mean(values, axis=0) for key, values in points.items()}
    neighbours = defaultdict(set)
    for a, b in edges:
        neighbours[a].add(b)
        neighbours[b].add(a)
    if any(len(adjacent) != 2 for adjacent in neighbours.values()):
        raise ValueError("boundary is open or branched; closed contours are not determined")
    loops = []
    remaining = set(neighbours)
    while remaining:
        start = min(remaining)
        order, previous, current = [], None, start
        while True:
            order.append(current)
            candidates = neighbours[current] - {previous}
            following = min(candidates)
            previous, current = current, following
            if current == start:
                break
            if current in order:
                raise ValueError("self-connected boundary")
        remaining.difference_update(order)
        loops.append(np.asarray([positions[key] for key in order]))
    return loops


def plane_loops(triangles, normal, offset, tolerance=1e-5):
    triangles = np.asarray(triangles)
    selected = triangles[np.all(np.abs(triangles @ normal - offset) <= tolerance, axis=1)]
    if not len(selected):
        raise ValueError("no triangulated planar cap at the requested plane")
    edges = selected[:, [[0, 1], [1, 2], [2, 0]], :].reshape(-1, 2, 3)
    loops = _edge_graph(edges, tolerance, boundary_only=True)
    if not loops:
        raise ValueError("planar boundary loops not found")
    return loops


def horizontal_loops(triangles, top=True):
    z = np.asarray(triangles)[:, :, 2]
    return plane_loops(triangles, np.array([0, 0, 1]), z.max() if top else z.min())


def simplify_loop(points, tolerance=1e-5):
    points = np.asarray(points)
    changed = True
    while changed and len(points) > 3:
        changed = False
        keep = []
        for index, point in enumerate(points):
            a, b = point - points[index - 1], points[(index + 1) % len(points)] - point
            denominator = max(np.linalg.norm(a) * np.linalg.norm(b), 1e-20)
            cosine = float(a @ b / denominator)
            if cosine > 1 - tolerance:
                changed = True
            else:
                keep.append(index)
        points = points[keep]
    return points


def polygon_area(points):
    p = np.asarray(points)
    q = np.roll(p, -1, axis=0)
    return float(np.sum(p[:, 0] * q[:, 1] - q[:, 0] * p[:, 1]) / 2)


def polygon_centroid(points):
    p = np.asarray(points)
    q = np.roll(p, -1, axis=0)
    cross = p[:, 0] * q[:, 1] - q[:, 0] * p[:, 1]
    return np.sum((p + q) * cross[:, None], axis=0) / (3 * cross.sum())


def inside_polygon(points, polygon):
    points, polygon = np.asarray(points), np.asarray(polygon)
    inside = np.zeros(points.shape[:-1], dtype=bool)
    x, y = points[..., 0], points[..., 1]
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        if abs(b[1] - a[1]) < 1e-15:
            continue
        crossing = (a[1] > y) != (b[1] > y)
        inside ^= crossing & (x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0])
    return inside


def fit_circle(points):
    points = np.asarray(points)[:, :2]
    reference = points.mean(axis=0)
    p = points - reference
    solution, _, rank, _ = np.linalg.lstsq(
        np.column_stack((2 * p, np.ones(len(p)))), np.sum(p * p, axis=1), rcond=None
    )
    if rank < 3:
        raise ValueError("circle is underdetermined")
    centre = solution[:2] + reference
    radius = float(np.sqrt(solution[2] + solution[:2] @ solution[:2]))
    errors = np.linalg.norm(points - centre, axis=1) - radius
    midpoints = (points + np.roll(points, -1, axis=0)) / 2
    chord_errors = np.linalg.norm(midpoints - centre, axis=1) - radius
    if np.max(np.abs(errors)) > max(1e-4, radius * 0.001):
        raise ValueError("boundary does not support a circle fit")
    if len(points) < 8 or np.max(np.abs(chord_errors)) > max(1e-4, radius * 0.01):
        raise ValueError("boundary is too coarse or polygonal to establish a circular marking")
    return {
        "centre_xy": centre.tolist(),
        "radius_m": radius,
        "vertex_rms_m": float(np.sqrt(np.mean(errors**2))),
        "vertex_max_error_m": float(np.max(np.abs(errors))),
        "chord_midpoint_max_error_m": float(np.max(np.abs(chord_errors))),
        "sample_count": len(points),
    }


def rectangle_frame(points):
    p = simplify_loop(np.asarray(points)[:, :2])
    if len(p) != 4:
        raise ValueError("wall footprint is not a four-corner rectangle")
    edges = np.roll(p, -1, axis=0) - p
    u = canonical(edges[np.argmax(np.linalg.norm(edges, axis=1))])
    n = np.array([-u[1], u[0]])
    projected = p @ np.column_stack((u, n))
    lo, hi = projected.min(axis=0), projected.max(axis=0)
    reconstructed = np.minimum(np.abs(projected - lo), np.abs(projected - hi))
    if reconstructed.max() > 2e-5:
        raise ValueError("wall footprint is not rectangular within mesh tolerance")
    return u, n, lo, hi


def segment_closest(a, b):
    """Closest points on two XY edges; centre of overlap for parallel end faces."""
    a, b = np.asarray(a), np.asarray(b)
    intersection = segment_intersection(a, b)
    if intersection is not None:
        return intersection[0], intersection[0]
    u = a[1] - a[0]
    length = np.linalg.norm(u)
    if length > 0:
        u /= length
        v = b[1] - b[0]
        if abs(np.linalg.det(np.array([u, v]))) < 1e-8:
            alo, ahi = sorted(a @ u)
            blo, bhi = sorted(b @ u)
            low, high = max(alo, blo), min(ahi, bhi)
            if high >= low:
                value = (low + high) / 2
                return a[0] + u * (value - a[0] @ u), b[0] + u * (value - b[0] @ u)
    candidates = []
    for swap, first, second in [(False, a, b), (True, b, a)]:
        vector = second[1] - second[0]
        denominator = float(vector @ vector)
        for point in first:
            fraction = np.clip((point - second[0]) @ vector / max(denominator, 1e-20), 0, 1)
            other = second[0] + fraction * vector
            candidates.append(
                (np.linalg.norm(point - other), other if swap else point, point if swap else other)
            )
    _, first, second = min(candidates, key=lambda item: item[0])
    return first, second


def segment_intersection(a, b):
    a, b = np.asarray(a), np.asarray(b)
    matrix = np.column_stack((a[1] - a[0], -(b[1] - b[0])))
    if abs(np.linalg.det(matrix)) < 1e-12:
        return None
    t, u = np.linalg.solve(matrix, b[0] - a[0])
    if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= u <= 1 + 1e-8:
        return a[0] + t * (a[1] - a[0]), float(t)
    return None


def slice_segments(triangles, height, tolerance=1e-9):
    triangles = np.asarray(triangles)
    z = triangles[:, :, 2]
    selected = triangles[
        (z.min(axis=1) <= height + tolerance) & (z.max(axis=1) >= height - tolerance)
    ]
    segments, coplanar = [], []
    for triangle in selected:
        distances = triangle[:, 2] - height
        if np.all(np.abs(distances) <= tolerance):
            coplanar.append(triangle)
            continue
        points = []
        for i, j in [(0, 1), (1, 2), (2, 0)]:
            if abs(distances[i]) <= tolerance:
                points.append(triangle[i])
            if distances[i] * distances[j] < 0:
                points.append(
                    triangle[i]
                    + distances[i] / (distances[i] - distances[j]) * (triangle[j] - triangle[i])
                )
        if points:
            unique = np.unique(np.round(points, 10), axis=0)
            if len(unique) == 1:
                segments.append([unique[0], unique[0]])
            elif len(unique) == 2:
                segments.append(unique)
    return np.asarray(segments).reshape(-1, 2, 3), np.asarray(coplanar).reshape(-1, 3, 3)


def section_loops(segments):
    return _edge_graph(segments)
