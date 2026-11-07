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

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String

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
        self.rejects: dict[str, int] = {}
        self.pub = self.create_publisher(String, out_topic, 10)
        self.create_subscription(CameraInfo, self.info_topic, self._on_info, qos_profile_sensor_data)
        self.create_subscription(Image, self.depth_topic, self._on_depth, qos_profile_sensor_data)
        self.get_logger().info(
            f"observer only: {self.depth_topic} + {self.info_topic} -> {out_topic}; "
            f"sim time {self.get_parameter('use_sim_time').value}"
        )

    def _on_info(self, m):
        if m.k[0] > 0 and m.k[4] > 0:
            self.k = list(m.k)

    def _publish(self, doc):
        self.pub.publish(String(data=json.dumps(doc, separators=(",", ":"))))

    def _reject(self, key, detail, frame_id="", stamp_ns=0):
        self.rejects[key] = self.rejects.get(key, 0) + 1
        if self.rejects[key] in (1, 10, 100, 1000):
            self.get_logger().warning(f"depth frame not used ({self.rejects[key]}x): {detail}")
        self._publish({"schema": SCHEMA, "frame_id": frame_id, "stamp_ns": stamp_ns, "rejected": key,
                       "detail": detail, "sectors": [], "nearest_m": None, "control_output": "DISABLED"})

    def _forward_ok(self, frame_id, stamp_ns):
        if self.checked_frame == frame_id:
            return True
        from rclpy.time import Time

        try:
            tf = self.tf_buffer.lookup_transform(self.base_frame, frame_id, Time())
        except Exception as e:  # not (yet) on the TF tree
            self._reject("no_tf", f"no TF {self.base_frame} <- {frame_id} ({type(e).__name__})", frame_id, stamp_ns)
            return False
        r = tf.transform.rotation
        ang = optical_axis_offset_deg(r.w, r.x, r.y, r.z)
        if ang > MAX_FORWARD_OFFSET_DEG:
            self._reject("camera_not_forward", f"{frame_id} optical axis {ang:.0f} deg off body forward", frame_id, stamp_ns)
            return False
        self.checked_frame = frame_id
        self.get_logger().info(f"{self.base_frame} <- {frame_id}: optical axis {ang:.1f} deg off forward")
        return True

    def _on_depth(self, m):
        frame_id = m.header.frame_id
        stamp_ns = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nanosec
        if self.k is None:
            return self._reject("no_camera_info", f"no camera_info yet on {self.info_topic}", frame_id, stamp_ns)
        if not self._forward_ok(frame_id, stamp_ns):
            return None
        now_ns = self.get_clock().now().nanoseconds  # sim time when use_sim_time:=true
        try:
            doc = forward_sectors(m.encoding, m.height, m.width, m.step, bytes(m.data), self.k,
                                  stamp_ns, now_ns, frame_id, self.config, bool(m.is_bigendian))
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
