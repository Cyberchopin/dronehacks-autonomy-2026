"""Bounded, synthetic-only integration tests; no hardware or network permitted."""

from __future__ import annotations

import builtins
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from aegisland.forensics.cli import main
from aegisland.forensics.integration import audit_bundle, integration_reports, validate_record
from aegisland.forensics.integration_fixtures import bundle_payloads, write_bundle
from aegisland.forensics.model import sha256
from aegisland.forensics.platform_manifest import platform_manifest, preflight, preflight_reports
from aegisland.forensics.recorder import json_bytes, read_regular, record_run, verify_run
from aegisland.forensics.scope import UNASSESSED

_FIXTURE_TEMP = tempfile.TemporaryDirectory(prefix="aegisland-integration-tests-")
FIXTURES = Path(_FIXTURE_TEMP.name)
write_bundle(FIXTURES / "integration-consistent", "consistent")
write_bundle(FIXTURES / "integration-adverse", "adverse")


@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "bundle"
    write_bundle(path)
    return path


def rows(path):
    return [json.loads(line) for line in (path / "records.jsonl").read_text().splitlines()]


def update_rows(path, values):
    (path / "records.jsonl").write_text(
        "\n".join(json.dumps(v, allow_nan=True) for v in values) + "\n"
    )


def manifest(path):
    return json.loads((path / "manifest.json").read_text())


def categories(summary):
    return {f["category"] for f in summary["findings"]}


def assert_no_authority(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"executed", "command_executed"}:
                assert item is False
            if key in {"authority", "authority_change"}:
                assert item == "NONE"
            if key == "full_3d_traversability":
                assert item == "UNKNOWN"
            if key == "supports_3d_traversal":
                assert item is False
            assert_no_authority(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_authority(item)


@pytest.mark.parametrize("scenario", ["consistent", "adverse"])
def test_fixture_generation_is_byte_deterministic(scenario):
    first, second = bundle_payloads(scenario), bundle_payloads(scenario)
    assert first == second
    for name, payload in first.items():
        assert (FIXTURES / f"integration-{scenario}" / name).read_bytes() == payload


def test_consistent_replay_never_increases_authority(bundle):
    summary, sources = audit_bundle(bundle)
    assert summary["findings"] == []
    assert summary["usable_records"] == 12
    assert summary["evidence_quality"] == "consistent_replay_only"
    assert summary["conclusion"]["knowledge"] == "unknown"
    assert_no_authority(summary)
    assert summary["sources"] == {name: sha256(payload) for name, payload in sources.items()}


def test_adverse_fixture_marks_stale_missing_order_calibration_skew_and_contradiction(tmp_path):
    write_bundle(tmp_path / "bad", "adverse")
    summary, _ = audit_bundle(tmp_path / "bad")
    assert categories(summary) >= {
        "stale_frame",
        "missing_frames",
        "out_of_order",
        "calibration_mismatch",
        "clock_skew",
        "contradictory_sensors",
    }
    assert summary["evidence_quality"] == "degraded"
    assert_no_authority(summary)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda rs: rs[0].update(evaluated_at_ns=2_000_000_000), "stale_frame"),
        (lambda rs: rs[0].update(evaluated_at_ns=0), "clock_skew"),
        (
            lambda rs: rs[0].update(evaluation_clock_domain="jetson_monotonic"),
            "unknown_clock_relation",
        ),
        (lambda rs: rs[0].update(calibration_id="wrong"), "calibration_mismatch"),
        (lambda rs: rs[0]["data"].update(sha256="0" * 64), "malformed_evidence"),
        (lambda rs: rs[0].update(timestamp_ns=float("nan")), "malformed_evidence"),
        (lambda rs: rs[1]["data"].update(quaternion_wxyz=[2, 0, 0, 0]), "malformed_evidence"),
        (lambda rs: rs[1]["data"].update(battery_voltage_v=float("inf")), "malformed_evidence"),
        (lambda rs: rs[2]["data"].update(range_m=None), "malformed_evidence"),
        (lambda rs: rs[2]["data"].update(range_m=4.0), "contradictory_sensors"),
        (lambda rs: rs[2]["data"].update(range_status="unknown"), "unknown_sensor_comparison"),
        (lambda rs: rs[2]["data"].update(sigma_m=None), "unknown_sensor_comparison"),
        (lambda rs: rs[3]["data"].update(source_frame_id=99), "unbound_advisory"),
        (lambda rs: rs[3]["data"].update(source_frame_sha256="0" * 64), "unbound_advisory"),
        (lambda rs: rs[3]["data"].update(command_executed=True), "malformed_evidence"),
        (lambda rs: rs[3]["data"].update(authority_change="INCREASE"), "malformed_evidence"),
        (lambda rs: rs[3]["data"].update(advisory_only=False), "malformed_evidence"),
        (lambda rs: rs[0].update(executed=True), "malformed_evidence"),
        (lambda rs: rs[0].update(frame_id=True), "malformed_evidence"),
        (lambda rs: rs[0].pop("clock_domain"), "malformed_evidence"),
        (lambda rs: rs.pop(), "missing_frames"),
        (lambda rs: rs.insert(1, rs[0]), "out_of_order"),
        (lambda rs: rs.reverse(), "out_of_order"),
    ],
)
def test_bad_evidence_can_never_increase_authority(bundle, mutation, expected):
    values = rows(bundle)
    mutation(values)
    update_rows(bundle, values)
    summary, _ = audit_bundle(bundle)
    assert expected in categories(summary)
    assert summary["authority"] == "NONE"
    assert summary["evidence_quality"] == "degraded"
    assert_no_authority(summary)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m["transforms"]["oak-to-body"].update(quaternion_xyzw=[0, 0, 0, 0]),
        lambda m: m["transforms"]["oak-to-body"].update(parent="world_ned"),
        lambda m: m["transforms"]["oak-to-body"].update(convention="child_from_parent"),
        lambda m: m["transforms"]["oak-to-body"].update(calibration_id="wrong"),
        lambda m: m["calibrations"]["oak-c1"].update(intrinsics=[0, 0, 0, 0]),
        lambda m: m["calibrations"]["oak-c1"].update(width=5),
        lambda m: m["calibrations"]["oak-c1"].update(unit="mm"),
    ],
)
def test_calibration_and_transform_validation_is_conservative(bundle, mutation):
    value = manifest(bundle)
    mutation(value)
    (bundle / "manifest.json").write_bytes(json_bytes(value))
    summary, _ = audit_bundle(bundle)
    assert summary["findings"]
    assert summary["usable_records"] < 12
    assert_no_authority(summary)


