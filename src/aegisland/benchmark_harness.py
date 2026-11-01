"""Additive offline harness: python -m aegisland.benchmark_harness --help."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import benchmark_adapters as adapters
from .benchmark_contract import (
    ADAPTERS,
    SCHEMA_VERSION,
    finite_tree,
    integer,
    number,
    read_json,
    read_jsonl,
    summarize,
    validate_frames,
    validate_platform,
)
from .trajectory_eval import absolute_trajectory_error, load_euroc_groundtruth, relative_pose_error

REPOSITORY = Path(__file__).resolve().parents[2]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def git(*args):
    process = subprocess.run(
        ["git", "-C", str(REPOSITORY), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return process.stdout.strip()


def environment():
    packages = {}
    for name in ("numpy", "opencv-python", "pytest"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "executable": sys.executable,
        "os": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def host_platform(kind, hardware):
    model = Path("/proc/device-tree/model")
    return validate_platform(
        {
            "kind": kind,
            "hardware": hardware,
            "machine": platform.machine(),
            "device_model": model.read_text().strip("\x00\n")
            if model.is_file()
            else platform.platform(),
        }
    )


def checksum_index(output):
    return {
        p.relative_to(output).as_posix(): sha256(p)
        for p in sorted(output.rglob("*"))
        if p.is_file() and p != output / "SHA256SUMS"
    }


def seal(output):
    with (output / "SHA256SUMS").open("x", encoding="utf-8") as stream:
        for name, digest in checksum_index(output).items():
            stream.write(f"{digest}  {name}\n")


def snapshot(source, output, names):
    """Copy only required original evidence; never edit archived runs."""
    target = output / "source"
    target.mkdir()
    for name in names:
        path = source / name
        if path.is_file():
            shutil.copyfile(path, target / name)
    # Verify original hashes for every ingested artifact if a legacy index exists.
    if (target / "SHA256SUMS").is_file():
        entries = {}
        for line in (target / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            if name in entries:
                raise ValueError("duplicate source SHA256 entry")
            entries[name] = digest
        for path in target.iterdir():
            if path.name != "SHA256SUMS" and entries.get(path.name) != sha256(path):
                raise ValueError(f"source SHA256 mismatch or missing entry: {path.name}")
    return target


def accuracy(rows, adapter, groundtruth, delta, tolerance):
    if not ADAPTERS[adapter]["metric_pose"]:
        return {"ate_se3": None, "rpe": None, "reason": "adapter has no metric localization pose"}
    if groundtruth is None:
        return {
            "ate_se3": None,
            "rpe": None,
            "reason": "no metric body-frame ground truth supplied",
        }
    from .trajectory_eval import Trajectory

    reference = load_euroc_groundtruth(groundtruth)
    if np.any(np.diff(reference.timestamps_s) <= 0):
        raise ValueError("ground-truth timestamps must be strictly increasing; duplicate rejected")
    valid = [row for row in rows if row["pose"] is not None]
    if not valid:
        return {"ate_se3": None, "rpe": None, "reason": "no tracked poses"}
    estimate = Trajectory(
        np.array([r["timestamp_ns"] / 1e9 for r in valid]),
        np.array([r["pose"]["position_m"] for r in valid]),
        np.array([r["pose"]["quaternion_xyzw"] for r in valid]),
    )
    try:
        ate = absolute_trajectory_error(estimate, reference, max_time_difference_s=tolerance)
    except ValueError as exc:
        if "timestamp pairs" not in str(exc):
            raise
        return {"ate_se3": None, "rpe": None, "reason": str(exc)}
    try:
        rpe = relative_pose_error(
            estimate, reference, delta_frames=delta, max_time_difference_s=tolerance
        )
        rpe_reason = None
    except ValueError as exc:
        if "not enough matched frames" not in str(exc):
            raise
        rpe, rpe_reason = None, str(exc)
    return {
        "ate_se3": ate,
        "rpe": rpe,
        "rpe_unavailable_reason": rpe_reason,
        "body_frame": "imu0",
        "alignment": "SE3, no scale correction",
        "max_time_difference_s": tolerance,
        "rpe_delta_frames": delta,
    }


def run(config, command):
    """Every invocation owns a new directory, including validation/dependency failures."""
    root = Path(config["output_root"])
    output = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": output.name,
        "status": "running",
        "executed": False,
        "failure": None,
        "inputs": {},
    }
    write_json(output / "manifest.json", manifest)
    try:
        write_json(output / "config.json", config)
        write_json(output / "command.json", {"argv": command, "cwd": str(Path.cwd())})
        write_json(output / "environment.json", environment())
        write_json(
            output / "revision.json",
            {
                "repository": str(REPOSITORY),
                "head": git("rev-parse", "HEAD"),
                "branch": git("branch", "--show-current"),
                "dirty_state": git("status", "--porcelain"),
                "code_sha256": {
                    str(p.relative_to(REPOSITORY)): sha256(p)
                    for p in sorted((REPOSITORY / "src" / "aegisland").rglob("*.py"))
                },
            },
        )
        adapter = config["adapter"]
        integer(config["expected_frames"], "expected_frames", 1)
        integer(config["warmup_frames"], "warmup_frames")
        integer(config["rpe_delta_frames"], "rpe_delta_frames", 1)
        if number(config["max_time_difference_s"], "max_time_difference_s") <= 0:
            raise ValueError("max_time_difference_s must be positive")
        if adapter not in ADAPTERS:
            raise ValueError("unknown adapter")
        source = config.get("source")
        if source:
            paths = (
                ["frames.jsonl", "metadata.json"]
                if config["format"] == "contract"
                else [
                    "frames.jsonl",
                    "summary.json" if adapter == "ffs-research" else "run.json",
                    "trajectory_body.tum",
                    "gpu_clocks.csv",
                    "SHA256SUMS",
                ]
            )
            original = Path(source).resolve()
            captured = snapshot(original, output, paths)
            manifest["inputs"][str(original)] = checksum_index(captured)
            if config["format"] == "contract":
                rows, info = adapters.recorded(captured, adapter, config["expected_frames"])
            else:
                origin = Path(config["origin_platform"])
                shutil.copyfile(origin, output / "origin-platform.json")
                rows, info = adapters.legacy(
                    captured,
                    adapter,
                    config["expected_frames"],
                    read_json(output / "origin-platform.json"),
                )
            measured_platform = info["origin_platform"]
            manifest["measurement"] = "imported evidence; harness host is not measurement platform"
        else:
            if adapter != "aegisland-vdr":
                raise ValueError(
                    "vendor adapter requires existing source artifacts; no runtime/device run"
                )
            measured_platform = host_platform(config["platform"], config["hardware"])
            if config.get("sequence"):
                images, stamps, inputs = adapters.euroc_inputs(
                    Path(config["sequence"]), config["expected_frames"], config.get("max_frames")
                )
                manifest["inputs"] = {str(p.resolve()): sha256(p) for p in inputs}
            else:
                images, stamps = adapters.synthetic(config["expected_frames"], config["seed"])
                inputs = output / "synthetic-inputs.npz"
                np.savez(inputs, images=np.stack(images), timestamps_ns=np.array(stamps))
                manifest["inputs"][inputs.name] = sha256(inputs)
            if len(images) != config["expected_frames"]:
                raise ValueError("inconsistent input frame count")
            rows, info = adapters.run_vdr(images, stamps)
            # Process high watermark includes Python, imports and input decode; not algorithm-only.
            try:
                import resource

                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                info["memory"].update(
                    peak_ram_bytes=int(peak * (1 if sys.platform == "darwin" else 1024)),
                    ram_scope="harness process lifetime peak RSS, including input decode",
                    vram_scope="not applicable: CPU VDR, no GPU allocation",
                )
            except ImportError:
                pass
            manifest["measurement"] = "native offline replay"
        validate_frames(rows, adapter, config["expected_frames"])
        with (output / "frames.jsonl").open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        groundtruth = None
        if config.get("groundtruth"):
            original = Path(config["groundtruth"])
            groundtruth = output / "groundtruth.csv"
            shutil.copyfile(original, groundtruth)
            manifest["inputs"][str(original.resolve())] = sha256(groundtruth)
        result = {
            "schema_version": SCHEMA_VERSION,
            "adapter": adapter,
            "executed": False,
            "platform": measured_platform,
            "capabilities": ADAPTERS[adapter],
            "metrics": summarize(rows, adapter, config["warmup_frames"], info["wall_s"]),
            "accuracy": accuracy(
                rows,
                adapter,
                groundtruth,
                config["rpe_delta_frames"],
                config["max_time_difference_s"],
            ),
            "memory": info["memory"],
            "latency_scope": info["latency_scope"],
            "valid_for_performance_claims": False,
            "performance_reason": "offline/import smoke: pacing, clock evidence and session repeats "
            "require separate review under the existing benchmark plan",
            "research_only": adapter == "ffs-research",
        }
        finite_tree(result)
        write_json(output / "result.json", result)
        if not any(row["status"] == "ok" for row in rows):
            raise ValueError("no successful output frames")
        if any(row["status"] == "error" for row in rows):
            raise ValueError("adapter reported error frames")
        manifest["status"] = "complete"
    except Exception as exc:  # noqa: BLE001 -- persist failure evidence at the runner boundary
        manifest.update(status="failed", failure={"type": type(exc).__name__, "reason": str(exc)})
    finally:
        manifest["finished_utc"] = datetime.now(UTC).isoformat()
        write_json(output / "manifest.json", manifest)
        seal(output)
    return output, manifest["status"] == "complete"


def verify_run(output):
    """Strict result reader: a failed/unsealed run is never accepted as a benchmark."""
    output = Path(output)
    listed = {}
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if name in listed:
            raise ValueError("duplicate SHA256 entry")
        listed[name] = digest
    if listed != checksum_index(output):
        raise ValueError("SHA256 mismatch or missing artifact")
    manifest, config, result = (
        read_json(output / name) for name in ("manifest.json", "config.json", "result.json")
    )
    if manifest["status"] != "complete" or manifest["executed"] is not False:
        raise ValueError("run did not complete with executed=False")
    if result["schema_version"] != SCHEMA_VERSION or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    if result["executed"] is not False or result["adapter"] != config["adapter"]:
        raise ValueError("result adapter/execution contract mismatch")
    validate_platform(result["platform"])
    rows = read_jsonl(output / "frames.jsonl", config["expected_frames"])
    validate_frames(rows, result["adapter"], config["expected_frames"])
    expected = summarize(
        rows, result["adapter"], config["warmup_frames"], result["metrics"]["fps"]["wall_s"]
    )
    if expected != result["metrics"]:
        raise ValueError("result metrics disagree with raw frame counts or samples")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    verify = sub.add_parser("verify", help="verify hashes, counts and raw result contract")
    verify.add_argument("directory", type=Path)
    replay = sub.add_parser("run", help="native VDR or read-only artifact import")
    replay.add_argument("--adapter", choices=sorted(ADAPTERS), required=True)
    replay.add_argument("--output-root", required=True)
    replay.add_argument("--expected-frames", type=int, required=True)
    replay.add_argument("--warmup-frames", type=int, default=1)
    replay.add_argument("--source", help="existing artifact directory; never modified")
    replay.add_argument("--format", choices=("legacy", "contract"), default="legacy")
    replay.add_argument("--origin-platform", help="legacy import: JSON of original platform")
    replay.add_argument("--platform", choices=("desktop", "orin", "other"))
    replay.add_argument("--hardware", help="native run: measured CPU/GPU model description")
    replay.add_argument(
        "--sequence", help="native VDR: existing EuRoC mav0; otherwise tiny synthetic"
    )
    replay.add_argument("--max-frames", type=int, help="native EuRoC: explicit prefix selection")
    replay.add_argument("--seed", type=int, default=7)
    replay.add_argument("--groundtruth", help="optional EuRoC metric imu0 ground-truth CSV")
    replay.add_argument("--rpe-delta-frames", type=int, default=20)
    replay.add_argument("--max-time-difference-s", type=float, default=0.005)
    args = parser.parse_args(argv)
    if args.operation == "verify":
        try:
            result = verify_run(args.directory)
        except (OSError, ValueError, KeyError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps({"verified": True, "adapter": result["adapter"], "executed": False}))
        return 0
    output, complete = run(
        vars(args),
        [
            sys.executable,
            "-m",
            "aegisland.benchmark_harness",
            *(sys.argv[1:] if argv is None else argv),
        ],
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": "complete" if complete else "failed",
                "executed": False,
            }
        )
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
