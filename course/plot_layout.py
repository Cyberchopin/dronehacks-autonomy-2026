"""Render extracted JSON as a headless, annotated XY map; never infer apertures.

The JSON stores feature AABBs, not individual mesh footprints. Those bounds are
drawn explicitly as rectangles over the more detailed occupancy projection.
"""

from __future__ import annotations

import argparse
import json
import math
import textwrap
from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.transforms import Bbox

matplotlib.use("Agg")

INK = "#173047"
KNOWN = "#087e8b"
EXCLUDED = "#65779c"
UNKNOWN = "#bc5100"
FREE = "#f3f6f9"
OCCUPIED = "#8b9caa"


def _unknown_records(layout: dict, identifiers: dict[str, str]) -> list[dict]:
    records = []
    for name, feature in layout["features"].items():
        flags = [str(flag) for flag in feature.get("flags", []) if "UNKNOWN" in str(flag).upper()]
        if not flags and (feature.get("kind") == "UNKNOWN" or feature.get("status") == "UNKNOWN"):
            flags = ["UNKNOWN: " + feature.get("reason", "Feature identity is unresolved.")]
        for flag in flags:
            records.append({"feature": name, "text": f"{identifiers[name]} {name}: {flag}"})
    for name, prior in layout.get("semantic_priors", {}).items():
        if prior.get("status") == "UNKNOWN":
            # Even a candidate wall group is not an established aperture location.
            records.append(
                {
                    "feature": None,
                    "text": f"{name} — UNKNOWN / UNLOCATED. {prior.get('reason', 'Unresolved prior.')}",
                }
            )
    return records


def _validate(layout: dict) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    header, grid = layout["header"], layout["occupancy"]
    if header["units"] not in {"m", "metres", "meters"} or header["axes"]["up"] != "+Z":
        raise ValueError("expected a metre, +Z-up layout")
    if header["axes"]["grid_plane"] != "XY":
        raise ValueError("expected an XY grid")
    cells = np.asarray(grid["cells"])
    if cells.ndim != 2 or min(cells.shape) == 0 or list(cells.shape) != grid["shape_yx"]:
        raise ValueError("grid cells must match the nonempty shape_yx")
    if not np.isin(cells, [0, 1]).all():
        raise ValueError("grid cells must contain only 0 (free projection) or 1 (occupied)")
    origin = np.asarray(grid["origin_xy"], dtype=float)
    resolution = float(grid["resolution_m"])
    if origin.shape != (2,) or not np.isfinite(origin).all():
        raise ValueError("grid origin must be a finite XY pair")
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("grid resolution must be finite and positive")
    maximum = origin + np.asarray(cells.shape[::-1]) * resolution
    if not np.allclose(maximum, grid["extent_max_xy"], rtol=0, atol=1e-9):
        raise ValueError("grid extent conflicts with origin, resolution, and shape")
    for name, feature in layout["features"].items():
        low, high = np.asarray(feature["bounds"]["min"]), np.asarray(feature["bounds"]["max"])
        if low.shape != (3,) or high.shape != (3,) or not np.isfinite([low, high]).all():
            raise ValueError(f"feature {name!r} needs finite XYZ bounds")
        if np.any(high < low):
            raise ValueError(f"feature {name!r} has reversed bounds")
    return cells, origin, resolution, maximum


def _place_labels(ax, features: dict, identifiers: dict, flagged: set[str]) -> None:
    """Place short ID labels without overlap; leaders terminate at known AABB centres."""
    canvas = ax.figure.canvas
    canvas.draw()
    renderer = canvas.get_renderer()
    font = FontProperties(size=8.5, weight="bold")
    used = []
    axes_box = ax.get_window_extent().padded(-5)
    # This is label spacing in screen points, not model positions or waypoints.
    offsets = [(0, 0)]
    for radius in (15, 28, 42, 60, 85, 115, 150):
        offsets.extend(
            (radius * math.cos(angle), radius * math.sin(angle))
            for angle in np.linspace(0, 2 * math.pi, 12, endpoint=False)
        )
    for name, feature in features.items():
        low, high = np.asarray(feature["bounds"]["min"]), np.asarray(feature["bounds"]["max"])
        anchor = (low[:2] + high[:2]) / 2
        label = identifiers[name] + ("?" if name in flagged else "")
        width, height, _ = renderer.get_text_width_height_descent(label, font, ismath=False)
        width, height = width + 10, height + 10
        anchor_pixels = ax.transData.transform(anchor)
        for dx, dy in offsets:
            centre = anchor_pixels + np.asarray([dx, dy]) * ax.figure.dpi / 72
            box = Bbox.from_bounds(centre[0] - width / 2, centre[1] - height / 2, width, height)
            if (
                axes_box.contains(*box.p0)
                and axes_box.contains(*box.p1)
                and not any(box.overlaps(previous) for previous in used)
            ):
                break
        else:
            raise ValueError("feature labels are too crowded; use a smaller feature set")
        used.append(box)
        colour = UNKNOWN if name in flagged else INK
        artist = ax.annotate(
            label,
            xy=anchor,
            xytext=(dx, dy),
            textcoords="offset points",
            ha="center",
            va="center",
            fontproperties=font,
            color=colour,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": colour, "lw": 0.6},
            arrowprops={"arrowstyle": "-", "color": colour, "lw": 0.7},
            zorder=8,
        )
        artist.set_gid(f"feature-label:{name}")


