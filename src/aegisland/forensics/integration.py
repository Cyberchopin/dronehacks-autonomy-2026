"""Replay-only OAK / PX4 / VL53L1X / advisory integration contracts.

No hardware library is imported. Validation can only reduce evidence quality;
authority remains NONE even for perfectly consistent synthetic observations.
"""

from __future__ import annotations

import html
import io
import math
import zipfile
from itertools import pairwise
from pathlib import Path

from .ingest import HASH
from .model import finite, integer, sha256, strict_json
from .platform_manifest import ENVIRONMENTS, platform_manifest
from .recorder import MAX_FILE_BYTES, json_bytes, read_regular, relative_file
from .scope import UNASSESSED, geometry_boundary

STREAMS = ("oak_rgb_depth", "px4_telemetry", "vl53l1x_downward", "perception_advisory")
CLOCKS = {"oak_device", "px4_boot", "jetson_monotonic", "vl53_monotonic", "replay"}
COMMON = {
    "schema_version",
    "stream",
    "timestamp_ns",
    "clock_domain",
    "evaluated_at_ns",
    "evaluation_clock_domain",
    "frame_id",
    "calibration_id",
    "transform_id",
    "executed",
    "data",
}
DATA_FIELDS = {
    "oak_rgb_depth": {"asset", "sha256", "encoding", "camera_view", "comparison_target"},
    "px4_telemetry": {
        "quaternion_wxyz",
        "attitude_frame",
        "battery_voltage_v",
        "local_position_valid",
        "failsafe",
        "nav_state",
    },
    "vl53l1x_downward": {"range_m", "range_status", "sigma_m", "mount", "comparison_target"},
    "perception_advisory": {
        "source_frame_id",
        "source_frame_sha256",
        "configuration_sha256",
        "state",
        "confidence",
        "rejection_reasons",
        "advisory_only",
        "control_output",
        "command_executed",
        "authority_change",
        "local_sensing_planes",
    },
}


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(detail)


