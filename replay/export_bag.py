"""Read an existing ROS 2 bag into bounded portable packets. No ROS runtime/node."""

from __future__ import annotations

import argparse
from collections import Counter, deque
import json
from pathlib import Path
import shlex
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay.frames import FrameWriter, provenance, unknown
from vision.attitude import quaternion_rotation, rotation_matrix

DEFAULT_TOPICS = {
    "mono": "/stereo/left/image",
    "depth": "/camera/depth/image_raw",
    "camera_info": "/camera/depth/camera_info",
    "attitude": "/fmu/out/vehicle_attitude",
    "position": "/fmu/out/vehicle_local_position_v1",
    "tf_static": "/tf_static",
}
EXPECTED_TYPES = {
    "mono": "sensor_msgs/msg/Image",
    "depth": "sensor_msgs/msg/Image",
    "camera_info": "sensor_msgs/msg/CameraInfo",
    "attitude": "px4_msgs/msg/VehicleAttitude",
    "position": "px4_msgs/msg/VehicleLocalPosition",
    "tf_static": "tf2_msgs/msg/TFMessage",
}


def header_fields(m):
    return {
        "stamp_ns": int(m.header.stamp.sec) * 1_000_000_000 + int(m.header.stamp.nanosec),
        "frame_id": str(m.header.frame_id),
    }


def image_packet(role, bag_time_ns, m):
    meta = {
        "role": role,
        "bag_time_ns": int(bag_time_ns),
        **header_fields(m),
        "width": int(m.width),
        "height": int(m.height),
    }
    if role == "camera_info":
        k = np.asarray(m.k, dtype=float)
        if k.shape != (9,) or not np.isfinite(k).all():
            raise ValueError("invalid CameraInfo K")
        # Duplicate small K in manifest for association without reloading all packets.
        meta["k"] = k.tolist()
        return meta, {"k": k}
    meta.update(encoding=str(m.encoding), step=int(m.step), is_bigendian=bool(m.is_bigendian))
    data = np.frombuffer(bytes(m.data), dtype=np.uint8)
    if meta["width"] <= 0 or meta["height"] <= 0 or data.size != meta["step"] * meta["height"]:
        raise ValueError("invalid Image dimensions or buffer length")
    return meta, {"data": data}


def telemetry(role, bag_time_ns, m):
    item = {
        "status": "KNOWN",
        "bag_time_ns": int(bag_time_ns),
        "timestamp_us": int(m.timestamp),
        "timestamp_sample_us": int(m.timestamp_sample),
    }
    if role == "attitude":
        q = np.asarray(m.q, dtype=float)
        quaternion_rotation(q)  # validate before strict JSON serialization
        item["q_wxyz"] = q.tolist()
        item["convention"] = "Hamilton FRD->NED"
    else:
        item["dist_bottom_valid"] = bool(m.dist_bottom_valid)
        value = float(m.dist_bottom)
        item["dist_bottom_m"] = value if np.isfinite(value) else None
    return item


def calibrated_transform(document, frame, base_frame):
    if document.get("base_frame") != base_frame or document.get("optical_frame") != frame:
        return unknown("calibration frame IDs do not match depth optical and base frames")
    try:
        rotation = rotation_matrix(document["rotation"])
        translation = np.asarray(document["translation_m"], dtype=float)
        if translation.shape != (3,) or not np.isfinite(translation).all():
            raise ValueError("translation must contain three finite metres")
    except (KeyError, TypeError, ValueError) as e:
        return unknown(f"invalid camera calibration: {e}")
    return {
        "status": "KNOWN",
        "base_frame": base_frame,
        "optical_frame": frame,
        "rotation": rotation.tolist(),
        "translation_m": translation.tolist(),
        "source": document.get("source", "explicit calibration file"),
    }


def static_transform(edges, source, target):
    """Compose a recorded static TF chain; never assume an optical mounting rotation."""
    graph, parents = {}, {}
    for (parent, child), matrix in edges.items():
        parents.setdefault(child, set()).add(parent)
        if matrix is None:
            continue  # changed static edge is ambiguous
        graph.setdefault(child, []).append((parent, matrix))
        graph.setdefault(parent, []).append((child, np.linalg.inv(matrix)))
    if any(len(p) > 1 for p in parents.values()):
        return unknown("recorded static TF has multiple parents for a child")
    queue, seen = deque([(source, np.eye(4))]), {source}
    while queue:
        node, matrix = queue.popleft()
        if node == target:
            return {
                "status": "KNOWN",
                "base_frame": target,
                "optical_frame": source,
                "rotation": matrix[:3, :3].tolist(),
                "translation_m": matrix[:3, 3].tolist(),
                "source": "recorded /tf_static chain",
            }
        for neighbour, transform in graph.get(node, []):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, transform @ matrix))
    return unknown("no unambiguous recorded static TF chain; supply verified --extrinsics")