def build_figure(layout: dict, dpi: int = 180) -> tuple[Figure, dict]:
    """Create an Agg figure plus a coverage report, without modifying the layout."""
    if not isinstance(dpi, int) or not 40 <= dpi <= 600:
        raise ValueError("dpi must be an integer from 40 to 600")
    cells, origin, resolution, maximum = _validate(layout)
    features = layout["features"]
    identifiers = {name: f"F{index:02d}" for index, name in enumerate(features, 1)}
    unknowns = _unknown_records(layout, identifiers)
    flagged = {record["feature"] for record in unknowns if record["feature"] is not None}
    wrapped_unknowns = [
        textwrap.fill(f"U{i:02d} · {r['text']}", 95) for i, r in enumerate(unknowns, 1)
    ]
    rows = max(1, math.ceil(len(features) / 2))
    unknown_lines = sum(text.count("\n") + 1 for text in wrapped_unknowns)
    height = max(12, rows * 0.36 + 5, unknown_lines * 0.5 + 2)
    figure = Figure(figsize=(22, height), dpi=dpi, facecolor="white")
    FigureCanvasAgg(figure)
    figure.suptitle(
        f"Published course layout | {layout['header']['source_file']}",
        x=0.045,
        y=0.975,
        ha="left",
        fontsize=21,
        weight="bold",
        color=INK,
    )
    figure.text(
        0.045,
        0.94,
        "Source SHA-256: " + layout["header"]["source_sha256"],
        fontsize=11,
        family="monospace",
        color=INK,
    )
    ax = figure.add_axes([0.045, 0.20, 0.48, 0.69])
    image = ax.imshow(
        cells,
        origin="lower",
        interpolation="nearest",
        vmin=0,
        vmax=1,
        cmap=ListedColormap([FREE, OCCUPIED]),
        extent=[origin[0], maximum[0], origin[1], maximum[1]],
        zorder=0,
    )
    image.set_gid("occupancy")
    for name, feature in features.items():
        low, high = np.asarray(feature["bounds"]["min"]), np.asarray(feature["bounds"]["max"])
        included = feature["include_in_occupancy"]
        colour = UNKNOWN if name in flagged else KNOWN if included else EXCLUDED
        style = "--" if name in flagged else "-" if included else ":"
        outline = Rectangle(
            low[:2],
            *(high[:2] - low[:2]),
            fill=False,
            edgecolor=colour,
            linestyle=style,
            linewidth=1.25,
            zorder=3,
        )
        outline.set_gid(f"feature-bounds:{name}")
        ax.add_patch(outline)
    span = maximum - origin
    ax.set_xlim(origin[0] - 0.025 * span[0], maximum[0] + 0.025 * span[0])
    ax.set_ylim(origin[1] - 0.025 * span[1], maximum[1] + 0.025 * span[1])
    ax.set_aspect("equal")
    ax.set_xlabel("X (m) →", fontsize=12, color=INK)
    ax.set_ylabel("Y (m) →", fontsize=12, color=INK)
    ax.set_title(f"XY top-down · Z-up · {resolution:g} m/cell", fontsize=13, color=INK, pad=12)
    ax.tick_params(labelsize=10, colors=INK)
    ax.grid(color="white", alpha=0.4, linewidth=0.5)
    _place_labels(ax, features, identifiers, flagged)

    figure.text(
        0.55,
        0.895,
        f"FEATURE KEY  ·  {len(features)}/{len(features)} outlined and labelled",
        fontsize=13,
        weight="bold",
        color=INK,
    )
    figure.text(
        0.55,
        0.87,
        "IDs index source groups; they are not a route order.  ? = see UNKNOWN register.",
        fontsize=9,
        color=INK,
    )
    inventory_pitch = min(0.0215, 0.37 / rows)
    for index, (name, feature) in enumerate(features.items()):
        column, row = divmod(index, rows)
        text = f"{identifiers[name]}{'?' if name in flagged else ' '}  {name}"
        entry = figure.text(
            0.55 + column * 0.225,
            0.842 - row * inventory_pitch,
            textwrap.fill(text, 38, subsequent_indent="      "),
            va="top",
            fontsize=9.3,
            color=UNKNOWN if name in flagged else INK,
            linespacing=1.1,
        )
        entry.set_gid(f"feature-key:{name}")

    figure.text(
        0.55,
        0.455,
        f"UNKNOWN REGISTER  ·  {len(unknowns)} unresolved records",
        fontsize=13,
        weight="bold",
        color=UNKNOWN,
    )
    y = 0.425
    unknown_font = 9.3
    for index, text in enumerate(wrapped_unknowns, 1):
        entry = figure.text(
            0.55, y, text, va="top", fontsize=unknown_font, color=UNKNOWN, linespacing=1.35
        )
        entry.set_gid(f"unknown:{index}")
        y -= (text.count("\n") + 1) * unknown_font / 72 / height * 1.35 + 0.009
    if not unknowns:
        figure.text(0.55, y, "No UNKNOWN records in this JSON.", fontsize=10, color=INK)

    handles = [
        Patch(facecolor=OCCUPIED, label="Occupied projection"),
        Patch(
            facecolor=FREE, edgecolor="#b4c1cc", label="Free projection (clearance not established)"
        ),
        Line2D([], [], color=KNOWN, lw=1.25, label="Included feature: XY bounds"),
        Line2D([], [], color=EXCLUDED, ls=":", lw=1.25, label="Excluded feature: XY bounds"),
        Line2D(
            [], [], color=UNKNOWN, ls="--", lw=1.25, label="UNKNOWN flag / unresolved prior (?)"
        ),
    ]
    figure.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.075, 0.145),
        ncol=2,
        frameon=False,
        fontsize=9,
    )

    # Scale length is computed in metres; its screen width uses the actual map transform.
    desired = float(span[0]) / 5
    power = 10 ** math.floor(math.log10(desired))
    scale = max(value * power for value in (1, 2, 5) if value * power <= desired)
    ends = ax.transData.transform([origin, origin + [scale, 0]])
    fraction = (ends[1, 0] - ends[0, 0]) / figure.bbox.width
    sx, sy = 0.09, 0.068
    bar = Line2D([sx, sx + fraction], [sy, sy], transform=figure.transFigure, color=INK, lw=3)
    bar.set_gid("scale-bar")
    figure.add_artist(bar)
    figure.text(sx + fraction / 2, sy + 0.009, f"{scale:g} m", ha="center", fontsize=10, color=INK)
    figure.text(
        0.045,
        0.031,
        "Outlines are axis-aligned XY bounds from JSON, not exact mesh outlines. Shared bounds may overlap. Unlocated apertures are listed only.",
        fontsize=10,
        color=INK,
    )
    figure.text(
        0.045,
        0.012,
        "Published layout (rule 6.4) · Preliminary feature priors, not a hard-coded route · All-height occupancy closes tunnel/window footprints.",
        fontsize=10,
        color=INK,
    )
    return figure, {
        "feature_count": len(features),
        "unknown_count": len(unknowns),
        "flagged_feature_count": len(flagged),
        "unlocated_unknown_count": sum(record["feature"] is None for record in unknowns),
        "scale_bar_m": scale,
    }


