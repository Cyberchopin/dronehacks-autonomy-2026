"""Measure mesh apertures and wall-end gaps; keep checkpoint-label ambiguity explicit."""

from __future__ import annotations

import argparse
from itertools import pairwise
from pathlib import Path

import numpy as np

if __package__:
    from .floor_markings import extract_markings
    from .mesh_geometry import (
        canonical,
        horizontal_loops,
        inside_polygon,
        load_mesh,
        plane_loops,
        polygon_area,
        polygon_centroid,
        rectangle_frame,
        segment_closest,
        segment_intersection,
        simplify_loop,
        unique_points,
        unknown,
        write_json,
    )
else:
    from floor_markings import extract_markings
    from mesh_geometry import (
        canonical,
        horizontal_loops,
        inside_polygon,
        load_mesh,
        plane_loops,
        polygon_area,
        polygon_centroid,
        rectangle_frame,
        segment_closest,
        segment_intersection,
        simplify_loop,
        unique_points,
        unknown,
        write_json,
    )


def _extruded_aperture(triangles, axis):
    axis = np.asarray(axis)
    points = unique_points(triangles)
    locations = points @ axis
    lo, hi = float(locations.min()), float(locations.max())
    if not np.all(np.minimum(np.abs(locations - lo), np.abs(locations - hi)) < 1e-5):
        raise ValueError("mesh is not an extrusion between two end planes")
    width_axis = canonical(np.cross(axis, [0, 0, 1]))
    profiles, centres, areas = [], [], []
    for location in (lo, hi):
        loops = plane_loops(triangles, axis, location)
        projected = [np.column_stack((loop @ width_axis, loop[:, 2])) for loop in loops]
        projected.sort(key=lambda loop: abs(polygon_area(loop)))
        if len(projected) != 2:
            raise ValueError("end plane must have one outer boundary and one enclosed hole")
        inner, outer = projected
        centre = polygon_centroid(inner)
        if not inside_polygon(np.array([centre]), outer)[0]:
            raise ValueError("aperture boundary is not inside its outer frame")
        profiles.append(inner)
        centres.append((width_axis * centre[0] + axis * location + [0, 0, centre[1]]).tolist())
        areas.append(abs(polygon_area(inner)))
    # Side surfaces must project onto profile edges, not internal baffles.
    projection = np.stack((triangles @ width_axis, triangles[:, :, 2]), axis=2)
    axis_values = triangles @ axis
    caps = np.all(np.abs(axis_values - lo) < 1e-5, axis=1) | np.all(
        np.abs(axis_values - hi) < 1e-5, axis=1
    )
    side = projection[~caps]
    a, b = side[:, 1] - side[:, 0], side[:, 2] - side[:, 0]
    area = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / 2
    if len(area) and area.max() > 1e-4:
        raise ValueError(
            "non-extruded internal geometry; clear aperture cannot be inferred from caps"
        )
    lows = np.array([profile.min(axis=0) for profile in profiles])
    highs = np.array([profile.max(axis=0) for profile in profiles])
    if np.max(np.abs(lows[0] - lows[1])) > 2e-5 or np.max(np.abs(highs[0] - highs[1])) > 2e-5:
        raise ValueError("end apertures differ; a uniform passage is not established")
    low, high = lows.max(axis=0), highs.min(axis=0)
    return {
        "end_centres_xyz": centres,
        "axis": axis.tolist(),
        "width_axis": width_axis.tolist(),
        "inner_width_m": float(high[0] - low[0]),
        "inner_height_m": float(high[1] - low[1]),
        "inner_z_range_m": [float(low[1]), float(high[1])],
        "inner_width_coordinates_m": [float(low[0]), float(high[0])],
        "inner_profiles_uz": [profile.tolist() for profile in profiles],
        "end_plane_offsets_m": [lo, hi],
        "length_m": hi - lo,
        "inner_profile_area_m2": areas,
        "max_side_projection_area_m2": float(area.max()) if len(area) else 0.0,
        "method": "Two cap surfaces each contain an enclosed boundary loop; remaining faces form an extrusion.",
    }


