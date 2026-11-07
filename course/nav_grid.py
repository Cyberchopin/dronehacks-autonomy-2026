"""Solid cross-section occupancy at sampled flight heights, retaining hollow passages."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

if __package__:
    from .extract_layout import _project_triangle
    from .mesh_geometry import inside_polygon, load_mesh, section_loops, slice_segments, write_json
else:
    from extract_layout import _project_triangle
    from mesh_geometry import inside_polygon, load_mesh, section_loops, slice_segments, write_json


def slice_occupancy(meshes, grid, height):
    """Fill material interiors by contour parity, then conservatively rasterise edges."""
    origin = np.asarray(grid["origin_xy"])
    cell = grid["resolution_m"]
    shape = tuple(grid["shape_yx"])
    occupied = np.zeros(shape, dtype=bool)
    rows, columns = np.indices(shape)
    centres = origin + (np.stack((columns, rows), axis=-1) + 0.5) * cell
    failures = []
    for name, triangles in meshes.items():
        if height < triangles[:, :, 2].min() - 1e-9 or height > triangles[:, :, 2].max() + 1e-9:
            continue
        segments, coplanar = slice_segments(triangles, height)
        if len(segments):
            try:
                loops = section_loops(segments)
                interior = np.zeros(shape, dtype=bool)
                for loop in loops:
                    interior ^= inside_polygon(centres, loop[:, :2])
                occupied |= interior
            except ValueError as error:
                failures.append(
                    {
                        "source_group": name,
                        "height_m": height,
                        "status": "UNKNOWN",
                        "reason": str(error),
                        "fallback": "Conservative full-height triangle projection for this group.",
                    }
                )
                for triangle in triangles:
                    _project_triangle(occupied, triangle, origin, cell)
            for segment in segments:
                _project_triangle(occupied, segment[[0, 1, 0]], origin, cell)
        for triangle in coplanar:
            _project_triangle(occupied, triangle, origin, cell)
    return occupied, failures


def build_nav_grid(meshes, header, layout, z_min=0.4, z_max=1.4, z_step=0.05, height=None):
    if (
        not all(math.isfinite(value) for value in (z_min, z_max, z_step))
        or z_min > z_max
        or z_step <= 0
    ):
        raise ValueError("height band and step must be finite, ordered, and have a positive step")
    selected = (z_min + z_max) / 2 if height is None else height
    if not math.isfinite(selected) or not z_min <= selected <= z_max:
        raise ValueError("selected height must lie within the flight-height band")
    if header["source_sha256"] != layout["header"]["source_sha256"]:
        raise ValueError("layout and OBJ source SHA-256 differ; regenerate layout first")
    grid = layout["occupancy"]
    if grid["resolution_m"] <= 0 or list(np.shape(grid["cells"])) != grid["shape_yx"]:
        raise ValueError("invalid reference grid")
    count = math.ceil((z_max - z_min) / z_step) + 1
    if count > 59:
        raise ValueError("at most 60 sampled height layers are supported")
    heights = sorted(set(np.round(np.r_[np.linspace(z_min, z_max, count), selected], 10).tolist()))
    selected = float(round(selected, 10))
    arrays, failures = [], []
    for z in heights:
        cells, issues = slice_occupancy(meshes, grid, z)
        arrays.append(cells)
        failures.extend(issues)
    free_masks = np.zeros(tuple(grid["shape_yx"]), dtype=np.int64)
    for index, cells in enumerate(arrays):
        free_masks |= (~cells).astype(np.int64) << index
    selected_cells = arrays[heights.index(selected)]
    occupancy = {
        key: grid[key]
        for key in (
            "origin_xy",
            "resolution_m",
            "shape_yx",
            "extent_max_xy",
            "indexing",
            "out_of_map",
        )
    }
    occupancy.update(
        {
            "height_m": selected,
            "cells": selected_cells.astype(int).tolist(),
            "occupied_cell_count": int(selected_cells.sum()),
            "values": {
                "0": "No modelled material in this cell at the selected height; body clearance remains unverified.",
                "1": "Occupied",
            },
        }
    )
    return {
        "header": dict(
            header,
            flight_height_band_m=[z_min, z_max],
            selected_height_m=selected,
            height_band_definition="Allowed sampled centre heights, NOT a full-height vehicle envelope. Main occupancy is one horizontal slice, not a union across the band.",
        ),
        "occupancy": occupancy,
        "sample_heights_m": heights,
        "layers": [
            {
                "height_m": z,
                "occupied_cell_count": int(cells.sum()),
                "cells": cells.astype(int).tolist(),
            }
            for z, cells in zip(heights, arrays, strict=True)
        ],
        "free_height_masks": free_masks.tolist(),
        "mask_definition": "Bit i is 1 exactly when the cell is free at sample_heights_m[i]. This does not establish safe motion between heights.",
        "band_available_occupied_cell_count": int(np.all(arrays, axis=0).sum()),
        "conservative_whole_band_occupied_cell_count": int(np.any(arrays, axis=0).sum()),
        "old_full_height_occupied_cell_count": int(np.asarray(grid["cells"]).sum()),
        "unknowns": failures
        + [
            {
                "status": "UNKNOWN",
                "reason": "Vehicle dimensions and localisation uncertainty are not supplied; sampled point/square clearance is not whole-drone clearance.",
            },
            {
                "status": "UNKNOWN",
                "reason": "Occupancy between sampled heights is not certified; route prior uses one layer without vertical transitions.",
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obj", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layout", type=Path, default=Path(__file__).with_name("layout.json"))
    parser.add_argument("--z-min", type=float, default=0.4)
    parser.add_argument("--z-max", type=float, default=1.4)
    parser.add_argument("--z-step", type=float, default=0.05)
    parser.add_argument("--height", type=float)
    args = parser.parse_args()
    try:
        result = build_nav_grid(
            *load_mesh(args.obj),
            json.loads(args.layout.read_text()),
            args.z_min,
            args.z_max,
            args.z_step,
            args.height,
        )
        write_json(args.out, result)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"Wrote {args.out}: {len(result['layers'])} slices in [{args.z_min:g}, {args.z_max:g}] m")
    print(
        f"Selected height {result['occupancy']['height_m']:g} m: {result['occupancy']['occupied_cell_count']} occupied cells; old full-height {result['old_full_height_occupied_cell_count']}"
    )
    print(
        f"Blocked at every sampled height: {result['band_available_occupied_cell_count']}; blocked somewhere in the band: {result['conservative_whole_band_occupied_cell_count']}"
    )
    print(
        f"Geometry fallback records: {len(result['unknowns']) - 2}; whole-drone clearance and between-layer clearance: UNKNOWN"
    )


if __name__ == "__main__":
    main()