def plot_layout(json_path: str | Path, out_path: str | Path, dpi: int = 180) -> dict:
    """Read a JSON snapshot and write a PNG; return its coverage and size."""
    layout = json.loads(Path(json_path).read_text(encoding="utf-8"))
    figure, report = build_figure(layout, dpi)
    output = Path(out_path)
    try:
        figure.savefig(
            output,
            format="png",
            dpi=dpi,
            metadata={
                "Source": layout["header"]["source_file"],
                "Source SHA-256": layout["header"]["source_sha256"],
            },
        )
        report["width_px"], report["height_px"] = figure.canvas.get_width_height()
        report["bytes"] = output.stat().st_size
    finally:
        figure.clear()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path, help="Extracted layout JSON")
    parser.add_argument("--out", type=Path, required=True, help="Output PNG")
    parser.add_argument("--dpi", type=int, default=180, help="Output DPI (40–600; default 180)")
    args = parser.parse_args()
    try:
        report = plot_layout(args.layout, args.out, args.dpi)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"error: {error}\n")
    print(
        f"Wrote {args.out}: {report['width_px']} x {report['height_px']} pixels; {report['bytes']} bytes"
    )
    print(f"Features: {report['feature_count']}/{report['feature_count']} outlined and labelled")
    print(
        f"UNKNOWN: {report['unknown_count']} records shown; {report['flagged_feature_count']} flagged feature bounds; {report['unlocated_unknown_count']} unlocated priors listed without coordinates"
    )
    print(f"Scale bar: {report['scale_bar_m']:g} m; axes: X right, Y up, Z-up top-down")


if __name__ == "__main__":
    main()
