"""Standalone HTML with inline SVG traces and embedded PNGs; no network assets."""

from html import escape
import math

PALETTE = ["#176dba", "#b13c38", "#138155", "#7753ad", "#ab6a09", "#317c88", "#bd3c82"]


def chart(title, unit, series):
    """Series: (name, [(seconds, value-or-None), ...]). Break at UNKNOWN or clock reset."""
    known = [
        (t, v) for _, points in series for t, v in points if v is not None and math.isfinite(v)
    ]
    if not known:
        return f"<section><h2>{escape(title)}</h2><p>UNKNOWN — no usable samples.</p></section>"
    xmin, xmax = min(t for t, _ in known), max(t for t, _ in known)
    ymin, ymax = min(v for _, v in known), max(v for _, v in known)
    if xmax == xmin:
        xmax = xmin + 1
    pad = max((ymax - ymin) * 0.08, 0.05)
    ymin, ymax = ymin - pad, ymax + pad

    def xy(t, v):
        return 64 + (t - xmin) / (xmax - xmin) * 800, 187 - (v - ymin) / (ymax - ymin) * 155

    parts = [
        f'<section><h2>{escape(title)}</h2><svg viewBox="0 0 900 232" role="img" '
        f'aria-label="{escape(title, quote=True)}"><rect width="900" height="232" fill="white"/>'
    ]
    for i in range(5):
        v = ymin + (ymax - ymin) * i / 4
        _, y = xy(xmin, v)
        parts.append(
            f'<path d="M64 {y:.2f}H864" stroke="#ddd"/><text x="58" y="{y + 4:.2f}" '
            f'text-anchor="end">{v:.3g}</text>'
        )
        t = xmin + (xmax - xmin) * i / 4
        x, _ = xy(t, ymin)
        parts.append(f'<text x="{x:.2f}" y="207" text-anchor="middle">{t:.2f}</text>')
    parts.append(
        f'<text x="64" y="19">{escape(unit)}</text><text x="690" y="228">image time (s)</text>'
    )
    legends = []
    for index, (name, points) in enumerate(series):
        color = PALETTE[index % len(PALETTE)]
        segment, previous = [], None

        def flush():
            if segment:
                parts.append(
                    f'<polyline fill="none" stroke="{color}" stroke-width="1.8" '
                    f'points="{" ".join(segment)}"/>'
                )
                segment.clear()

        for t, value in points:
            if value is None or (previous is not None and t < previous):
                flush()
            previous = t
            if value is None:
                continue
            x, y = xy(t, value)
            segment.append(f"{x:.2f},{y:.2f}")
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2" fill="{color}"><title>'
                f"{escape(name)}: {value:.4g} at {t:.3f}s</title></circle>"
            )
        flush()
        legends.append(f'<span style="color:{color}">● {escape(name)}</span>')
    parts.append('</svg><div class="legend">' + " · ".join(legends) + "</div></section>")
    return "".join(parts)


def count_table(title, counts):
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(counts.items()))
    return f"<h2>{escape(title)}</h2><table>{rows or '<tr><td>None</td></tr>'}</table>"


