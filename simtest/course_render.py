"""Render depth + mono camera frames from the published course geometry. PURE (numpy only), no ROS.

Purpose: test vision/forward_sectors (and smoke-test vision/floor_line) against the ACTUAL course
layout instead of a single synthetic stripe, while the DroneHacks simulator is unavailable. It is a
coarse box-world, NOT the simulator and NOT photorealistic: walls/boulders/tunnel/net are rendered
as their axis-aligned bounding boxes, the floor as a plane, and pad rings as circles. It has no
materials, lighting or stereo-matching model beyond simple shading and optional noise/dropout.

Treat results as "do the depth and the sector logic behave sensibly in the real geometry", never as
flight evidence. Known limits: a wall-with-a-window renders as a solid box (its opening is not in
the AABB data), and the maze guide line's PATH is not in the AABB data, so this renderer does not
reproduce it. Feed it richer geometry (course/passages.json, course/floor_markings.json) when that
exists to lift these limits.

Frames come out in exactly the message layout the vision code consumes:
  depth  32FC1 metres, z along the optical axis (NaN = no return)
  mono   mono8, uint8
with a pinhole K. Camera optical frame is REP-103 (x right, y down, z forward); world is ENU
(x east, y north, z up), matching the rest of the stack's "forward camera" assumption.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

# intensity by surface kind (mono8); floor markings are painted brighter on top of the floor
_KIND_SHADE = {
    "floor": 90, "wall": 135, "boulder": 110, "tunnel": 125, "tunnel_support": 120,
    "boundary_net": 70, "overhead_net": 70, "floor_marking": 90,
}
_MARKING_SHADE = 205


@dataclass
class Camera:
    pos: tuple[float, float, float] = (-2.5, 0.9, 0.8)   # world ENU metres (near the launch mark)
    yaw_deg: float = 0.0        # 0 = facing +x (east); +ccw about world up
    pitch_deg: float = 10.0     # nose-down tilt, degrees (a forward/down course camera)
    hfov_deg: float = 71.5      # OAK-D S2-ish horizontal FOV; set from the real CameraInfo when known


@dataclass
class RenderConfig:
    width: int = 640
    height: int = 400
    max_range_m: float = 12.0
    noise_m: float = 0.0        # gaussian depth noise std (0 = deterministic, for tests)
    dropout: float = 0.0        # fraction of valid pixels randomly set to no-return
    mono_noise: float = 2.0
    seed: int = 0


@dataclass
class World:
    boxes: np.ndarray              # (N, 2, 3) min/max per box, world ENU metres
    box_kind: list[str] = field(default_factory=list)
    rings: list[tuple[float, float, float, float]] = field(default_factory=list)  # (cx, cy, r_out, r_in)
    floor_z: float = 0.0


def world_from_layout(layout: dict, *, include_net: bool = True) -> World:
    """Build a box-world from course/layout.json: occupancy features become boxes; pad-ring floor
    markings become circles (centre+radius from their square AABB)."""
    boxes, kinds, rings = [], [], []
    for name, f in layout["features"].items():
        kind = str(f.get("kind", ""))
        b = f["bounds"]
        mn, mx = [float(x) for x in b["min"]], [float(x) for x in b["max"]]
        if "ring" in name.lower():
            cx, cy = (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2
            r_out = max(mx[0] - mn[0], mx[1] - mn[1]) / 2
            rings.append((cx, cy, r_out, 0.0))
            continue
        if not f.get("include_in_occupancy", False):
            continue  # thin floor markings (except rings, handled above) add no geometry to depth
        if not include_net and "net" in kind:
            continue
        boxes.append([mn, mx])
        kinds.append(kind)
    arr = np.array(boxes, dtype=np.float64) if boxes else np.zeros((0, 2, 3))
    return World(boxes=arr, box_kind=kinds, rings=rings)


def _camera_basis(cam: Camera):
    yaw, pitch = math.radians(cam.yaw_deg), math.radians(cam.pitch_deg)
    forward = np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), -math.sin(pitch)])
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 0.0, 1.0])
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)            # camera x: points right when level
    down = np.cross(forward, right)           # camera y: points down; right x down = forward
    return right, down, forward


def intrinsics(cam: Camera, cfg: RenderConfig):
    fx = (cfg.width / 2) / math.tan(math.radians(cam.hfov_deg) / 2)
    fy = fx                                   # square pixels
    cx, cy = cfg.width / 2, cfg.height / 2
    return fx, fy, cx, cy


def _ray_dirs(cam: Camera, cfg: RenderConfig):
    fx, fy, cx, cy = intrinsics(cam, cfg)
    us = (np.arange(cfg.width) - cx) / fx
    vs = (np.arange(cfg.height) - cy) / fy
    xd, yd = np.meshgrid(us, vs)              # (H, W)
    right, down, forward = _camera_basis(cam)
    # direction = xd*right + yd*down + forward, then normalise
    dirs = (xd[..., None] * right + yd[..., None] * down + forward)  # (H, W, 3)
    norm = np.linalg.norm(dirs, axis=2, keepdims=True)
    unit = dirs / norm
    axis_cos = (1.0 / norm[..., 0])           # forward . unit_dir = 1/norm; z = range * axis_cos
    return unit, axis_cos


def _slab_hits(origin, dirs, box_min, box_max):
    """Nearest positive entry distance (euclidean) of each ray into one AABB; inf where it misses."""
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / dirs
        t1 = (box_min - origin) * inv
        t2 = (box_max - origin) * inv
    tmin = np.minimum(t1, t2)
    tmax = np.maximum(t1, t2)
    enter = np.nanmax(tmin, axis=2)
    exit_ = np.nanmin(tmax, axis=2)
    hit = (exit_ >= np.maximum(enter, 0.0)) & (exit_ > 0.0)
    s = np.where(enter > 0.0, enter, exit_)   # if the camera is inside the box, use the exit face
    return np.where(hit, s, np.inf)


def render(world: World, cam: Camera, cfg: RenderConfig | None = None):
    """-> (depth_z float32 HxW metres [NaN=no return], valid bool HxW, mono uint8 HxW, K tuple)."""
    cfg = cfg or RenderConfig()
    rng = np.random.default_rng(cfg.seed)
    origin = np.array(cam.pos, dtype=np.float64)
    unit, axis_cos = _ray_dirs(cam, cfg)
    H, W = cfg.height, cfg.width
    best_s = np.full((H, W), np.inf)
    best_kind = np.full((H, W), -1, dtype=np.int64)

    kinds_order = list(dict.fromkeys(world.box_kind))
    kind_index = {k: i for i, k in enumerate(kinds_order)}
    FLOOR = len(kinds_order)                   # floor gets the next index

    for i in range(world.boxes.shape[0]):
        s = _slab_hits(origin, unit, world.boxes[i, 0], world.boxes[i, 1])
        closer = s < best_s
        best_s = np.where(closer, s, best_s)
        best_kind = np.where(closer, kind_index[world.box_kind[i]], best_kind)

    # floor plane z = floor_z, only where the ray descends
    dz = unit[..., 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        s_floor = (world.floor_z - origin[2]) / dz
    s_floor = np.where((dz < -1e-9) & (s_floor > 0.0), s_floor, np.inf)
    closer = s_floor < best_s
    best_s = np.where(closer, s_floor, best_s)
    best_kind = np.where(closer, FLOOR, best_kind)

    valid = np.isfinite(best_s) & (best_s <= cfg.max_range_m)
    s = np.where(valid, best_s, np.nan)
    if cfg.noise_m > 0:
        s = s + rng.normal(0, cfg.noise_m, s.shape)
    if cfg.dropout > 0:
        drop = (rng.random(s.shape) < cfg.dropout) & valid
        valid = valid & ~drop
        s = np.where(valid, s, np.nan)
    depth_z = (s * axis_cos).astype(np.float32)
    depth_z[~valid] = np.nan

    mono = _shade(world, cam, cfg, origin, unit, best_s, best_kind, kinds_order, FLOOR, valid, rng)
    fx, fy, cx, cy = intrinsics(cam, cfg)
    return depth_z, valid, mono, (fx, fy, cx, cy)


def _shade(world, cam, cfg, origin, unit, best_s, best_kind, kinds_order, FLOOR, valid, rng):
    H, W = cfg.height, cfg.width
    mono = np.full((H, W), 70.0)               # background = far net
    for idx, kind in enumerate(kinds_order):
        mono = np.where(best_kind == idx, _KIND_SHADE.get(kind, 120), mono)
    floor_mask = best_kind == FLOOR
    mono = np.where(floor_mask, _KIND_SHADE["floor"], mono)
    # distance shading: nearer is a little brighter
    with np.errstate(invalid="ignore"):
        shade = np.clip(1.15 - best_s / cfg.max_range_m, 0.5, 1.15)
    mono = mono * np.where(valid, shade, 1.0)
    # pad rings painted on the floor where the ray meets z=0
    if world.rings and floor_mask.any():
        hit = origin + unit * best_s[..., None]
        hx, hy = hit[..., 0], hit[..., 1]
        for cx, cy, r_out, _ in world.rings:
            d = np.hypot(hx - cx, hy - cy)
            ring = floor_mask & (np.abs(d - r_out) < 0.03)
            mono = np.where(ring, _MARKING_SHADE, mono)
    mono = mono + rng.normal(0, cfg.mono_noise, mono.shape)
    return np.clip(np.rint(mono), 0, 255).astype(np.uint8)


def depth_message_bytes(depth_z: np.ndarray) -> bytes:
    """32FC1 little-endian bytes, NaN preserved, as sensor_msgs/Image.data would carry."""
    return np.ascontiguousarray(depth_z, dtype="<f4").tobytes()


def load_layout(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
