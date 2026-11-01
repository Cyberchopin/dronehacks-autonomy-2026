"""Local snapshots and exclusive, sealed evidence directories. No hardware I/O."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .model import sha256, strict_json

MAX_FILE_BYTES = 32 * 1024 * 1024


def read_regular(path: Path) -> bytes:
    # Never open a device, FIFO or symlink supplied as an evidence file.
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Evidence must be a regular file without symlinks: {path}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Evidence changed to a nonregular file while being opened")
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"Evidence file exceeds {MAX_FILE_BYTES} bytes: {path}")
    return data


def relative_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Evidence asset path must be relative")
    parts = Path(name).parts
    if any(part in {"..", "."} for part in parts):
        raise ValueError("Evidence asset path traverses parent directories")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Evidence asset path contains a symlink")
    current.resolve().relative_to(root.resolve())
    return current


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _safe_authority(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"executed", "command_executed"} and item is not False:
                raise ValueError(f"{key} must remain false")
            if key == "authority" and item != "NONE":
                raise ValueError("authority must remain NONE")
            if key == "authority_change" and item != "NONE":
                raise ValueError("authority_change must remain NONE")
            if key == "full_3d_traversability" and item != "UNKNOWN":
                raise ValueError("3D traversability must remain UNKNOWN")
            if key == "supports_3d_traversal" and item is not False:
                raise ValueError("Local evidence cannot support 3D traversal")
            _safe_authority(item)
    elif isinstance(value, list):
        for item in value:
            _safe_authority(item)


def record_run(
    output_root: Path,
    summary: dict,
    sources: dict[str, bytes],
    reports: dict[str, bytes] | None = None,
    run_id: str | None = None,
) -> Path:
    """Exclusive creation; a seal is written last. Failed/incomplete runs never verify."""
    _safe_authority(summary)
    if summary.get("executed") is not False or summary.get("authority") != "NONE":
        raise ValueError("A run summary must explicitly remain executed=False, authority=NONE")
    if "sources" in summary and summary["sources"] != {
        name: sha256(payload) for name, payload in sources.items()
    }:
        raise ValueError("Summary source hashes differ from captured snapshots")
    run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ-") + uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", run_id):
        raise ValueError("Invalid run ID")
    implementation = {
        "executed": False,
        "authority": "NONE",
        "python": sys.version,
        "source_sha256": {
            path.name: sha256(read_regular(path))
            for path in sorted(Path(__file__).parent.glob("*.py"))
        },
        "scope": "Local source-byte identity; not proof of execution or hardware attestation.",
    }
    payloads = {
        "summary.json": json_bytes(summary),
        "implementation.json": json_bytes(implementation),
        **(reports or {}),
    }
    if set(reports or {}) & {"summary.json", "seal.json", "implementation.json"}:
        raise ValueError("Reserved report filename")
    for name, data in sources.items():
        if not isinstance(data, bytes):
            # ValueError, not TypeError: CLI callers catch (OSError, ValueError).
            raise ValueError("Source snapshots must be bytes")  # noqa: TRY004
        payloads["source/" + name] = data
    for name in payloads:
        if (
            Path(name).is_absolute()
            or any(p in {"..", "."} for p in Path(name).parts)
            or not name
            or name == "seal.json"
        ):
            raise ValueError("Unsafe evidence output filename")
    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / run_id
    directory.mkdir(exist_ok=False)  # Never resume, merge or replace a run.
    for name, payload in payloads.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(payload)
    seal = {
        "schema_version": 1,
        "status": "sealed",
        "run_id": run_id,
        "executed": False,
        "authority": "NONE",
        "files": {name: sha256(payload) for name, payload in sorted(payloads.items())},
    }
    with (directory / "seal.json").open("xb") as handle:
        handle.write(json_bytes(seal))
    return directory


def verify_run(directory: Path) -> dict:
    seal = strict_json(read_regular(directory / "seal.json").decode())
    if (
        not isinstance(seal, dict)
        or seal.get("status") != "sealed"
        or seal.get("executed") is not False
        or seal.get("authority") != "NONE"
        or not isinstance(seal.get("files"), dict)
        or "summary.json" not in seal["files"]
    ):
        raise ValueError("Unsealed or malformed evidence directory")
    if (
        type(seal.get("schema_version")) is not int
        or seal["schema_version"] != 1
        or seal.get("run_id") != directory.name
    ):
        raise ValueError("Evidence seal version/run identity mismatch")
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlinks are not sealed evidence")
        if not path.is_dir():
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(seal["files"]) | {"seal.json"}:
        raise ValueError("Evidence inventory differs from seal")
    for name, digest in seal["files"].items():
        if sha256(read_regular(relative_file(directory, name))) != digest:
            raise ValueError(f"Evidence hash mismatch: {name}")
    summary = strict_json(read_regular(directory / "summary.json").decode())
    if not isinstance(summary, dict):
        # ValueError, not TypeError: CLI callers catch (OSError, ValueError).
        raise ValueError("Evidence summary must be an object")  # noqa: TRY004
    _safe_authority(summary)
    if summary.get("executed") is not False or summary.get("authority") != "NONE":
        raise ValueError("Invalid evidence authority boundary")
    if "sources" in summary and summary["sources"] != {
        name.removeprefix("source/"): digest
        for name, digest in seal["files"].items()
        if name.startswith("source/")
    }:
        raise ValueError("Summary source hashes differ from sealed snapshots")
    if summary.get("purpose") == "integration_replay_only":
        from .integration import audit_bundle

        rebuilt, _ = audit_bundle(directory / "source")

        def finding_classes(value: dict) -> list[tuple]:
            if not isinstance(value.get("findings"), list) or not all(
                isinstance(item, dict) for item in value["findings"]
            ):
                raise ValueError("Replay findings must be a list of objects")
            return [
                (item.get("category"), item.get("knowledge"), item.get("record"))
                for item in value.get("findings", [])
            ]

        # OS errors may name different original/snapshot paths. Recompute the
        # evidence classes and references; original diagnostic text is hash-sealed.
        if finding_classes(summary) != finding_classes(rebuilt):
            raise ValueError("Replay evidence disagrees with summary: findings")
        for key in (
            "records_parsed",
            "usable_records",
            "replay_records",
            "geometry",
            "evidence_quality",
            "source_type",
            "sources",
            "origin_environment",
            "hardware_accessed",
            "dependency_audit",
        ):
            if summary.get(key) != rebuilt[key]:
                raise ValueError(f"Replay evidence disagrees with summary: {key}")
    return {
        "status": "observed",
        "detail": "Exact file inventory and SHA-256 match; "
        "authenticity and physical behavior remain unknown.",
        "executed": False,
        "authority": "NONE",
        "files": len(actual),
    }