def extract_tunnel(triangles, approach_xy=None):
    points = unique_points(triangles)
    _, eigenvectors = np.linalg.eigh(np.cov(points.T))
    candidates, axes = [], []
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    norms = np.linalg.norm(normals, axis=1)
    normals = normals[norms > 1e-12] / norms[norms > 1e-12, None]
    # Cap normals cover equal-eigenvalue cases where PCA cannot identify the axis.
    for vector in np.vstack((eigenvectors.T, normals)):
        if abs(vector[2]) > 1e-5:
            continue
        vector[2] = 0
        axis = canonical(vector)
        if any(abs(axis @ previous) > 1 - 1e-8 for previous in axes):
            continue
        axes.append(axis)
        try:
            candidates.append(_extruded_aperture(triangles, axis))
        except ValueError:
            continue
    if len(candidates) != 1:
        raise ValueError("a unique horizontal, open-ended extrusion axis is not determined")
    result = candidates[0]
    result["status"] = "RESOLVED"
    result["cross_section_note"] = (
        "Measured maximum inner width and height, not a guaranteed inscribed rectangle; use the actual profile for body clearance."
    )
    if approach_xy is None:
        result["direction_status"] = "UNKNOWN"
        result["direction_reason"] = "Entry versus exit requires an approach reference."
    else:
        ends = np.array(result["end_centres_xyz"])
        distances = np.linalg.norm(ends[:, :2] - approach_xy, axis=1)
        if abs(distances[0] - distances[1]) < 1e-5:
            result["direction_status"] = "UNKNOWN"
            result["direction_reason"] = "Approach reference is equidistant from the two openings."
        else:
            first = int(np.argmin(distances))
            result["entry_centre_xyz"] = ends[first].tolist()
            result["exit_centre_xyz"] = ends[1 - first].tolist()
            result["passage_axis"] = ((ends[1 - first] - ends[first]) / result["length_m"]).tolist()
            result["direction_status"] = "INFERRED_FROM_APPROACH"
            result["direction_reason"] = "Entry is nearest the fitted maze guideline terminus."
    return result


def extract_window(triangles):
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    horizontal = np.abs(normals[:, 2]) < 1e-4 * lengths
    if not horizontal.any():
        raise ValueError("no vertical wall face found")
    normal = normals[np.argmax(np.where(horizontal, lengths, -1))].copy()
    normal[2] = 0
    normal = canonical(normal)
    result = _extruded_aperture(triangles, normal)
    for profile in result["inner_profiles_uz"]:
        corners = simplify_loop(np.asarray(profile))
        if len(corners) != 4:
            raise ValueError("window hole is not rectangular")
        low, high = corners.min(axis=0), corners.max(axis=0)
        if np.minimum(abs(corners - low), abs(corners - high)).max() > 2e-5:
            raise ValueError("window hole edges are not horizontal/vertical within tolerance")
    result.update(
        {
            "status": "RESOLVED",
            "centre_xyz": np.mean(result["end_centres_xyz"], axis=0).tolist(),
            "width_m": result["inner_width_m"],
            "height_m": result["inner_height_m"],
            "sill_height_m": result["inner_z_range_m"][0],
            "lintel_height_m": result["inner_z_range_m"][1],
            "wall_thickness_m": result["length_m"],
            "normal_xy": normal[:2].tolist(),
        }
    )
    width_axis = np.array(result["width_axis"])
    centre = np.array(result["centre_xyz"])
    result["crossing_line_xy"] = [
        (centre + sign * width_axis * result["width_m"] / 2)[:2].tolist() for sign in (-1, 1)
    ]
    return result


def wall_geometry(triangles):
    loops = horizontal_loops(triangles, top=False)
    if len(loops) != 1:
        raise ValueError("wall base has multiple components")
    polygon = simplify_loop(loops[0])[:, :2]
    u, n, low, high = rectangle_frame(polygon)
    ends = [
        np.array([u * value + n * low[1], u * value + n * high[1]]) for value in (low[0], high[0])
    ]
    return {"polygon": polygon, "ends": ends, "axis": u, "thickness": high[1] - low[1]}