def vector(value: object, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(finite(v) for v in value)


def quaternion(value: object) -> bool:
    return (
        vector(value, 4)
        and all(abs(v) <= 1 for v in value)
        and abs(sum(v * v for v in value) - 1) <= 1e-3
    )


def calibration_valid(calibration: object) -> bool:
    if not isinstance(calibration, dict) or calibration.get("sensor") not in STREAMS:
        return False
    if calibration["sensor"] != "oak_rgb_depth":
        return calibration.get("unit") == "m" and calibration.get("provenance") in {
            "synthetic",
            "recording",
        }
    intrinsics = calibration.get("intrinsics")
    return (
        integer(calibration.get("width"))
        and integer(calibration.get("height"))
        and 2 <= calibration["width"] <= 4096
        and 2 <= calibration["height"] <= 4096
        and vector(intrinsics, 4)
        and min(intrinsics[:2]) > 0
        and 0 <= intrinsics[2] < calibration["width"]
        and 0 <= intrinsics[3] < calibration["height"]
        and calibration.get("unit") == "m"
        and calibration.get("depth_semantics") == "optical_axis_z"
        and calibration.get("provenance") in {"synthetic", "recording"}
    )


def transform_valid(transform: object) -> bool:
    return (
        isinstance(transform, dict)
        and transform.get("parent") == "body_frd"
        and isinstance(transform.get("child"), str)
        and bool(transform["child"])
        and transform["child"] != transform["parent"]
        and transform.get("convention") == "parent_from_child"
        and vector(transform.get("translation_m"), 3)
        and quaternion(transform.get("quaternion_xyzw"))
        and isinstance(transform.get("calibration_id"), str)
        and transform.get("provenance") in {"synthetic", "recording"}
    )


def validate_record(row: object) -> None:
    require(
        isinstance(row, dict) and set(row) == COMMON, "Record fields differ from replay v1 contract"
    )
    require(
        type(row["schema_version"]) is int and row["schema_version"] == 1, "Invalid schema version"
    )
    require(row["executed"] is False, "executed must be literal false")
    require(isinstance(row["stream"], str) and row["stream"] in STREAMS, "Unsupported stream")
    require(
        isinstance(row["clock_domain"], str) and row["clock_domain"] in CLOCKS,
        "Unknown clock domain",
    )
    require(
        isinstance(row["evaluation_clock_domain"], str)
        and row["evaluation_clock_domain"] in CLOCKS,
        "Unknown evaluation clock domain",
    )
    require(
        all(integer(row[key]) for key in ("timestamp_ns", "evaluated_at_ns", "frame_id")),
        "Timestamps and frame ID must be nonnegative signed-64-bit integers",
    )
    require(
        all(
            value is None or isinstance(value, str) and bool(value)
            for value in (row["calibration_id"], row["transform_id"])
        ),
        "Invalid calibration/transform ID",
    )
    data, stream = row["data"], row["stream"]
    require(
        isinstance(data, dict) and set(data) == DATA_FIELDS[stream], "Invalid stream payload fields"
    )
    if stream == "oak_rgb_depth":
        require(isinstance(data["asset"], str) and bool(data["asset"]), "Missing frame asset")
        require(
            isinstance(data["sha256"], str) and bool(HASH.fullmatch(data["sha256"])),
            "Invalid asset hash",
        )
        require(
            data["encoding"] in ("RGB8", "BGR8") and data["camera_view"] in ("forward", "downward"),
            "Explicit encoding and camera view required",
        )
        require(
            data["comparison_target"] is None or isinstance(data["comparison_target"], str),
            "Invalid target",
        )
    elif stream == "px4_telemetry":
        require(
            row["calibration_id"] is None and row["transform_id"] is None,
            "PX4 telemetry must use its explicit standardized attitude convention, not camera transforms",
        )
        require(
            quaternion(data["quaternion_wxyz"]),
            "PX4 attitude requires normalized finite wxyz quaternion",
        )
        require(data["attitude_frame"] == "ned_from_frd", "Unknown PX4 attitude convention")
        require(
            data["battery_voltage_v"] is None
            or finite(data["battery_voltage_v"])
            and 0 < data["battery_voltage_v"] < 1000,
            "Invalid battery voltage",
        )
        require(
            all(
                value is None or type(value) is bool
                for value in (data["local_position_valid"], data["failsafe"])
            ),
            "Invalid telemetry validity flags",
        )
        require(
            data["nav_state"] is None or integer(data["nav_state"]) and data["nav_state"] <= 255,
            "Invalid recorded navigation state",
        )
    elif stream == "vl53l1x_downward":
        require(
            data["mount"] == "downward" and data["range_status"] in ("valid", "invalid", "unknown"),
            "VL53L1X requires explicit downward mount and range status",
        )
        require(
            data["range_m"] is None or finite(data["range_m"]) and 0 < data["range_m"] <= 10,
            "VL53L1X distance must be finite metres in (0,10] or null",
        )
        require(
            data["sigma_m"] is None or finite(data["sigma_m"]) and 0 <= data["sigma_m"] <= 10,
            "Invalid range uncertainty",
        )
        require(
            data["range_status"] != "valid" or data["range_m"] is not None,
            "Valid range missing value",
        )
        require(
            data["comparison_target"] is None or isinstance(data["comparison_target"], str),
            "Invalid target",
        )
    else:
        require(integer(data["source_frame_id"]), "Advisory source frame ID required")
        require(
            all(
                isinstance(data[key], str) and bool(HASH.fullmatch(data[key]))
                for key in ("source_frame_sha256", "configuration_sha256")
            ),
            "Invalid advisory hash",
        )
        require(
            data["advisory_only"] is True
            and data["control_output"] == "DISABLED"
            and data["command_executed"] is False
            and data["authority_change"] == "NONE",
            "Advisory attempted to cross the authority boundary",
        )
        require(isinstance(data["state"], str) and bool(data["state"]), "Missing advisory state")
        require(
            finite(data["confidence"]) and 0 <= data["confidence"] <= 1,
            "Invalid advisory confidence",
        )
        require(
            isinstance(data["rejection_reasons"], list)
            and all(isinstance(reason, str) for reason in data["rejection_reasons"]),
            "Invalid rejection list",
        )
        require(
            isinstance(data["local_sensing_planes"], list),
            "Explicit local sensing plane list required",
        )
        for plane in data["local_sensing_planes"]:
            validate_local_plane(plane)


def validate_local_plane(plane: object) -> None:
    fields = {
        "evidence_path",
        "scope",
        "supported_meaning",
        "local_plane_supported",
        "full_3d_traversability",
        "supports_3d_traversal",
        "probe_z_m",
        "width_at_probe_m",
        "sampled_bbox_normalized",
        "unassessed",
        "executed",
        "authority_change",
        "rejection_reasons",
        "rgb_depth_consistency",
    }
    require(isinstance(plane, dict) and set(plane) == fields, "Invalid local sensing plane fields")
    require(
        plane["scope"] == "local_camera_z_probe_plane"
        and plane["supported_meaning"] == "observed_local_plane_width_only",
        "Local plane scope must not become volume or path support",
    )
    require(
        plane["full_3d_traversability"] == "UNKNOWN"
        and plane["supports_3d_traversal"] is False
        and plane["executed"] is False
        and plane["authority_change"] == "NONE",
        "3D traversability must remain UNKNOWN; execution/authority disabled",
    )
    require(type(plane["local_plane_supported"]) is bool, "Local support must be boolean")
    require(
        isinstance(plane["evidence_path"], str) and bool(plane["evidence_path"]),
        "Plane origin reference required",
    )
    require(
        isinstance(plane["unassessed"], list)
        and all(isinstance(v, str) for v in plane["unassessed"])
        and set(UNASSESSED) <= set(plane["unassessed"]),
        "Unassessed ROI/volume/dynamics limits must survive",
    )
    require(
        isinstance(plane["rejection_reasons"], list)
        and all(isinstance(v, str) for v in plane["rejection_reasons"]),
        "Plane rejection reasons required",
    )
    require(
        plane["rgb_depth_consistency"] in ("unverified", "ambiguous"),
        "RGB/depth consistency unverified",
    )
    for name in ("probe_z_m", "width_at_probe_m"):
        require(
            plane[name] is None or finite(plane[name]) and 0 <= plane[name] <= 1e4,
            "Plane measurements must be finite metres or null",
        )
    roi = plane["sampled_bbox_normalized"]
    require(
        roi is None
        or vector(roi, 4)
        and all(0 <= v <= 1 for v in roi)
        and roi[2] > 0
        and roi[3] > 0
        and roi[0] + roi[2] <= 1
        and roi[1] + roi[3] <= 1,
        "Invalid sampled plane ROI",
    )
    if plane["local_plane_supported"]:
        require(
            plane["probe_z_m"] is not None
            and plane["probe_z_m"] > 0
            and plane["width_at_probe_m"] is not None
            and roi is not None
            and not plane["rejection_reasons"]
            and plane["rgb_depth_consistency"] != "ambiguous",
            "Local support cannot ignore missing geometry, conflict or rejection reasons",
        )


def load_frame(payload: bytes, calibration: dict) -> float | None:
    """Inspect recorded NPZ arrays, never unpickle or run a camera pipeline."""
    import numpy as np

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        require(
            len(archive.infolist()) == 3
            and sum(i.file_size for i in archive.infolist()) <= MAX_FILE_BYTES,
            "Oversize or unsupported frame archive",
        )
    with np.load(io.BytesIO(payload), allow_pickle=False) as frame:
        require(
            set(frame.files) == {"rgb", "depth_m", "valid"}, "Frame needs rgb/depth_m/valid arrays"
        )
        rgb, depth, valid = frame["rgb"], frame["depth_m"], frame["valid"]
        shape = (calibration["height"], calibration["width"])
        require(
            rgb.dtype == np.uint8 and rgb.shape == (*shape, 3),
            "RGB shape/dtype/calibration mismatch",
        )
        require(
            depth.dtype.kind == "f"
            and depth.shape == shape
            and valid.dtype == bool
            and valid.shape == shape,
            "Aligned depth/mask shape/dtype mismatch",
        )
        require(
            bool(np.isfinite(depth).all()) and not bool((depth[valid] <= 0).any()),
            "Non-finite depth or nonpositive valid depth",
        )
        y, x = shape[0] // 2, shape[1] // 2
        return float(depth[y, x]) if valid[y, x] else None


def _down_axis(transform: dict) -> tuple[float, float, float]:
    x, y, z, w = transform["quaternion_xyzw"]
    return (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y))


