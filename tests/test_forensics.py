"""Synthetic-only validation: never evidence of actual PX4 flight behavior."""

from __future__ import annotations

import ast
import builtins
import json
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from aegisland.forensics import analyze
from aegisland.forensics.alignment import load_alignment
from aegisland.forensics.analysis import Thresholds
from aegisland.forensics.cli import main
from aegisland.forensics.fixtures import (
    fixture_payloads,
    jetson_row,
    synthetic_ulog,
    write_fixtures,
)
from aegisland.forensics.ingest import JETSON_FIELDS, ingest_jetson, ingest_px4
from aegisland.forensics.model import Ingestion, sha256, strict_json
from aegisland.forensics.report import REPORT_FILES, write_reports

_FIXTURE_TEMP = tempfile.TemporaryDirectory(prefix="aegisland-forensics-tests-")
FIXTURES = Path(_FIXTURE_TEMP.name)
write_fixtures(FIXTURES)
ULog = pytest.importorskip("pyulog").ULog


def jetson_file(tmp_path, rows):
    path = tmp_path / "jetson.jsonl"
    path.write_text("\n".join(json.dumps(row, allow_nan=True) for row in rows) + "\n")
    return path


def categories(result):
    return {finding.category for finding in result.findings}


def test_generated_fixtures_are_reproducible():
    for name, payload in fixture_payloads().items():
        assert (FIXTURES / name).read_bytes() == payload


def test_published_schema_tracks_required_parser_contract():
    schema_path = Path(__file__).parents[1] / "docs/forensics/jetson-perception.schema.json"
    schema = strict_json(schema_path.read_text())
    assert set(schema["required"]) == JETSON_FIELDS
    assert schema["additionalProperties"] is False
    assert schema["properties"]["executed"]["const"] is False
    assert set(schema["properties"]) == JETSON_FIELDS | {"tracking_valid"}


def test_pyulog_really_decodes_binary_fixture():
    ulog = ULog(str(FIXTURES / "synthetic.ulg"))
    assert ulog.msg_info_dict["forensics_fixture"] == "synthetic-only-v1"
    assert {dataset.name for dataset in ulog.data_list} == {
        "vehicle_local_position",
        "vehicle_status",
        "actuator_motors",
    }
    parsed = ingest_px4(FIXTURES / "synthetic.ulg")
    assert parsed.complete
    assert len(parsed.samples) == 9
    assert parsed.metadata["pyulog_version"] == "1.2.2"
    assert parsed.sha256 == sha256((FIXTURES / "synthetic.ulg").read_bytes())


def test_detects_all_requested_anomalies_and_separates_knowledge():
    result = analyze(FIXTURES / "synthetic.ulg", FIXTURES / "jetson.jsonl")
    assert categories(result) >= {
        "estimator_invalid",
        "tracking_loss",
        "depth_hole",
        "dropped_frame",
        "latency_spike",
        "mode_switch",
        "failsafe",
        "control_saturation_candidate",
        "timestamp_rollback",
    }
    kinds = {(f.category, f.knowledge) for f in result.findings}
    assert ("failsafe", "observed") in kinds
    assert ("control_saturation_candidate", "inferred") in kinds
    assert ("tracking_loss", "observed") in kinds
    assert ("tracking_loss", "inferred") in kinds
    assert ("depth_hole", "inferred") in kinds
    assert ("time_alignment", "unknown") in kinds
    assert result.to_dict()["finding_counts"]["timestamp_rollback"] == 4


@pytest.mark.parametrize(
    "name,category",
    [
        ("empty.ulg", "empty_input"),
        ("corrupt.ulg", "corrupt_log"),
        ("truncated.ulg", "corrupt_log"),
        ("missing-fields.ulg", "missing_field"),
        ("nonfinite.ulg", "nonfinite_value"),
    ],
)
def test_px4_damaged_logs_remain_explicitly_incomplete(name, category):
    result = ingest_px4(FIXTURES / name)
    assert not result.complete
    assert category in categories(result)
    json.dumps(analyze(FIXTURES / name).to_dict(), allow_nan=False)
    if name == "truncated.ulg":
        assert result.samples  # Complete prefix recovered, tail loss remains unknown.


