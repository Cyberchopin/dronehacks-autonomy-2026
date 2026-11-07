"""Fit published floor markings from planar triangle boundaries, not AABBs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

if __package__:
    from .mesh_geometry import (
        fit_circle,
        horizontal_loops,
        load_mesh,
        polygon_centroid,
        simplify_loop,
        unknown,
        write_json,
    )
else:
    from mesh_geometry import (
        fit_circle,
        horizontal_loops,
        load_mesh,
        polygon_centroid,
        simplify_loop,
        unknown,
        write_json,
    )


def fit_strip(loop):
    """Recover the medial polyline of a constant-width, unbranched mitered strip."""
    polygon = simplify_loop(np.asarray(loop)[:, :2])
    lengths = np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)
    cap_indices = np.argsort(lengths)[:2]
    i, j = sorted(cap_indices.tolist())
    if not np.isclose(lengths[i], lengths[j], atol=2e-5, rtol=1e-3):
        raise ValueError("two matching end caps are not determined")
    left = polygon[i + 1 : j + 1]
    right = np.concatenate((polygon[j + 1 :], polygon[: i + 1]))[::-1]
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("strip is branched or its two boundary chains do not correspond")
    centreline = (left + right) / 2
    widths, residuals = [], []
    for k in range(len(centreline) - 1):
        direction = centreline[k + 1] - centreline[k]
        if np.linalg.norm(direction) < 1e-8:
            raise ValueError("degenerate strip centreline")
        direction /= np.linalg.norm(direction)
        normal = np.array([-direction[1], direction[0]])
        offsets = np.array(
            [
                (left[k] - centreline[k]) @ normal,
                (left[k + 1] - centreline[k + 1]) @ normal,
                (right[k] - centreline[k]) @ normal,
                (right[k + 1] - centreline[k + 1]) @ normal,
            ]
        )
        widths.extend(np.abs(offsets) * 2)
    width = float(np.median(widths))
    residuals = (np.asarray(widths) - width) / 2
    if np.max(np.abs(residuals)) > max(2e-5, width * 0.01):
        raise ValueError("paired boundary edges do not support a constant-width strip")
    if max(abs(lengths[i] - width), abs(lengths[j] - width)) > max(2e-5, width * 0.01):
        raise ValueError("selected short edges are not strip end caps")
    return {
        "status": "RESOLVED",
        "polyline_xy": centreline.tolist(),
        "width_m": width,
        "fit_rms_m": float(np.sqrt(np.mean(residuals**2))),
        "fit_max_error_m": float(np.max(np.abs(residuals))),
        "fit_definition": "Paired triangle-boundary edges versus the medial strip's parallel offsets; miter corners retained.",
        "direction_status": "UNKNOWN",
        "direction_reason": "A geometric polyline is reversible without a launch reference.",
    }


def extract_markings(meshes, header):
    features = {}
    for name, triangles in meshes.items():
        label = name.casefold()
        if not label.startswith(("guideline", "landing pad", "launch mark", "approach ring")):
            continue
        try:
            loops = horizontal_loops(triangles)
            if label.startswith("guideline"):
                strokes = []
                for loop in loops:
                    try:
                        strokes.append(fit_strip(loop))
                    except ValueError as error:
                        strokes.append(unknown(error, boundary_xy=loop[:, :2].tolist()))
                features[name] = {
                    "status": "RESOLVED"
                    if all(s["status"] == "RESOLVED" for s in strokes)
                    else "UNKNOWN",
                    "kind": "guideline",
                    "strokes": strokes,
                    "stroke_order_status": "SINGLE_COMPONENT" if len(strokes) == 1 else "UNKNOWN",
                    "stroke_order_reason": "Disconnected strokes are never joined or given a traversal order.",
                }
            elif "cross" in label:
                if len(loops) != 1:
                    raise ValueError("cross has multiple planar boundaries")
                polygon = loops[0][:, :2]
                features[name] = {
                    "status": "RESOLVED",
                    "kind": "polygon_mark",
                    "centre_xy": polygon_centroid(polygon).tolist(),
                    "polygon_xy": polygon.tolist(),
                    "size_xy_m": np.ptp(polygon, axis=0).tolist(),
                    "fit_rms_m": 0.0,
                    "fit_definition": "Exact planar polygon from triangle-boundary edges; no curve fitted.",
                }
            else:
                circles = sorted((fit_circle(loop) for loop in loops), key=lambda c: c["radius_m"])
                expected = 2 if "ring" in label else 1
                if len(circles) != expected:
                    raise ValueError(
                        f"expected {expected} circular boundaries, found {len(circles)}"
                    )
                centres = np.array([circle["centre_xy"] for circle in circles])
                centre = centres.mean(axis=0)
                if np.max(np.linalg.norm(centres - centre, axis=1)) > 1e-4:
                    raise ValueError("circular boundaries are not concentric")
                features[name] = {
                    "status": "RESOLVED",
                    "kind": "ring" if expected == 2 else "disk",
                    "centre_xy": centre.tolist(),
                    "radius_m": float(np.mean([circle["radius_m"] for circle in circles])),
                    "outer_radius_m": circles[-1]["radius_m"],
                    "inner_radius_m": circles[0]["radius_m"] if expected == 2 else None,
                    "size_xy_m": [2 * circles[-1]["radius_m"]] * 2,
                    "fit_rms_m": max(c["vertex_rms_m"] for c in circles),
                    "fit_max_error_m": max(c["vertex_max_error_m"] for c in circles),
                    "boundary_fits": circles,
                }
        except ValueError as error:
            features[name] = unknown(error)
        if "approach ring" in label:
            features[name]["semantic_flags"] = [
                "UNKNOWN: meaning of the stage label; this marking is not checkpoint 4 (Gate B/window)."
            ]
    launch = [
        name
        for name, value in features.items()
        if name.casefold().startswith("launch mark") and value["status"] == "RESOLVED"
    ]
    guidelines = [name for name, value in features.items() if value.get("kind") == "guideline"]
    rings = [
        name
        for name, value in features.items()
        if name.casefold().startswith("landing pad ring") and value["status"] == "RESOLVED"
    ]
    selection = {
        "launch": launch[0] if len(launch) == 1 else None,
        "guideline": guidelines[0] if len(guidelines) == 1 else None,
        "landing_outer_ring": max(rings, key=lambda name: features[name]["outer_radius_m"])
        if rings
        else None,
    }
    if len(launch) == 1 and len(guidelines) == 1:
        guide = features[guidelines[0]]
        if len(guide["strokes"]) == 1 and guide["strokes"][0]["status"] == "RESOLVED":
            stroke = guide["strokes"][0]
            line = np.array(stroke["polyline_xy"])
            centre = np.array(features[launch[0]]["centre_xy"])
            distances = np.linalg.norm(line[[0, -1]] - centre, axis=1)
            if abs(distances[0] - distances[1]) > 1e-4:
                if distances[1] < distances[0]:
                    stroke["polyline_xy"].reverse()
                stroke["direction_status"] = "INFERRED_FROM_LAUNCH"
                stroke["direction_reason"] = (
                    "Start endpoint is the one nearest the fitted launch marking."
                )
    return {"header": header, "features": features, "selection": selection}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obj", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = extract_markings(*load_mesh(args.obj))
        write_json(args.out, result)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote {args.out}: {len(result['features'])} markings")
    for name, item in result["features"].items():
        if item.get("kind") == "guideline":
            for index, stroke in enumerate(item["strokes"]):
                print(
                    f"{name} stroke {index}: {len(stroke.get('polyline_xy', []))} points; RMS {stroke.get('fit_rms_m')}; {stroke['status']}"
                )
        elif item["status"] == "RESOLVED":
            print(
                f"{name}: centre {item['centre_xy']}; radius {item.get('radius_m')}; RMS {item['fit_rms_m']}"
            )
        else:
            print(f"{name}: UNKNOWN: {item['reason']}")


if __name__ == "__main__":
    main()