def gap_between_edges(first, second):
    a, b = segment_closest(first, second)
    width = float(np.linalg.norm(a - b))
    if width < 1e-5:
        raise ValueError("edges touch; this is not an open gap")
    return {
        "status": "RESOLVED",
        "centre_xy": ((a + b) / 2).tolist(),
        "width_m": width,
        "crossing_line_xy": [a.tolist(), b.tolist()],
        "bounding_edges_xy": [np.asarray(first).tolist(), np.asarray(second).tolist()],
        "height_m": None,
        "height_status": "UNKNOWN",
        "height_reason": "An absence-of-wall gap has no modelled lintel; no finite clear height is inferred.",
        "method": "Clear gap derived from actual neighbouring mesh wall edges, not a modelled gate frame.",
        "official_scoring_line_status": "UNKNOWN",
        "official_scoring_line_reason": "The mesh has no referee dashed line; this measured connector is a geometric crossing prior.",
    }


def _maze_crossings(walls, guideline):
    results = []
    for name, wall in walls.items():
        if "maze divider" not in name.casefold():
            continue
        for end_index, edge in enumerate(wall["ends"]):
            start = edge.mean(axis=0)
            direction = wall["axis"] * (-1 if end_index == 0 else 1)
            hits = []
            for other_name, other in walls.items():
                if other_name == name:
                    continue
                for p, q in zip(
                    other["polygon"], np.roll(other["polygon"], -1, axis=0), strict=True
                ):
                    matrix = np.column_stack((direction, -(q - p)))
                    if abs(np.linalg.det(matrix)) < 1e-12:
                        continue
                    distance, fraction = np.linalg.solve(matrix, p - start)
                    if distance > 0.005 and -1e-8 <= fraction <= 1 + 1e-8:
                        hits.append(
                            (distance, other_name, np.array([p, q]), start + distance * direction)
                        )
            if not hits:
                continue
            distance, other_name, boundary, end = min(hits, key=lambda hit: hit[0])
            if distance < 0.01:
                continue
            cumulative = 0.0
            for p, q in pairwise(guideline):
                hit = segment_intersection([p, q], [start, end])
                length = np.linalg.norm(q - p)
                if hit is not None:
                    point, fraction = hit
                    # Use the divider axis at its end-face midpoint, not an arbitrary nearest corner.
                    gap = gap_between_edges(edge, boundary)
                    gap["crossing_line_xy"] = [start.tolist(), end.tolist()]
                    gap["centre_xy"] = ((start + end) / 2).tolist()
                    gap["width_m"] = float(distance)
                    gap["source_groups"] = [name, other_name]
                    gap["guideline_intersection_xy"] = point.tolist()
                    gap["guideline_distance_m"] = float(cumulative + fraction * length)
                    gap["traversal_normal_xy"] = ((q - p) / length).tolist()
                    results.append(gap)
                cumulative += length
    results.sort(key=lambda value: value["guideline_distance_m"])
    return results


def _free_ends(name, walls, join_tolerance=0.005):
    result = []
    for edge in walls[name]["ends"]:
        blocked = False
        for other_name, wall in walls.items():
            if name == other_name:
                continue
            for p, q in zip(wall["polygon"], np.roll(wall["polygon"], -1, axis=0), strict=True):
                a, b = segment_closest(edge, [p, q])
                if np.linalg.norm(a - b) <= join_tolerance:
                    blocked = True
        if not blocked:
            result.append(edge)
    return result