def test_short_and_partial_record_headers(tmp_path):
    for index, payload in enumerate((b"ULog", synthetic_ulog() + b"\x01")):
        path = tmp_path / f"corrupt{index}.ulg"
        path.write_bytes(payload)
        result = ingest_px4(path)
        assert "corrupt_log" in categories(result)
        assert not result.complete


def test_pyulog_structural_failure_is_reported(tmp_path):
    # Framing is valid, but a subscription lacks its required ID and name.
    path = tmp_path / "malformed.ulg"
    path.write_bytes(synthetic_ulog()[:16] + struct.pack("<HB", 1, ord("A")) + b"\x00")
    result = ingest_px4(path)
    assert not result.complete
    assert {"corrupt_log", "no_samples"} <= categories(result)


def test_pyulog_missing_dependency_is_explicit(monkeypatch):
    original_import = builtins.__import__

    def without_pyulog(name, *args, **kwargs):
        if name == "pyulog":
            raise ImportError("synthetic dependency absence")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pyulog)
    result = ingest_px4(FIXTURES / "synthetic.ulg")
    assert "missing_dependency" in categories(result)
    assert not result.complete


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp": -1},
        {"timestamp": 1.5},
        {"timestamp": True},
        {"timestamp": 2**63},
        {"frame_id": "1"},
        {"frame_id": -1},
        {"schema_version": True},
        {"clock": "wall_time"},
        {"depth_coverage": 1.1},
        {"invalid_depth_ratio": -0.1},
        {"line_confidence": float("nan")},
        {"depth_coverage": float("inf")},
        {"latency_ms": -1},
        {"obstacle_distance_m": -1},
        {"latency_ms": True},
        {"dropped_frame": 1},
        {"mode": ""},
        {"decision": {}},
        {"tracking_valid": "false"},
        {"source_hashes": {}},
        {"source_hashes": {"a": "fake"}},
        {"executed": True},
        {"executed": 0},
        {"unexpected_command": "anything"},
    ],
)
def test_jetson_invalid_fields_are_rejected_without_health_inference(tmp_path, changes):
    row = {**jetson_row(), **changes}
    result = ingest_jetson(jetson_file(tmp_path, [row]))
    assert not result.complete and not result.samples
    assert categories(result) & {"corrupt_record", "invalid_record"}


@pytest.mark.parametrize("field", sorted(jetson_row()))
def test_each_required_jetson_field_is_required(tmp_path, field):
    row = jetson_row()
    del row[field]
    result = ingest_jetson(jetson_file(tmp_path, [row]))
    assert not result.complete and not result.samples
    assert "invalid_record" in categories(result)


def test_explicit_null_measurements_are_unknown(tmp_path):
    row = jetson_row()
    for name in (
        "depth_coverage",
        "invalid_depth_ratio",
        "line_confidence",
        "latency_ms",
        "obstacle_distance_m",
    ):
        row[name] = None
    path = jetson_file(tmp_path, [row])
    result = analyze(jetson_path=path)
    assert len(result.jetson.samples) == 1
    assert "unknown_measurement" in categories(result)
    assert "depth_hole" not in categories(result)
    assert "tracking_loss" not in categories(result)
    assert result.to_dict()["coverage"]["depth_hole"]["status"] == "unknown"


def test_corrupt_jsonl_recovers_valid_lines_and_original_line_numbers(tmp_path):
    path = tmp_path / "mixed.jsonl"
    path.write_bytes(b"\xff\n\nnot JSON\n" + json.dumps(jetson_row()).encode() + b"\n")
    result = ingest_jetson(path)
    assert not result.complete
    assert len(result.samples) == 1 and result.samples[0].index == 4
    assert len([f for f in result.findings if f.category == "corrupt_record"]) == 2


