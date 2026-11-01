"""Known synthetic samples validate the contract, never vendor performance claims."""

import json
from pathlib import Path

import pytest

from aegisland.benchmark_adapters import euroc_inputs, frame, legacy, recorded, unavailable_memory
from aegisland.benchmark_contract import (
    read_jsonl,
    strict_json,
    summarize,
    validate_frames,
    validate_platform,
)
from aegisland.benchmark_harness import (
    accuracy,
    checksum_index,
    main,
    read_json,
    run,
    sha256,
    verify_run,
    write_json,
)

DESKTOP = {
    "kind": "desktop",
    "hardware": "test CPU",
    "machine": "x86_64",
    "device_model": "synthetic test host",
}


def config(tmp_path, **changes):
    return {
        "adapter": "aegisland-vdr",
        "output_root": str(tmp_path / "runs"),
        "expected_frames": 8,
        "warmup_frames": 1,
        "seed": 7,
        "platform": "desktop",
        "hardware": "test CPU",
        "rpe_delta_frames": 2,
        "max_time_difference_s": 0.005,
        "format": "legacy",
        **changes,
    }


def jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def pose(x):
    return {"position_m": [x, x * x, 0.0], "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0]}


@pytest.mark.parametrize(
    "text",
    [
        '{"v":NaN}',
        '{"v":Infinity}',
        '{"v":-Infinity}',
        '{"v":[1e999]}',
        '{"a":1,"a":2}',
    ],
)
def test_strict_json_rejects_nonfinite_and_duplicate_keys(text):
    with pytest.raises(ValueError):
        strict_json(text)


@pytest.mark.parametrize(
    "content,count",
    [
        ('{"timestamp_ns":1}', 1),  # even a complete last object requires its commit newline
        ('{"timestamp_ns":1}\n{"timestamp_ns":', 2),
        ('{"timestamp_ns":1}\n', 2),  # truncation at a whole-line boundary
        ('{"timestamp_ns":1}\n{"timestamp_ns":1}\n', 2),
        ('{"timestamp_ns":2}\n{"timestamp_ns":1}\n', 2),
        ('{"timestamp_ns":true}\n', 1),
        ('{"timestamp_ns":1}\n\n', 2),
        ('{"timestamp_ns":1,"signal":1e999}\n', 1),
    ],
)
def test_jsonl_rejects_truncation_timestamps_and_counts(tmp_path, content, count):
    path = tmp_path / "frames.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError):
        read_jsonl(path, count)


def test_cold_warm_percentiles_drop_loss_recovery_and_coverage():
    rows = [
        frame(0, "lost", 100, "startup"),
        frame(10_000_000, "ok", 1),
        frame(20_000_000, "dropped", reason="queue_overflow"),
        frame(30_000_000, "lost", 3, "no_pose"),
        frame(50_000_000, "ok", 5),
        frame(60_000_000, "lost", 7, "no_pose"),
    ]
    result = summarize(rows, "aegisland-vdr", 1, wall_s=2)
    assert result["latency_ms"]["cold"]["p50"] == 100
    assert result["latency_ms"]["warm"]["p50"] == 4
    assert result["latency_ms"]["warm"]["p95"] == pytest.approx(6.7)
    assert result["latency_ms"]["warm"]["p99"] == pytest.approx(6.94)
    assert result["drop_rate"] == pytest.approx(1 / 6)
    assert result["fps"]["attempted_wall"] == 2.5
    assert result["coverage"]["successful_frame_fraction"] == pytest.approx(2 / 6)
    assert result["tracking"]["loss_episodes"] == [
        {"start_ns": 20_000_000, "recovered_ns": 50_000_000, "recovery_ms": 30},
        {"start_ns": 60_000_000, "recovered_ns": None, "recovery_ms": None},
    ]


@pytest.mark.parametrize(
    "changes,adapter",
    [
        ({"executed": True}, "aegisland-vdr"),
        ({"latency_ms": float("nan")}, "aegisland-vdr"),
        ({"latency_ms": -1}, "aegisland-vdr"),
        ({"coverage": 1.1}, "aegisland-vdr"),
        ({"status": "lost"}, "aegisland-vdr"),
        ({"pose": pose(1)}, "aegisland-vdr"),
        ({}, "cuvslam-stereo"),
        ({"status": "lost", "failure_reason": "unavailable"}, "oak-depthai-stereo"),
    ],
)
def test_frame_contract_rejects_invalid_or_mislabelled_samples(changes, adapter):
    with pytest.raises(ValueError):
        validate_frames([{**frame(0, "ok", 1), **changes}], adapter, 1)


def test_desktop_cannot_be_orin():
    with pytest.raises(ValueError, match="desktop != Orin"):
        validate_platform({**DESKTOP, "kind": "orin"})
    assert (
        validate_platform(
            {
                **DESKTOP,
                "kind": "orin",
                "machine": "aarch64",
                "device_model": "NVIDIA Jetson Orin Nano",
            }
        )["kind"]
        == "orin"
    )


@pytest.mark.parametrize("mode", ["stereo", "inertial"])
def test_legacy_cuvslam_counts_pose_and_origin(tmp_path, mode):
    rows = [{"timestamp_ns": i * 50_000_000, "tracked": True, "track_ms": i + 1} for i in range(3)]
    jsonl(tmp_path / "frames.jsonl", rows)
    metadata = {
        "mode": mode,
        "platform": "Linux x86_64 WSL2",
        "counts": {"stereo_frames": 3, "tracked_frames": 3, "untracked_frames": 0},
        "timing": {"total_wall_s": 1},
    }
    write_json(tmp_path / "run.json", metadata)
    trajectory = tmp_path / "trajectory_body.tum"
    trajectory.write_text("0 0 0 0 0 0 0 1\n0.05 1 0 0 0 0 0 1\n0.1 2 0 0 0 0 0 1\n")
    converted, info = legacy(tmp_path, "cuvslam-" + mode, 3, DESKTOP)
    assert converted[-1]["pose"]["position_m"] == [2, 0, 0]
    assert info["wall_s"] == 1
    with pytest.raises(ValueError, match="desktop != Orin"):
        legacy(
            tmp_path,
            "cuvslam-" + mode,
            3,
            {**DESKTOP, "kind": "orin", "machine": "aarch64", "device_model": "Jetson Orin"},
        )
    trajectory.write_text(trajectory.read_text().replace("0.1 2", "0.05 2"))
    with pytest.raises(ValueError, match="duplicate"):
        legacy(tmp_path, "cuvslam-" + mode, 3, DESKTOP)
    metadata["counts"]["stereo_frames"] = 4
    write_json(tmp_path / "run.json", metadata)
    with pytest.raises(ValueError, match="count"):
        legacy(tmp_path, "cuvslam-" + mode, 3, DESKTOP)


def test_legacy_vdr_does_not_invent_per_frame_timings(tmp_path):
    jsonl(
        tmp_path / "frames.jsonl",
        [
            {"timestamp_ns": 0, "valid": False, "x_normalized": 0, "y_normalized": 0},
            {"timestamp_ns": 1, "valid": True, "x_normalized": 0.1, "y_normalized": 0},
        ],
    )
    write_json(tmp_path / "run.json", {"counts": {"frames": 2, "valid": 1}})
    rows, _ = legacy(tmp_path, "aegisland-vdr", 2, DESKTOP)
    metrics = summarize(rows, "aegisland-vdr")
    assert metrics["latency_ms"]["warm"]["p99"] is None
    assert metrics["fps"]["attempted_wall"] is None
    assert accuracy(rows, "aegisland-vdr", None, 1, 0.005)["ate_se3"] is None


def test_ffs_research_preserves_pixel_coverage_and_allocator_scope(tmp_path):
    jsonl(
        tmp_path / "frames.jsonl",
        [
            {
                "timestamp_ns": i,
                "ffs_invalid_fraction": 0.25,
                "ffs_rectify_ms": 1,
                "ffs_upload_pad_ms": 2,
                "ffs_model_ms": 3,
                "ffs_post_ms": 4,
            }
            for i in range(2)
        ],
    )
    write_json(tmp_path / "summary.json", {"frames": 2, "peak_cuda_memory_mb": 2})
    rows, info = legacy(tmp_path, "ffs-research", 2, DESKTOP)
    metrics = summarize(rows, "ffs-research")
    assert metrics["coverage"]["mean_valid_pixel_fraction"] == 0.75
    assert metrics["latency_ms"]["warm"]["p99"] == 10
    assert metrics["tracking"]["loss_episodes"] is None
    assert info["memory"]["peak_vram_bytes"] == 2 * 2**20
    assert "allocator" in info["memory"]["vram_scope"]


def producer(tmp_path):
    source = tmp_path / "producer"
    source.mkdir()
    rows = [frame(0, "ok", 3, coverage=0.8), frame(50_000_000, "dropped", reason="queue_overflow")]
    jsonl(source / "frames.jsonl", rows)
    metadata = {
        "schema_version": 1,
        "executed": False,
        "adapter": "oak-depthai-stereo",
        "expected_frames": 2,
        "timestamps_ns": [0, 50_000_000],
        "platform": DESKTOP,
        "latency_scope": "synthetic test producer latency",
        "head": "test-revision",
        "environment": {},
        "command": ["test-producer"],
        "memory": unavailable_memory(),
    }
    write_json(source / "metadata.json", metadata)
    return source


def test_oak_recorded_schedule_and_no_flight_execution(tmp_path):
    source = producer(tmp_path)
    rows, _ = recorded(source, "oak-depthai-stereo", 2)
    assert all(r["executed"] is False for r in rows)
    metadata = read_json(source / "metadata.json")
    metadata["timestamps_ns"] = [0, 60_000_000]
    write_json(source / "metadata.json", metadata)
    with pytest.raises(ValueError, match="schedule"):
        recorded(source, "oak-depthai-stereo", 2)


def test_import_is_unique_readonly_and_detects_tampering(tmp_path):
    source = producer(tmp_path)
    original = {p.name: sha256(p) for p in source.iterdir()}
    options = config(
        tmp_path,
        adapter="oak-depthai-stereo",
        source=str(source),
        format="contract",
        expected_frames=2,
    )
    first, ok = run(options, ["test"])
    second, ok2 = run(options, ["test"])
    assert ok and ok2 and first != second
    result = verify_run(first)
    assert result["platform"] == DESKTOP
    assert not result["valid_for_performance_claims"]
    assert result["accuracy"]["ate_se3"] is None
    assert original == {p.name: sha256(p) for p in source.iterdir()}
    assert all(
        (first / name).is_file()
        for name in (
            "manifest.json",
            "config.json",
            "command.json",
            "revision.json",
            "environment.json",
            "SHA256SUMS",
            "result.json",
        )
    )
    (first / "frames.jsonl").write_text((first / "frames.jsonl").read_text().rstrip())
    with pytest.raises(ValueError, match="SHA256"):
        verify_run(first)


def test_failed_input_has_manifest_environment_and_hashes(tmp_path):
    source = producer(tmp_path)
    (source / "frames.jsonl").write_text('{"timestamp_ns":0}')
    output, ok = run(
        config(
            tmp_path,
            adapter="oak-depthai-stereo",
            source=str(source),
            format="contract",
            expected_frames=2,
        ),
        ["test"],
    )
    assert not ok
    manifest = read_json(output / "manifest.json")
    assert manifest["status"] == "failed" and manifest["executed"] is False
    assert "truncated" in manifest["failure"]["reason"]
    assert (output / "environment.json").exists() and (output / "SHA256SUMS").exists()


def test_native_vdr_smoke_and_wrong_platform_failure(tmp_path):
    output, ok = run(config(tmp_path), ["test"])
    assert ok
    result = verify_run(output)
    assert result["metrics"]["counts"]["expected"] == 8
    assert result["accuracy"]["reason"] == "adapter has no metric localization pose"
    assert (output / "synthetic-inputs.npz").is_file()
    failed, ok = run(config(tmp_path, platform="orin"), ["test"])
    assert not ok and "Orin" in read_json(failed / "manifest.json")["failure"]["reason"]


def test_cli_records_missing_dependency_source_as_failure(tmp_path, capsys):
    assert (
        main(
            [
                "run",
                "--adapter",
                "cuvslam-stereo",
                "--expected-frames",
                "2",
                "--output-root",
                str(tmp_path),
            ]
        )
        == 1
    )
    reply = json.loads(capsys.readouterr().out)
    assert reply["executed"] is False
    assert read_json(Path(reply["output"]) / "manifest.json")["status"] == "failed"


def test_known_metric_trajectory_reuses_existing_ate_rpe(tmp_path):
    rows = [frame(i * 50_000_000, "ok", 1, pose=pose(i)) for i in range(5)]
    truth = tmp_path / "truth.csv"
    truth.write_text(
        "".join(f"{r['timestamp_ns']},{i},{i * i},0,1,0,0,0\n" for i, r in enumerate(rows))
    )
    result = accuracy(rows, "cuvslam-stereo", truth, 1, 0.005)
    assert result["ate_se3"]["rmse"] == pytest.approx(0, abs=1e-10)
    assert result["rpe"]["translation_rmse_m"] == pytest.approx(0, abs=1e-10)
    assert accuracy(rows, "cuvslam-stereo", truth, 20, 0.005)["rpe"] is None
    truth.write_text(truth.read_text() + truth.read_text().splitlines()[-1] + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        accuracy(rows, "cuvslam-stereo", truth, 1, 0.005)


def test_result_reader_rejects_inconsistent_resealed_summary(tmp_path):
    source = producer(tmp_path)
    output, ok = run(
        config(
            tmp_path,
            adapter="oak-depthai-stereo",
            source=str(source),
            format="contract",
            expected_frames=2,
        ),
        ["test"],
    )
    assert ok
    result = read_json(output / "result.json")
    result["metrics"]["counts"]["expected"] = 3
    write_json(output / "result.json", result)
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksum_index(output).items())
    )
    with pytest.raises(ValueError, match="disagree"):
        verify_run(output)


