"""Small analytic meshes for offline tests; no course-model constants."""

from pathlib import Path

import numpy as np


def extruded_ring(outer, inner, length=0.2, offset=(0, 0, 0)):
    """Extrude matching U/Z polygons along +Y; include annular end caps."""
    outer, inner = np.asarray(outer), np.asarray(inner)
    count = len(outer)
    points = []
    for y in (0, length):
        for loop in (outer, inner):
            points.extend([u, y, z] for u, z in loop)
    points = np.asarray(points) + offset
    faces = []
    for i in range(count):
        j = (i + 1) % count
        for plane in (0, 2 * count):
            faces.extend(
                [
                    [plane + i, plane + j, plane + count + j],
                    [plane + i, plane + count + j, plane + count + i],
                ]
            )
        for ring in (0, count):
            a, b = ring + i, ring + j
            faces.extend([[a, b, b + 2 * count], [a, b + 2 * count, a + 2 * count]])
    return points[np.asarray(faces)]


def rectangle(x0, z0, x1, z1):
    return np.array([[x0, z0], [x1, z0], [x1, z1], [x0, z1]], dtype=float)


def window_mesh():
    return extruded_ring(rectangle(-1, 0, 1, 2), rectangle(-0.4, 0.3, 0.4, 1.3), length=0.1)


def tube_mesh():
    angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    outer = np.column_stack((0.6 * np.cos(angles), 1 + 0.8 * np.sin(angles)))
    inner = np.column_stack((0.5 * np.cos(angles), 1 + 0.7 * np.sin(angles)))
    return extruded_ring(outer, inner, length=0.8, offset=(1, 2, 0))


def slab(polygon, z0=0, z1=0.001):
    """Extrude a polygon visible from vertex 0 (rectangles and our L-shaped strip)."""
    polygon = np.asarray(polygon)
    n = len(polygon)
    points = np.r_[
        np.column_stack((polygon, np.full(n, z0))), np.column_stack((polygon, np.full(n, z1)))
    ]
    faces = []
    for i in range(1, n - 1):
        faces.extend([[0, i, i + 1], [n, n + i, n + i + 1]])
    for i in range(n):
        j = (i + 1) % n
        faces.extend([[i, j, j + n], [i, j + n, i + n]])
    return points[np.asarray(faces)]


def circle_mark(radius, centre=(0, 0), inner=None):
    angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    outer = radius * np.column_stack((np.cos(angles), np.sin(angles))) + centre
    if inner is None:
        return slab(outer)
    inside = inner * np.column_stack((np.cos(angles), np.sin(angles))) + centre
    # Convert the test tube helper's U/Z profile into a horizontal XY marking.
    triangles = extruded_ring(outer, inside, length=0.001)
    return triangles[:, :, [0, 2, 1]]


def write_mesh(path, groups):
    lines = ["# Units = metres; Z-up"]
    offset = 0
    for name, triangles in groups.items():
        points, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
        lines.append("g " + name)
        lines.extend("v " + " ".join(f"{x:.12g}" for x in point) for point in points)
        lines.extend(
            "f " + " ".join(str(int(index) + offset + 1) for index in face)
            for face in inverse.reshape(-1, 3)
        )
        offset += len(points)
    Path(path).write_text("\n".join(lines) + "\n")
    return path
