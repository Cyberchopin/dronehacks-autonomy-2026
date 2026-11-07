"""Recommend detector settings from offline samples; never write flight configuration."""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay.frames import load_manifest, load_packet
from replay.run import image_args
from vision.floor_line import LineConfig, decode_mono, detect_floor_line


def sweep(
    folder,
    *,
    polarities=("dark", "bright"),
    roi_tops=(0.25, 0.35, 0.45),
    contrast_deltas=(10.0, 18.0, 30.0),
):
    configs = [
        LineConfig(polarity=p, roi_top=r, contrast_delta=d)
        for p, r, d in itertools.product(polarities, roi_tops, contrast_deltas)
    ]
    if not configs or any(
        not np.isfinite(c.contrast_delta) or c.contrast_delta <= 0 for c in configs
    ):
        raise ValueError("nonempty grid and positive finite contrasts required")
    manifest = load_manifest(folder)
    frames = [f for f in manifest["frames"] if f["role"] == "mono"]
    if not frames:
        raise ValueError("no mono frames; detection ranking UNKNOWN")
    stats = [dict(detected=0, ambiguous=0, confidence=0.0) for _ in configs]
    errors = 0
    # One packet in memory at a time; apply the whole grid before loading the next.
    for f in frames:
        try:
            gray = decode_mono(
                *image_args(f, load_packet(folder, f)), is_bigendian=f["is_bigendian"]
            )
        except (ValueError, OSError, KeyError, TypeError):
            errors += 1
            continue
        for c, stat in zip(configs, stats, strict=True):
            line = detect_floor_line(gray, c)
            stat["detected"] += line["detected"]
            stat["ambiguous"] += line["status"] == "ambiguous"
            stat["confidence"] += line["confidence"]
    results = []
    for c, stat in zip(configs, stats, strict=True):
        detection, ambiguity = stat["detected"] / len(frames), stat["ambiguous"] / len(frames)
        results.append(
            {
                "polarity": c.polarity,
                "roi_top": c.roi_top,
                "contrast_delta": c.contrast_delta,
                "detection_rate": detection,
                "ambiguity_rate": ambiguity,
                "mean_confidence": stat["confidence"] / len(frames),
                "score": detection * (1 - ambiguity),
                "frames": len(frames),
                "input_errors": errors,
            }
        )
    return sorted(
        results,
        key=lambda r: (
            -r["score"],
            r["ambiguity_rate"],
            -r["mean_confidence"],
            r["polarity"],
            r["roi_top"],
            r["contrast_delta"],
        ),
    )


def format_table(rows):
    lines = ["rank polarity roi_top contrast detection ambiguity score errors"]
    lines.extend(
        f"{i:>4} {r['polarity']:>8} {r['roi_top']:>7.2f} {r['contrast_delta']:>8.1f} "
        f"{r['detection_rate']:>9.3f} {r['ambiguity_rate']:>9.3f} {r['score']:>5.3f} {r['input_errors']:>6}"
        for i, r in enumerate(rows, 1)
    )
    lines.append(
        "Recommendation only: score = detection * (1 - ambiguity). Detection is not accuracy."
    )
    lines.append("Inspect thumbnails and negative scenes; no flight-time configuration written.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path)
    parser.add_argument(
        "--polarities", nargs="+", choices=["dark", "bright"], default=["dark", "bright"]
    )
    parser.add_argument("--roi-tops", nargs="+", type=float, default=[0.25, 0.35, 0.45])
    parser.add_argument("--contrast-deltas", nargs="+", type=float, default=[10.0, 18.0, 30.0])
    args = parser.parse_args(argv)
    try:
        rows = sweep(
            args.frames,
            polarities=args.polarities,
            roi_tops=args.roi_tops,
            contrast_deltas=args.contrast_deltas,
        )
    except (ValueError, OSError) as e:
        parser.exit(2, f"sweep failed: {e}\n")
    print(format_table(rows))


if __name__ == "__main__":
    main()
