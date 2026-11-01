"""Deterministic counterexamples: rejection and limits, not flight validation."""

import json
from dataclasses import replace

import numpy as np
import pytest

from aegisland.course_config import CourseConfig
from aegisland.course_perception import CoursePerception
from aegisland.course_replay import run
from aegisland.course_synthetic import adversarial_frame, adversarial_suite, suite, synthetic_frame
from aegisland.gps_denied import VisualDeadReckoner


@pytest.mark.parametrize(
    "kind", ["partial_ring", "curved_shadow", "wall_edge", "wall_highlight", "short_fragment"]
)
@pytest.mark.parametrize(
    "width,height,offset,scale",
    [(160, 120, -0.08, 0.75), (320, 240, 0.0, 1.0), (640, 480, 0.08, 1.25), (480, 240, 0.0, 1.0)],
)
def test_false_paths_are_rejected_at_multiple_sizes(kind, width, height, offset, scale):
    sample = adversarial_frame(kind, width=width, height=height, offset=offset, scale=scale)
    config = replace(CourseConfig(), line_polarity="dark" if kind == "curved_shadow" else "bright")
    line = CoursePerception(config).observe(sample)["line"]
    assert not line["detected"]
    assert line["confidence"] < config.line_confidence_min
    assert line["points_normalized"] == []
    assert line["rejection_reasons"]
    assert line["status"] in {"unknown", "ambiguous"}


@pytest.mark.parametrize("width,height", [(160, 120), (320, 240), (640, 480)])
def test_original_clipped_pad_counterexample_is_no_longer_a_supported_line(width, height):
    sample = synthetic_frame("clipped_pad", width=width, height=height)
    evidence = CoursePerception().observe(sample)
    assert not evidence["line"]["detected"]
    assert not evidence["landing"]["descent_geometry_suitable"]


@pytest.mark.parametrize("width,height", [(160, 120), (320, 240), (640, 480)])
def test_clean_slanted_stripe_retains_measured_geometric_support(width, height):
    sample = adversarial_frame("slanted_line", width=width, height=height)
    line = CoursePerception().observe(sample)["line"]
    assert line["detected"] and line["geometry_consistent"]
    assert line["confidence"] >= CourseConfig().line_confidence_min
    assert line["geometry"]["fit_rms_fraction"] < CourseConfig().line_max_fit_rms_fraction
    assert line["semantic_identity"] == "unverified"
    assert line["coordinate_unit"] == "normalized_image"


def test_sufficiently_long_fragment_without_near_field_evidence_is_still_unknown():
    sample = synthetic_frame("line")
    image = sample.image.copy()
    # Preserve >70% ROI coverage but remove the near-field endpoint.
    image[int(image.shape[0] * 0.88) :] = 65
    line = CoursePerception().observe(replace(sample, image=image))["line"]
    assert not line["detected"] and "line_near_field_unsupported" in line["rejection_reasons"]


def test_geometric_failure_and_competition_never_export_confident_path_points():
    perception = CoursePerception()
    arc = perception.observe(adversarial_frame("partial_ring"))["line"]
    assert arc["candidate_confidence"] > 0.9  # Old coverage/contrast score would have passed.
    assert arc["ambiguous"] and not arc["geometry_consistent"]
    assert arc["confidence"] == 0 and not arc["points_normalized"]
    competing = perception.observe(synthetic_frame("parallel_lines"))["line"]
    assert competing["ambiguous"] and competing["confidence"] == 0
    assert not competing["points_normalized"]


@pytest.mark.parametrize("kind", ["outside_roi_obstacle", "beyond_probe_obstacle"])
def test_obstacles_outside_observed_plane_never_promote_gap_to_3d_traversability(kind):
    perception = CoursePerception()
    base = perception.observe(synthetic_frame("blank"))
    evidence = perception.observe(adversarial_frame(kind))
    gap = evidence["clearance"]
    assert gap["local_plane_supported"]  # Explicitly demonstrate the residual sensing limit.
    assert gap["width_at_probe_m"] == base["clearance"]["width_at_probe_m"]
    assert gap["scope"] == "local_camera_z_probe_plane"
    assert gap["full_3d_traversability"] == "UNKNOWN"
    assert gap["supports_3d_traversal"] is False
    assert {"outside_sampled_roi", "beyond_probe_plane", "swept_vehicle_volume"} <= set(
        gap["unassessed"]
    )
    assert gap["authority_change"] == evidence["authority_change"] == "NONE"
    assert not gap["executed"] and not evidence["executed"]


def test_stale_gap_evidence_cannot_reuse_previously_supported_width():
    perception = CoursePerception()
    sample = synthetic_frame("blank")
    assert perception.observe(sample)["clearance"]["local_plane_supported"]
    evidence = perception.observe(replace(sample, evaluated_at_ns=1_300_000_000))
    gap = evidence["clearance"]
    assert not gap["supported"] and not gap["local_plane_supported"]
    assert gap["width_at_probe_m"] is None and gap["free_column_span_normalized"] is None
    assert "depth_stale_or_future" in gap["rejection_reasons"]
    assert gap["full_3d_traversability"] == "UNKNOWN"
    assert evidence["authority_change"] == gap["authority_change"] == "NONE"


