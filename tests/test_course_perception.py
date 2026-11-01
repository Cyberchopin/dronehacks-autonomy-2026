import json
from dataclasses import replace

import cv2
import numpy as np
import pytest

from aegisland.course_config import CourseConfig
from aegisland.course_perception import CoursePerception
from aegisland.course_replay import load_recording, run
from aegisland.course_synthetic import suite, synthetic_frame
from aegisland.depth_sectors import Intrinsics, SectorConfig


@pytest.fixture
def perception():
    return CoursePerception()


@pytest.mark.parametrize("kind", ["line", "maze"])
@pytest.mark.parametrize(
    "width,height,offset", [(160, 120, -0.23), (320, 240, 0.0), (640, 480, 0.22), (480, 240, -0.15)]
)
def test_line_and_maze_generalize_across_resolution_and_translation(
    perception, kind, width, height, offset
):
    line = perception.observe(synthetic_frame(kind, width=width, height=height, offset=offset))[
        "line"
    ]
    assert line["detected"] and line["confidence"] > 0.9
    points = np.array(line["points_normalized"])
    assert points[-1, 0] == pytest.approx(0.5 + offset, abs=0.02)
    assert np.all((points >= 0) & (points <= 1))


@pytest.mark.parametrize(
    "kind", ["blank", "broken_line", "parallel_lines", "branch", "pad", "opening", "blackout"]
)
def test_nonpath_and_ambiguous_geometry_do_not_invent_a_route(perception, kind):
    result = perception.observe(synthetic_frame(kind))
    assert not result["line"]["detected"]
    assert result["line"]["rejection_reasons"]


def test_polarity_is_an_explicit_configuration_with_provenance(perception):
    frame = synthetic_frame("dark_line")
    assert not perception.observe(frame)["line"]["detected"]
    config = replace(CourseConfig(), line_polarity="dark", provenance="unit:dark-paint")
    result = CoursePerception(config).observe(frame)
    assert result["line"]["detected"]
    assert result["configuration"] == config.snapshot()
    assert config.snapshot()["sha256"] != CourseConfig().snapshot()["sha256"]


def test_low_light_retry_has_measured_gain_and_no_control_authority(perception):
    result = perception.observe(synthetic_frame("dim_recoverable"))
    light = result["low_light"]
    assert light["retry_applied"] and light["line_recovered"]
    assert light["contrast_gain"] >= perception.config.recovery_min_contrast_gain
    assert light["raw_line_confidence"] < perception.config.line_confidence_min
    assert light["retry_line_confidence"] > perception.config.line_confidence_min
    assert light["authority_change"] == "NONE"
    assert result["state"] == "degraded"
    assert result["control_output"] == "DISABLED" and not result["command_executed"]


@pytest.mark.parametrize("kind", ["dim_line", "blackout"])
def test_clahe_cannot_recover_missing_signal(perception, kind):
    result = perception.observe(synthetic_frame(kind))
    assert result["low_light"]["retry_applied"]
    assert not result["low_light"]["line_recovered"]
    assert not result["line"]["detected"]
    assert not result["landing"]["descent_geometry_suitable"]


@pytest.mark.parametrize(
    "kind,supported", [("opening", True), ("blocked_opening", False), ("unknown_opening", False)]
)
def test_exit_is_a_visual_candidate_with_independent_depth_support(perception, kind, supported):
    result = perception.observe(synthetic_frame(kind))
    assert len(result["openings"]) == 1
    opening = result["openings"][0]
    assert opening["confidence"] > 0.85
    assert opening["exit_identity"] == "unverified"
    assert opening["clearance"]["supported"] is supported


def test_opening_scales_and_translates_without_changing_detector(perception):
    for width, height, shift in [(160, 120, -0.08), (640, 480, 0.08)]:
        sample = synthetic_frame("opening", width=width, height=height)
        image = cv2.warpAffine(
            sample.image,
            np.float32([[1, 0, width * shift], [0, 1, 0]]),
            (width, height),
            borderValue=(65, 65, 65),
        )
        opening = perception.observe(replace(sample, image=image))["openings"][0]
        assert opening["clearance"]["supported"]
        assert opening["bbox_normalized"][0] == pytest.approx(0.2 + shift, abs=0.03)


