"""Portable NPZ packets and a strict JSON manifest; standard library + NumPy."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import numpy as np

SCHEMA = "replay.frames/1"
ROOT = Path(__file__).resolve().parents[1]


def json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False, ensure_ascii=True) + "\n").encode()


def provenance():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "UNKNOWN", None
    return {"repo_commit": commit, "repo_dirty": dirty}


def unknown(reason):
    return {"status": "UNKNOWN", "reason": reason}


class FrameWriter:
    """Bounded, create-only output. max_mb is decimal MB, including the manifest.

    Reserve 8 KiB per packet for association metadata plus 64 KiB globally. Never
    overwrite an existing directory or remove files when a limit is reached.
    """

    def __init__(self, out, manifest, *, max_frames=600, max_mb=300):
        if not isinstance(max_frames, int) or max_frames < 1:
            raise ValueError("max_frames must be a positive integer")
        if not np.isfinite(max_mb) or max_mb <= 0:
            raise ValueError("max_mb must be positive and finite")
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.limit_bytes = int(max_mb * 1_000_000)
        self.max_frames, self.bytes_written = max_frames, 0
        self.doc = {**manifest, "schema": SCHEMA, "frames": [], "limit_reached": None}
        self.doc["limits"] = {"max_frames": max_frames, "max_mb": max_mb}
        self.doc["usage"] = "offline tuning only; never an input during a run (rule 6.4)"

    def add(self, metadata, **arrays):
        if len(self.doc["frames"]) >= self.max_frames:
            self.doc["limit_reached"] = self.doc["limit_reached"] or "max_frames"
            return False
        payload = io.BytesIO()
        np.savez_compressed(payload, metadata=np.array(json.dumps(metadata)), **arrays)
        blob = payload.getvalue()
        reserved = 65536 + 8192 * (len(self.doc["frames"]) + 1)
        if self.bytes_written + len(blob) + reserved > self.limit_bytes:
            self.doc["limit_reached"] = "max_mb"
            return False
        name = f"{len(self.doc['frames']):06d}_{metadata['role']}.npz"
        with (self.out / name).open("xb") as f:
            f.write(blob)
        self.bytes_written += len(blob)
        self.doc["frames"].append(
            {**metadata, "file": name, "sha256": hashlib.sha256(blob).hexdigest()}
        )
        return True

    def finish(self):
        self.doc["npz_bytes"] = self.bytes_written
        blob = json_bytes(self.doc)
        if self.bytes_written + len(blob) > self.limit_bytes:
            raise ValueError("manifest exceeds byte budget; partial NPZ output preserved")
        with (self.out / "manifest.json").open("xb") as f:
            f.write(blob)
        return self.doc


def load_manifest(folder):
    path = Path(folder) / "manifest.json"
    doc = json.loads(path.read_text(), parse_constant=lambda v: invalid_json(v))
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("frames"), list):
        raise ValueError("unsupported frames manifest")
    return doc


def invalid_json(value):
    raise ValueError(f"nonfinite JSON number {value}")


def load_packet(folder, frame):
    root = Path(folder).resolve()
    path = (root / frame["file"]).resolve()
    if path.parent != root or path.suffix != ".npz":
        raise ValueError("packet must be an NPZ directly inside the frames folder")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != frame["sha256"]:
        raise ValueError(f"packet checksum mismatch: {path.name}")
    with np.load(io.BytesIO(blob), allow_pickle=False) as packet:
        metadata = json.loads(str(packet["metadata"]))
        if any(frame.get(k) != v for k, v in metadata.items()):
            raise ValueError("packet metadata disagrees with manifest")
        return {name: packet[name].copy() for name in packet.files if name != "metadata"}
