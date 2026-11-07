"""Gravity-level sectors on CPU-rendered pinhole depth; no simulator or ROS."""

import json
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simtest import course_render as renderer  # noqa: E402
from vision.attitude import is_recent, level_from_px4, quaternion_rotation  # noqa: E402
from vision.depth_sectors import SectorConfig, sector_report  # noqa: E402
from vision.forward_sectors import (  # noqa: E402
    decode_depth,
    forward_sectors,
    intrinsics_from_k,
    report_to_dict,
)

CFG = renderer.RenderConfig(mono_noise=0)
STAMP = 10_000_000_000
OPTICAL_TO_FLU = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]])


def scene(pitch=0, *, yaw=0, floor_only=False):
    # Wide wall covers every horizontal sector so a side floor hit is detectable.
    boxes = np.zeros((0, 2, 3)) if floor_only else np.array([[[5, -10, 0], [5.1, 10, 1.7]]])
    world = renderer.World(boxes, [] if floor_only else ["wall"])
    cam = renderer.Camera(pos=(0, 0, 0.8), yaw_deg=yaw, pitch_deg=pitch)
    depth, _, _, (fx, fy, cx, cy) = renderer.render(world, cam, CFG)
    k = [fx, 0, cx, 0, fy, cy, 0, 0, 1]
    angle = np.radians(yaw)
    c, s = np.cos(angle), np.sin(angle)
    world_to_level = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
    rotation = world_to_level @ np.column_stack(renderer._camera_basis(cam))
    args = (
        "32FC1",
        CFG.height,
        CFG.width,
        CFG.width * 4,
        renderer.depth_message_bytes(depth),
        k,
        STAMP,
        STAMP,
    )
    return args, rotation


def centre(doc):
    assert doc["sectors"][3]["observed"]
    return doc["sectors"][3]["nearest_m"]


def test_level_camera_floor_removed_wall_at_five_metres():
    args, rotation = scene()
    before = forward_sectors(*args)
    after = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    assert 3.0 < centre(before) < 3.6
    assert centre(after) == pytest.approx(5, abs=0.02)
    assert before["leveled"] is False and after["leveled"] is True
    assert all(s["observed"] and s["nearest_m"] >= 5 for s in after["sectors"])
    json.dumps(after, allow_nan=False)


def test_pitched_ten_degrees_matches_level_within_centimetres():
    args, rotation = scene()
    level = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    args, rotation = scene(pitch=10)
    pitched = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    unlevelled = forward_sectors(*args)
    assert abs(centre(pitched) - centre(level)) < 0.03
    assert abs(centre(unlevelled) - centre(level)) > 1.0
    assert [s["azimuth_deg"] for s in pitched["sectors"]] == [
        s["azimuth_deg"] for s in level["sectors"]
    ]


def test_ten_degree_roll_does_not_make_a_side_obstacle(monkeypatch):
    args, rotation = scene()
    level = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    original_basis = renderer._camera_basis

    def rolled_basis(cam):
        right, down, forward = original_basis(cam)
        c, s = np.cos(np.radians(10)), np.sin(np.radians(10))
        return c * right + s * down, -s * right + c * down, forward

    # The renderer has yaw/pitch only. Apply a rigid roll to its ray basis and
    # obtain the leveling matrix from exactly that same basis, without resampling.
    monkeypatch.setattr(renderer, "_camera_basis", rolled_basis)
    args, rotation = scene()
    rolled = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    for baseline, sector in zip(level["sectors"], rolled["sectors"], strict=True):
        assert sector["observed"]
        assert sector["nearest_m"] >= 5
        assert sector["nearest_m"] == pytest.approx(baseline["nearest_m"], abs=0.03)


def test_floor_only_is_unknown_not_clear():
    args, rotation = scene(floor_only=True)
    doc = forward_sectors(*args, R_level_cam=rotation, camera_height_m=0.8)
    assert doc["nearest_m"] is None
    assert not any(s["observed"] for s in doc["sectors"])
    assert doc["frame_valid_fraction"] == 0


def test_leveling_without_height_does_not_claim_floor_filter():
    args, rotation = scene()
    doc = forward_sectors(*args, R_level_cam=rotation)
    assert doc["leveled"] is True
    assert centre(doc) < 3.6  # horizon band alone still includes descending rays