def test_distinct_clocks_are_not_assumed_aligned_or_contradictory(bundle):
    values = rows(bundle)
    for row in values:
        if row["stream"] == "vl53l1x_downward":
            row.update(clock_domain="vl53_monotonic", evaluation_clock_domain="vl53_monotonic")
            row["data"]["range_m"] = 4.0
    update_rows(bundle, values)
    value = manifest(bundle)
    value["streams"]["vl53l1x_downward"]["clock_domain"] = "vl53_monotonic"
    (bundle / "manifest.json").write_bytes(json_bytes(value))
    summary, _ = audit_bundle(bundle)
    assert "contradictory_sensors" not in categories(summary)
    assert {"unknown_sensor_comparison", "unknown_cross_clock_alignment"} <= categories(summary)


def test_unrelated_rays_or_targets_are_not_compared(bundle):
    values = rows(bundle)
    values[2]["data"].update(comparison_target="different-surface", range_m=4.0)
    update_rows(bundle, values)
    summary, _ = audit_bundle(bundle)
    assert "unknown_sensor_comparison" in categories(summary)
    assert "contradictory_sensors" not in categories(summary)


@pytest.mark.parametrize(
    "raw", [b"", b"[]\n", b"{", b'{"executed":false,"executed":true}\n', b"\xff\n"]
)
def test_corrupt_empty_missing_or_truncated_records_never_elevate(bundle, raw):
    (bundle / "records.jsonl").write_bytes(raw)
    summary, _ = audit_bundle(bundle)
    assert summary["findings"] and summary["usable_records"] == 0
    assert_no_authority(summary)


