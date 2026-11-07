"""Headless export/replay/sweep checks on renderer fixtures, not real sim evidence."""

import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replay.export_bag import (  # noqa: E402
    DEFAULT_TOPICS,
    EXPECTED_TYPES,
    export_records,
    static_transform,
)
from replay.frames import FrameWriter, load_manifest, load_packet  # noqa: E402
from replay.run import evaluate, level_inputs, write_report  # noqa: E402
from replay.sweep import sweep  # noqa: E402
from simtest.course_render import Camera, RenderConfig, World, render  # noqa: E402
from vision.floor_line import LineConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OPTICAL_TO_FLU = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]])


def header(stamp, frame="optical"):
    return NS(frame_id=frame, stamp=NS(sec=stamp // 10**9, nanosec=stamp % 10**9))


def fixture_records(kind="line", count=12, *, sparse=True):
    """Pinhole depth/mono from course_render; controlled image-space markings.

    Plain white floor and randomly scattered black dots/black stripe are fixture
    textures painted on its lower image region, not recordings or photorealism.
    """
    cfg = RenderConfig(width=320, height=200, mono_noise=0, noise_m=0)
    world = World(np.array([[[5, -10, 0], [5.1, 10, 1.7]]]), ["wall"])
    camera = Camera(pos=(0, 0, 0.8), pitch_deg=0)
    depth, _, mono, (fx, fy, cx, cy) = render(world, camera, cfg)
    stamp = 10**9
    info = NS(
        header=header(stamp), width=cfg.width, height=cfg.height, k=[fx, 0, cx, 0, fy, cy, 0, 0, 1]
    )
    tf = NS(
        header=header(0, "base_link"),
        child_frame_id="optical",
        transform=NS(rotation=NS(w=0.5, x=-0.5, y=0.5, z=-0.5), translation=NS(x=0, y=0, z=0)),
    )
    records = [("tf_static", stamp - 1, NS(transforms=[tf])), ("camera_info", stamp, info)]
    originals = []
    for i in range(count):
        time = stamp + i * 100_000_000
        rng = np.random.default_rng(100 + i)
        gray = mono.copy()
        gray[:] = 230
        gray[:60] = 170
        if kind == "line":
            for y in range(80, cfg.height):
                x = int(155 + i + 0.05 * (cfg.height - y))
                gray[y, x - 4 : x + 4] = 10
        elif kind == "dots":
            for _ in range(180):
                cv2.circle(
                    gray,
                    (int(rng.integers(4, 316)), int(rng.integers(70, 199))),
                    int(rng.integers(1, 4)),
                    10,
                    -1,
                )
        else:
            raise ValueError(kind)
        dz = depth.copy()
        if sparse:
            dz[rng.random(dz.shape) > 0.3] = np.nan
        originals.append((gray.copy(), dz.copy()))
        records.append(
            (
                "mono",
                time + 2,
                NS(
                    header=header(time, "left_optical"),
                    width=cfg.width,
                    height=cfg.height,
                    encoding="mono8",
                    step=cfg.width,
                    is_bigendian=False,
                    data=gray.tobytes(),
                ),
            )
        )
        records.append(
            (
                "depth",
                time + 3,
                NS(
                    header=header(time),
                    width=cfg.width,
                    height=cfg.height,
                    encoding="32FC1",
                    step=cfg.width * 4,
                    is_bigendian=False,
                    data=dz.astype("<f4").tobytes(),
                ),
            )
        )
        records.append(
            (
                "attitude",
                time + 4,
                NS(
                    timestamp=100_000 + i * 100_000,
                    timestamp_sample=100_000 + i * 100_000,
                    q=[1, 0, 0, 0],
                ),
            )
        )
        records.append(
            (
                "position",
                time + 5,
                NS(
                    timestamp=100_000 + i * 100_000,
                    timestamp_sample=100_000 + i * 100_000,
                    dist_bottom=0.8,
                    dist_bottom_valid=True,
                ),
            )
        )
    return sorted(records, key=lambda x: x[1]), originals


def make_export(out, *, kind="line", count=12, records=None, **options):
    records = records if records is not None else fixture_records(kind, count)[0]

    def factory(roles):
        return (record for record in records if record[0] in roles)

    available = {DEFAULT_TOPICS[r]: EXPECTED_TYPES[r] for r in {r[0] for r in records}}
    return export_records(
        factory,
        available,
        out,
        bag_name="synthetic-fixture",
        every=1,
        command="synthetic fixture (no bag)",
        source_kind="synthetic renderer",
        **options,
    )


@pytest.fixture
def line_folder(tmp_path):
    folder = tmp_path / "line_frames"
    make_export(folder)
    return folder


def test_npz_manifest_roundtrip_and_nearest_stamps(tmp_path):
    records, originals = fixture_records(count=3)
    folder = tmp_path / "frames"
    doc = make_export(folder, records=records)
    assert load_manifest(folder) == doc
    assert doc["counts"]["mono"] == doc["exported_counts"]["mono"] == 3
    assert doc["sim_time_span_ns"] == [10**9, 1_200_000_000]
    frames = doc["frames"]
    mono = next(f for f in frames if f["role"] == "mono")
    depth = next(f for f in frames if f["role"] == "depth")
    assert load_packet(folder, mono)["data"].tobytes() == originals[0][0].tobytes()
    assert load_packet(folder, depth)["data"].tobytes() == originals[0][1].astype("<f4").tobytes()
    assert depth["attitude"]["timestamp_us"] == 100_000  # boot clock isn't image time
    assert depth["attitude"]["delta_ns"] == 1  # future nearest allowed, explicitly recorded
    assert depth["position"]["delta_ns"] == 2
    np.testing.assert_allclose(depth["extrinsics"]["rotation"], OPTICAL_TO_FLU)
    assert depth["camera_info"]["status"] == "KNOWN"


def test_sampling_limits_and_no_overwrite(tmp_path):
    records, _ = fixture_records(count=10)
    available = {DEFAULT_TOPICS[r]: EXPECTED_TYPES[r] for r, _, _ in records}

    def factory(roles):
        return (r for r in records if r[0] in roles)

    out = tmp_path / "sampled"
    doc = export_records(factory, available, out, bag_name="fixture", every=3, max_frames=6)
    assert len(doc["frames"]) == 6 and doc["limit_reached"] == "max_frames"
    assert [f["stamp_ns"] for f in doc["frames"] if f["role"] == "mono"] == [
        10**9,
        1_300_000_000,
        1_600_000_000,
    ]
    with pytest.raises(FileExistsError):
        make_export(out)
    small = tmp_path / "small"
    doc = make_export(small, max_mb=0.08)
    assert sum(p.stat().st_size for p in small.iterdir()) <= 80_000
    assert doc["limit_reached"] == "max_mb"


def test_report_outputs_traces_sparse_depth_and_embedded_thumbnails(line_folder, tmp_path):
    out = tmp_path / "report"
    report = write_report(line_folder, out, line_config=LineConfig(polarity="dark"))
    saved = json.loads((out / "report.json").read_text())
    assert saved == report
    assert report["summary"]["detection_rate"] > 0.9
    assert 0.2 < report["summary"]["mean_depth_valid_fraction"] < 0.35
    assert report["summary"]["leveled_frames"] == 12
    assert report["summary"]["floor_filtered_frames"] == 12
    assert len(report["thumbnails"]) == 10
    assert all(not r["advisory"]["executed"] for r in report["line_frames"])
    assert all(len(r["depth"]["sectors"]) == 7 for r in report["depth_frames"])
    html = (out / "report.html").read_text()
    assert "data:image/png;base64," in html and "<svg " in html
    assert 'src="http' not in html and "<script src=" not in html
    assert "synthetic renderer" in html and "UNKNOWN" in html
    assert "Per-sector ray range" in html and "Steering advisory" in html


def test_sweep_ranks_dark_above_bright(line_folder):
    rows = sweep(line_folder, roi_tops=(0.35,), contrast_deltas=(18,))
    assert rows[0]["polarity"] == "dark"
    assert rows[0]["detection_rate"] > 0.9
    assert rows[0]["detection_rate"] > rows[1]["detection_rate"]
    assert rows[0]["ambiguity_rate"] == 0


def test_dense_depth_reports_wall_ranges(tmp_path):
    records, _ = fixture_records(count=2, sparse=False)
    folder = tmp_path / "dense"
    make_export(folder, records=records)
    report = evaluate(folder)
    assert report["summary"]["unknown_sector_rate"] == 0
    for row in report["depth_frames"]:
        assert row["depth"]["sectors"][3]["nearest_m"] == pytest.approx(5, abs=0.03)


def test_dark_dots_do_not_become_a_line(tmp_path):
    folder = tmp_path / "dots"
    make_export(folder, kind="dots", count=16)
    report = evaluate(folder, line_config=LineConfig(polarity="dark"))
    # Keep this strict: do not retune detector/test to hide a dotted-floor false positive.
    assert report["summary"]["detection_rate"] <= 0.1
    assert report["rejection_reason_counts"]
    assert all(not r["advisory"]["steer"] for r in report["line_frames"])


def test_missing_topics_and_transforms_are_unknown(tmp_path):
    records, _ = fixture_records(count=2)
    records = [r for r in records if r[0] not in {"tf_static", "position"}]
    folder = tmp_path / "missing"
    doc = make_export(folder, records=records)
    assert doc["topics"]["position"]["status"] == "UNKNOWN"
    report = evaluate(folder)
    assert report["summary"]["leveled_frames"] == 0
    assert report["leveling_unknown_reasons"]
    assert all(not r["depth"]["leveled"] for r in report["depth_frames"])


def test_calibration_and_stale_invalid_telemetry(line_folder):
    frame = next(f for f in load_manifest(line_folder)["frames"] if f["role"] == "depth")
    rotation, height, _, _ = level_inputs(frame)
    np.testing.assert_allclose(rotation, OPTICAL_TO_FLU)
    assert height == pytest.approx(0.8)
    frame["position"]["dist_bottom_valid"] = False
    assert level_inputs(frame)[1] is None
    frame["attitude"]["delta_ns"] = 201_000_000
    assert level_inputs(frame)[0] is None
    frame["attitude"]["delta_ns"] = 0
    frame["attitude"]["q_wxyz"] = [0, 0, 0, 0]
    assert level_inputs(frame)[0] is None


def test_corrupt_packet_is_counted_not_silently_dropped(line_folder):
    doc = load_manifest(line_folder)
    f = next(f for f in doc["frames"] if f["role"] == "mono")
    (line_folder / f["file"]).write_bytes(b"corrupt synthetic packet")
    report = evaluate(line_folder)
    assert report["summary"]["input_error_count"] == 1
    assert report["summary"]["mono_frames"] == 12
    assert report["summary"]["detection_rate"] == pytest.approx(11 / 12)


def test_static_tf_chain_composition_and_conflict():
    a, b = np.eye(4), np.eye(4)
    a[:3, :3] = OPTICAL_TO_FLU
    b[2, 3] = 0.1
    resolved = static_transform({("mount", "optical"): a, ("base", "mount"): b}, "optical", "base")
    assert resolved["status"] == "KNOWN" and resolved["translation_m"][2] == 0.1
    assert static_transform({("base", "optical"): None}, "optical", "base")["status"] == "UNKNOWN"


def test_export_has_no_ros_import_side_effect_or_publication():
    path = ROOT / "replay/export_bag.py"
    tree = ast.parse(path.read_text())
    forbidden = {
        "create_publisher",
        "publish",
        "spin",
        "spin_once",
        "init",
        "Recorder",
        "Player",
        "SequentialWriter",
    }
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden
        for n in ast.walk(tree)
    )
    spec = importlib.util.spec_from_file_location("export_without_ros", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.export_records)


def test_cli_replay_and_sweep(line_folder, tmp_path):
    out = tmp_path / "cli-report"
    run = subprocess.run(
        [
            sys.executable,
            "replay/run.py",
            str(line_folder),
            "--out",
            str(out),
            "--polarity",
            "dark",
            "--roi-top",
            ".35",
            "--contrast-delta",
            "18",
            "--sectors",
            "5",
            "--max-range",
            "8",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert (out / "report.html").stat().st_size > 1000
    result = subprocess.run(
        [
            sys.executable,
            "replay/sweep.py",
            str(line_folder),
            "--roi-tops",
            ".35",
            "--contrast-deltas",
            "18",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "dark" in result.stdout.splitlines()[1]
    assert "no flight-time configuration written" in result.stdout


def test_empty_export_denominators_are_unknown(tmp_path):
    folder = tmp_path / "empty"
    writer = FrameWriter(folder, {"bag_name": "empty", "topics": {}})
    writer.finish()
    report = evaluate(folder)
    assert report["summary"]["detection_rate"] is None
    assert report["summary"]["unknown_sector_rate"] is None
    with pytest.raises(ValueError, match="no mono"):
        sweep(folder)


def test_multiple_static_parents_are_unknown():
    assert (
        static_transform(
            {("a", "optical"): np.eye(4), ("b", "optical"): np.eye(4)}, "optical", "a"
        )["status"]
        == "UNKNOWN"
    )


def test_nearest_invalid_attitude_is_not_replaced_by_a_farther_valid_sample(tmp_path):
    records, _ = fixture_records(count=1)
    records.append(
        ("attitude", 10**9 + 3, NS(timestamp=99_999, timestamp_sample=99_998, q=[0, 0, 0, 0]))
    )
    records.sort(key=lambda r: r[1])
    folder = tmp_path / "invalid-attitude"
    doc = make_export(folder, records=records)
    depth = next(f for f in doc["frames"] if f["role"] == "depth")
    assert depth["attitude"]["status"] == "UNKNOWN"
    assert depth["attitude"]["timestamp_sample_us"] == 99_998
    report = evaluate(folder)
    assert report["summary"]["leveled_frames"] == 0
    assert report["summary"]["input_error_count"] == 0  # usable legacy depth, bad attitude flagged


def test_corrupt_camera_info_makes_all_sectors_unknown(line_folder):
    doc = load_manifest(line_folder)
    info = next(f for f in doc["frames"] if f["role"] == "camera_info")
    (line_folder / info["file"]).write_bytes(b"corrupt synthetic calibration")
    report = evaluate(line_folder)
    assert report["summary"]["unknown_sector_rate"] == 1
    assert report["summary"]["input_error_count"] == 12
    assert report["summary"]["mean_depth_valid_fraction"] > 0.2


def test_missing_camera_info_and_explicit_calibration(tmp_path):
    records, _ = fixture_records(count=2)
    records = [r for r in records if r[0] not in {"camera_info", "tf_static"}]
    folder = tmp_path / "explicit"
    doc = make_export(
        folder,
        records=records,
        extrinsics={
            "base_frame": "base_link",
            "optical_frame": "optical",
            "rotation": OPTICAL_TO_FLU.tolist(),
            "translation_m": [0, 0, 0.1],
            "source": "synthetic fixture only",
        },
    )
    depth = next(f for f in doc["frames"] if f["role"] == "depth")
    assert depth["extrinsics"]["status"] == "KNOWN"
    assert depth["camera_info"]["status"] == "UNKNOWN"
    report = evaluate(folder)
    assert report["summary"]["unknown_sector_rate"] == 1


def test_missing_ros_has_clear_error(monkeypatch):
    from replay.export_bag import ros_source

    monkeypatch.setitem(sys.modules, "rosbag2_py", None)
    with pytest.raises(RuntimeError, match="ROS 2 Jazzy"):
        ros_source("unused")


def test_ros_reader_adapter_is_read_only_with_fake_jazzy_boundary(monkeypatch, tmp_path):
    from replay import export_bag
    from types import ModuleType

    records, _ = fixture_records(count=2)
    calls = []

    class Reader:
        def open(self, storage, converter):
            calls.append((storage.uri, storage.storage_id))
            self.items = iter([])

        def get_all_topics_and_types(self):
            return [NS(name=DEFAULT_TOPICS[r], type=EXPECTED_TYPES[r]) for r in DEFAULT_TOPICS]

        def set_filter(self, filter):
            self.items = iter(
                (DEFAULT_TOPICS[r], m, t)
                for r, t, m in records
                if DEFAULT_TOPICS[r] in filter.topics
            )
            self.next_item = next(self.items, None)

        def has_next(self):
            return self.next_item is not None

        def read_next(self):
            item = self.next_item
            self.next_item = next(self.items, None)
            return item

    def install(name, **members):
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)

    install(
        "rosbag2_py",
        SequentialReader=Reader,
        StorageOptions=NS,
        StorageFilter=NS,
        ConverterOptions=lambda *args: None,
    )
    install("rclpy")
    install("rclpy.serialization", deserialize_message=lambda m, t: m)
    install("rosidl_runtime_py")
    install("rosidl_runtime_py.utilities", get_message=lambda name: name)
    out = tmp_path / "adapter"
    export_bag.main([str(tmp_path / "existing-bag"), "--out", str(out), "--every", "1"])
    assert load_manifest(out)["exported_counts"] == {"camera_info": 1, "mono": 2, "depth": 2}
    assert len(calls) == 3  # inspect metadata, read image streams, read telemetry/TF
