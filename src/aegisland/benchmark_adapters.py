"""Offline adapters. Vendor runtimes stay in their existing isolated environments."""

from __future__ import annotations

import csv
import time

import numpy as np

from .benchmark_contract import (
    integer,
    number,
    read_json,
    read_jsonl,
    timestamps,
    validate_frames,
    validate_platform,
)
from .trajectory_eval import load_tum


def frame(timestamp, status, latency=None, reason=None, **extra):
    return {
        "timestamp_ns": timestamp,
        "status": status,
        "latency_ms": latency,
        "failure_reason": reason,
        "executed": False,
        "pose": None,
        "coverage": None,
        **extra,
    }


def unavailable_memory():
    return {
        "peak_ram_bytes": None,
        "peak_vram_bytes": None,
        "ram_scope": "unavailable: original process peak RSS was not recorded",
        "vram_scope": "unavailable: original device/process peak was not recorded",
    }


def checked_trajectory(path):
    trajectory = load_tum(path)
    if np.any(np.diff(trajectory.timestamps_s) <= 0):
        raise ValueError("trajectory timestamps must be strictly increasing; duplicate rejected")
    return trajectory


def legacy(source, adapter, expected_frames, origin_platform):
    """Read snapshots only. No legacy script is imported or executed."""
    origin_platform = validate_platform(origin_platform)
    summary_path = source / ("summary.json" if adapter == "ffs-research" else "run.json")
    metadata = read_json(summary_path)
    rows = read_jsonl(source / "frames.jsonl", expected_frames)
    if any(row.get("executed", False) is not False for row in rows):
        raise ValueError("legacy frames must have executed=False when present")
    # Prevent relabelling archived x86/WSL measurements as an Orin run.
    origin_description = str(metadata.get("platform", "")).lower()
    if origin_platform["kind"] == "orin" and any(
        name in origin_description for name in ("x86", "amd64", "wsl")
    ):
        raise ValueError("legacy origin is desktop != Orin")
    wall_s, memory = None, unavailable_memory()
    converted = []
    if adapter.startswith("cuvslam-"):
        if metadata["mode"] != adapter.removeprefix("cuvslam-"):
            raise ValueError("cuVSLAM mode disagrees with adapter")
        counts = metadata["counts"]
        if integer(counts["stereo_frames"], "stereo_frames", 1) != expected_frames:
            raise ValueError("inconsistent frame count in cuVSLAM summary")
        if any(type(r["tracked"]) is not bool for r in rows):
            raise ValueError("tracked must be boolean")
        tracked = sum(r["tracked"] for r in rows)
        if (
            integer(counts["tracked_frames"], "tracked_frames") != tracked
            or integer(counts["untracked_frames"], "untracked_frames") != expected_frames - tracked
        ):
            raise ValueError("inconsistent tracked frame counts")
        poses = checked_trajectory(source / "trajectory_body.tum") if tracked else None
        if (
            not tracked
            and (source / "trajectory_body.tum").is_file()
            and any(
                line.strip() and not line.lstrip().startswith("#")
                for line in (source / "trajectory_body.tum").read_text().splitlines()
            )
        ):
            raise ValueError("inconsistent trajectory frame count: poses without tracked frames")
        if poses is not None and len(poses.timestamps_s) != tracked:
            raise ValueError("inconsistent trajectory frame count")
        pose_index = 0
        for row in rows:
            pose = None
            if row["tracked"]:
                if abs(poses.timestamps_s[pose_index] - row["timestamp_ns"] / 1e9) > 1e-6:
                    raise ValueError("trajectory timestamp disagrees with tracked frame")
                pose = {
                    "position_m": poses.positions_m[pose_index].tolist(),
                    "quaternion_xyzw": poses.quaternions_xyzw[pose_index].tolist(),
                }
                pose_index += 1
            converted.append(
                frame(
                    row["timestamp_ns"],
                    "ok" if row["tracked"] else "lost",
                    number(row["track_ms"], "track_ms"),
                    None if row["tracked"] else "tracker_returned_no_pose",
                    pose=pose,
                )
            )
        wall_s = metadata["timing"].get("total_wall_s")
        scope = "Tracker.track host wall time, includes upload, excludes image decode"
    elif adapter == "aegisland-vdr":
        if integer(metadata["counts"]["frames"], "frames", 1) != expected_frames:
            raise ValueError("inconsistent VDR frame count")
        if any(type(r["valid"]) is not bool for r in rows):
            raise ValueError("VDR valid must be boolean")
        if integer(metadata["counts"]["valid"], "valid") != sum(r["valid"] for r in rows):
            raise ValueError("inconsistent VDR valid frame count")
        for row in rows:
            converted.append(
                frame(
                    row["timestamp_ns"],
                    "ok" if row["valid"] else "lost",
                    reason=None if row["valid"] else "vdr_invalid_or_initializing",
                    normalized_xy=[row["x_normalized"], row["y_normalized"]],
                )
            )
        scope = "unavailable: legacy VDR has aggregate timing only; cannot reconstruct tails"
    elif adapter == "ffs-research":
        if integer(metadata["frames"], "frames", 1) != expected_frames:
            raise ValueError("inconsistent FFS frame count")
        for row in rows:
            invalid = number(row["ffs_invalid_fraction"], "ffs_invalid_fraction")
            if invalid > 1:
                raise ValueError("invalid pixel fraction must be <= 1")
            latency = sum(
                number(row[key], key)
                for key in ("ffs_rectify_ms", "ffs_upload_pad_ms", "ffs_model_ms", "ffs_post_ms")
            )
            converted.append(frame(row["timestamp_ns"], "ok", latency, coverage=1 - invalid))
        if metadata.get("peak_cuda_memory_mb") is not None:
            memory.update(
                peak_vram_bytes=int(
                    number(metadata["peak_cuda_memory_mb"], "peak_cuda_memory_mb") * 2**20
                ),
                vram_scope="torch.cuda.max_memory_allocated; allocator only, excludes reserved/driver",
            )
        scope = "rectify + upload/pad + synchronized model + post; excludes decode and LR repeat"
    else:
        raise ValueError("no legacy per-frame adapter; use contract format for OAK/DepthAI")
    validate_frames(converted, adapter, expected_frames)
    return converted, {
        "wall_s": wall_s,
        "memory": memory,
        "latency_scope": scope,
        "origin_platform": origin_platform,
        "origin_metadata": metadata,
    }