@pytest.mark.parametrize("value", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_ambiguous_or_nonfinite_constants(value):
    with pytest.raises(ValueError):
        strict_json(value)


def test_json_numeric_overflow_and_nonobject_rows(tmp_path):
    path = tmp_path / "overflow.jsonl"
    text = json.dumps(jetson_row()).replace('"latency_ms": 12.0', '"latency_ms": 1e999')
    path.write_text(text + "\n[]\nnull\n")
    result = ingest_jetson(path)
    assert not result.samples and not result.complete


def test_empty_inputs_and_unreadable_paths_still_produce_unknown_results(tmp_path):
    for result in (
        analyze(),
        analyze(FIXTURES / "empty.ulg", FIXTURES / "empty.jsonl"),
        analyze(tmp_path / "absent.ulg", tmp_path / "absent.jsonl"),
    ):
        assert not result.px4.samples and not result.jetson.samples
        assert result.alignment.status == "unknown"
        assert all(item["status"] == "unknown" for item in result.to_dict()["coverage"].values())
        assert result.executed is False
        write_reports(result, tmp_path / "empty-report")


def test_out_of_order_is_preserved_not_silently_sorted(tmp_path):
    rows = [jetson_row(i) for i in range(3)]
    rows[2]["timestamp"] = 1
    rows[2]["mode"] = "changed_after_rollback"
    result = analyze(jetson_path=jetson_file(tmp_path, rows))
    assert [s.timestamp for s in result.jetson.samples] == [9_000_000_000, 10_000_000_000, 1]
    assert "timestamp_rollback" in categories(result)
    assert "mode_switch" not in categories(result)  # Cannot compare ambiguous epochs.


def test_thresholds_are_review_settings_and_edge_values_do_not_fire(tmp_path):
    row = jetson_row()
    row.update(depth_coverage=0.5, invalid_depth_ratio=0.5, line_confidence=0.3, latency_ms=100)
    result = analyze(jetson_path=jetson_file(tmp_path, [row]))
    assert not categories(result) & {"tracking_loss", "depth_hole", "latency_spike"}
    result = analyze(
        jetson_path=jetson_file(tmp_path, [row]), thresholds=Thresholds(latency_ms_max=50)
    )
    assert "latency_spike" in categories(result)
    with pytest.raises(ValueError):
        Thresholds(latency_ms_max=float("nan"))


def test_no_alignment_by_start_time_and_no_failsafe_without_status():
    result = analyze(jetson_path=FIXTURES / "aligned-jetson.jsonl")
    assert result.alignment.status == "unknown"
    assert result.to_dict()["coverage"]["failsafe"]["status"] == "unknown"
    assert "failsafe" not in categories(result)


def test_hash_bound_alignment_is_conditional_and_bounded():
    result = analyze(
        FIXTURES / "aligned.ulg", FIXTURES / "aligned-jetson.jsonl", FIXTURES / "alignment.json"
    )
    assert result.alignment.status == "inferred"
    assert result.alignment.map_jetson(10_000_000_000) == 2_000_000
    assert result.alignment.map_jetson(9_000_000_000) == 1_000_000
    assert result.alignment.map_jetson(11_000_000_000) == 3_000_000
    assert result.alignment.map_jetson(8_999_999_999) is None
    assert result.alignment.map_jetson(11_000_000_001) is None
    assert result.alignment.uncertainty_us == 100
    assert result.alignment.drift_ppm == 0
    assert "unverified" in result.alignment.reason


@pytest.fixture
def paired(tmp_path):
    write_fixtures(tmp_path)
    return tmp_path


def mutate_evidence(path, mutate):
    evidence_path = path / "sync-evidence.jsonl"
    rows = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    mutate(rows)
    evidence = "\n".join(json.dumps(row) for row in rows).encode()
    evidence_path.write_bytes(evidence)
    descriptor_path = path / "alignment.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["evidence_sha256"] = sha256(evidence)
    descriptor_path.write_text(json.dumps(descriptor))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.reverse(),
        lambda rows: rows[1].update(event_id=rows[0]["event_id"]),
        lambda rows: rows[1].update(px4_boot_us=4_000_000),
        lambda rows: rows[1].update(uncertainty_us=5001),
        lambda rows: rows[1].update(jetson_monotonic_ns=float("inf")),
        lambda rows: rows[1].update(uncertainty_us=True),
        lambda rows: rows[1].pop("event_id"),
        lambda rows: rows.insert(
            1,
            {
                "event_id": "inconsistent-midpoint",
                "px4_boot_us": 2_010_000,
                "jetson_monotonic_ns": 10_000_000_000,
                "uncertainty_us": 100,
            },
        ),
    ],
)
def test_invalid_clock_observations_cannot_establish_alignment(paired, mutation):
    mutate_evidence(paired, mutation)
    result = analyze(
        paired / "aligned.ulg", paired / "aligned-jetson.jsonl", paired / "alignment.json"
    )
    assert result.alignment.status == "unknown"
    assert result.alignment.map_jetson(10_000_000_000) is None