def audit_bundle(root: Path) -> tuple[dict, dict[str, bytes]]:
    sources: dict[str, bytes] = {}
    findings: list[dict] = []
    records: list[dict] = []
    accepted: list[dict] = []
    center_depths: dict[int, float | None] = {}
    manifest = {}

    def issue(
        category: str, detail: str, knowledge: str = "unknown", index: int | None = None
    ) -> None:
        findings.append(
            {
                "category": category,
                "knowledge": knowledge,
                "detail": detail,
                "record": index,
                "executed": False,
                "authority": "NONE",
            }
        )

    def capture(name: str) -> bytes:
        if name not in sources:
            payload = read_regular(relative_file(root, name))
            require(
                sum(map(len, sources.values())) + len(payload) <= 128 * 1024 * 1024,
                "Replay bundle exceeds bounded 128 MiB snapshot budget",
            )
            sources[name] = payload
        return sources[name]

    try:
        manifest = strict_json(capture("manifest.json").decode())
        require(
            isinstance(manifest, dict)
            and manifest.get("schema") == "dronehacks.integration-replay.v1"
            and manifest.get("executed") is False
            and manifest.get("authority") == "NONE",
            "Manifest must identify replay v1, executed=false, authority=NONE",
        )
        require(
            manifest.get("source_type") in ("synthetic", "recording"),
            "Explicit evidence source type required",
        )
        require(
            isinstance(manifest.get("origin_environment"), str)
            and manifest["origin_environment"] in ENVIRONMENTS,
            "Explicit origin environment required",
        )
        require(
            isinstance(manifest.get("streams"), dict) and set(manifest["streams"]) == set(STREAMS),
            "Manifest must schedule all four required streams",
        )
        require(
            isinstance(manifest.get("calibrations"), dict)
            and isinstance(manifest.get("transforms"), dict),
            "Calibration and transform registries required",
        )
        schedules = {}
        for stream, spec in manifest["streams"].items():
            require(
                isinstance(spec, dict)
                and isinstance(spec.get("clock_domain"), str)
                and spec["clock_domain"] in CLOCKS,
                "Stream clock domain required",
            )
            schedule = spec.get("schedule")
            require(
                isinstance(schedule, list) and bool(schedule),
                "Nonempty expected per-stream schedule required",
            )
            previous_time = previous_id = -1
            for slot in schedule:
                require(
                    isinstance(slot, dict)
                    and set(slot) == {"frame_id", "timestamp_ns"}
                    and integer(slot["frame_id"])
                    and integer(slot["timestamp_ns"])
                    and slot["timestamp_ns"] > previous_time
                    and slot["frame_id"] > previous_id,
                    "Expected schedule timestamps/frame IDs must strictly increase",
                )
                previous_time, previous_id = slot["timestamp_ns"], slot["frame_id"]
            schedules[stream] = {(slot["frame_id"], slot["timestamp_ns"]) for slot in schedule}
        raw = capture("records.jsonl")
        if raw and not raw.endswith(b"\n"):
            issue(
                "truncated_records",
                "Missing final JSONL newline; a complete tail is not established.",
            )
        seen = {stream: set() for stream in STREAMS}
        previous = {}
        for line_number, line in enumerate(raw.splitlines(), 1):
            try:
                row = strict_json(line.decode())
                validate_record(row)
                records.append(row)
                stream, stamp, frame_id = row["stream"], row["timestamp_ns"], row["frame_id"]
                spec = manifest["streams"][stream]
                key = (frame_id, stamp)
                require(
                    key in schedules[stream],
                    "Unexpected frame ID/timestamp, not in declared schedule",
                )
                require(
                    row["clock_domain"] == spec["clock_domain"],
                    "Record clock domain differs from schedule",
                )
                require(key not in seen[stream], "Duplicate stream frame slot")
                seen[stream].add(key)
                if stream in previous:
                    old_id, old_time = previous[stream]
                    require(
                        stamp > old_time and frame_id > old_id,
                        "Out-of-order timestamps or frame IDs",
                    )
                    if frame_id > old_id + 1:
                        issue(
                            "dropped_frame",
                            f"Frame ID gap in {stream}; drop/subsampling cause unknown.",
                            "inferred",
                            line_number,
                        )
                previous[stream] = (frame_id, stamp)
                require(
                    row["evaluation_clock_domain"] == row["clock_domain"],
                    "Age unknown: evaluation and capture clocks differ",
                )
                age = row["evaluated_at_ns"] - stamp
                require(
                    age >= 0,
                    "Clock skew/future frame: capture timestamp exceeds replay evaluation time",
                )
                require(age <= 200_000_000, "Stale frame exceeds 200 ms replay age bound")
                if stream in {"oak_rgb_depth", "vl53l1x_downward"}:
                    cid, tid = row["calibration_id"], row["transform_id"]
                    require(
                        cid == spec.get("calibration_id") and tid == spec.get("transform_id"),
                        "Calibration mismatch: record IDs differ from stream expectation",
                    )
                    calibration = manifest["calibrations"].get(cid)
                    transform = manifest["transforms"].get(tid)
                    require(
                        calibration_valid(calibration) and calibration["sensor"] == stream,
                        "Calibration missing, invalid, or belongs to a different sensor",
                    )
                    require(
                        transform_valid(transform) and transform["calibration_id"] == cid,
                        "Transform missing, invalid quaternion/convention or calibration binding",
                    )
                    if stream == "oak_rgb_depth":
                        payload = capture(row["data"]["asset"])
                        require(
                            sha256(payload) == row["data"]["sha256"],
                            "Frame payload SHA-256 mismatch",
                        )
                        center_depths[frame_id] = load_frame(payload, calibration)
                accepted.append(row)
            except (
                ValueError,
                TypeError,
                KeyError,
                OSError,
                UnicodeError,
                OverflowError,
                RecursionError,
                zipfile.BadZipFile,
                EOFError,
            ) as error:
                message = str(error)
                category = next(
                    (
                        name
                        for token, name in (
                            ("Stale", "stale_frame"),
                            ("skew", "clock_skew"),
                            ("clocks differ", "unknown_clock_relation"),
                            ("Out-of-order", "out_of_order"),
                            ("Duplicate", "out_of_order"),
                            ("Calibration", "calibration_mismatch"),
                            ("Transform", "transform_mismatch"),
                        )
                        if token in message
                    ),
                    "malformed_evidence",
                )
                issue(category, message, index=line_number)
        for stream in STREAMS:
            missing = schedules[stream] - seen[stream]
            if missing:
                issue(
                    "missing_frames",
                    f"{stream}: {len(missing)} scheduled frame slots absent.",
                    "observed",
                )
            if not any(row["stream"] == stream for row in accepted):
                issue("missing_usable_stream", f"{stream}: no usable evidence.")
        oak = {row["frame_id"]: row for row in accepted if row["stream"] == "oak_rgb_depth"}
        for row in accepted:
            if row["stream"] == "perception_advisory":
                frame = oak.get(row["data"]["source_frame_id"])
                if (
                    frame is None
                    or frame["data"]["sha256"] != row["data"]["source_frame_sha256"]
                    or row["calibration_id"] != frame["calibration_id"]
                    or row["transform_id"] != frame["transform_id"]
                    or row["clock_domain"] != frame["clock_domain"]
                    or abs(row["timestamp_ns"] - frame["timestamp_ns"]) > 25_000_000
                ):
                    issue(
                        "unbound_advisory",
                        "Advisory lacks a usable, hash/time/calibration-bound source frame.",
                    )
            elif row["stream"] == "vl53l1x_downward":
                data, frame = row["data"], oak.get(row["frame_id"])
                if frame is None or data["range_status"] != "valid":
                    issue(
                        "unknown_sensor_comparison",
                        "Missing OAK frame or invalid/unknown range status.",
                    )
                    continue
                left = manifest["transforms"][frame["transform_id"]]
                right = manifest["transforms"][row["transform_id"]]
                direction = sum(a * b for a, b in zip(_down_axis(left), _down_axis(right)))
                distance = math.dist(left["translation_m"], right["translation_m"])
                comparable = (
                    frame["clock_domain"] == row["clock_domain"]
                    and abs(frame["timestamp_ns"] - row["timestamp_ns"]) <= 25_000_000
                    and frame["data"]["camera_view"] == "downward"
                    and bool(data["comparison_target"])
                    and data["comparison_target"] == frame["data"]["comparison_target"]
                    and direction >= 0.999
                    and distance <= 0.02
                    and _down_axis(right)[2] >= 0.999
                )
                depth = center_depths.get(frame["frame_id"])
                if not comparable or depth is None or data["sigma_m"] is None:
                    issue(
                        "unknown_sensor_comparison",
                        "Time, beam/target geometry, transform or uncertainty "
                        "does not support comparison; no agreement inferred.",
                    )
                elif abs(depth - data["range_m"]) > max(0.25, 3 * data["sigma_m"]):
                    issue(
                        "contradictory_sensors",
                        "Co-declared downward target ranges disagree: "
                        f"OAK center z={depth} m, VL53L1X={data['range_m']} m. "
                        "Same surface and physical calibration are unverified.",
                        "inferred",
                    )
        if len({row["clock_domain"] for row in accepted}) > 1 or manifest.get("clock_pairs"):
            _check_clock_pairs(manifest.get("clock_pairs", []), issue)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as error:
        issue("invalid_bundle", f"Cannot establish replay contract: {error}")
    if not isinstance(manifest, dict):
        manifest = {}
    summary = {
        "schema_version": 1,
        "purpose": "integration_replay_only",
        "executed": False,
        "authority": "NONE",
        "authority_change": "NONE",
        "geometry": geometry_boundary(),
        "hardware_accessed": False,
        "source_type": manifest.get("source_type")
        if manifest.get("source_type") in ("synthetic", "recording")
        else "unknown",
        "origin_environment": {
            "declaration": manifest.get("origin_environment")
            if isinstance(manifest.get("origin_environment"), str)
            and manifest["origin_environment"] in ENVIRONMENTS
            else "unknown",
            "knowledge": "unknown",
            "detail": "Producer claim, not attestation.",
        },
        "platform": platform_manifest(),
        "dependency_audit": "provisional_pending_final_exit_0",
        "records_parsed": len(records),
        "usable_records": len(accepted),
        "replay_records": [
            {
                "record": row,
                "knowledge": "observed",
                "executed": False,
                "authority": "NONE",
                "timestamp_ns_text": str(row["timestamp_ns"]),
                "frame_id_text": str(row["frame_id"]),
            }
            for row in accepted
        ],
        "evidence_quality": "degraded" if findings else "consistent_replay_only",
        "findings": findings,
        "sources": {name: sha256(data) for name, data in sources.items()},
        "conclusion": {
            "knowledge": "unknown",
            "detail": "Control/flight suitability is unknown. "
            "No evidence, including consistent synthetic evidence, increases authority.",
        },
    }
    return summary, sources