@pytest.mark.parametrize("pitch", [0, 10, -20])
def test_without_rotation_is_identical_to_original_report(pitch):
    args, _ = scene(pitch=pitch)
    encoding, h, w, step, data, k, stamp, now = args
    z, valid = decode_depth(encoding, h, w, step, data)
    original = report_to_dict(sector_report(z, valid, stamp, intrinsics_from_k(k), now_ns=now))
    doc = forward_sectors(*args)
    assert doc.pop("leveled") is False
    assert doc == original
    with_height_only = forward_sectors(*args, camera_height_m=0.8)
    assert with_height_only.pop("leveled") is False
    assert with_height_only == original


@pytest.mark.parametrize(
    "bad_rotation",
    [
        np.eye(2),
        np.zeros((3, 3)),
        np.diag([1, 1, -1]),
        np.eye(3) * 1.01,
        np.full((3, 3), np.nan),
        np.full((3, 3), np.inf),
        "bad",
        np.eye(3, dtype=complex) * (1 + 1j),
    ],
)
def test_invalid_rotation_raises(bad_rotation):
    args, _ = scene()
    with pytest.raises(ValueError, match="rotation"):
        forward_sectors(*args, R_level_cam=bad_rotation)


@pytest.mark.parametrize("height", [0, -1, np.nan, np.inf, -np.inf, "bad"])
def test_invalid_height_raises(height):
    args, rotation = scene()
    with pytest.raises(ValueError, match="camera_height_m"):
        forward_sectors(*args, R_level_cam=rotation, camera_height_m=height)


@pytest.mark.parametrize("margin", [-0.1, np.nan, np.inf, "bad"])
def test_invalid_floor_margin_raises(margin):
    args, rotation = scene()
    with pytest.raises(ValueError, match="floor_margin_m"):
        forward_sectors(*args, R_level_cam=rotation, floor_margin_m=margin)


def test_level_elevation_band_is_used_and_azimuth_stays_positive_right():
    # With a tight horizon band, a pitched image's centre is outside the band.
    args, rotation = scene(pitch=10)
    config = SectorConfig(vertical_band_deg=1)
    z = np.full((CFG.height, CFG.width), np.nan, dtype=np.float32)
    z[CFG.height // 2 - 2 : CFG.height // 2 + 3, :] = 1
    changed = (*args[:4], renderer.depth_message_bytes(z), *args[5:])
    doc = forward_sectors(*changed, R_level_cam=rotation, config=config)
    assert not any(s["observed"] for s in doc["sectors"])
    legacy = forward_sectors(*changed, config=config)
    assert any(s["observed"] for s in legacy["sectors"])

    args, rotation = scene()
    z[:] = 5
    z[:, CFG.width // 2 + 10 :] = 1
    doc = forward_sectors(
        *(*args[:4], renderer.depth_message_bytes(z), *args[5:]), R_level_cam=rotation
    )
    left, right = doc["sectors"][0], doc["sectors"][-1]
    assert left["azimuth_deg"][1] < 0 < right["azimuth_deg"][0]
    assert right["nearest_m"] < 1.5 < left["nearest_m"]


def euler_quaternion(roll, pitch, yaw):
    r, p, y = np.radians([roll, pitch, yaw]) / 2
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return [
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ]


@pytest.mark.parametrize("yaw", [0, 35, -170])
def test_px4_roll_pitch_frames_and_yaw_removal(yaw):
    # In FRD/NED, positive pitch points the nose up; renderer pitch is nose down.
    args, rendered_rotation = scene(pitch=10)
    from_px4 = level_from_px4(euler_quaternion(0, -10, yaw)) @ OPTICAL_TO_FLU
    np.testing.assert_allclose(from_px4, rendered_rotation, atol=1e-12)
    r, p = np.radians([10, -8])
    roll = np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])
    pitch = np.array([[np.cos(p), 0, np.sin(p)], [0, 1, 0], [-np.sin(p), 0, np.cos(p)]])
    flip = np.diag([1, -1, -1])
    np.testing.assert_allclose(
        level_from_px4(euler_quaternion(10, -8, yaw)), flip @ pitch @ roll @ flip, atol=1e-12
    )