def test_dropped_frame_id_and_expected_whole_line_loss(bundle):
    value = manifest(bundle)
    for spec in value["streams"].values():
        spec["schedule"][2]["frame_id"] = 4
    (bundle / "manifest.json").write_bytes(json_bytes(value))
    values = rows(bundle)
    for row in values:
        if row["frame_id"] == 2:
            row["frame_id"] = 4
            if row["stream"] == "perception_advisory":
                row["data"]["source_frame_id"] = 4
    update_rows(bundle, values)
    assert "dropped_frame" in categories(audit_bundle(bundle)[0])


def test_bad_manifest_and_missing_bundle_still_generate_unknown(tmp_path):
    for payload in (b"[]", b"null", b"{", b'{"executed":true}'):
        (tmp_path / "manifest.json").write_bytes(payload)
        summary, _ = audit_bundle(tmp_path)
        assert "invalid_bundle" in categories(summary)
        assert_no_authority(summary)
    assert "invalid_bundle" in categories(audit_bundle(tmp_path / "missing")[0])


def test_rejected_manifest_cannot_reflect_an_authority_claim_into_summary(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "dronehacks.integration-replay.v1",
                "executed": False,
                "authority": "NONE",
                "source_type": {"executed": True},
                "origin_environment": {"authority": "CONTROL"},
            }
        )
    )
    summary, sources = audit_bundle(tmp_path)
    assert_no_authority(summary)
    assert summary["source_type"] == "unknown"
    assert summary["origin_environment"]["declaration"] == "unknown"
    record_run(tmp_path / "runs", summary, sources, run_id="rejected")


def test_payload_traversal_symlinks_and_nonregular_files_rejected(bundle, tmp_path):
    values = rows(bundle)
    values[0]["data"]["asset"] = "../outside.npz"
    update_rows(bundle, values)
    assert "malformed_evidence" in categories(audit_bundle(bundle)[0])
    link = bundle / "alias.npz"
    link.symlink_to(bundle / "frames/frame.npz")
    values[0]["data"]["asset"] = "alias.npz"
    update_rows(bundle, values)
    assert "malformed_evidence" in categories(audit_bundle(bundle)[0])
    with pytest.raises(ValueError, match="regular"):
        read_regular(tmp_path)


def test_archive_hash_or_array_changes_are_unknown(bundle):
    # Even an updated declared hash cannot make invalid array dimensions valid.
    import io

    import numpy as np

    payload = io.BytesIO()
    np.savez(
        payload,
        rgb=np.zeros((2, 2, 3), dtype=np.uint8),
        depth_m=np.full((2, 2), float("nan")),
        valid=np.ones((2, 2), dtype=bool),
    )
    data = payload.getvalue()
    (bundle / "frames/frame.npz").write_bytes(data)
    values = rows(bundle)
    for row in values:
        if row["stream"] == "oak_rgb_depth":
            row["data"]["sha256"] = sha256(data)
    update_rows(bundle, values)
    summary, _ = audit_bundle(bundle)
    assert "malformed_evidence" in categories(summary)
    assert_no_authority(summary)


@pytest.mark.parametrize(
    "declared,machine,model,expected,consistent",
    [
        ("desktop", "x86_64", None, "desktop", True),
        ("replay", "x86_64", None, "desktop", True),
        ("sitl", "x86_64", None, "desktop", True),
        ("unknown", "mystery", None, "unknown", True),
        ("jetson_orin_nano", "x86_64", "Orin Nano", "desktop", False),
        ("jetson_orin_nano", "aarch64", None, "unknown", False),
        ("jetson_orin_nano", "aarch64", "Jetson Orin NX", "unknown", False),
        ("jetson_orin_nano", "aarch64", "Jetson Orin Nano", "jetson_orin_nano", True),
    ],
)
def test_platforms_never_promote_desktop_replay_or_sitl_to_measured_hardware(
    declared, machine, model, expected, consistent
):
    result = platform_manifest(declared, machine=machine, system="test", device_model=model)
    assert result["host"]["classification"] == expected
    assert result["declaration_consistent"] is consistent
    assert result["execution_context"] == "replay"
    assert not any(result["measured_validation"].values())
    assert_no_authority(result)