def test_chicane_gap_is_metric_projection_and_envelope_is_configured(perception):
    sample = synthetic_frame("chicane")
    clearance = perception.observe(sample)["clearance"]
    expected = (int(320 * 0.65) - int(320 * 0.28)) * 2.0 / sample.intrinsics.fx
    assert clearance["width_at_probe_m"] == pytest.approx(expected)
    assert clearance["supported"]
    wide = replace(CourseConfig(), envelope_width_m=1.2, provenance="unit:wide-envelope")
    assert not CoursePerception(wide).observe(sample)["clearance"]["supported"]
    narrow = perception.observe(synthetic_frame("narrow_gap"))["clearance"]
    assert narrow["width_at_probe_m"] < narrow["required_width_m"]
    assert narrow["rejection_reasons"] == ["insufficient_observed_clearance"]


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("missing", "depth_missing"),
        ("stale", "depth_stale_or_future"),
        ("future", "depth_stale_or_future"),
        ("unsynced", "image_depth_unsynchronized"),
        ("old_image", "image_stale_or_future"),
        ("future_image", "image_stale_or_future"),
        ("zeros", "depth_sector_degraded"),
        ("nan", "depth_sector_degraded"),
        ("blind", "local_depth_blind_zone"),
        ("far", "local_depth_insufficient"),
    ],
)
def test_untrusted_depth_never_becomes_free_space(perception, fault, reason):
    sample = synthetic_frame("line")
    changes = {
        "missing": {
            "depth_m": None,
            "depth_valid": None,
            "depth_timestamp_ns": None,
            "intrinsics": None,
            "calibration_id": None,
        },
        "stale": {"depth_timestamp_ns": 700_000_000},
        "future": {"depth_timestamp_ns": 1_030_000_000},
        "unsynced": {"depth_timestamp_ns": 950_000_000},
        "old_image": {"timestamp_ns": 700_000_000},
        "future_image": {"timestamp_ns": 1_030_000_000},
        "zeros": {"depth_m": np.zeros_like(sample.depth_m)},
        "nan": {"depth_m": np.full_like(sample.depth_m, np.nan)},
        "blind": {"depth_m": np.full_like(sample.depth_m, 0.1)},
        "far": {"depth_m": np.full_like(sample.depth_m, 50.0)},
    }
    result = perception.observe(replace(sample, **changes[fault]))
    assert not result["clearance"]["supported"]
    assert result["clearance"]["width_at_probe_m"] is None
    assert reason in result["clearance"]["rejection_reasons"]
    json.dumps(result, allow_nan=False)


def test_one_near_pixel_cannot_be_erased_by_depth_percentiles(perception):
    sample = synthetic_frame("narrow_gap")
    depth = sample.depth_m.copy()
    depth[:, 100:220] = 3.0
    full = perception.observe(replace(sample, depth_m=depth))["clearance"]
    depth[120, 160] = 0.5
    split = perception.observe(replace(sample, depth_m=depth))["clearance"]
    assert full["supported"] and not split["supported"]
    assert split["width_at_probe_m"] < full["width_at_probe_m"] / 2 + 0.02


@pytest.mark.parametrize("kind", ["pad", "dark_pad"])
@pytest.mark.parametrize(
    "width,height,offset,scale", [(160, 120, -0.1, 1.0), (320, 240, 0.1, 0.7), (640, 480, 0.0, 1.2)]
)
def test_annulus_confidence_and_geometry_across_sizes(
    perception, kind, width, height, offset, scale
):
    sample = synthetic_frame(kind, width=width, height=height, offset=offset, scale=scale)
    # Changing apparent size and distance together keeps the metric pad footprint adequate.
    sample = replace(sample, depth_m=np.full_like(sample.depth_m, 1.7 / scale))
    landing = perception.observe(sample)["landing"]
    assert landing["detected"] and landing["confidence"] >= 0.65
    assert landing["descent_geometry_suitable"] and not landing["rejection_reasons"]
    assert landing["candidate"]["safe"] is False
    assert landing["plane"]["max_residual_m"] < 1e-5
    assert "gravity_alignment" in landing["unassessed"]


def test_too_small_metric_pad_cannot_support_descent_geometry(perception):
    sample = synthetic_frame("pad")
    landing = perception.observe(replace(sample, depth_m=np.full_like(sample.depth_m, 0.45)))[
        "landing"
    ]
    assert landing["detected"] and not landing["descent_geometry_suitable"]
    assert "landing_footprint_too_small" in landing["rejection_reasons"]


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("solid_disk", "no_outer_ring"),
        ("ellipse", "no_outer_ring"),
        ("clipped_pad", "no_outer_ring"),
        ("intruded_pad", "landing_surface_not_planar"),
        ("tilted_pad", "landing_surface_tilted"),
        ("two_pads", "competing_outer_rings"),
    ],
)
def test_landing_failure_cases_have_explicit_rejections(perception, kind, reason):
    result = perception.observe(synthetic_frame(kind))["landing"]
    assert not result["descent_geometry_suitable"]
    assert reason in result["rejection_reasons"]
    assert 0 <= result["confidence"] <= 1


def test_rectangle_is_not_a_pad_even_in_downward_view(perception):
    sample = replace(synthetic_frame("opening"), camera_view="downward")
    assert not perception.observe(sample)["landing"]["detected"]


def test_pad_is_rejected_with_local_unknown_depth_or_low_light(perception):
    sample = synthetic_frame("pad")
    valid = sample.depth_valid.copy()
    valid[95:145, 135:185] = False
    landing = perception.observe(replace(sample, depth_valid=valid))["landing"]
    assert not landing["descent_geometry_suitable"]
    assert "local_depth_insufficient" in landing["rejection_reasons"]
    landing = perception.observe(replace(sample, image=(sample.image * 0.15).astype(np.uint8)))[
        "landing"
    ]
    assert not landing["descent_geometry_suitable"]
    assert "low_light_raw_evidence" in landing["rejection_reasons"]


