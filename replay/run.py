"""Replay exported packets through perception and steering advice, without ROS."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from dataclasses import asdict
import hashlib
from pathlib import Path
import shlex
import sys

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nav.line_follow import LineFollower
from replay.frames import json_bytes, load_manifest, load_packet, provenance, unknown
from vision.attitude import level_from_px4, rotation_matrix
from vision.depth_sectors import SectorConfig
from vision.floor_line import LineConfig, decode_mono, floor_line_message
from vision.forward_sectors import decode_depth, forward_sectors


def image_args(frame, packet):
    return (
        frame["encoding"],
        frame["height"],
        frame["width"],
        frame["step"],
        packet["data"].tobytes(),
    )


def sample_problem(item, max_sync_ms):
    if item.get("status") != "KNOWN":
        return item.get("reason", "sample missing")
    if abs(item["delta_ns"]) > max_sync_ms * 1e6:
        return "nearest sample exceeds synchronization tolerance"
    lag = item["timestamp_us"] - item["timestamp_sample_us"]
    if item["timestamp_sample_us"] <= 0 or lag < 0 or lag / 1000 > max_sync_ms:
        return "invalid/stale PX4 source sample timestamps"
    return None


def level_inputs(frame, max_sync_ms=200):
    attitude, ext = frame.get("attitude", {}), frame.get("extrinsics", {})
    problem = sample_problem(attitude, max_sync_ms)
    if problem:
        return None, None, unknown(f"attitude: {problem}"), unknown("no leveling")
    if ext.get("status") != "KNOWN":
        return (
            None,
            None,
            unknown(f"extrinsics: {ext.get('reason', 'missing')}"),
            unknown("no leveling"),
        )
    try:
        base_cam = rotation_matrix(ext["rotation"])
        if base_cam[0, 2] < np.cos(np.radians(25)):
            raise ValueError("camera optical axis is more than 25 degrees off body forward")
        level_base = level_from_px4(attitude["q_wxyz"])
        rotation = level_base @ base_cam
    except (KeyError, ValueError, TypeError) as e:
        return None, None, unknown(str(e)), unknown("no leveling")
    leveling = {
        "status": "KNOWN",
        "attitude_delta_ns": attitude["delta_ns"],
        "extrinsics_source": ext.get("source"),
        "offline_nearest_matching": True,
    }
    position = frame.get("position", {})
    problem = sample_problem(position, max_sync_ms)
    if problem or not position.get("dist_bottom_valid") or position.get("dist_bottom_m") is None:
        return rotation, None, leveling, unknown(problem or "dist_bottom invalid")
    try:
        translation = np.asarray(ext["translation_m"], dtype=float)
        if translation.shape != (3,) or not np.isfinite(translation).all():
            raise ValueError("invalid optical-centre translation")
        height = position["dist_bottom_m"] + float((level_base @ translation)[2])
        if not np.isfinite(height) or height <= 0 or position["dist_bottom_m"] <= 0:
            raise ValueError("camera height must be positive and finite")
    except (KeyError, TypeError, ValueError) as e:
        return rotation, None, leveling, unknown(str(e))
    return (
        rotation,
        height,
        leveling,
        {"status": "KNOWN", "camera_height_m": height, "position_delta_ns": position["delta_ns"]},
    )


def missing_line(reason, stamp):
    return {
        "detected": False,
        "status": "unknown",
        "confidence": 0.0,
        "fresh": False,
        "bottom_offset": None,
        "image_lean_deg": None,
        "points_normalized": [],
        "stamp_ns": stamp,
        "rejection_reasons": [reason],
        "control_output": "DISABLED",
    }


def unknown_depth(reason, sectors):
    return {
        "leveled": False,
        "nearest_m": None,
        "control_output": "DISABLED",
        "sectors": [
            {
                "observed": False,
                "nearest_m": None,
                "reason": reason,
                "valid_fraction": 0.0,
                "azimuth_deg": None,
            }
            for _ in range(sectors)
        ],
    }


def thumbnail(gray, line, time_s):
    view = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    h, w = gray.shape
    if line["detected"]:
        points = np.array(
            [[round(x * w), round(y * h)] for x, y in line["points_normalized"]], dtype=np.int32
        )
        cv2.polylines(view, [points], False, (0, 220, 0), max(1, w // 160))
    scale = min(1.0, 320 / w, 220 / h)
    view = cv2.resize(view, (max(1, round(w * scale)), max(1, round(h * scale))))
    label = f"{time_s:.2f}s: " + ("line (identity unverified)" if line["detected"] else "no line")
    cv2.rectangle(view, (0, 0), (view.shape[1], 21), (20, 20, 20), -1)
    cv2.putText(view, label, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    ok, encoded = cv2.imencode(".png", view)
    if not ok:
        raise ValueError("thumbnail PNG encoding failed")
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")


def evaluate(folder, *, line_config=None, sector_config=None, max_sync_ms=200, thumbnails=10):
    line_config = line_config or LineConfig(polarity="dark")
    sector_config = sector_config or SectorConfig()
    if not np.isfinite(line_config.contrast_delta) or line_config.contrast_delta <= 0:
        raise ValueError("contrast_delta must be positive and finite")
    if (
        sector_config.sectors < 1
        or not np.isfinite(sector_config.max_range_m)
        or sector_config.max_range_m <= 0
    ):
        raise ValueError("sectors and max_range must be positive and finite")
    if not np.isfinite(max_sync_ms) or max_sync_ms <= 0:
        raise ValueError("max_sync_ms must be positive and finite")
    if not 0 <= thumbnails <= 12:
        raise ValueError("thumbnails must be in [0, 12]")
    manifest = load_manifest(folder)
    frames = sorted(manifest["frames"], key=lambda f: f["bag_time_ns"])
    calibrations = {f["file"]: f for f in frames if f["role"] == "camera_info"}
    images = [f for f in frames if f["role"] in {"mono", "depth"}]
    start = min((f["stamp_ns"] for f in images), default=0)
    mono = [f for f in images if f["role"] == "mono"]
    chosen = set(np.linspace(0, len(mono) - 1, min(thumbnails, len(mono)), dtype=int))
    follower, last_stamp = LineFollower(), None
    line_rows, depth_rows, thumbs = [], [], []
    errors, reasons, leveling_reasons, floor_reasons = Counter(), Counter(), Counter(), Counter()
    resets = 0
    for f in images:
        row = {
            "file": f["file"],
            "stamp_ns": f["stamp_ns"],
            "bag_time_ns": f["bag_time_ns"],
            "time_s": (f["stamp_ns"] - start) / 1e9,
        }
        try:
            packet = load_packet(folder, f)
            args = image_args(f, packet)
            if f["role"] == "mono":
                line = floor_line_message(
                    *args,
                    f["stamp_ns"],
                    f["stamp_ns"],
                    f["frame_id"],
                    line_config,
                    f["is_bigendian"],
                )
                row["line"] = line
                if len(line_rows) in chosen:
                    gray = decode_mono(*args, is_bigendian=f["is_bigendian"])
                    thumbs.append(
                        {
                            "file": f["file"],
                            "time_s": row["time_s"],
                            "detected": line["detected"],
                            "data_uri": thumbnail(gray, line, row["time_s"]),
                        }
                    )
            else:
                _, valid = decode_depth(*args, is_bigendian=f["is_bigendian"])
                row["depth_valid_fraction"] = float(valid.mean())
                rotation, height, leveling, floor = level_inputs(f, max_sync_ms)
                row.update(leveling=leveling, floor_filter=floor)
                info = f.get("camera_info", {})
                if info.get("status") != "KNOWN":
                    raise ValueError("CameraInfo UNKNOWN")
                if info["delta_ns"] > max_sync_ms * 1e6:
                    raise ValueError("CameraInfo only available too far in future")
                calibration = load_packet(folder, calibrations[info["file"]])
                if not np.array_equal(calibration["k"], info["k"]):
                    raise ValueError("associated CameraInfo K differs from stored packet")
                row["depth"] = forward_sectors(
                    *args,
                    info["k"],
                    f["stamp_ns"],
                    f["stamp_ns"],
                    f["frame_id"],
                    sector_config,
                    f["is_bigendian"],
                    R_level_cam=rotation,
                    camera_height_m=height,
                )
        except (OSError, KeyError, ValueError, TypeError) as e:
            reason = f"input_error: {e}"
            errors[reason] += 1
            row["error"] = reason
            if f["role"] == "mono":
                row["line"] = missing_line(reason, f["stamp_ns"])
            else:
                row["depth"] = unknown_depth(reason, sector_config.sectors)
                row.setdefault("depth_valid_fraction", None)
                row.setdefault("leveling", unknown(reason))
                row.setdefault("floor_filter", unknown(reason))
        if f["role"] == "mono":
            if last_stamp is not None and f["stamp_ns"] < last_stamp:
                follower.reset()
                resets += 1
            last_stamp = f["stamp_ns"]
            row["advisory"] = follower.update(row["line"], f["stamp_ns"] / 1e9)
            recent = [r["line"]["detected"] for r in line_rows[-29:]] + [row["line"]["detected"]]
            row["rolling_detection_rate"] = float(np.mean(recent))
            reasons.update(row["line"]["rejection_reasons"])
            line_rows.append(row)
        else:
            row["unknown_sector_fraction"] = (
                sum(not s["observed"] for s in row["depth"]["sectors"]) / sector_config.sectors
            )
            if row["leveling"]["status"] == "UNKNOWN":
                leveling_reasons[row["leveling"]["reason"]] += 1
            if row["floor_filter"]["status"] == "UNKNOWN":
                floor_reasons[row["floor_filter"]["reason"]] += 1
            depth_rows.append(row)

    def mean(values):
        return float(np.mean(values)) if values else None

    summary = {
        "mono_frames": len(line_rows),
        "depth_frames": len(depth_rows),
        "detection_rate": mean([r["line"]["detected"] for r in line_rows]),
        "ambiguity_rate": mean([r["line"]["status"] == "ambiguous" for r in line_rows]),
        "mean_confidence": mean([r["line"]["confidence"] for r in line_rows]),
        "unknown_sector_rate": mean([r["unknown_sector_fraction"] for r in depth_rows]),
        "mean_depth_valid_fraction": mean(
            [r["depth_valid_fraction"] for r in depth_rows if r["depth_valid_fraction"] is not None]
        ),
        "leveled_frames": sum(r["depth"]["leveled"] for r in depth_rows),
        "floor_filtered_frames": sum(
            r["floor_filter"]["status"] == "KNOWN" and "error" not in r for r in depth_rows
        ),
        "line_clock_resets": resets,
        "input_error_count": sum(errors.values()),
    }
    return {
        "schema": "replay.report/1",
        "bag_name": manifest["bag_name"],
        **provenance(),
        "source_kind": manifest.get("source_kind", "UNKNOWN"),
        "manifest_sha256": hashlib.sha256(
            (Path(folder) / "manifest.json").read_bytes()
        ).hexdigest(),
        "export_repo_commit": manifest.get("repo_commit", "UNKNOWN"),
        "export_command": manifest.get("command", "UNKNOWN"),
        "topics": manifest["topics"],
        "summary": summary,
        "config": {
            "line": asdict(line_config),
            "depth": asdict(sector_config),
            "max_sync_ms": max_sync_ms,
        },
        "rejection_reason_counts": dict(reasons),
        "input_errors": dict(errors),
        "leveling_unknown_reasons": dict(leveling_reasons),
        "floor_filter_unknown_reasons": dict(floor_reasons),
        "line_frames": line_rows,
        "depth_frames": depth_rows,
        "thumbnails": thumbs,
        "time_axis": "image header seconds relative to first image stamp; resets may overlap",
        "rolling_detection_window": "last 30 sampled mono frames (or all so far)",
        "freshness": "offline sample evaluation (now=header stamp), not live latency evidence",
        "interpretation": "detection frequency is not accuracy without human labels; line identity unverified",
        "usage": "recordings are for offline tuning only, never an input during a run (rule 6.4)",
        "control_output": "DISABLED",
        "executed": False,
    }


def write_report(folder, out, *, command="UNKNOWN", **options):
    from replay.html_report import render_html

    report = evaluate(folder, **options)
    report["command"] = command
    out = Path(out)
    if out.resolve() == Path(folder).resolve() or Path(folder).resolve() in out.resolve().parents:
        raise ValueError("report output must be separate from source frames")
    out.mkdir(parents=True, exist_ok=False)
    (out / "report.json").write_bytes(json_bytes(report))
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--polarity", choices=["dark", "bright"], default="dark")
    parser.add_argument("--roi-top", type=float, default=0.35)
    parser.add_argument("--contrast-delta", type=float, default=18)
    parser.add_argument("--sectors", type=int, default=7)
    parser.add_argument("--max-range", type=float, default=10)
    parser.add_argument("--max-sync-ms", type=float, default=200)
    args = parser.parse_args(argv)
    try:
        report = write_report(
            args.frames,
            args.out,
            line_config=LineConfig(
                polarity=args.polarity, roi_top=args.roi_top, contrast_delta=args.contrast_delta
            ),
            sector_config=SectorConfig(sectors=args.sectors, max_range_m=args.max_range),
            max_sync_ms=args.max_sync_ms,
            command=shlex.join([sys.executable, "replay/run.py", *(argv or sys.argv[1:])]),
        )
    except (ValueError, OSError) as e:
        parser.exit(2, f"replay failed: {e}\n")
    print(json_bytes(report["summary"]).decode(), end="")
    print(f"Wrote {args.out / 'report.json'} and {args.out / 'report.html'}")


if __name__ == "__main__":
    main()
