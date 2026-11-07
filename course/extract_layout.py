"""Extract feature priors and a floor projection from a metre, Z-up course OBJ.

The supported dialect is the published Onshape export: a complete ``g`` label
(including spaces) names one piece, followed by its ``v`` declarations. ``o``
records subdivide surfaces, not features. No coordinates or routes are embedded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class _Group:
    vertices: list[int] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)


class OutOfMapError(ValueError):
    """The requested XY position is outside the grid's half-open extent."""


def _parse_obj(raw: bytes) -> tuple[np.ndarray, dict[str, _Group]]:
    vertices: list[list[float]] = []
    groups: dict[str, _Group] = {}
    current: _Group | None = None
    for line_number, original in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if original.lstrip().startswith("#"):
            units = re.search(r"\bunits\s*[:=]\s*(\w+)", original, re.IGNORECASE)
            if units and units[1].lower() not in {"m", "meter", "meters", "metre", "metres"}:
                raise ValueError(f"line {line_number}: expected metres, found {units[1]!r}")
            if re.search(r"\b[xy][ -]up\b", original, re.IGNORECASE):
                raise ValueError(f"line {line_number}: expected Z-up coordinates")
        fields = original.split("#", 1)[0].split()
        if not fields:
            continue
        tag, *values = fields
        try:
            if tag == "g":
                if not values:
                    raise ValueError("an empty group name is unsupported")
                current = groups.setdefault(" ".join(values), _Group())
            elif tag == "v":
                if current is None:
                    raise ValueError("vertices must follow a named g record")
                if len(values) not in {3, 4}:
                    raise ValueError("expected three XYZ coordinates (optional w=1)")
                point = [float(value) for value in values]
                if not all(math.isfinite(value) for value in point):
                    raise ValueError("vertex coordinates must be finite")
                if len(point) == 4 and point[3] != 1:
                    raise ValueError("homogeneous vertices with w != 1 are unsupported")
                current.vertices.append(len(vertices))
                vertices.append(point[:3])
            elif tag == "f":
                if current is None:
                    raise ValueError("faces must follow a named g record")
                if len(values) != 3:
                    raise ValueError("only triangular faces are supported; triangulate the OBJ")
                triangle = []
                for value in values:
                    index = int(value.split("/", 1)[0])
                    if index == 0:
                        raise ValueError("OBJ indices are one-based, not zero")
                    index = index - 1 if index > 0 else len(vertices) + index
                    if not 0 <= index < len(vertices):
                        raise ValueError("face references an undeclared vertex")
                    triangle.append(index)
                current.triangles.append(tuple(triangle))
        except ValueError as error:
            raise ValueError(f"line {line_number}: {error}") from error
    if not vertices:
        raise ValueError("OBJ has no grouped vertices")
    for name, group in groups.items():
        if not group.vertices:
            raise ValueError(f"group {name!r} has no local v declarations")
        local = set(group.vertices)
        if any(index not in local for face in group.triangles for index in face):
            raise ValueError(f"group {name!r} references vertices declared in another group")
    return np.asarray(vertices, dtype=float), groups


def _classify(name: str, low: np.ndarray, high: np.ndarray, surface_tolerance: float) -> dict:
    """Names supply labels; geometry must support exclusions from occupancy."""
    label = name.casefold()
    extent = high - low
    flags = []
    kind = "UNKNOWN"
    occupied = True
    reason = "Unrecognised geometry is conservatively included."
    on_floor = low[2] >= -surface_tolerance and high[2] <= surface_tolerance
    if label.startswith("floor") and high[2] <= 0 and extent[0] > 0 and extent[1] > 0:
        kind, occupied = "floor", False
        reason = "Named floor lies at or below source Z=0."
    elif label.startswith("net roof") and low[2] > 0 and extent[2] < min(extent[:2]):
        kind, occupied = "overhead_net", False
        reason = "Horizontal roof net is retained as a feature; ceiling clearance is not 2-D."
    elif label.startswith(("landing pad", "launch mark", "guideline", "approach ring")):
        if on_floor:
            kind, occupied = "floor_marking", False
            reason = "Named floor marking/pad is within the configured surface tolerance of Z=0."
        else:
            flags.append(
                "UNKNOWN: marking/pad label conflicts with height; included as an obstacle."
            )
    elif label.startswith("net side"):
        kind = "boundary_net"
    elif "wall" in label or "maze divider" in label or label.startswith("barrier"):
        kind = "wall"
    elif label.startswith("boulder"):
        kind = "boulder"
    elif label.startswith("tube cradle"):
        kind = "tunnel_support"
    elif label.startswith(("tube oval", "tunnel")):
        kind = "tunnel"
    if occupied and kind != "UNKNOWN":
        reason = "Static geometry projected over all heights."
    if kind == "UNKNOWN" and not flags:
        flags.append("UNKNOWN: semantic identity; original group name and geometry are preserved.")
    if "window" in label:
        flags.append("UNKNOWN: aperture bounds; this group's bounds describe the entire wall.")
    if "approach ring" in label:
        flags.append(
            "UNKNOWN: stage label meaning; this floor ring is not checkpoint 4 (Gate B/window)."
        )
    if "cut to" in label:
        flags.append(
            "UNKNOWN: axis intended by the cut label; use measured XYZ bounds, not the name."
        )
    if label.startswith("tube oval"):
        flags.append("UNKNOWN: dimension order in the name; use measured XYZ bounds.")
    return {"kind": kind, "include_in_occupancy": occupied, "reason": reason, "flags": flags}


