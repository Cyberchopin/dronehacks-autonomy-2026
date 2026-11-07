"""Compute a coarse corridor seed from published mesh priors; no flight commands."""

from __future__ import annotations

import argparse
import heapq
import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np

if __package__:
    from .extract_layout import world_to_cell
    from .mesh_geometry import segment_intersection, unknown, write_json
else:
    from extract_layout import world_to_cell
    from mesh_geometry import segment_intersection, unknown, write_json


def line_cells(first, last):
    """Supercover of a centre-to-centre segment; corner-touching cells are included."""
    row, column = first
    end_row, end_column = last
    dy, dx = end_row - row, end_column - column
    sy, sx = int(np.sign(dy)), int(np.sign(dx))
    delta_x = 1 / abs(dx) if dx else math.inf
    delta_y = 1 / abs(dy) if dy else math.inf
    tx, ty = delta_x / 2, delta_y / 2
    result = [(row, column)]
    while (row, column) != (end_row, end_column):
        if abs(tx - ty) < 1e-12:
            result.extend([(row, column + sx), (row + sy, column)])
            column, row = column + sx, row + sy
            tx, ty = tx + delta_x, ty + delta_y
        elif tx < ty:
            column, tx = column + sx, tx + delta_x
        else:
            row, ty = row + sy, ty + delta_y
        result.append((row, column))
    return result


def line_clear(mask, first, last):
    return all(
        0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and not mask[r, c]
        for r, c in line_cells(first, last)
    )


def inflate(mask, radius, cell):
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("clearance radius must be finite and nonnegative")
    inflated = mask.copy()
    steps = math.ceil(radius / cell)
    if steps == 0:
        return inflated
    rows, columns = mask.shape
    for dy in range(-steps, steps + 1):
        for dx in range(-steps, steps + 1):
            if math.hypot(max(abs(dx) - 1, 0), max(abs(dy) - 1, 0)) * cell > radius:
                continue
            if abs(dy) >= rows or abs(dx) >= columns:
                continue
            sy, sx = max(0, -dy), max(0, -dx)
            ey, ex = min(rows, rows - dy), min(columns, columns - dx)
            inflated[sy + dy : ey + dy, sx + dx : ex + dx] |= mask[sy:ey, sx:ex]
    inflated[:steps] = inflated[-steps:] = True
    inflated[:, :steps] = inflated[:, -steps:] = True
    return inflated


def obstacle_distance(mask):
    distances = np.full(mask.shape, np.inf)
    queue = []
    for row, column in np.argwhere(mask):
        distances[row, column] = 0
        queue.append((0.0, int(row), int(column)))
    heapq.heapify(queue)
    while queue:
        distance, row, column = heapq.heappop(queue)
        if distance != distances[row, column]:
            continue
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            r, c = row + dy, column + dx
            if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and distance + 1 < distances[r, c]:
                distances[r, c] = distance + 1
                heapq.heappush(queue, (distance + 1, r, c))
    return distances


def astar(mask, first, last, distances=None):
    if mask[first] or mask[last]:
        raise ValueError("a route constraint lies in occupied/inflated geometry")
    distances = obstacle_distance(mask) if distances is None else distances
    queue, previous, costs = [(0.0, first)], {}, {first: 0.0}
    while queue:
        _, current = heapq.heappop(queue)
        if current == last:
            path = [last]
            while path[-1] != first:
                path.append(previous[path[-1]])
            return path[::-1], costs[last]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == dy == 0:
                    continue
                following = current[0] + dy, current[1] + dx
                r, c = following
                if not (0 <= r < mask.shape[0] and 0 <= c < mask.shape[1]) or not line_clear(
                    mask, current, following
                ):
                    continue
                cost = costs[current] + math.hypot(dx, dy) * (1 + 2 / (1 + distances[following]))
                if cost >= costs.get(following, math.inf):
                    continue
                costs[following], previous[following] = cost, current
                heuristic = math.hypot(last[0] - r, last[1] - c)
                heapq.heappush(queue, (cost + heuristic, following))
    raise ValueError("no connected free corridor satisfies the checkpoint constraints")


def simplify_path(path, mask):
    result, i = [path[0]], 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not line_clear(mask, path[i], path[j]):
            j -= 1
        result.append(path[j])
        i = j
    return result