def recorded(source, adapter, expected_frames):
    """Canonical producer interface, including recorded OAK/DepthAI StereoDepth output."""
    metadata = read_json(source / "metadata.json")
    if metadata.get("schema_version") != 1 or metadata.get("executed") is not False:
        raise ValueError("producer schema_version=1 and executed=False required")
    if (
        metadata["adapter"] != adapter
        or integer(metadata["expected_frames"], "expected_frames", 1) != expected_frames
    ):
        raise ValueError("inconsistent adapter or frame count in producer metadata")
    validate_platform(metadata["platform"])
    for name in ("latency_scope", "head"):
        if not isinstance(metadata.get(name), str) or not metadata[name].strip():
            raise ValueError(f"producer {name} required")
    if not isinstance(metadata.get("environment"), dict):
        raise ValueError("producer environment required")  # noqa: TRY004 -- contract validation
    if not isinstance(metadata.get("command"), list) or not metadata["command"]:
        raise ValueError("producer command argv required")
    schedule = timestamps(metadata["timestamps_ns"])
    rows = read_jsonl(source / "frames.jsonl", expected_frames)
    if [r["timestamp_ns"] for r in rows] != schedule:
        raise ValueError("frame timestamps disagree with expected producer schedule")
    validate_frames(rows, adapter, expected_frames)
    memory = metadata.get("memory", unavailable_memory())
    for name in ("peak_ram_bytes", "peak_vram_bytes"):
        if memory.get(name) is not None:
            integer(memory[name], name)
    for name in ("ram_scope", "vram_scope"):
        if not isinstance(memory.get(name), str) or not memory[name].strip():
            raise ValueError(f"memory.{name} required")
    return rows, {
        "wall_s": metadata.get("wall_s"),
        "memory": memory,
        "latency_scope": metadata["latency_scope"],
        "origin_platform": metadata["platform"],
        "origin_metadata": metadata,
    }


def synthetic(count=8, seed=7):
    """Small translated texture, no physical scale or ground-truth trajectory."""
    integer(count, "synthetic frame count", 1)
    texture = np.random.default_rng(seed).integers(0, 256, (120, 160), dtype=np.uint8)
    images = [np.roll(texture, i, axis=1) for i in range(count)]
    return images, [i * 50_000_000 for i in range(count)]


def euroc_inputs(sequence, expected_frames, max_frames=None):
    import cv2

    stamps, images, paths, selected = [], [], [sequence / "cam0" / "data.csv"], []
    with paths[0].open(encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if not row or row[0].lstrip().startswith("#"):
                continue
            selected.append((int(row[0]), sequence / "cam0" / "data" / row[1].strip()))
    if max_frames is not None:
        integer(max_frames, "max_frames", 1)
        selected = selected[:max_frames]
    if len(selected) != expected_frames:
        raise ValueError("inconsistent input frame count")
    for timestamp, path in selected:
        stamps.append(timestamp)
        paths.append(path)
    timestamps(stamps)
    for path in paths[1:]:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"cannot decode input: {path}")
        images.append(image)
    return images, stamps, paths


def run_vdr(images, stamps):
    import cv2

    from .gps_denied import VisualDeadReckoner
    from .motion_compensation import CameraMotionCompensator

    if len(images) != len(stamps) or not images:
        raise ValueError("inconsistent or empty VDR input frame count")
    timestamps(stamps)
    previous_threads = cv2.getNumThreads()
    rows = []
    try:
        cv2.setNumThreads(1)
        compensator, reckoner = CameraMotionCompensator(), VisualDeadReckoner()
        started = time.perf_counter()
        for index, (image, timestamp) in enumerate(zip(images, stamps)):
            call_start = time.perf_counter()
            if index:
                result = compensator.compensate(images[index - 1], image)
                pose = reckoner.update(
                    homography=result.homography if result.success else None,
                    image_shape=image.shape,
                    inlier_ratio=result.inlier_ratio,
                )
            else:
                pose = reckoner.current()
            elapsed_ms = (time.perf_counter() - call_start) * 1000
            rows.append(
                frame(
                    timestamp,
                    "ok" if pose.valid else "lost",
                    elapsed_ms,
                    None if pose.valid else "vdr_invalid_or_initializing",
                    normalized_xy=[pose.x, pose.y],
                )
            )
        wall_s = time.perf_counter() - started
    finally:
        cv2.setNumThreads(previous_threads)
    return rows, {
        "wall_s": wall_s,
        "memory": unavailable_memory(),
        "latency_scope": "compensate + update (first frame: current), excludes decode/init",
    }