def extract_passages(meshes, header, markings=None, gate_b_groups=None):
    markings = markings or extract_markings(meshes, header)
    guide_name = markings["selection"]["guideline"]
    guideline = None
    if guide_name:
        strokes = markings["features"][guide_name]["strokes"]
        if (
            len(strokes) == 1
            and strokes[0]["status"] == "RESOLVED"
            and strokes[0]["direction_status"] != "UNKNOWN"
        ):
            guideline = np.array(strokes[0]["polyline_xy"])
    result = {
        name: unknown("No unique matching geometry found.")
        for name in ("tunnel", "window", "gate_a", "gate_b", "first_corridor")
    }
    for key, predicate, function in [
        (
            "tunnel",
            lambda name: name.casefold().startswith(("tube oval", "tunnel")),
            extract_tunnel,
        ),
        ("window", lambda name: "window" in name.casefold(), extract_window),
    ]:
        matches = [name for name in meshes if predicate(name) and "cradle" not in name.casefold()]
        if len(matches) == 1:
            name = matches[0]
            try:
                value = (
                    function(meshes[name], guideline[-1] if guideline is not None else None)
                    if key == "tunnel"
                    else function(meshes[name])
                )
                value["source_group"] = name
                result[key] = value
            except ValueError as error:
                result[key] = unknown(error, source_group=name)
    walls = {}
    for name, triangles in meshes.items():
        if any(word in name.casefold() for word in ("wall", "maze divider", "barrier", "net side")):
            try:
                walls[name] = wall_geometry(triangles)
            except ValueError:
                continue
    crossings = _maze_crossings(walls, guideline) if guideline is not None else []
    if crossings:
        result["first_corridor"] = dict(
            crossings[0],
            checkpoint_association="INFERRED: first guideline-crossed maze exit gap; official turn checkpoint line is not modelled.",
            guide_first_turn_xy=guideline[1].tolist(),
        )
        result["gate_a"] = dict(
            crossings[-1],
            checkpoint_association="Published description: leave maze where the guideline ends; this is its terminal wall-end gap.",
        )
    approaches = [name for name in walls if "approach wall" in name.casefold()]
    chicanes = [name for name in walls if "chicane wall" in name.casefold()]
    if gate_b_groups:
        approaches, chicanes = [gate_b_groups[0]], [gate_b_groups[1]]
    candidates = []
    for first in approaches:
        for second in chicanes:
            if first not in walls or second not in walls:
                continue
            for a in _free_ends(first, walls):
                for b in _free_ends(second, walls):
                    gap = gap_between_edges(a, b)
                    gap["source_groups"] = [first, second]
                    candidates.append(gap)
    candidates.sort(key=lambda value: value["width_m"])
    if candidates:
        candidate = candidates[0]
        if gate_b_groups:
            result["gate_b"] = dict(
                candidate,
                checkpoint_association="Router-supplied wall-group pair; all geometry measured from the mesh.",
            )
        else:
            result["gate_b"] = unknown(
                "Gate B is not named in the mesh. The nearest free approach/chicane wall ends give a measurable candidate, but checkpoint identity requires confirmation.",
                candidate=candidate,
                other_candidates=candidates[1:],
            )
    return {
        "header": header,
        "passages": result,
        "maze_gap_crossings": crossings,
        "vehicle_clearance_status": "UNKNOWN: drone dimensions and runtime localisation uncertainty are not supplied.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obj", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--gate-b-groups",
        nargs=2,
        help="Router-confirmed bounding wall names; coordinates are still mesh-derived",
    )
    args = parser.parse_args()
    try:
        result = extract_passages(*load_mesh(args.obj), gate_b_groups=args.gate_b_groups)
        write_json(args.out, result)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote {args.out}")
    for name, value in result["passages"].items():
        if name == "tunnel" and value["status"] == "RESOLVED":
            print(
                f"tunnel: inner {value['inner_width_m']:.6f} x {value['inner_height_m']:.6f} m; entry {value.get('entry_centre_xyz')}; exit {value.get('exit_centre_xyz')}"
            )
        elif name == "window" and value["status"] == "RESOLVED":
            print(
                f"window: centre {value['centre_xyz']}; {value['width_m']:.6f} x {value['height_m']:.6f} m; sill {value['sill_height_m']:.6f} m"
            )
        else:
            gap = value.get("candidate", value)
            print(
                f"{name}: {value['status']}; centre {gap.get('centre_xy')}; width {gap.get('width_m')}; {value.get('reason', '')}"
            )


if __name__ == "__main__":
    main()