@pytest.mark.parametrize(
    "changes", [{"calibration_id": None}, {"calibration_id": ""}, {"intrinsics": None}]
)
def test_missing_calibration_rejected_before_any_inference_or_output(
    changes, monkeypatch, tmp_path
):
    perception = CoursePerception()
    called = []
    monkeypatch.setattr(perception, "_line", lambda gray: called.append(True))
    invalid = replace(synthetic_frame("blank"), **changes)
    with pytest.raises(ValueError, match="calibration|intrinsics"):
        perception.observe(invalid)
    assert not called
    with pytest.raises(ValueError):
        run(tmp_path / "invalid", CourseConfig(), [invalid])
    trace = tmp_path / "invalid" / "trace.jsonl"
    assert not trace.exists() or not trace.read_text()


@pytest.mark.parametrize("width,height", [(160, 120), (320, 240), (640, 480)])
def test_rgb_blocker_and_far_depth_are_ambiguous_in_every_nested_aperture(width, height):
    sample = adversarial_frame("rgb_blocker_depth_far", width=width, height=height)
    evidence = CoursePerception().observe(sample)
    assert evidence["depth"]["valid"]  # Quality alone does not resolve the contradiction.
    gaps = [evidence["clearance"], *[o["clearance"] for o in evidence["openings"]]]
    assert evidence["openings"]
    for gap in gaps:
        assert not gap["supported"] and not gap["local_plane_supported"]
        assert gap["rgb_depth_consistency"] == "ambiguous"
        assert "rgb_depth_conflict_suspected" in gap["rejection_reasons"]
        assert gap["width_at_probe_m"] is None
        assert gap["supports_3d_traversal"] is False
        assert gap["authority_change"] == "NONE" and gap["executed"] is False


def test_visual_aperture_with_near_depth_does_not_confirm_exit_or_traversal():
    evidence = CoursePerception().observe(adversarial_frame("rgb_opening_depth_wall"))
    assert evidence["openings"]
    for opening in evidence["openings"]:
        assert opening["exit_identity"] == "unverified"
        assert opening["rgb_depth_consistency"] == "visual_aperture_not_confirmed_by_depth"
        assert not opening["clearance"]["supported"]
        assert not opening["clearance"]["supports_3d_traversal"]


def test_fixtures_are_deterministic():
    for a, b in zip(adversarial_suite(), adversarial_suite()):
        np.testing.assert_array_equal(a.image, b.image)
        np.testing.assert_array_equal(a.depth_m, b.depth_m)


def _check_execution_flags(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"executed", "command_executed", "supports_3d_traversal"}:
                assert item is False
            if key == "authority_change":
                assert item == "NONE"
            _check_execution_flags(item)
    elif isinstance(value, list):
        for item in value:
            _check_execution_flags(item)


def test_every_result_explicitly_disables_execution_and_stretch_goals(tmp_path):
    samples = [*suite(), *adversarial_suite()]
    for sample in samples:
        evidence = CoursePerception().observe(sample)
        _check_execution_flags(evidence)
        assert evidence["capabilities"] == {
            "window_navigation": "unimplemented",
            "return_navigation": "unimplemented",
            "metric_vio_slam": "not_provided",
        }
        assert evidence["executed"] is False and evidence["control_output"] == "DISABLED"
        assert not {"action", "command", "waypoint", "pose_m", "velocity_mps"} & evidence.keys()
        for opening in evidence["openings"]:
            assert opening["clearance"]["scope"] == "local_camera_z_probe_plane"
    report = run(tmp_path / "replay", CourseConfig(), samples)
    _check_execution_flags(report)
    for line in (tmp_path / "replay" / "trace.jsonl").read_text().splitlines():
        event = json.loads(line)
        _check_execution_flags(event)
        assert event["executed"] is False


def test_adversarial_results_do_not_depend_on_absolute_time_frame_number_or_history():
    perception = CoursePerception()
    for sample in adversarial_suite():
        original = perception.observe(sample)
        shifted = replace(
            sample,
            frame_index=777,
            timestamp_ns=sample.timestamp_ns + 10**14,
            depth_timestamp_ns=sample.depth_timestamp_ns + 10**14,
            evaluated_at_ns=sample.evaluated_at_ns + 10**14,
        )
        perception.observe(synthetic_frame("pad"))
        replayed = perception.observe(shifted)
        assert original["line"] == replayed["line"]
        assert original["clearance"] == replayed["clearance"]
        assert original["state"] == replayed["state"]


def test_existing_normalized_motion_is_dimensionless_not_metric_vio():
    # Same image displacement fraction at different resolutions produces the same
    # dimensionless value, without a calibrated distance or elapsed-time input.
    poses = []
    for width in (320, 640):
        homography = np.eye(3)
        homography[0, 2] = width * 0.1
        poses.append(
            VisualDeadReckoner().update(
                homography=homography, image_shape=(width, width), inlier_ratio=0.9
            )
        )
    assert poses[0].x == pytest.approx(-0.1) and poses[1].x == pytest.approx(-0.1)
    assert "NOT meters" in VisualDeadReckoner.__doc__
    assert "NOT full VIO or SLAM" in VisualDeadReckoner.__doc__


@pytest.mark.parametrize(
    "changes", [{"line_fit_width_multiplier": 0.5}, {"line_min_geometry_rows": 1}]
)
def test_geometry_fit_cannot_be_configured_without_enough_evidence(changes):
    with pytest.raises(ValueError, match="line geometry"):
        CourseConfig(**changes)
