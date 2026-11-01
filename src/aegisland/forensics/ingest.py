"""Local file readers. PX4 decoding is delegated to PyULog, never MAVLink."""

from __future__ import annotations

import io
import re
import struct
from contextlib import redirect_stdout
from pathlib import Path

from .model import (
    JETSON_CLOCK,
    PX4_CLOCK,
    Ingestion,
    Sample,
    finite,
    integer,
    read_snapshot,
    strict_json,
)

JETSON_FIELDS = {
    "schema_version",
    "clock",
    "timestamp",
    "frame_id",
    "depth_coverage",
    "invalid_depth_ratio",
    "line_confidence",
    "obstacle_distance_m",
    "mode",
    "decision",
    "latency_ms",
    "dropped_frame",
    "source_hashes",
    "executed",
}
HASH = re.compile(r"[0-9a-f]{64}\Z")
# Deliberately omit positions, maps, mission items and setpoints from report data.
TOPICS = {
    "vehicle_local_position": ("xy_valid", "z_valid", "v_xy_valid", "v_z_valid"),
    "vehicle_status": ("nav_state", "failsafe"),
    "actuator_motors": tuple(f"control[{i}]" for i in range(12)),
}


def jetson_errors(row: object) -> list[str]:
    if not isinstance(row, dict):
        return ["record must be an object"]
    errors = [f"missing {name}" for name in sorted(JETSON_FIELDS - row.keys())]
    if row.get("schema_version") != 1 or type(row.get("schema_version")) is not int:
        errors.append("schema_version must be integer 1")
    if row.get("clock") != JETSON_CLOCK:
        errors.append(f"clock must be {JETSON_CLOCK}")
    if row.get("executed") is not False:
        errors.append("executed must be literal false (analysis boundary)")
    for name in ("timestamp", "frame_id"):
        if not integer(row.get(name)):
            errors.append(f"{name} must be a nonnegative signed-64-bit integer")
    for name in ("depth_coverage", "invalid_depth_ratio", "line_confidence"):
        value = row.get(name)
        if value is not None and (not finite(value) or not 0 <= value <= 1):
            errors.append(f"{name} must be null or finite in [0,1]")
    for name in ("latency_ms", "obstacle_distance_m"):
        value = row.get(name)
        if value is not None and (not finite(value) or not 0 <= value <= 1e12):
            errors.append(f"{name} must be null or finite in [0,1e12]")
    for name in ("mode", "decision"):
        value = row.get(name)
        if not isinstance(value, str) or not value or len(value) > 256:
            errors.append(f"{name} must be a nonempty string (max 256)")
    if type(row.get("dropped_frame")) is not bool:
        errors.append("dropped_frame must be boolean for this record")
    hashes = row.get("source_hashes")
    if (
        not isinstance(hashes, dict)
        or not hashes
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not HASH.fullmatch(v)
            for k, v in hashes.items()
        )
    ):
        errors.append("source_hashes must be a nonempty name: lowercase SHA-256 object")
    if "tracking_valid" in row and type(row["tracking_valid"]) is not bool:
        errors.append("tracking_valid must be boolean when present")
    if row.keys() - JETSON_FIELDS - {"tracking_valid"}:
        errors.append("unsupported fields; schema is closed")
    return errors


def ingest_jetson(path: Path | None) -> Ingestion:
    result = Ingestion("jetson", parser="strict-jsonl-v1")
    if path is None:
        result.issue("missing_input", "No Jetson log supplied.")
        return result
    data = read_snapshot(path, result)
    if data is None:
        return result
    for line_number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = strict_json(line.decode("utf-8"))
            errors = jetson_errors(row)
        except (ValueError, UnicodeError, RecursionError) as error:
            result.issue("corrupt_record", str(error), index=line_number)
            continue
        if errors:
            result.issue("invalid_record", "; ".join(errors), index=line_number)
            continue
        values = {k: v for k, v in row.items() if k not in {"timestamp", "clock", "executed"}}
        result.samples.append(
            Sample("jetson", "perception", line_number, row["timestamp"], JETSON_CLOCK, values)
        )
        missing = [
            name
            for name in (
                "depth_coverage",
                "invalid_depth_ratio",
                "line_confidence",
                "obstacle_distance_m",
                "latency_ms",
            )
            if row[name] is None
        ]
        if missing:
            result.issue(
                "unknown_measurement",
                "Null measurements: " + ", ".join(missing),
                index=line_number,
                stream="perception",
            )
    if not result.samples:
        result.issue("no_samples", "No valid Jetson records; absence of findings is not health.")
    return result


