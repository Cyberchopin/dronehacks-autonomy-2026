"""ROS 2 observer: depth image -> /vision/forward_sectors (std_msgs/String JSON).

OBSERVER ONLY. This node has no PX4 publisher, no vehicle command, no arming/mode/parameter
client. It cannot move the aircraft. refnav is unchanged and does not read this topic yet.

  in   depth        sensor_msgs/Image (32FC1 m or 16UC1 mm), param depth_topic (same default as flight.yaml)
       camera_info  sensor_msgs/CameraInfo, param depth_info_topic (default: <depth dir>/camera_info)
       TF           base_frame <- depth frame_id; the optical axis must be within 25 deg of body forward
  out  out_topic    std_msgs/String JSON, schema "vision.forward_sectors/1" (see vision/README.md).
                    A frame that cannot be used is still published, with "rejected": "<reason>" and no
                    sectors, so a consumer sees UNKNOWN instead of silence.

Run (only after the team agrees; it does not fly, but it uses the shared companion):
  python3 -m vision.node --ros-args -p use_sim_time:=true
"""

from __future__ import annotations

import json

import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String

try:
    from px4_msgs.msg import VehicleAttitude
except ImportError:
    VehicleAttitude = None

try:
    from px4_msgs.msg import VehicleLocalPosition
except ImportError:
    VehicleLocalPosition = None

from .attitude import is_recent, level_from_px4, quaternion_rotation
from .depth_sectors import SectorConfig
from .forward_sectors import SCHEMA, forward_sectors, optical_axis_offset_deg

MAX_FORWARD_OFFSET_DEG = 25.0  # same limit as refnav/node.py::_calibration