def test_source_hash_mismatch_is_preserved_as_failed_run(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    write_json(source / "run.json", {"counts": {"frames": 1, "valid": 1}})
    jsonl(
        source / "frames.jsonl",
        [{"timestamp_ns": 0, "valid": True, "x_normalized": 0, "y_normalized": 0}],
    )
    (source / "SHA256SUMS").write_text(f"{'0' * 64}  frames.jsonl\n")
    origin = tmp_path / "origin.json"
    write_json(origin, DESKTOP)
    output, ok = run(
        config(tmp_path, source=str(source), origin_platform=str(origin), expected_frames=1),
        ["test"],
    )
    assert not ok
    assert "SHA256" in read_json(output / "manifest.json")["failure"]["reason"]
    assert "source/SHA256SUMS" in checksum_index(output)


def test_error_frames_cannot_be_accepted_as_successful_run(tmp_path):
    source = producer(tmp_path)
    jsonl(
        source / "frames.jsonl",
        [frame(0, "ok", 3, coverage=0.8), frame(50_000_000, "error", 1, "device_error")],
    )
    output, ok = run(
        config(
            tmp_path,
            adapter="oak-depthai-stereo",
            source=str(source),
            format="contract",
            expected_frames=2,
        ),
        ["test"],
    )
    assert not ok
    assert "error frames" in read_json(output / "manifest.json")["failure"]["reason"]
    with pytest.raises(ValueError, match="did not complete"):
        verify_run(output)


def test_euroc_prefix_and_count_validation_before_decode(tmp_path, monkeypatch):
    import cv2
    import numpy as np

    camera = tmp_path / "cam0"
    (camera / "data").mkdir(parents=True)
    (camera / "data.csv").write_text("# timestamp,filename\n0,a.png\n50000000,b.png\n")
    cv2.imwrite(str(camera / "data" / "a.png"), np.zeros((16, 16), dtype=np.uint8))
    images, stamps, paths = euroc_inputs(tmp_path, expected_frames=1, max_frames=1)
    assert len(images) == 1 and stamps == [0] and len(paths) == 2

    def fail_decode(*args):
        pytest.fail("count mismatch must be rejected before decoding")

    monkeypatch.setattr(cv2, "imread", fail_decode)
    with pytest.raises(ValueError, match="frame count"):
        euroc_inputs(tmp_path, expected_frames=1)


def test_no_tracked_frames_cannot_hide_nonempty_trajectory(tmp_path):
    write_json(
        tmp_path / "run.json",
        {
            "mode": "stereo",
            "counts": {"stereo_frames": 1, "tracked_frames": 0, "untracked_frames": 1},
            "timing": {},
        },
    )
    jsonl(tmp_path / "frames.jsonl", [{"timestamp_ns": 0, "tracked": False, "track_ms": 1}])
    (tmp_path / "trajectory_body.tum").write_text("0 0 0 0 0 0 0 1\n")
    with pytest.raises(ValueError, match="poses without tracked"):
        legacy(tmp_path, "cuvslam-stereo", 1, DESKTOP)