@pytest.mark.parametrize("q", [[0, 0, 0, 0], [np.nan, 0, 0, 0], [1, 0], [np.inf, 0, 0, 0]])
def test_invalid_quaternion(q):
    with pytest.raises(ValueError):
        quaternion_rotation(q)


def test_missing_stale_future_or_misaligned_attitude_is_not_recent():
    assert is_recent(STAMP - 50_000_000, STAMP, STAMP, 200)
    assert not is_recent(None, STAMP, STAMP, 200)
    assert not is_recent(STAMP - 201_000_000, STAMP, STAMP, 200)
    assert not is_recent(STAMP + 1, STAMP, STAMP, 200)
    assert not is_recent(STAMP, STAMP, STAMP - 201_000_000, 200)


@pytest.fixture
def node_module(monkeypatch):
    """Exercise the real callbacks with ROS boundary doubles; not a ROS integration test."""

    class FakeNode:
        output = "/vision/forward_sectors"

        def __init__(self, name):
            self.now_ns = STAMP
            self.messages, self.logs, self.subscriptions, self.publishers = [], [], [], []

        def declare_parameter(self, name, default):
            return SimpleNamespace(value=self.output if name == "out_topic" else default)

        def get_parameter(self, name):
            return SimpleNamespace(value=False)

        def resolve_topic_name(self, topic):
            return topic

        def get_clock(self):
            return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=self.now_ns))

        def get_logger(self):
            return SimpleNamespace(warning=self.logs.append, info=lambda text: None)

        def create_publisher(self, msg_type, topic, qos):
            self.publishers.append(topic)
            return SimpleNamespace(publish=lambda m: self.messages.append(json.loads(m.data)))

        def create_subscription(self, msg_type, topic, callback, qos):
            self.subscriptions.append(topic)

    transform = SimpleNamespace(
        rotation=SimpleNamespace(w=0.5, x=-0.5, y=0.5, z=-0.5),
        translation=SimpleNamespace(x=0, y=0, z=0),
    )

    def install(name, **members):
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)

    install("rclpy")
    install("rclpy.node", Node=FakeNode)
    install("rclpy.qos", qos_profile_sensor_data=None)
    install("rclpy.time", Time=SimpleNamespace)
    install("sensor_msgs")
    install("sensor_msgs.msg", CameraInfo=SimpleNamespace, Image=SimpleNamespace)
    install("std_msgs")
    install("std_msgs.msg", String=SimpleNamespace)
    install(
        "tf2_ros",
        Buffer=lambda: SimpleNamespace(
            lookup_transform=lambda *a: SimpleNamespace(transform=transform)
        ),
        TransformListener=lambda *a: None,
    )
    install("px4_msgs")
    install(
        "px4_msgs.msg",
        VehicleAttitude=lambda: SimpleNamespace(
            MESSAGE_VERSION=0, q=[1, 0, 0, 0], timestamp=0, timestamp_sample=0
        ),
        VehicleLocalPosition=lambda: SimpleNamespace(
            MESSAGE_VERSION=1,
            timestamp=0,
            timestamp_sample=0,
            dist_bottom=0.0,
            dist_bottom_valid=False,
        ),
    )
    spec = importlib.util.spec_from_file_location(
        "vision._node_under_test", Path(__file__).resolve().parents[1] / "vision/node.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def depth_message(args):
    encoding, h, w, step, data, k, stamp, _ = args
    return SimpleNamespace(
        encoding=encoding,
        height=h,
        width=w,
        step=step,
        data=data,
        is_bigendian=False,
        header=SimpleNamespace(
            frame_id="optical",
            stamp=SimpleNamespace(
                sec=stamp // 1_000_000_000,
                nanosec=stamp % 1_000_000_000,
            ),
        ),
    )


def px4_attitude(timestamp=1_000_000, q=(1, 0, 0, 0), lag_us=0):
    return SimpleNamespace(timestamp=timestamp, timestamp_sample=timestamp - lag_us, q=q)


def px4_position(timestamp=1_000_000, valid=True, height=0.8):
    return SimpleNamespace(
        timestamp=timestamp, timestamp_sample=timestamp, dist_bottom=height, dist_bottom_valid=valid
    )


def test_node_publishes_legacy_when_attitude_missing_or_stale_and_warns_once(node_module):
    node = node_module.ForwardSectors()
    args, _ = scene()
    node.k = args[5]
    node._on_depth(depth_message(args))
    node._on_depth(depth_message(args))
    assert all(d["leveled"] is False for d in node.messages)
    assert len(node.logs) == 1
    node._on_attitude(px4_attitude())
    node._on_position(px4_position())
    node._on_depth(depth_message(args))
    assert node.messages[-1]["leveled"] is True
    assert centre(node.messages[-1]) == pytest.approx(5, abs=0.02)
    node.now_ns += 201_000_000
    node._on_depth(depth_message(args))
    assert node.messages[-1]["leveled"] is False
    assert len(node.logs) == 1
    assert node.publishers == ["/vision/forward_sectors"]
    assert "/fmu/out/vehicle_attitude" in node.subscriptions
    assert "/fmu/out/vehicle_local_position_v1" in node.subscriptions


def test_node_height_validity_age_and_camera_offset(node_module):
    node = node_module.ForwardSectors()
    assert node._forward_ok("optical", STAMP)
    node.camera_in_base = np.array([0, 0, 0.1])
    node._on_attitude(px4_attitude())
    node._on_position(px4_position())
    rotation, height = node._level_inputs(STAMP, STAMP)
    np.testing.assert_allclose(rotation, OPTICAL_TO_FLU)
    assert height == pytest.approx(0.9)
    node._on_position(px4_position(timestamp=1_000_001, valid=False))
    assert node._level_inputs(STAMP, STAMP)[1] is None
    node._on_position(px4_position(timestamp=1_000_002, height=np.nan))
    assert node._level_inputs(STAMP, STAMP)[1] is None
    node._on_position(px4_position(timestamp=1_000_003))
    node.now_ns += 201_000_000
    node._on_attitude(px4_attitude(timestamp=1_201_000))
    rotation, height = node._level_inputs(node.now_ns, node.now_ns)
    assert rotation is not None and height is None  # fresh attitude, stale height


def test_node_invalid_delayed_or_duplicate_attitude_cannot_become_fresh(node_module):
    node = node_module.ForwardSectors()
    node._forward_ok("optical", STAMP)
    node._on_attitude(px4_attitude(lag_us=201_000))
    assert node._level_inputs(STAMP, STAMP) == (None, None)
    node._on_attitude(px4_attitude(timestamp=1_000_001))
    node.now_ns += 201_000_000
    node._on_attitude(px4_attitude(timestamp=1_000_001))  # same sample doesn't refresh
    assert node._level_inputs(node.now_ns, node.now_ns) == (None, None)
    node._on_attitude(px4_attitude(timestamp=1_000_002, q=(0, 0, 0, 0)))
    assert node.attitude is None


def test_node_missing_px4_or_incompatible_schema_is_guarded(node_module, monkeypatch):
    monkeypatch.setattr(node_module, "VehicleAttitude", None)
    node = node_module.ForwardSectors()
    assert not any(t.startswith("/fmu/") for t in node.subscriptions)
    monkeypatch.setattr(node_module, "VehicleAttitude", lambda: SimpleNamespace(q=[1, 0]))
    monkeypatch.setattr(
        node_module, "VehicleLocalPosition", lambda: SimpleNamespace(MESSAGE_VERSION=0)
    )
    node = node_module.ForwardSectors()
    assert not any(t.startswith("/fmu/") for t in node.subscriptions)
    assert len(node.logs) == 2


def test_node_missing_position_message_keeps_attitude_subscription(node_module, monkeypatch):
    monkeypatch.setattr(node_module, "VehicleLocalPosition", None)
    node = node_module.ForwardSectors()
    assert "/fmu/out/vehicle_attitude" in node.subscriptions
    assert "/fmu/out/vehicle_local_position_v1" not in node.subscriptions


def test_node_rejects_px4_command_output_topic(node_module, monkeypatch):
    monkeypatch.setattr(node_module.Node, "output", "/fmu/in/trajectory_setpoint")
    with pytest.raises(ValueError, match="must not publish"):
        node_module.ForwardSectors()