def plan_corridor(grid, start_xy, checkpoints, radius=0.0):
    """Generic ordered portal planner. Crossings themselves must be direct and clear."""
    resolution = grid["resolution_m"]
    origin = np.asarray(grid["origin_xy"])
    mask = inflate(np.asarray(grid["cells"], dtype=bool), radius, resolution)
    distances = obstacle_distance(mask)
    cell = lambda point: world_to_cell({"occupancy": grid}, *point)
    xy = lambda point: origin + (np.array(point[::-1]) + 0.5) * resolution
    path = [cell(start_xy)]
    records, cost = [], 0.0
    for checkpoint in checkpoints:
        record = dict(checkpoint)
        record["crossings"] = []
        for portal in checkpoint.get("portals", []):
            line = np.asarray(portal["line_xy"])
            centre = line.mean(axis=0)
            normal = np.asarray(portal["normal_xy"], dtype=float)
            normal /= np.linalg.norm(normal)
            offset = max(2 * resolution, portal.get("half_depth_m", 0.0) + radius + resolution)
            first, last = cell(centre - normal * offset), cell(centre + normal * offset)
            approach, score = astar(mask, path[-1], first, distances)
            path.extend(simplify_path(approach, mask)[1:])
            if not line_clear(mask, first, last):
                raise ValueError("the direct portal crossing is blocked at this height/margin")
            hit = segment_intersection([xy(first), xy(last)], line)
            if hit is None or (xy(last) - xy(first)) @ normal <= 0:
                raise ValueError("grid crossing misses the finite portal or its required direction")
            before = len(path) - 1
            path.append(last)
            record["crossings"].append(
                {
                    "line_xy": line.tolist(),
                    "normal_xy": normal.tolist(),
                    "intersection_xy": hit[0].tolist(),
                    "polyline_indices": [before, before + 1],
                    "whole_drone_status": "UNKNOWN: body extent and pose uncertainty must be applied by the runtime.",
                    "whole_drone_condition": "Trailing-most body point has positive signed distance along the crossing normal.",
                }
            )
            cost += score + np.linalg.norm(np.asarray(last) - first)
        if "target_xy" in checkpoint:
            segment, score = astar(mask, path[-1], cell(checkpoint["target_xy"]), distances)
            path.extend(simplify_path(segment, mask)[1:])
            cost += score
        record["end_polyline_index"] = len(path) - 1
        records.append(record)
    if not all(line_clear(mask, a, b) for a, b in pairwise(path)):
        raise ValueError("coarsened route failed its independent grid supercover check")
    polyline = np.array([xy(point) for point in path])
    return {
        "status": "GEOMETRIC_SEED",
        "corridor_polyline_xy": polyline.tolist(),
        "length_m": float(np.linalg.norm(np.diff(polyline, axis=0), axis=1).sum()),
        "search_cost": float(cost),
        "checkpoints": records,
        "clearance_radius_m": radius,
        "grid_validation": "Every simplified segment and every finite portal crossing checked against the same selected-height grid, with no diagonal corner cutting.",
    }