def test_preflight_never_imports_or_opens_hardware_and_does_not_write(tmp_path, monkeypatch):
    original = builtins.__import__

    def restricted(name, *args, **kwargs):
        assert name.split(".")[0] not in {
            "depthai",
            "torch",
            "cupy",
            "mavsdk",
            "pymavlink",
            "socket",
            "subprocess",
        }
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", restricted)
    before = list(tmp_path.iterdir())
    summary = preflight(tmp_path)
    assert list(tmp_path.iterdir()) == before
    assert summary["hardware_readiness"] == "unknown"
    assert summary["checks"]["cuda"]["runtime_available"] is None
    assert summary["checks"]["expected_permissions"]["verified"] is False
    assert_no_authority(summary)


def test_exclusive_recorder_preserves_source_bytes_and_detects_tampering(bundle, tmp_path):
    summary, sources = audit_bundle(bundle)
    before = {name: (bundle / name).read_bytes() for name in sources}
    run = record_run(tmp_path / "runs", summary, sources, integration_reports(summary), "run1")
    assert verify_run(run)["status"] == "observed"
    assert {name: (bundle / name).read_bytes() for name in sources} == before
    for name, payload in sources.items():
        assert (run / "source" / name).read_bytes() == payload
    with pytest.raises(FileExistsError):
        record_run(tmp_path / "runs", summary, sources, run_id="run1")
    (run / "source/records.jsonl").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_run(run)


@pytest.mark.parametrize(
    "failure", ["unsealed", "extra", "symlink", "authority", "summary_source", "summary_count"]
)
def test_failed_or_resealed_inconsistent_runs_cannot_verify(bundle, tmp_path, failure):
    summary, sources = audit_bundle(bundle)
    run = record_run(tmp_path / "runs", summary, sources, run_id="run1")
    if failure == "unsealed":
        (run / "seal.json").unlink()
    elif failure == "extra":
        (run / "extra.txt").write_text("extra")
    elif failure == "symlink":
        (run / "alias").symlink_to(run / "summary.json")
    else:
        if failure == "authority":
            summary["authority"] = "CONTROL"
        elif failure == "summary_count":
            summary["usable_records"] = 99
        else:
            summary["sources"]["records.jsonl"] = "0" * 64
        (run / "summary.json").write_bytes(json_bytes(summary))
        seal = json.loads((run / "seal.json").read_text())
        seal["files"]["summary.json"] = sha256((run / "summary.json").read_bytes())
        (run / "seal.json").write_bytes(json_bytes(seal))
    with pytest.raises((ValueError, OSError)):
        verify_run(run)


def test_recorder_rejects_authority_and_path_escape_before_mkdir(tmp_path):
    with pytest.raises(ValueError):
        record_run(tmp_path / "runs", {"executed": True, "authority": "NONE"}, {}, run_id="id")
    with pytest.raises(ValueError):
        record_run(
            tmp_path / "runs",
            {"executed": False, "authority": "NONE"},
            {"../escape": b"x"},
            run_id="id",
        )
    assert not (tmp_path / "runs").exists()