@pytest.mark.parametrize("tamper", ["input", "evidence", "descriptor", "missing", "executed"])
def test_clock_provenance_failures_are_unknown(paired, tamper):
    if tamper == "input":
        with (paired / "aligned-jetson.jsonl").open("ab") as handle:
            handle.write(b"\n")
    elif tamper == "evidence":
        with (paired / "sync-evidence.jsonl").open("ab") as handle:
            handle.write(b"\n")
    elif tamper == "descriptor":
        (paired / "alignment.json").write_text("[]")
    elif tamper == "missing":
        (paired / "sync-evidence.jsonl").unlink()
    else:
        path = paired / "alignment.json"
        descriptor = json.loads(path.read_text())
        descriptor["executed"] = True
        path.write_text(json.dumps(descriptor))
    result = analyze(
        paired / "aligned.ulg", paired / "aligned-jetson.jsonl", paired / "alignment.json"
    )
    assert result.alignment.status == "unknown"


def test_rollbacks_and_incomplete_sources_disable_mapping(paired):
    descriptor = paired / "alignment.json"
    row = json.loads(descriptor.read_text())
    row["source_hashes"] = {
        "px4": sha256((paired / "synthetic.ulg").read_bytes()),
        "jetson": sha256((paired / "jetson.jsonl").read_bytes()),
    }
    descriptor.write_text(json.dumps(row))
    result = analyze(paired / "synthetic.ulg", paired / "jetson.jsonl", descriptor)
    assert "rollback" in result.alignment.reason
    incomplete = Ingestion("px4", complete=False)
    assert load_alignment(descriptor, incomplete, result.jetson).status == "unknown"


def test_reports_are_offline_self_contained_safe_and_linked_to_input_bytes(tmp_path):
    row = jetson_row()
    row.update(mode='<script>alert("bad")</script>', decision="</script><img src=x onerror=bad>")
    path = jetson_file(tmp_path, [row, {**row, "frame_id": 1, "mode": "review"}])
    result = analyze(jetson_path=path)
    summary = write_reports(result, tmp_path / "report")
    assert all((tmp_path / "report" / name).exists() for name in REPORT_FILES)
    document = (tmp_path / "report" / "report.html").read_text()
    assert "<img src=x" not in document
    assert "<script>alert" not in document
    assert "connect-src 'none'" in document
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)="https?://', document)
    assert 'type="range"' in document
    assert sha256(path.read_bytes()) in document
    embedded = re.search(
        r'<script type="application/json" id="evidence">(.*?)</script>', document, flags=re.DOTALL
    ).group(1)
    assert json.loads(embedded) == summary
    assert json.loads((tmp_path / "report" / "summary.json").read_text()) == summary
    assert "Flight Forensics finding ledger" in (tmp_path / "report" / "findings.md").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node optional for local replay DOM smoke")