def _check_clock_pairs(pairs: object, issue) -> None:
    if not pairs:
        issue(
            "unknown_cross_clock_alignment",
            "No paired-clock rate evidence; cross-domain alignment unknown.",
        )
        return
    if not isinstance(pairs, list) or len(pairs) < 2:
        issue("invalid_clock_pairs", "At least two rate observations required.")
        return
    try:
        expected = {"source_clock", "target_clock", "source_ns", "target_ns", "uncertainty_ns"}
        for pair in pairs:
            require(isinstance(pair, dict) and set(pair) == expected, "Malformed clock pair")
            require(
                all(
                    isinstance(pair[key], str) and pair[key] in CLOCKS
                    for key in ("source_clock", "target_clock")
                ),
                "Invalid clock domains",
            )
            require(
                pair["source_clock"] != pair["target_clock"],
                "Rate observations require distinct clocks",
            )
            require(
                all(integer(pair[key]) for key in ("source_ns", "target_ns", "uncertainty_ns"))
                and pair["uncertainty_ns"] <= 5_000_000,
                "Invalid paired-clock uncertainty",
            )
        first, last = pairs[0], pairs[-1]
        for prior, current in pairwise(pairs):
            require(
                all(current[key] == first[key] for key in ("source_clock", "target_clock"))
                and current["source_ns"] > prior["source_ns"]
                and current["target_ns"] > prior["target_ns"],
                "Out-of-order or mixed clock observations",
            )
        scale = (last["target_ns"] - first["target_ns"]) / (last["source_ns"] - first["source_ns"])
        uncertainty = first["uncertainty_ns"] + last["uncertainty_ns"]
        difference = abs(
            (last["target_ns"] - first["target_ns"]) - (last["source_ns"] - first["source_ns"])
        )
        if difference > uncertainty + 0.002 * (last["source_ns"] - first["source_ns"]):
            issue(
                "clock_skew",
                f"Paired clock rate drift candidate: {(scale - 1) * 1e6:.3f} ppm; "
                "physical synchronization remains unknown.",
                "inferred",
            )
        for pair in pairs[1:-1]:
            residual = abs(
                pair["target_ns"]
                - first["target_ns"]
                - scale * (pair["source_ns"] - first["source_ns"])
            )
            if residual > 5_000_000 + pair["uncertainty_ns"]:
                issue(
                    "clock_skew",
                    "Paired-clock observations conflict with one affine rate model.",
                    "inferred",
                )
    except (ValueError, TypeError, KeyError) as error:
        issue("invalid_clock_pairs", str(error))