def export_records(
    factory,
    available_topics,
    out,
    *,
    bag_name,
    topics=None,
    every=3,
    max_frames=600,
    max_mb=300,
    base_frame="base_link",
    extrinsics=None,
    command="UNKNOWN",
    source_kind="rosbag2",
):
    """Two read-only passes. factory(roles) yields (role, record_ns, decoded message).

    First pass samples each image/CameraInfo stream independently; second pass
    associates telemetry and static TF. Memory stays bounded by exported packet count.
    Synthetic tests use this same path without importing ROS.
    """
    if not isinstance(every, int) or every < 1:
        raise ValueError("every must be a positive integer")
    topics = topics or DEFAULT_TOPICS
    if len(set(topics.values())) != len(topics):
        raise ValueError("each role must select a distinct topic")
    confirmed = {
        role: (
            {"status": "KNOWN", "name": name, "type": available_topics[name]}
            if available_topics.get(name) == EXPECTED_TYPES[role]
            else {
                **unknown("topic absent or message type differs; confirm bag metadata"),
                "requested": name,
                "actual_type": available_topics.get(name),
            }
        )
        for role, name in topics.items()
    }
    enabled = {role for role, info in confirmed.items() if info["status"] == "KNOWN"}
    if not enabled.intersection({"mono", "depth"}):
        raise ValueError("UNKNOWN image topics: no supported mono/depth topic found in bag")
    manifest = {
        "bag_name": bag_name,
        "source_kind": source_kind,
        "topics": confirmed,
        "available_topics": available_topics,
        "every": every,
        "command": command,
        "base_frame": base_frame,
        **provenance(),
        "counts": {},
        "errors": {},
        "association_clock": "bag record nanoseconds; nearest may be in the future",
        "source_clock_alignment": "UNKNOWN; PX4 boot timestamps retained separately",
        "sim_time_basis": "image header stamps; sim clock domain must be confirmed by producer",
    }
    writer = FrameWriter(out, manifest, max_frames=max_frames, max_mb=max_mb)
    counts, errors = Counter(), Counter()
    bag_min = bag_max = sim_min = sim_max = None
    for role, stamp, m in factory(enabled.intersection({"mono", "depth", "camera_info"})):
        counts[role] += 1
        bag_min = stamp if bag_min is None else min(bag_min, stamp)
        bag_max = stamp if bag_max is None else max(bag_max, stamp)
        hstamp = header_fields(m)["stamp_ns"]
        if role in {"mono", "depth"}:
            sim_min = hstamp if sim_min is None else min(sim_min, hstamp)
            sim_max = hstamp if sim_max is None else max(sim_max, hstamp)
        if (counts[role] - 1) % every or writer.doc["limit_reached"]:
            continue
        try:
            metadata, arrays = image_packet(role, stamp, m)
            writer.add(metadata, **arrays)
        except (ValueError, TypeError, AttributeError) as e:
            errors[f"{role}: {e}"] += 1
    frames = writer.doc["frames"]
    images = [f for f in frames if f["role"] in {"mono", "depth"}]
    anchors = np.array([f["bag_time_ns"] for f in images], dtype=np.int64)
    distances = {role: np.full(len(images), np.inf) for role in ("attitude", "position")}
    edges = {}
    for role, stamp, m in factory(enabled.intersection({"attitude", "position", "tf_static"})):
        counts[role] += 1
        bag_min = stamp if bag_min is None else min(bag_min, stamp)
        bag_max = stamp if bag_max is None else max(bag_max, stamp)
        try:
            if role == "tf_static":
                for tf in m.transforms:
                    key = (tf.header.frame_id, tf.child_frame_id)
                    if len(edges) >= 1024 and key not in edges:
                        raise ValueError("static TF edge limit reached")
                    r, t = tf.transform.rotation, tf.transform.translation
                    matrix = np.eye(4)
                    matrix[:3, :3] = quaternion_rotation([r.w, r.x, r.y, r.z])
                    matrix[:3, 3] = [t.x, t.y, t.z]
                    if not np.isfinite(matrix).all():
                        raise ValueError("nonfinite static TF")
                    if key in edges and (edges[key] is None or not np.allclose(edges[key], matrix)):
                        edges[key] = None
                    else:
                        edges[key] = matrix
                continue
            try:
                item = telemetry(role, stamp, m)
            except (ValueError, AttributeError, TypeError) as e:
                # Keep the nearest INVALID sample, rather than silently borrowing a valid one.
                item = {
                    **unknown(str(e)),
                    "bag_time_ns": int(stamp),
                    "timestamp_us": getattr(m, "timestamp", None),
                    "timestamp_sample_us": getattr(m, "timestamp_sample", None),
                }
                errors[f"{role}: {e}"] += 1
            delta = np.abs(anchors - stamp)
            for i in np.flatnonzero(delta < distances[role]):
                distances[role][i] = delta[i]
                images[i][role] = {**item, "delta_ns": int(stamp - anchors[i])}
        except (ValueError, TypeError, AttributeError) as e:
            errors[f"{role}: {e}"] += 1
    infos = [f for f in frames if f["role"] == "camera_info"]
    for frame in images:
        for role in ("attitude", "position"):
            frame.setdefault(role, unknown("no recorded sample"))
        if frame["role"] == "depth":
            matching = [
                i
                for i in infos
                if i["frame_id"] == frame["frame_id"]
                and (i["width"], i["height"]) == (frame["width"], frame["height"])
            ]
            earlier = [i for i in matching if i["bag_time_ns"] <= frame["bag_time_ns"]]
            if matching:
                info = (
                    max(earlier, key=lambda i: i["bag_time_ns"])
                    if earlier
                    else min(matching, key=lambda i: i["bag_time_ns"])
                )
                frame["camera_info"] = {
                    "status": "KNOWN",
                    "file": info["file"],
                    "stamp_ns": info["stamp_ns"],
                    "bag_time_ns": info["bag_time_ns"],
                    "k": info["k"],
                    "delta_ns": info["bag_time_ns"] - frame["bag_time_ns"],
                }
            else:
                frame["camera_info"] = unknown("no sampled CameraInfo with matching frame ID/size")
            frame["extrinsics"] = (
                calibrated_transform(extrinsics, frame["frame_id"], base_frame)
                if extrinsics
                else static_transform(edges, frame["frame_id"], base_frame)
            )
    writer.doc.update(
        counts=dict(counts),
        errors=dict(errors),
        exported_counts=dict(Counter(f["role"] for f in frames)),
        bag_record_span_ns=[bag_min, bag_max],
        sim_time_span_ns=[sim_min, sim_max],
        exported_sim_time_span_ns=[
            min((f["stamp_ns"] for f in images), default=None),
            max((f["stamp_ns"] for f in images), default=None),
        ],
    )
    return writer.finish()