def test_replay_interactions_and_nanosecond_precision(tmp_path):
    rows = [jetson_row(i) for i in range(3)]
    for index, row in enumerate(rows):
        row["timestamp"] = 9_007_199_254_740_993 + index * 1000
    report_path = tmp_path / "replay"
    summary = write_reports(analyze(jetson_path=jetson_file(tmp_path, rows)), report_path)
    assert summary["samples"][0]["timestamp_text"] == "9007199254740993"
    result = subprocess.run(
        [
            shutil.which("node"),
            str(Path(__file__).with_name("forensics_replay_smoke.cjs")),
            str(report_path / "report.html"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_report_never_overwrites_inputs(tmp_path):
    input_path = tmp_path / "summary.json"
    original = json.dumps(jetson_row()) + "\n"
    input_path.write_text(original)
    with pytest.raises(ValueError, match="overwrite"):
        write_reports(analyze(jetson_path=input_path), tmp_path)
    assert input_path.read_text() == original


def test_report_never_overwrites_rejected_alignment_evidence(tmp_path):
    evidence = tmp_path / "summary.json"
    evidence.write_text("original rejected clock evidence")
    descriptor = tmp_path / "alignment.json"
    descriptor.write_text(json.dumps({"evidence_file": "summary.json"}))
    result = analyze(alignment_path=descriptor)
    assert result.alignment.status == "unknown"
    with pytest.raises(ValueError, match="overwrite"):
        write_reports(result, tmp_path)
    assert evidence.read_text() == "original rejected clock evidence"


def test_fixture_generation_refuses_different_existing_data(tmp_path):
    (tmp_path / "synthetic.ulg").write_bytes(b"evidence")
    with pytest.raises(ValueError, match="overwrite"):
        write_fixtures(tmp_path)
    assert (tmp_path / "synthetic.ulg").read_bytes() == b"evidence"


def test_executed_boundary_is_not_a_configurable_interface(tmp_path):
    result = analyze(FIXTURES / "synthetic.ulg", FIXTURES / "jetson.jsonl")
    with pytest.raises(FrozenInstanceError):
        result.executed = True
    with pytest.raises(FrozenInstanceError):
        result.px4.samples[0].executed = True

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "executed":
                    assert item is False
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(result.to_dict())
    with pytest.raises(SystemExit):
        main(["report", "--output", str(tmp_path), "--execute"])


def test_no_control_network_or_process_dependencies_in_forensics():
    package = Path(__file__).parents[1] / "src" / "aegisland" / "forensics"
    forbidden = {
        "mavsdk",
        "pymavlink",
        "socket",
        "requests",
        "urllib",
        "subprocess",
        "commands",
        "execution",
        "planner",
        "agent",
        "mavlink_odometry",
        "px4",
    }
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not {part for name in names for part in name.split(".")} & forbidden


def test_cli_complete_partial_and_error_exit_contract(tmp_path, capsys):
    assert main(["fixtures", "--output", str(tmp_path / "fixtures")]) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert (
        main(
            [
                "report",
                "--px4",
                str(FIXTURES / "synthetic.ulg"),
                "--jetson",
                str(FIXTURES / "jetson.jsonl"),
                "--output",
                str(tmp_path / "complete"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["alignment"] == "unknown"
    assert (
        main(
            [
                "report",
                "--px4",
                str(FIXTURES / "corrupt.ulg"),
                "--output",
                str(tmp_path / "partial"),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["incomplete"] is True
    assert (tmp_path / "partial" / "report.html").exists()
    assert main(["report", "--latency-ms-max", "nan", "--output", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().err)["executed"] is False