def integration_reports(summary: dict) -> dict[str, bytes]:
    lines = [
        "# Integration replay findings",
        "",
        "executed=False; authority=NONE.",
        "",
        "Synthetic/replay consistency does not validate Orin, OAK, PX4, SITL or flight.",
        "Local sensing plane only. full_3d_traversability=UNKNOWN; supports_3d_traversal=false.",
        "",
    ]
    for item in summary["findings"]:
        # HTML escaping also prevents injected active HTML in Markdown viewers.
        lines.append(
            "- "
            + html.escape(f"{item['knowledge']} / {item['category']}: {item['detail']}").replace(
                "\n", " "
            )
        )
    text = json_bytes(summary).decode()
    data = text.replace("<", "\\u003c")
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; connect-src 'none'\">"
        "<title>Integration replay forensics</title><h1>Integration replay forensics</h1>"
        "<p>Read-only replay · executed=False · authority=NONE · Hardware validation unknown.</p>"
        "<p>Local sensing plane only. <strong>3D traversability: UNKNOWN.</strong> "
        "Local width, matching ranges and descent geometry do not establish traversability.</p>"
        '<h2>Read-only diagnostic record replay</h2><label for="stream">Stream </label><select id="stream"></select>'
        '<label for="slot"> Record </label><input id="slot" type="range" min="0" max="0" value="0">'
        '<pre id="record"></pre><h2>Evidence summary</h2><pre>' + html.escape(text) + "</pre>"
        '<script id="evidence" type="application/json">' + data + "</script>"
        """<script>
'use strict';
const evidence=JSON.parse(document.getElementById('evidence').textContent);
const selector=document.getElementById('stream'), slider=document.getElementById('slot');
const groups=new Map();
for(const item of evidence.replay_records){
  item.record.timestamp_ns=item.timestamp_ns_text;item.record.frame_id=item.frame_id_text;
  const key=item.record.stream;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);
}
for(const key of groups.keys()){const option=document.createElement('option');option.value=key;option.textContent=key;selector.append(option);}
let selected=[];
function show(){document.getElementById('record').textContent=selected[Number(slider.value)]?JSON.stringify(selected[Number(slider.value)],null,2):'No usable records. Evidence unknown; authority NONE.';}
function choose(){selected=groups.get(selector.value)||[];slider.value='0';slider.max=String(Math.max(0,selected.length-1));slider.disabled=!selected.length;show();}
selector.addEventListener('change',choose);slider.addEventListener('input',show);choose();
</script></html>"""
    )
    return {"report.html": page.encode(), "findings.md": ("\n".join(lines) + "\n").encode()}