def test_cli_exclusive_run_verify_preflight_and_invalid_evidence(bundle, tmp_path, capsys):
    root = tmp_path / "runs"
    assert (
        main(
            [
                "integration",
                "--bundle",
                str(bundle),
                "--output-root",
                str(root),
                "--run-id",
                "integration",
            ]
        )
        == 0
    )
    assert_no_authority(json.loads(capsys.readouterr().out))
    assert main(["verify", str(root / "integration")]) == 0
    capsys.readouterr()
    assert main(["preflight", "--output-root", str(root), "--run-id", "preflight"]) == 0
    capsys.readouterr()
    assert verify_run(root / "preflight")["executed"] is False
    assert main(["preflight", "--output-root", str(root), "--run-id", "preflight"]) == 1
    capsys.readouterr()
    assert (
        main(
            [
                "integration",
                "--bundle",
                str(tmp_path / "absent"),
                "--output-root",
                str(root),
                "--run-id",
                "missing",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert verify_run(root / "missing")["status"] == "observed"  # Seal integrity != valid evidence.


def test_record_validator_accepts_only_observational_payloads(bundle):
    row = rows(bundle)[0]
    validate_record(row)
    row["data"]["arming"] = True
    with pytest.raises(ValueError):
        validate_record(row)


def local_plane():
    return {
        "evidence_path": "openings[0].clearance",
        "scope": "local_camera_z_probe_plane",
        "supported_meaning": "observed_local_plane_width_only",
        "local_plane_supported": True,
        "full_3d_traversability": "UNKNOWN",
        "supports_3d_traversal": False,
        "probe_z_m": 2.0,
        "width_at_probe_m": 1.0,
        "sampled_bbox_normalized": [0.1, 0.1, 0.8, 0.8],
        "unassessed": list(UNASSESSED),
        "executed": False,
        "authority_change": "NONE",
        "rejection_reasons": [],
        "rgb_depth_consistency": "unverified",
    }


def test_positive_local_plane_preserves_unknown_3d_and_all_unassessed_limits(bundle):
    values = rows(bundle)
    values[3]["data"]["local_sensing_planes"] = [local_plane()]
    update_rows(bundle, values)
    summary, _ = audit_bundle(bundle)
    advisory = next(
        item["record"]
        for item in summary["replay_records"]
        if item["record"]["stream"] == "perception_advisory"
    )
    preserved = advisory["data"]["local_sensing_planes"][0]
    assert preserved == local_plane()
    assert preserved["local_plane_supported"] is True
    assert summary["geometry"]["full_3d_traversability"] == "UNKNOWN"
    assert_no_authority(summary)


@pytest.mark.parametrize(
    "change",
    [
        {"full_3d_traversability": "SUPPORTED"},
        {"supports_3d_traversal": True},
        {"scope": "full_swept_volume"},
        {"unassessed": []},
        {"width_at_probe_m": None},
        {"sampled_bbox_normalized": [0.5, 0.5, 1, 1]},
        {"rgb_depth_consistency": "ambiguous"},
        {"authority_change": "INCREASE"},
        {"executed": True},
    ],
)
def test_local_support_never_becomes_3d_permission_or_erases_unknowns(bundle, change):
    value = {**local_plane(), **change}
    values = rows(bundle)
    values[3]["data"]["local_sensing_planes"] = [value]
    update_rows(bundle, values)
    summary, _ = audit_bundle(bundle)
    assert "malformed_evidence" in categories(summary)
    assert_no_authority(summary)


def test_recorder_rejects_3d_authority_claim_even_without_execution(tmp_path):
    with pytest.raises(ValueError, match="3D"):
        record_run(
            tmp_path / "runs",
            {"executed": False, "authority": "NONE", "full_3d_traversability": "SUPPORTED"},
            {},
        )


def test_output_cannot_modify_input_bundle(bundle, capsys):
    before = sorted(path.relative_to(bundle) for path in bundle.rglob("*"))
    assert (
        main(["integration", "--bundle", str(bundle), "--output-root", str(bundle / "runs")]) == 1
    )
    assert "outside" in capsys.readouterr().err
    assert sorted(path.relative_to(bundle) for path in bundle.rglob("*")) == before


def test_preflight_report_is_self_contained_and_sealable(tmp_path):
    summary = preflight(tmp_path)
    run = record_run(tmp_path / "runs", summary, {}, preflight_reports(summary), "static")
    assert verify_run(run)["status"] == "observed"
    assert "Hardware readiness unknown" in (run / "report.html").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node optional for replay DOM smoke")
def test_four_stream_replay_controls_use_safe_text_and_keep_unknown_3d(bundle, tmp_path):
    summary, sources = audit_bundle(bundle)
    run = record_run(tmp_path / "runs", summary, sources, integration_reports(summary), "replay")
    script = Path(__file__).with_name("forensics_replay_smoke.cjs")
    result = subprocess.run(
        [shutil.which("node"), str(script), str(run / "report.html"), "--integration"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