class ForwardSectors(Node):
    def __init__(self):
        super().__init__("vision_forward_sectors")
        self.depth_topic = self.declare_parameter("depth_topic", "/camera/depth/image_raw").value
        info = self.declare_parameter("depth_info_topic", "").value
        self.info_topic = info or self.depth_topic.rsplit("/", 1)[0] + "/camera_info"
        self.base_frame = self.declare_parameter("base_frame", "base_link").value
        out_topic = self.declare_parameter("out_topic", "/vision/forward_sectors").value
        resolved_out = self.resolve_topic_name(out_topic)
        if resolved_out == "/fmu/in" or resolved_out.startswith("/fmu/in/"):
            raise ValueError("observer output must not publish on /fmu/in/*")
        self.config = SectorConfig(
            sectors=int(self.declare_parameter("sectors", 7).value),
            max_range_m=float(self.declare_parameter("max_range_m", 10.0).value),
            max_age_ms=float(self.declare_parameter("max_age_ms", 200.0).value),
        )

        from tf2_ros import Buffer, TransformListener

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.k = None
        self.checked_frame = None
        self.base_from_cam = None
        self.camera_in_base = None
        self.attitude = None
        self.height = None
        self.last_attitude_timestamp = 0
        self.last_position_timestamp = 0
        self.warnings: set[str] = set()
        self.rejects: dict[str, int] = {}
        self.pub = self.create_publisher(String, out_topic, 10)
        self.create_subscription(
            CameraInfo, self.info_topic, self._on_info, qos_profile_sensor_data
        )
        self.create_subscription(Image, self.depth_topic, self._on_depth, qos_profile_sensor_data)
        self._subscribe_px4()
        self.get_logger().info(
            f"observer only: {self.depth_topic} + {self.info_topic} -> {out_topic}; "
            f"sim time {self.get_parameter('use_sim_time').value}"
        )

    def _warn_once(self, key, detail):
        if key not in self.warnings:
            self.warnings.add(key)
            self.get_logger().warning(detail)

    def _subscribe_px4(self):
        # Official definitions are cited in README. Installed ROS messages must
        # expose these fields too; missing/unsupported messages fail to legacy.
        if VehicleAttitude is None:
            self._warn_once("px4_unavailable", "px4_msgs unavailable: depth will be unlevelled")
            return
        attitude = VehicleAttitude()
        if (
            getattr(attitude, "MESSAGE_VERSION", None) == 0
            and all(hasattr(attitude, f) for f in ("q", "timestamp", "timestamp_sample"))
            and len(attitude.q) == 4
        ):
            self.create_subscription(
                VehicleAttitude,
                "/fmu/out/vehicle_attitude",
                self._on_attitude,
                qos_profile_sensor_data,
            )
        else:
            self._warn_once("px4_attitude_schema", "UNKNOWN PX4 attitude schema: no leveling")
        if VehicleLocalPosition is None:
            self._warn_once("px4_height_schema", "PX4 position unavailable: no floor filter")
            return
        position = VehicleLocalPosition()
        if getattr(position, "MESSAGE_VERSION", None) == 1 and all(
            hasattr(position, f)
            for f in ("dist_bottom", "dist_bottom_valid", "timestamp", "timestamp_sample")
        ):
            self.create_subscription(
                VehicleLocalPosition,
                "/fmu/out/vehicle_local_position_v1",
                self._on_position,
                qos_profile_sensor_data,
            )
        else:
            self._warn_once("px4_height_schema", "UNKNOWN PX4 position v1 schema: no floor filter")

    def _sample_time(self, m):
        # PX4 timestamps are boot microseconds, not ROS time. Subtract the
        # source's sample-to-publication delay from local reception time only.
        # Transport latency is UNKNOWN without clock synchronisation.
        if not 0 < m.timestamp_sample <= m.timestamp:
            raise ValueError("invalid PX4 sample timestamps")
        return self.get_clock().now().nanoseconds - int(m.timestamp - m.timestamp_sample) * 1000

    def _on_attitude(self, m):
        if m.timestamp <= self.last_attitude_timestamp:
            return  # duplicates/out-of-order delivery must not refresh old evidence
        self.last_attitude_timestamp = m.timestamp
        try:
            self.attitude = (level_from_px4(m.q), self._sample_time(m))
        except ValueError:
            self.attitude = None
            self._warn_once("invalid_attitude", "invalid PX4 attitude: depth will be unlevelled")

    def _on_position(self, m):
        if m.timestamp <= self.last_position_timestamp:
            return
        self.last_position_timestamp = m.timestamp
        self.height = None  # invalid height revokes the last valid floor filter
        if not m.dist_bottom_valid or not np.isfinite(m.dist_bottom) or m.dist_bottom <= 0:
            return
        try:
            self.height = (float(m.dist_bottom), self._sample_time(m))
        except ValueError:
            return

    def _level_inputs(self, now_ns, stamp_ns):
        if self.attitude is None or not is_recent(
            self.attitude[1], now_ns, stamp_ns, self.config.max_age_ms
        ):
            self._warn_once(
                "no_recent_attitude", "PX4 attitude missing/stale: publishing leveled=false"
            )
            return None, None
        level_from_base = self.attitude[0]
        rotation = level_from_base @ self.base_from_cam
        camera_height = None
        if self.height is not None and is_recent(
            self.height[1], now_ns, stamp_ns, self.config.max_age_ms
        ):
            # dist_bottom is at the vehicle reference; translate to optical centre.
            candidate = self.height[0] + float((level_from_base @ self.camera_in_base)[2])
            if np.isfinite(candidate) and candidate > 0:
                camera_height = candidate
        return rotation, camera_height

    def _on_info(self, m):
        if m.k[0] > 0 and m.k[4] > 0:
            self.k = list(m.k)

    def _publish(self, doc):
        self.pub.publish(String(data=json.dumps(doc, separators=(",", ":"))))

    def _reject(self, key, detail, frame_id="", stamp_ns=0):
        self.rejects[key] = self.rejects.get(key, 0) + 1
        if self.rejects[key] in (1, 10, 100, 1000):
            self.get_logger().warning(f"depth frame not used ({self.rejects[key]}x): {detail}")
        self._publish(
            {
                "schema": SCHEMA,
                "frame_id": frame_id,
                "stamp_ns": stamp_ns,
                "rejected": key,
                "leveled": False,
                "detail": detail,
                "sectors": [],
                "nearest_m": None,
                "control_output": "DISABLED",
            }
        )

    def _forward_ok(self, frame_id, stamp_ns):
        from rclpy.time import Time

        try:
            tf = self.tf_buffer.lookup_transform(
                self.base_frame, frame_id, Time(nanoseconds=stamp_ns)
            )
        except Exception as e:  # not (yet) on the TF tree
            self._reject(
                "no_tf",
                f"no TF {self.base_frame} <- {frame_id} ({type(e).__name__})",
                frame_id,
                stamp_ns,
            )
            return False
        r = tf.transform.rotation
        ang = optical_axis_offset_deg(r.w, r.x, r.y, r.z)
        if ang > MAX_FORWARD_OFFSET_DEG:
            self._reject(
                "camera_not_forward",
                f"{frame_id} optical axis {ang:.0f} deg off body forward",
                frame_id,
                stamp_ns,
            )
            return False
        try:
            self.base_from_cam = quaternion_rotation((r.w, r.x, r.y, r.z))
            t = tf.transform.translation
            self.camera_in_base = np.array([t.x, t.y, t.z], dtype=float)
            if not np.isfinite(self.camera_in_base).all():
                raise ValueError("non-finite TF translation")
        except ValueError as e:
            self._reject("invalid_tf", str(e), frame_id, stamp_ns)
            return False
        if self.checked_frame != frame_id:
            self.get_logger().info(
                f"{self.base_frame} <- {frame_id}: optical axis {ang:.1f} deg off forward"
            )
            self.checked_frame = frame_id
        return True

    def _on_depth(self, m):
        frame_id = m.header.frame_id
        stamp_ns = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nanosec
        if self.k is None:
            return self._reject(
                "no_camera_info", f"no camera_info yet on {self.info_topic}", frame_id, stamp_ns
            )
        if not self._forward_ok(frame_id, stamp_ns):
            return None
        now_ns = self.get_clock().now().nanoseconds  # sim time when use_sim_time:=true
        rotation, height = self._level_inputs(now_ns, stamp_ns)
        try:
            doc = forward_sectors(
                m.encoding,
                m.height,
                m.width,
                m.step,
                bytes(m.data),
                self.k,
                stamp_ns,
                now_ns,
                frame_id,
                self.config,
                bool(m.is_bigendian),
                R_level_cam=rotation,
                camera_height_m=height,
            )
        except ValueError as e:
            return self._reject("undecodable", str(e), frame_id, stamp_ns)
        self._publish(doc)
        return None


def main():
    rclpy.init()
    node = ForwardSectors()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