def ros_source(path, storage_id=""):
    # Import only on the teammate's machine with ROS 2 Jazzy + matching px4_msgs.
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as e:
        raise RuntimeError(
            "export needs ROS 2 Jazzy, rosbag2_py and recorded message packages"
        ) from e

    def reader():
        result = rosbag2_py.SequentialReader()
        result.open(
            rosbag2_py.StorageOptions(uri=str(path), storage_id=storage_id),
            rosbag2_py.ConverterOptions("", ""),
        )
        return result

    initial = reader()
    available = {t.name: t.type for t in initial.get_all_topics_and_types()}
    return reader, available, deserialize_message, get_message, rosbag2_py


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--every", type=int, default=3)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument("--max-mb", type=float, default=300)
    parser.add_argument("--storage-id", default="", help="auto from metadata; or sqlite3/mcap")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--extrinsics", type=Path, help="verified optical-to-body calibration JSON")
    for role, topic in DEFAULT_TOPICS.items():
        parser.add_argument(f"--{role.replace('_', '-')}-topic", default=topic)
    args = parser.parse_args(argv)
    if args.out.resolve() == args.bag.resolve() or args.bag.resolve() in args.out.resolve().parents:
        parser.error("output must be outside the read-only bag directory")
    try:
        reader, available, deserialize, get_message, rosbag = ros_source(args.bag, args.storage_id)
        topics = {role: getattr(args, f"{role}_topic") for role in DEFAULT_TOPICS}
        inverse = {topic: role for role, topic in topics.items()}

        def factory(roles):
            if not roles:
                return
            source = reader()
            source.set_filter(rosbag.StorageFilter(topics=[topics[r] for r in roles]))
            types = {topics[r]: get_message(available[topics[r]]) for r in roles}
            while source.has_next():
                topic, data, stamp = source.read_next()
                yield inverse[topic], int(stamp), deserialize(data, types[topic])

        doc = export_records(
            factory,
            available,
            args.out,
            bag_name=args.bag.name,
            topics=topics,
            every=args.every,
            max_frames=args.max_frames,
            max_mb=args.max_mb,
            base_frame=args.base_frame,
            extrinsics=json.loads(args.extrinsics.read_text()) if args.extrinsics else None,
            command=shlex.join([sys.executable, "replay/export_bag.py", *(argv or sys.argv[1:])]),
        )
    except (OSError, ValueError, RuntimeError, ImportError) as e:
        parser.exit(2, f"export failed: {e}\n")
    print(
        json.dumps(
            {
                "exported": doc["exported_counts"],
                "limit_reached": doc["limit_reached"],
                "out": str(args.out),
            }
        )
    )


if __name__ == "__main__":
    main()