def test_no_state_is_a_checkpoint_schedule_and_input_is_not_mutated(perception):
    sample = synthetic_frame("line")
    before = sample.image.copy(), sample.depth_m.copy(), sample.depth_valid.copy()
    first = perception.observe(sample)
    shifted = replace(
        sample,
        frame_index=900,
        timestamp_ns=sample.timestamp_ns + 10**12,
        evaluated_at_ns=sample.evaluated_at_ns + 10**12,
        depth_timestamp_ns=sample.depth_timestamp_ns + 10**12,
    )
    second = perception.observe(shifted)
    assert first["line"] == second["line"]
    assert first["state"] == second["state"] == "line_supported"
    assert first["clearance"] == second["clearance"]
    for original, actual in zip(before, (sample.image, sample.depth_m, sample.depth_valid)):
        np.testing.assert_array_equal(original, actual)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_type": "live"},
        {"source_id": ""},
        {"depth_valid": None},
        {"calibration_id": ""},
        {"intrinsics": Intrinsics(0, 1, 0, 0)},
        {"timestamp_ns": 1.1},
        {"camera_view": "unknown"},
    ],
)
def test_invalid_input_rejected_before_inference(perception, changes):
    with pytest.raises(ValueError):
        perception.observe(replace(synthetic_frame("line"), **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"provenance": ""},
        {"line_confidence_min": 1.1},
        {"clahe_tiles": 2.2},
        {"plane_max_samples": 2},
        {"canny_low": 130},
        {"roi_inset_fraction": 0.6},
        {"depth": SectorConfig(max_age_ms=float("nan"))},
        {"depth": SectorConfig(sectors=0)},
    ],
)
def test_invalid_thresholds_fail_at_configuration(changes):
    with pytest.raises(ValueError):
        CourseConfig(**changes)


def test_recorded_archive_roundtrip_and_local_trace(tmp_path):
    sample = synthetic_frame("pad")
    archive = tmp_path / "saved-fixture.npz"
    np.savez_compressed(
        archive,
        image=sample.image,
        depth_m=sample.depth_m,
        depth_valid=sample.depth_valid,
        timestamp_ns=sample.timestamp_ns,
        evaluated_at_ns=sample.evaluated_at_ns,
        camera_view=sample.camera_view,
        depth_timestamp_ns=sample.depth_timestamp_ns,
        intrinsics=np.array(
            [sample.intrinsics.fx, sample.intrinsics.fy, sample.intrinsics.cx, sample.intrinsics.cy]
        ),
        calibration_id=sample.calibration_id,
    )
    loaded = load_recording(archive, 5)
    loaded.validate()
    assert loaded.source_type == "recording" and "sha256" in loaded.source_id
    report = run(tmp_path / "replay", CourseConfig(), [loaded])
    assert report["samples"][0]["descent_geometry_suitable"]
    event = json.loads((tmp_path / "replay" / "trace.jsonl").read_text())
    assert event["evidence"]["configuration"] == CourseConfig().snapshot()
    assert event["evidence"]["stage_ms"]["landing.ring"] > 0
    assert not event["command_executed"]
    assert "decision" not in event and "command" not in event
    with pytest.raises(FileExistsError):
        run(tmp_path / "replay", CourseConfig(), [loaded])


def test_every_synthetic_trace_is_json_safe_and_advisory(perception):
    for sample in suite():
        evidence = perception.observe(sample)
        json.dumps(evidence, allow_nan=False)
        assert evidence["advisory_only"]
        assert evidence["control_output"] == "DISABLED"
        assert evidence["processing_ms"] >= sum(evidence["stage_ms"].values())


@pytest.mark.parametrize("contrast,detected", [(30, False), (43, False), (45, True), (90, True)])
def test_observed_line_contrast_boundary(perception, contrast, detected):
    sample = synthetic_frame("line")
    image = sample.image.copy()
    image[image[:, :, 0] == 245] = 65 + contrast
    line = perception.observe(replace(sample, image=image))["line"]
    assert line["detected"] is detected


@pytest.mark.parametrize("pixels,supported", [(72, False), (74, True)])
def test_metric_gap_boundary_at_known_intrinsics(perception, pixels, supported):
    sample = synthetic_frame("blank")
    depth = np.full_like(sample.depth_m, 0.8)
    depth[:, 120 : 120 + pixels] = 3.0
    gap = perception.observe(replace(sample, depth_m=depth))["clearance"]
    assert gap["supported"] is supported
    assert gap["width_at_probe_m"] == pytest.approx(pixels * 2 / 224)


def test_archive_does_not_silently_truncate_float_timestamps(tmp_path):
    archive = tmp_path / "invalid.npz"
    np.savez(
        archive,
        image=synthetic_frame("line").image,
        timestamp_ns=1.5,
        evaluated_at_ns=2,
        camera_view="forward",
    )
    with pytest.raises(ValueError, match="integer nanoseconds"):
        load_recording(archive, 0)