def _profile_line(tunnel, centre, height):
    profile = np.asarray(tunnel["inner_profiles_uz"][0])
    values = []
    for a, b in zip(profile, np.roll(profile, -1, axis=0), strict=True):
        if (a[1] > height) != (b[1] > height):
            values.append(a[0] + (height - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
    values = sorted({round(float(value), 10) for value in values})
    if len(values) != 2:
        raise ValueError("tunnel profile has no unique clear chord at the selected height")
    width_axis = np.asarray(tunnel["width_axis"])
    axis = np.asarray(tunnel["axis"])
    centre = np.asarray(centre)
    offset = centre @ axis
    return [(width_axis * value + axis * offset)[:2].tolist() for value in values]


def _checkpoints(passages, markings, height, alternative):
    p = passages["passages"]
    for name in ("first_corridor", "gate_a", "tunnel", alternative):
        if p[name]["status"] != "RESOLVED":
            raise ValueError(f"checkpoint geometry {name!r} is UNKNOWN")
    selection, features = markings["selection"], markings["features"]
    if not selection["launch"] or not selection["landing_outer_ring"]:
        raise ValueError("launch or landing outer ring is UNKNOWN")
    launch = features[selection["launch"]]["centre_xy"]
    pad = features[selection["landing_outer_ring"]]
    checkpoints = []
    for number, name in [(1, "first_corridor"), (2, "gate_a")]:
        gap = p[name]
        checkpoints.append(
            {
                "number": number,
                "name": name,
                "portals": [
                    {"line_xy": gap["crossing_line_xy"], "normal_xy": gap["traversal_normal_xy"]}
                ],
                "official_scoring_line_status": gap["official_scoring_line_status"],
            }
        )
    tunnel = p["tunnel"]
    if "entry_centre_xyz" not in tunnel:
        raise ValueError("tunnel traversal direction is UNKNOWN")
    direction = tunnel["passage_axis"][:2]
    portals = [
        {"line_xy": _profile_line(tunnel, tunnel[key], height), "normal_xy": direction}
        for key in ("entry_centre_xyz", "exit_centre_xyz")
    ]
    checkpoints.append(
        {
            "number": 3,
            "name": "tunnel",
            "portals": portals,
            "checkpoint_crossing": "exit portal; entry portal is a traversal constraint",
        }
    )
    chosen = p[alternative]
    line = np.asarray(chosen["crossing_line_xy"])
    tangent = line[1] - line[0]
    normal = np.array([-tangent[1], tangent[0]]) / np.linalg.norm(tangent)
    if normal @ (np.asarray(pad["centre_xy"]) - line.mean(axis=0)) < 0:
        normal *= -1
    if alternative == "window" and not chosen["sill_height_m"] < height < chosen["lintel_height_m"]:
        raise ValueError("selected height is outside the window opening")
    checkpoints.append(
        {
            "number": 4,
            "name": alternative,
            "portals": [
                {
                    "line_xy": line.tolist(),
                    "normal_xy": normal.tolist(),
                    "half_depth_m": chosen.get("wall_thickness_m", 0) / 2,
                }
            ],
        }
    )
    checkpoints.append(
        {
            "number": 5,
            "name": "landing_pad_outer_ring",
            "target_xy": pad["centre_xy"],
            "crossing_line_xy": None,
            "boundary": {
                "kind": "circle",
                "centre_xy": pad["centre_xy"],
                "radius_m": pad["inner_radius_m"],
                "definition": "Inner edge of outer painted ring, a conservative containment prior.",
            },
            "completion_status": "UNKNOWN: whole-drone containment, landing and disarming require runtime observations; this module issues no commands.",
        }
    )
    return launch, checkpoints


def build_route_prior(nav, passages, markings, radius=0.0):
    sources = [document["header"]["source_sha256"] for document in (nav, passages, markings)]
    if len(set(sources)) != 1:
        raise ValueError("input priors have different source SHA-256 values")
    candidates, failures = [], []
    height = nav["occupancy"]["height_m"]
    for alternative in ("gate_b", "window"):
        try:
            launch, checkpoints = _checkpoints(passages, markings, height, alternative)
            seed = plan_corridor(nav["occupancy"], launch, checkpoints, radius)
            seed["checkpoint_4_alternative"] = alternative
            candidates.append(seed)
        except ValueError as error:
            failures.append({"alternative": alternative, "reason": str(error)})
    result = (
        min(candidates, key=lambda item: item["search_cost"])
        if candidates
        else unknown("No complete corridor seed satisfies the resolved checkpoint constraints.")
    )
    result.update(
        {
            "header": dict(
                nav["header"],
                artifact="Map-derived corridor seed; not executable flight waypoints or timings.",
            ),
            "analysis_height_m": height,
            "alternative_failures": failures,
            "selection_method": "Lowest computed A* clearance-weighted search cost among resolved alternatives; no score, bonus, timing or prerecorded run data.",
            "runtime_contract": "Re-extract when the published model changes. Runtime localises against live perception, checks vehicle/body clearance, replans around observed differences, and determines whole-drone crossing/landing state.",
            "unknowns": [
                "Official dashed checkpoint-line placement is not encoded in the mesh; wall-edge connectors and cap planes are geometric priors.",
                "Vehicle dimensions, localisation error, operational clearance, landing/disarm state and between-height transitions are not established.",
            ],
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=Path(__file__).with_name("nav_grid.json"))
    parser.add_argument("--passages", type=Path, default=Path(__file__).with_name("passages.json"))
    parser.add_argument(
        "--markings", type=Path, default=Path(__file__).with_name("floor_markings.json")
    )
    parser.add_argument(
        "--clearance",
        type=float,
        default=0.0,
        help="Optional geometric XY margin; zero does not certify whole-drone clearance",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_route_prior(
            *(json.loads(path.read_text()) for path in (args.grid, args.passages, args.markings)),
            args.clearance,
        )
        write_json(args.out, result)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote {args.out}: {result['status']}")
    if result["status"] == "GEOMETRIC_SEED":
        print(
            f"{len(result['corridor_polyline_xy'])} polyline points; {result['length_m']:.6f} m; checkpoints {[c['number'] for c in result['checkpoints']]}; checkpoint 4 via {result['checkpoint_4_alternative']}"
        )
    for item in result["alternative_failures"]:
        print(f"Unavailable {item['alternative']}: {item['reason']}")
    print(
        "Whole-drone clearance and official referee-line placement: UNKNOWN; runtime perception/refinement required."
    )


if __name__ == "__main__":
    main()