def _project_triangle(grid: np.ndarray, triangle: np.ndarray, origin: np.ndarray, cell: float):
    """Mark every closed grid square intersecting a projected triangle, including edges.

    Triangle/square separation uses XY bounds and normals to triangle edges.
    Degenerate projections (vertical faces becoming lines) are supported.
    """
    xy = triangle[:, :2]
    first = np.floor(np.nextafter((xy.min(axis=0) - origin) / cell, -np.inf)).astype(int)
    last = np.floor((xy.max(axis=0) - origin) / cell).astype(int)
    first = np.maximum(first, 0)
    last = np.minimum(last, np.asarray(grid.shape[::-1]) - 1)
    if np.any(last < first):
        return
    x0, y0 = first
    x1, y1 = last + 1
    view = grid[y0:y1, x0:x1]
    if view.all():
        return
    rows, columns = np.nonzero(~view)
    centres = origin + (np.column_stack((columns + x0, rows + y0)) + 0.5) * cell
    intersects = np.ones(len(rows), dtype=bool)
    for edge in np.roll(xy, -1, axis=0) - xy:
        normal = np.asarray([-edge[1], edge[0]])
        length = np.linalg.norm(normal)
        if length == 0:
            continue
        normal /= length
        projected = xy @ normal
        centre_projection = centres @ normal
        radius = 0.5 * cell * np.abs(normal).sum()
        tolerance = 64 * np.finfo(float).eps * max(1, np.abs(projected).max())
        intersects &= (centre_projection + radius >= projected.min() - tolerance) & (
            centre_projection - radius <= projected.max() + tolerance
        )
    view[rows[intersects], columns[intersects]] = True


def _semantic_priors(features: dict) -> dict:
    """References only: no flight order, route, or inferred gate planes."""
    windows = [name for name in features if "window" in name.casefold()]
    return {
        "gate_a": {
            "status": "UNKNOWN",
            "bounds": None,
            "centroid": None,
            "reason": "A gate plane/aperture is not identified by the supported group schema.",
        },
        "gate_b": {
            "status": "UNKNOWN",
            "bounds": None,
            "centroid": None,
            "window_wall_groups": windows,
            "reason": "Checkpoint description says Gate B/window; no separate gate aperture is resolved.",
        },
        "window_aperture": {
            "status": "UNKNOWN",
            "bounds": None,
            "centroid": None,
            "wall_groups": windows,
            "reason": "A whole-wall AABB is not an opening; no aperture is inferred from its name.",
        },
    }