def render_html(report):
    s, lines, depth = report["summary"], report["line_frames"], report["depth_frames"]

    def line_series(name, field):
        return name, [(r["time_s"], r["line"][field]) for r in lines]

    def depth_series(name, field):
        return name, [(r["time_s"], r[field]) for r in depth]

    graphs = [
        chart(
            "Line detection and confidence",
            "fraction",
            [
                line_series("detected", "detected"),
                line_series("confidence", "confidence"),
                (
                    "rolling detection rate (30 frames)",
                    [(r["time_s"], r["rolling_detection_rate"]) for r in lines],
                ),
            ],
        ),
        chart(
            "Line bottom offset",
            "normalized offset (+right)",
            [line_series("offset", "bottom_offset")],
        ),
        chart("Image-plane lean", "degrees (+right)", [line_series("lean", "image_lean_deg")]),
        chart(
            "Depth validity and unknown sectors",
            "fraction",
            [
                depth_series("valid depth pixels", "depth_valid_fraction"),
                depth_series("unknown sectors", "unknown_sector_fraction"),
            ],
        ),
    ]
    sector_series = []
    for i in range(report["config"]["depth"]["sectors"]):
        sector_series.append(
            (
                f"sector {i} (left to right)",
                [(r["time_s"], r["depth"]["sectors"][i]["nearest_m"]) for r in depth],
            )
        )
    graphs.append(chart("Per-sector ray range", "metres", sector_series))
    for field, unit in [("lateral_mps", "m/s (+right)"), ("yaw_rate_dps", "deg/s (+right)")]:
        graphs.append(
            chart(
                f"Steering advisory: {field}",
                unit,
                [(field, [(r["time_s"], r["advisory"][field]) for r in lines])],
            )
        )
    graphs.append(
        chart(
            "Advisory state (never executed)",
            "0 stop / 1 coast / 2 steer",
            [
                (
                    "state",
                    [
                        (r["time_s"], {"stop": 0, "coast": 1, "steer": 2}[r["advisory"]["action"]])
                        for r in lines
                    ],
                )
            ],
        )
    )
    summary = "".join(
        f"<tr><th>{escape(k)}</th><td>{'UNKNOWN' if v is None else escape(str(round(v, 4) if isinstance(v, float) else v))}</td></tr>"
        for k, v in s.items()
    )
    thumbs = "".join(
        f'<figure><img alt="{"detected line" if t["detected"] else "no line"} at {t["time_s"]:.2f}s" src="{t["data_uri"]}"><figcaption>{escape(t["file"])} · {t["time_s"]:.2f}s</figcaption></figure>'
        for t in report["thumbnails"]
    )
    topic_rows = "".join(
        f"<tr><td>{escape(k)}</td><td>{escape(v.get('name', v.get('requested', 'UNKNOWN')))}</td><td>{escape(v['status'])}</td></tr>"
        for k, v in report["topics"].items()
    )
    config = report["config"]["line"]
    settings = escape(
        f"polarity={config['polarity']}; roi_top={config['roi_top']}; "
        f"contrast_delta={config['contrast_delta']}; "
        f"sectors={report['config']['depth']['sectors']}; "
        f"max_range={report['config']['depth']['max_range_m']} m"
    )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Offline perception replay — {escape(report["bag_name"])}</title>
<style>body{{font:15px system-ui,sans-serif;background:#edf1f5;color:#172b3a;max-width:1100px;margin:auto;padding:24px}}
section,header,.panel{{background:white;padding:18px;margin:16px 0;border-radius:8px}}
h1{{margin-top:0}}h2{{font-size:18px}}table{{border-collapse:collapse;width:100%}}
td,th{{text-align:left;border-bottom:1px solid #ddd;padding:6px;overflow-wrap:anywhere}}
svg{{width:100%;height:auto;font:12px sans-serif}}.legend{{font-size:13px}}.thumbs{{display:flex;flex-wrap:wrap;gap:10px}}
figure{{margin:0}}img{{max-width:100%}}figcaption{{font-size:12px}}.notice{{background:#fff1cd;padding:12px}}
code{{overflow-wrap:anywhere}}details{{margin:12px 0}}</style>
<header><h1>Offline perception replay</h1><p>{escape(report["bag_name"])} · source: <b>{escape(report["source_kind"])}</b></p>
<p><code>{settings}</code></p>
<p class="notice">{escape(report["usage"])}. No commands were executed.</p>
<p>{escape(report["interpretation"])}. Domain: real venue orange tarp/black tape; simulator textures differ.</p>
<p>{escape(report["freshness"])}. Nearest telemetry can be a future sample; this is not a causal flight replay.</p>
<p>Range gaps mean either UNKNOWN or observed beyond max range; consult unknown-sector traces and JSON.
Image streams are evaluated independently without repeating nearest image pairs.</p></header>
<div class="panel"><h2>Summary</h2><table>{summary}</table><p>Zero samples → UNKNOWN, not zero error.</p></div>
{"".join(graphs)}<div class="panel"><h2>Sampled images</h2><div class="thumbs">{thumbs or "No decodable mono frames."}</div>
<p>Up to 10 evenly spaced mono samples; fewer when the export is short. Green overlay is image-space evidence.</p></div>
<div class="panel">{count_table("Line rejection reasons", report["rejection_reason_counts"])}
{count_table("Input errors", report["input_errors"])}{count_table("Leveling UNKNOWN", report["leveling_unknown_reasons"])}
{count_table("Floor filter UNKNOWN", report["floor_filter_unknown_reasons"])}<h2>Topics</h2><table>{topic_rows}</table>
<details><summary>Provenance</summary><p>Replay commit: <code>{escape(report["repo_commit"])}</code></p>
<p>Manifest SHA-256: <code>{report["manifest_sha256"]}</code></p><p>Export: <code>{escape(report["export_command"])}</code></p>
<p>Replay: <code>{escape(report.get("command", "UNKNOWN"))}</code></p></details></div></html>"""