def _framed_prefix(data: bytes, result: Ingestion) -> bytes | None:
    if len(data) < 16 or data[:7] != b"ULog\x01\x12\x35":
        result.issue("corrupt_log", "Invalid or truncated ULog header.")
        return None
    if data[7] != 1:
        result.issue(
            "unsupported_format", f"ULog version {data[7]} is not validated by this reader."
        )
    # A framing check complements PyULog, which can tolerate a truncated tail.
    offset = 16
    while offset < len(data):
        if len(data) - offset < 3:
            result.issue("corrupt_log", f"Truncated ULog record header at byte {offset}.")
            return data[:offset]
        size = struct.unpack_from("<H", data, offset)[0]
        end = offset + 3 + size
        if end > len(data):
            result.issue("corrupt_log", f"Truncated ULog record payload at byte {offset}.")
            return data[:offset]
        kind = chr(data[offset + 2])
        minimum = {
            "A": 4,
            "D": 2,
            "R": 2,
            "O": 2,
            "S": 8,
            "L": 9,
            "C": 11,
            "I": 2,
            "M": 3,
            "P": 2,
            "Q": 3,
            "F": 3,
            "B": 40,
        }.get(kind, 0)
        if size < minimum:
            result.issue("corrupt_log", f"ULog {kind} record too short at byte {offset}.")
            return data[:offset]
        offset = end
    return data


def ingest_px4(path: Path | None) -> Ingestion:
    result = Ingestion("px4", parser="PyULog")
    if path is None:
        result.issue("missing_input", "No PX4 log supplied.")
        return result
    data = read_snapshot(path, result)
    if data is None:
        return result
    framed = _framed_prefix(data, result)
    if framed is None:
        return result
    try:
        from importlib.metadata import version

        from pyulog import ULog

        result.metadata["pyulog_version"] = version("pyulog")
    except ImportError:
        result.issue(
            "missing_dependency", "Install requirements-forensics.txt into this worktree .venv."
        )
        return result
    try:
        # Capture parser diagnostics so stdout remains a machine-readable CLI result.
        diagnostics = io.StringIO()
        with redirect_stdout(diagnostics):
            ulog = ULog(
                io.BytesIO(framed),
                message_name_filter_list=list(TOPICS),
                disable_str_exceptions=False,
            )
        if ulog.file_corruption:
            result.issue("corrupt_log", "PyULog reported file corruption; recovered samples only.")
        if diagnostics.getvalue():
            result.metadata["parser_diagnostics"] = diagnostics.getvalue()[:2000]
        result.metadata["synthetic_marker"] = ulog.msg_info_dict.get("forensics_fixture")
        result.metadata["topics"] = []
        for dataset in ulog.data_list:
            if dataset.name not in TOPICS:
                continue
            stream = f"{dataset.name}[{dataset.multi_id}]"
            result.metadata["topics"].append(stream)
            fields = dataset.data
            if "timestamp" not in fields:
                result.issue("missing_field", "Topic lacks timestamp.", stream=stream)
                continue
            selected = [name for name in TOPICS[dataset.name] if name in fields]
            if not selected:
                result.issue(
                    "missing_field", "No supported diagnostic fields in topic.", stream=stream
                )
            required = TOPICS[dataset.name] if dataset.name != "actuator_motors" else ()
            missing = set(required) - fields.keys()
            if missing:
                result.issue(
                    "missing_field", "Missing fields: " + ", ".join(sorted(missing)), stream=stream
                )
            for index, timestamp in enumerate(fields["timestamp"]):
                raw_time = timestamp.item()
                stamp = raw_time if integer(raw_time) else None
                if stamp is None:
                    result.issue(
                        "invalid_timestamp",
                        "PX4 boot timestamp is not an integer.",
                        index=index,
                        stream=stream,
                    )
                values = {}
                for name in selected:
                    raw = fields[name][index].item()
                    if not finite(raw):
                        result.issue(
                            "nonfinite_value",
                            f"{name} is non-finite; treated as unknown.",
                            index=index,
                            stream=stream,
                        )
                        values[name] = None
                    elif (name.endswith("_valid") or name == "failsafe") and raw not in (0, 1):
                        result.issue(
                            "invalid_value", f"{name} must be 0 or 1.", index=index, stream=stream
                        )
                        values[name] = None
                    elif name.startswith("control[") and not -1 <= raw <= 1:
                        result.issue(
                            "invalid_value",
                            f"{name} outside normalized [-1,1].",
                            index=index,
                            stream=stream,
                        )
                        values[name] = None
                    else:
                        values[name] = raw
                result.samples.append(Sample("px4", stream, index, stamp, PX4_CLOCK, values))
        result.metadata["ulog_dropouts"] = len(ulog.dropouts)
        for dropout in ulog.dropouts:
            result.issue(
                "log_dropout",
                f"ULog dropout duration_ms={dropout.duration}; "
                "this is logger loss, not proof of camera frame loss.",
                knowledge="observed",
            )
    except Exception as error:  # noqa: BLE001 - see reason below
        # PyULog may raise struct/NumPy/version-specific exceptions on damaged data.
        # Retain already recovered rows and make incompleteness explicit.
        result.issue(
            "corrupt_log", f"PyULog could not fully decode: {type(error).__name__}: {error}"
        )
    if not result.samples:
        result.issue("no_samples", "No supported PX4 samples; real behavior is unknown.")
    return result