def extract_layout(
    obj_path: str | Path, resolution: float = 0.05, surface_tolerance: float = 0.01
) -> dict:
    """Read the current model and return JSON-compatible priors, without writing files.

    Coordinates are used as metres, XYZ/Z-up, with no scaling or recentering.
    ``centroid`` explicitly means the AABB midpoint, not a volume/mass centroid.
    The surface tolerance affects only named floor markings/pads, never walls.
    """
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("resolution must be finite and positive")
    if not math.isfinite(surface_tolerance) or surface_tolerance < 0:
        raise ValueError("surface_tolerance must be finite and nonnegative")
    path = Path(obj_path)
    raw = path.read_bytes()
    vertices, groups = _parse_obj(raw)
    features = {}
    for name, group in groups.items():
        points = vertices[group.vertices]
        low, high = points.min(axis=0), points.max(axis=0)
        semantics = _classify(name, low, high, surface_tolerance)
        method = "excluded"
        if semantics["include_in_occupancy"]:
            method = "triangle_projection" if group.triangles else "aabb_fallback"
            if not group.triangles:
                semantics["flags"].append(
                    "UNKNOWN: no faces; occupancy uses the conservative XY AABB."
                )
        features[name] = {
            "bounds": {"min": low.tolist(), "max": high.tolist()},
            "centroid": ((low + high) / 2).tolist(),
            "vertex_count": len(group.vertices),
            "triangle_count": len(group.triangles),
            "projection_method": method,
            **semantics,
        }

    model_low, model_high = vertices.min(axis=0), vertices.max(axis=0)
    origin = np.floor(model_low[:2] / resolution) * resolution
    dimensions = np.maximum(1, np.ceil((model_high[:2] - origin) / resolution))
    if not np.isfinite(dimensions).all() or dimensions.prod() > 4_000_000:
        raise ValueError("requested grid exceeds 4,000,000 cells; use a coarser resolution")
    columns, rows = dimensions.astype(int)
    cells = np.zeros((rows, columns), dtype=bool)
    for name, group in groups.items():
        feature = features[name]
        if not feature["include_in_occupancy"]:
            continue
        if group.triangles:
            for face in group.triangles:
                _project_triangle(cells, vertices[list(face)], origin, resolution)
        else:
            low, high = feature["bounds"]["min"], feature["bounds"]["max"]
            rectangle = np.asarray(
                [
                    [low[0], low[1], 0],
                    [high[0], low[1], 0],
                    [high[0], high[1], 0],
                    [low[0], high[1], 0],
                ]
            )
            for indices in ([0, 1, 2], [0, 2, 3]):
                _project_triangle(cells, rectangle[indices], origin, resolution)

    return {
        "header": {
            "schema_version": 1,
            "source_file": path.name,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "units": "metres",
            "axes": {"coordinate_order": "XYZ", "up": "+Z", "grid_plane": "XY"},
            "coordinate_origin": "Unchanged source origin; published course origin is floor centre.",
            "frame_contract": "OBJ is unitless unless declared; metre/Z-up input is required.",
            "centroid_definition": "Axis-aligned bounds midpoint; not a flight target.",
            "provenance": "Published course model only; no run or recording data.",
            "notice": "map from the published layout (rule 6.4); feature priors, not a hard-coded route; coordinates are preliminary and may change.",
        },
        "model_bounds": {"min": model_low.tolist(), "max": model_high.tolist()},
        "feature_count": len(features),
        "features": features,
        "semantic_priors": _semantic_priors(features),
        "occupancy": {
            "origin_xy": origin.tolist(),
            "resolution_m": resolution,
            "shape_yx": [int(rows), int(columns)],
            "extent_max_xy": (origin + np.asarray([columns, rows]) * resolution).tolist(),
            "indexing": "cells[row_y][column_x]; rows increase with +Y, columns with +X",
            "values": {
                "0": "No included geometry projected here; clearance is not guaranteed.",
                "1": "Occupied",
            },
            "projection": "All heights of included mesh triangles; any cell intersection is occupied.",
            "surface_tolerance_m": surface_tolerance,
            "out_of_map": "OutOfMapError; extent is half-open, including minimum and excluding maximum.",
            "occupied_cell_count": int(cells.sum()),
            "cells": cells.astype(int).tolist(),
        },
    }


def world_to_cell(layout: dict, x: float, y: float) -> tuple[int, int]:
    """Return (row, column); outside positions are never clamped or wrapped."""
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("query coordinates must be finite")
    grid = layout["occupancy"]
    origin_x, origin_y = grid["origin_xy"]
    max_x, max_y = grid["extent_max_xy"]
    if not (origin_x <= x < max_x and origin_y <= y < max_y):
        raise OutOfMapError(f"XY ({x}, {y}) is outside the map")
    column = math.floor((x - origin_x) / grid["resolution_m"])
    row = math.floor((y - origin_y) / grid["resolution_m"])
    rows, columns = grid["shape_yx"]
    # The extent check has already established that the point is inside.
    # Subtraction/division can round its final ULP onto the exclusive edge.
    if column == columns:
        column = columns - 1
    if row == rows:
        row = rows - 1
    if not (0 <= row < rows and 0 <= column < columns):
        raise OutOfMapError(f"XY ({x}, {y}) rounds outside the grid")
    return row, column


def query_occupancy(layout: dict, x: float, y: float) -> int:
    """Return 0/1 occupancy; positions outside the map raise OutOfMapError."""
    row, column = world_to_cell(layout, x, y)
    return layout["occupancy"]["cells"][row][column]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obj", type=Path, help="Published metre/Z-up OBJ with group-local vertices")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--cell-size", type=float, default=0.05, help="Grid resolution in metres")
    parser.add_argument(
        "--surface-tolerance", type=float, default=0.01, help="Floor marking tolerance in metres"
    )
    args = parser.parse_args()
    try:
        layout = extract_layout(args.obj, args.cell_size, args.surface_tolerance)
        args.out.write_text(json.dumps(layout, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    grid = layout["occupancy"]
    print(f"Wrote {args.out}: {layout['feature_count']} features")
    print(
        f"Grid: {grid['shape_yx'][0]} rows x {grid['shape_yx'][1]} columns; {grid['resolution_m']:g} m/cell; origin XY {grid['origin_xy']}"
    )
    print(f"Occupied cells: {grid['occupied_cell_count']}")
    print(f"Source SHA-256: {layout['header']['source_sha256']}")
    for name, feature in layout["features"].items():
        for flag in feature["flags"]:
            print(f"{name}: {flag}")
    print("UNKNOWN semantic priors: " + ", ".join(layout["semantic_priors"]))


if __name__ == "__main__":
    main()
