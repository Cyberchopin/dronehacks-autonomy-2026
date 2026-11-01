# Full-suite timeout triage and narrow closeout

The historical complete-suite run remains **unresolved: 300-second timeout, exit 124**. This pass did not increase that timeout, redesign the harness, or modify implementation/tests. The evidence supports repeated CPU image-processing work in existing simulation tests as a material cause of the timeout; it does not establish that every interrupted case would eventually pass.

## Scope and evidence

- Checkout: `<worktrees>/harness`; branch `work/dronehacks-harness`; HEAD `e13b6984b2479691e9178223fbbaa5a3460585e8`.
- Read `HANDOFF.md`, the contract and migration notes before closeout. Only this report and `HANDOFF.md` are changed by closeout; pre-existing uncommitted code/tests remain intact.
- No downloads, GPU inference/benchmarks, cloud operations or flight commands. The real CUDA integration test was kept disabled by removing `AEGISLAND_GRAY_EXE` from child environments. PX4 tests exercise offline policy/serialization only. Harness results keep `executed=false`.
- SHA-256 compared **877 pre-existing files** under `benchmarks/results`, `output`, and `runs` before/after the pass: **zero changed or missing**. Newly allocated closeout artifacts were excluded from that before/after set.
- Local raw evidence: [`runs/full-suite-timeout-triage-20261101T012143Z-e0e65918`](../runs/full-suite-timeout-triage-20261101T012143Z-e0e65918/). This ignored run directory contains `collection.json`, full stdout, `module-counts.json`, `shards.json`, `results.json`, per-shard logs, per-phase `*.events.jsonl`, JUnit XML for completed shards, command checks, preservation hashes and copies of the temporary triage driver/plugin. The inventory and results below also persist in this document.

## Keep the three validation claims separate

1. **53 harness-related tests passed**: 38 new contract/harness cases, 4 existing GPS-denied cases and 11 existing trajectory cases. This selection was rerun in a bounded shard.
2. **Expanded regression previously passed 286 tests, with 1 skipped and 53 deselected**, in 54.91 seconds, exit 0. Those 53 deselected legacy tests are not the 53 harness-related cases. The selections overlap, so their passed counts must not be added. The four initial disjoint shards below recheck the same 287-case expanded selection.
3. **The complete 340-case suite is unresolved** because the prior aggregate run exceeded 300 seconds. Bounded shard results are diagnostic evidence, not a replacement complete-suite pass.

## Inventory and shard method

Collection returned **exit 0 in 0.818224 seconds**: **340 unique test node IDs across 59 modules**. All node IDs are listed in the appendix. Every module belongs to exactly one of the 18 shards; there are no overlaps or silently omitted tests.

Tests ran sequentially, without parallel workers, using the existing read-only Python environment `<main-checkout>/.venv/bin/python`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH` pointing to this checkout and the temporary timing plugin, and `OPENCV_FOR_THREADS_NUM=OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=1`. No dependencies or test bodies were changed. Other work on the host can affect timings; these are test-triage observations, not benchmark latency claims.

Budgets were fixed before execution: 30 seconds for each legacy module and small core group, 60 seconds for CPU profiling/subprocess tests, 90 seconds for the remaining CPU/unit/scenario group. These are independent diagnostic budgets, all below the old aggregate limit. `timeout --signal=TERM --kill-after=3s` reports exit 124 at a budget limit; no timeout was extended to obtain a pass.

A temporary pytest plugin flushed every start/setup/call/teardown report to JSONL, so termination does not discard completed per-test timings. `faulthandler_timeout=15` prints the current stack after 15 seconds in a test; that diagnostic message is not an assertion failure or itself a test cancellation. Wall durations below are measured around the subprocess and rounded to six decimal places; raw JSON retains full floating-point measurements. CPU time includes user/system time of reaped subprocess descendants.

| Shard | Collected | Budget s | Wall s | CPU s | Exit | Passed calls | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `harness-related` | 53 | 30 | 1.383633 | 1.248802 | 0 | 53 | 0 |
| `offline-control-guards` | 37 | 30 | 0.299760 | 0.276564 | 0 | 37 | 0 |
| `cpu-profiling-cuda-opt-in` | 19 | 60 | 9.611429 | 6.530044 | 0 | 18 | 1 |
| `other-cpu-unit-and-scenarios` | 178 | 90 | 41.224334 | 38.035828 | 0 | 178 | 0 |
| `baseline_ablation` | 3 | 30 | 30.018170 | 27.698385 | 124 | 1 | 0 |
| `component_ablation` | 4 | 30 | 30.042679 | 27.723673 | 124 | 1 | 0 |
| `fault_timeline` | 3 | 30 | 30.070304 | 27.751128 | 124 | 1 | 0 |
| `flicker_benchmark` | 5 | 30 | 30.007756 | 27.694330 | 124 | 1 | 0 |
| `fusion_authority_ablation` | 5 | 30 | 30.005568 | 27.692899 | 124 | 0 | 0 |
| `health_hysteresis_ablation` | 3 | 30 | 30.006210 | 27.684937 | 124 | 0 | 0 |
| `imu_fault_timeline` | 4 | 30 | 30.076430 | 27.754773 | 124 | 1 | 0 |
| `perception_fault_benchmark` | 2 | 30 | 0.236915 | 0.218514 | 0 | 2 | 0 |
| `perception_scene_benchmark` | 5 | 30 | 0.500220 | 0.461427 | 0 | 5 | 0 |
| `perception_severity_benchmark` | 5 | 30 | 1.486903 | 1.371825 | 0 | 5 | 0 |
| `reliability_benchmark` | 4 | 30 | 30.006848 | 27.693586 | 124 | 1 | 0 |
| `safety_assessment` | 4 | 30 | 30.007558 | 27.689287 | 124 | 0 | 0 |
| `safety_dashboard` | 2 | 30 | 0.145694 | 0.134200 | 0 | 2 | 0 |
| `sensor_failure_benchmark` | 4 | 30 | 0.244640 | 0.225431 | 0 | 4 | 0 |

“Passed calls” counts completed assertion bodies; it does not mean a timed-out module passed. The complete per-test status includes teardown completion in the appendix. Across these disjoint shards: **310 fully passed, 1 skipped, 9 interrupted, 20 not started before their shard budgets**. Failed phase reports observed: **0**. Interrupted/not-started cases remain unresolved.

## Why the aggregate run exceeds its budget

The baseline, component-ablation and fault-timeline modules each completed their first scenario replay before starting another fresh replay and hitting the shard budget. Their helpers repeatedly call `run_fault_timeline()` rather than sharing computed results between tests. The GPS-denied camera-failure scenario contains 80 frames; the default simulator produces 960×540 images. The call chain is `test → run_fault_timeline → agent.step → perception.observe → perception._motion → cv2.calcOpticalFlowFarneback`. Faulthandler captured execution at [perception.py](../src/aegisland/perception.py) line 329 in that call, not in a socket wait or benchmark-harness lock.

Flicker, fusion-authority and health-hysteresis tests also rebuild related timelines; [safety_assessment.py](../src/aegisland/safety_assessment.py) builds flicker, authority, health and sensor matrices for each assessment invocation. Thus independent tests can repeat substantial CPU work. This is legacy evaluation coverage, outside the new adapter/result contract. No caching, fixture changes, frame-count reductions or unrelated test edits were made.

The near-wall CPU consumption and completed first replays support **slow CPU-bound work and repeated computation** as the observed cause. A 30-second interrupted call alone cannot prove a hang, and no deadlock is demonstrated. Cases never reached after an earlier slow case cannot be individually classified as slow or passing.

Slowest completed call bodies (seconds, excluding setup/teardown):

| Test | Call s |
| --- | ---: |
| `tests/test_reliability_benchmark.py::test_cascading_failure_moves_through_capability_modes` | 22.721524 |
| `tests/test_fault_timeline.py::test_fault_timeline_covers_complete_scenario` | 22.516181 |
| `tests/test_flicker_benchmark.py::test_health_does_not_reenter_healthy_during_flicker` | 22.495815 |
| `tests/test_component_ablation.py::test_semantic_trust_eliminates_unsafe_continuation` | 22.369385 |
| `tests/test_baseline_ablation.py::test_aegisland_reaches_safe_state_faster` | 22.314307 |
| `tests/test_evaluation.py::test_evaluation_returns_metrics_for_known_scenario` | 20.551544 |
| `tests/test_imu_fault_timeline.py::test_out_of_order_imu_packets_are_compensated` | 15.061166 |
| `tests/test_evaluation.py::test_compound_emergency_scenario_records_recovery` | 9.653764 |
| `tests/test_compound_scenario.py::test_critical_battery_collision_triggers_emergency_recovery` | 9.464556 |
| `tests/test_profiling.py::test_real_module_cli_regression[True]` | 1.518095 |
| `tests/test_profiling.py::test_stage_replay_exact_and_branch_summary_recomputable` | 1.423925 |
| `tests/test_profiling.py::test_original_reference_gate` | 1.225670 |

Active tests when a shard was terminated:

- `baseline_ablation` (exit 124): `tests/test_baseline_ablation.py::test_aegisland_has_zero_unsafe_continuation`.
- `component_ablation` (exit 124): `tests/test_component_ablation.py::test_semantic_trust_reaches_safe_state_immediately`.
- `fault_timeline` (exit 124): `tests/test_fault_timeline.py::test_gps_loss_precedes_camera_fault`.
- `flicker_benchmark` (exit 124): `tests/test_flicker_benchmark.py::test_capability_policy_blocks_raw_reentry_during_flicker`.
- `fusion_authority_ablation` (exit 124): `tests/test_fusion_authority_ablation.py::test_capability_policy_blocks_premature_authority`.
- `health_hysteresis_ablation` (exit 124): `tests/test_health_hysteresis_ablation.py::test_hysteresis_blocks_premature_healthy_reentry`.
- `imu_fault_timeline` (exit 124): `tests/test_imu_fault_timeline.py::test_stale_imu_degrades_to_visual_only_navigation`.
- `reliability_benchmark` (exit 124): `tests/test_reliability_benchmark.py::test_combined_position_sensor_failure_never_continues_mission`.
- `safety_assessment` (exit 124): `tests/test_safety_assessment.py::test_deterministic_safety_gates_pass`.

## Hardware, network and unrelated coverage

- **Hardware-dependent and skipped:** `tests/test_cuda_gray.py::test_real_gpu_odd_size_padded_rows` requires an explicitly configured GPU executable (`AEGISLAND_GRAY_EXE`). It was not enabled or executed.
- **CPU profiling:** its tests invoke CPU-only CLI subprocesses and collect local `nvidia-smi -q`, CPU, Git and package metadata. Metadata collection uses its existing 30-second command guard. The profiling shard completed; it did not perform CUDA inference or launch the GPU integration executable. These subprocess/metadata paths are potential machine-dependent delays, but were not a hanging path in this pass.
- **Network/cloud:** no live service is required by the inspected test call paths. The legacy `CloudTraceStore` network implementation exists, but these scenario tests use `MemoryTraceStore`; no cloud writer/endpoint was invoked. This is a source/call-path assessment, not a packet-capture claim.
- **PX4/control:** policy, telemetry conversion and MAVLink serialization tests are offline. No SITL/HIL server, drone connection or flight command was started.
- **Unrelated to harness closeout:** the legacy ablation/timeline/assessment matrices exercise full landing/safety simulation. The new contract tests and serialization/math tests complete independently. The former exclusion filter also deselected cheaper modules; being deselected in that earlier run is not evidence that a module is slow.

## Documented commands and paths

Read and checked all shell blocks and links in `HANDOFF.md`, `docs/dronehacks-benchmark-contract.md`, and `docs/benchmark-migration-notes.md`. Shell syntax checks use `bash -n`; CLI/pytest/Ruff help confirms supported command forms. The historical full-suite command is checked as documentation, not rerun with a larger limit. Its tests are accounted for by the disjoint shards.

Executed native VDR smoke, verification, an eight-frame EuRoC-prefix run, migration import and verification. For `/path/to/mav0`, generated only eight small local synthetic PNGs and their CSV. `RUN_ID`, `NEW_RUN_DIR`, `DIR`, `N`, `ADAPTER_ID`, user hardware descriptions and `runs/origin-platform.json` are explicit placeholders/prerequisites; they are not claimed to be existing literal paths. The origin JSON was supplied in the new closeout directory, and all new commands used unique output children there. The default system Python has no NumPy; documented commands require the already-stated dependency environment, whose absolute interpreter was used here.

All four named historical source directories exist. Six pre-existing completed native/import runs were verified read-only. The before/after SHA check covers their original files as well as the historical benchmark results.

| Command check | Wall s | Exit |
| --- | ---: | ---: |
| `git-diff-check` | 0.096504 | 0 |
| `shell-syntax:HANDOFF.md:1` | 0.005346 | 0 |
| `shell-syntax:HANDOFF.md:2` | 0.001070 | 0 |
| `shell-syntax:HANDOFF.md:3` | 0.000911 | 0 |
| `shell-syntax:docs/dronehacks-benchmark-contract.md:1` | 0.000936 | 0 |
| `shell-syntax:docs/dronehacks-benchmark-contract.md:2` | 0.000830 | 0 |
| `shell-syntax:docs/benchmark-migration-notes.md:1` | 0.000845 | 0 |
| `cli-help:` | 0.089072 | 0 |
| `cli-help:run` | 0.086144 | 0 |
| `cli-help:verify` | 0.085118 | 0 |
| `pytest-help` | 0.122740 | 0 |
| `ruff-help` | 0.001836 | 0 |
| `documented-native-vdr` | 0.247604 | 0 |
| `documented-verify-native` | 0.094472 | 0 |
| `documented-euroc-prefix-with-generated-fixture` | 0.279418 | 0 |
| `documented-verify-euroc-prefix` | 0.091674 | 0 |
| `documented-migration-import` | 0.214745 | 0 |
| `documented-verify-migration-import` | 0.100611 | 0 |
| `ruff-repository` | 0.013189 | 0 |

Final Markdown-link and whitespace checks are also recorded in the closeout evidence. `git diff --check` is run, and the new/untracked closeout documents are checked explicitly because ordinary Git diff does not include untracked files.

## Remaining work and bounded follow-up

No demonstrated harness defect was found, so no implementation/test changes were made. Keep the aggregate suite unresolved and retain the legacy simulation timeouts as diagnostics. If further investigation is authorized, use the recorded active node IDs and the same fixed budget to inspect those existing scenario tests independently; any changes to legacy caching/fixtures or suite structure belong in a separate task. No longer timeout is recommended as a way to claim success.

To reproduce one bounded diagnostic using the saved plugin, substitute an actual module from the inventory for `tests/test_baseline_ablation.py` and a fresh event-log path:

```sh
RUN_DIR=runs/full-suite-timeout-triage-20261101T012143Z-e0e65918
env -u AEGISLAND_GRAY_EXE PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src:$RUN_DIR" \
  OPENCV_FOR_THREADS_NUM=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  DH_TRIAGE_EVENTS="$RUN_DIR/recheck-UNIQUE.events.jsonl" \
  timeout --signal=TERM --kill-after=3s 30s \
  <main-checkout>/.venv/bin/python -m pytest \
  tests/test_baseline_ablation.py -vv -o addopts= -o faulthandler_timeout=15 \
  -p dhtriage_timing --durations=0 --durations-min=0
```

## Appendix: full collected inventory and observed statuses

The following is the complete collection, preserving parametrized IDs. `NOT_STARTED` means that shard ended before this case; `INTERRUPTED` means it started but did not complete teardown before the limit. Neither is a pass.

### tests/test_agent_loop.py

Shard: `other-cpu-unit-and-scenarios`; collected: 14.

```text
PASSED tests/test_agent_loop.py::test_uncertainty_triggers_a_second_opencv_tool_call
PASSED tests/test_agent_loop.py::test_critical_battery_and_collision_flows_through_agent
PASSED tests/test_agent_loop.py::test_emergency_action_does_not_flap_after_one_safe_frame
PASSED tests/test_agent_loop.py::test_human_review_creates_pending_approval_request
PASSED tests/test_agent_loop.py::test_pending_human_approval_blocks_command_execution
PASSED tests/test_agent_loop.py::test_approved_action_can_dispatch
PASSED tests/test_agent_loop.py::test_rejected_action_remains_blocked
PASSED tests/test_agent_loop.py::test_expired_action_remains_blocked
PASSED tests/test_agent_loop.py::test_agent_computes_temporal_risk_for_approaching_object
PASSED tests/test_agent_loop.py::test_agent_uses_visual_navigation_when_gps_is_lost
PASSED tests/test_agent_loop.py::test_gps_loss_uses_time_aligned_visual_inertial_fallback
PASSED tests/test_agent_loop.py::test_sensor_health_filters_visual_and_imu_before_fusion
PASSED tests/test_agent_loop.py::test_failed_camera_with_gps_loss_enters_safe_degraded_mode
PASSED tests/test_agent_loop.py::test_visual_sensor_requires_sustained_recovery_before_healthy
```

### tests/test_approval.py

Shard: `offline-control-guards`; collected: 3.

```text
PASSED tests/test_approval.py::test_approval_request_has_stable_identity
PASSED tests/test_approval.py::test_approval_lifecycle_can_reach_approved
PASSED tests/test_approval.py::test_non_approval_decision_creates_no_request
```

### tests/test_baseline_ablation.py

Shard: `baseline_ablation`; collected: 3.

```text
PASSED tests/test_baseline_ablation.py::test_aegisland_reaches_safe_state_faster
INTERRUPTED tests/test_baseline_ablation.py::test_aegisland_has_zero_unsafe_continuation
NOT_STARTED tests/test_baseline_ablation.py::test_aegisland_recovers_more_conservatively
```

### tests/test_benchmark_contract.py

Shard: `harness-related`; collected: 38.

```text
PASSED tests/test_benchmark_contract.py::test_strict_json_rejects_nonfinite_and_duplicate_keys[{"v":NaN}]
PASSED tests/test_benchmark_contract.py::test_strict_json_rejects_nonfinite_and_duplicate_keys[{"v":Infinity}]
PASSED tests/test_benchmark_contract.py::test_strict_json_rejects_nonfinite_and_duplicate_keys[{"v":-Infinity}]
PASSED tests/test_benchmark_contract.py::test_strict_json_rejects_nonfinite_and_duplicate_keys[{"v":[1e999]}]
PASSED tests/test_benchmark_contract.py::test_strict_json_rejects_nonfinite_and_duplicate_keys[{"a":1,"a":2}]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1}-1]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1}\n{"timestamp_ns":-2]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1}\n-2]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1}\n{"timestamp_ns":1}\n-2]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":2}\n{"timestamp_ns":1}\n-2]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":true}\n-1]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1}\n\n-2]
PASSED tests/test_benchmark_contract.py::test_jsonl_rejects_truncation_timestamps_and_counts[{"timestamp_ns":1,"signal":1e999}\n-1]
PASSED tests/test_benchmark_contract.py::test_cold_warm_percentiles_drop_loss_recovery_and_coverage
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes0-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes1-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes2-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes3-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes4-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes5-aegisland-vdr]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes6-cuvslam-stereo]
PASSED tests/test_benchmark_contract.py::test_frame_contract_rejects_invalid_or_mislabelled_samples[changes7-oak-depthai-stereo]
PASSED tests/test_benchmark_contract.py::test_desktop_cannot_be_orin
PASSED tests/test_benchmark_contract.py::test_legacy_cuvslam_counts_pose_and_origin[stereo]
PASSED tests/test_benchmark_contract.py::test_legacy_cuvslam_counts_pose_and_origin[inertial]
PASSED tests/test_benchmark_contract.py::test_legacy_vdr_does_not_invent_per_frame_timings
PASSED tests/test_benchmark_contract.py::test_ffs_research_preserves_pixel_coverage_and_allocator_scope
PASSED tests/test_benchmark_contract.py::test_oak_recorded_schedule_and_no_flight_execution
PASSED tests/test_benchmark_contract.py::test_import_is_unique_readonly_and_detects_tampering
PASSED tests/test_benchmark_contract.py::test_failed_input_has_manifest_environment_and_hashes
PASSED tests/test_benchmark_contract.py::test_native_vdr_smoke_and_wrong_platform_failure
PASSED tests/test_benchmark_contract.py::test_cli_records_missing_dependency_source_as_failure
PASSED tests/test_benchmark_contract.py::test_known_metric_trajectory_reuses_existing_ate_rpe
PASSED tests/test_benchmark_contract.py::test_result_reader_rejects_inconsistent_resealed_summary
PASSED tests/test_benchmark_contract.py::test_source_hash_mismatch_is_preserved_as_failed_run
PASSED tests/test_benchmark_contract.py::test_error_frames_cannot_be_accepted_as_successful_run
PASSED tests/test_benchmark_contract.py::test_euroc_prefix_and_count_validation_before_decode
PASSED tests/test_benchmark_contract.py::test_no_tracked_frames_cannot_hide_nonempty_trajectory
```

### tests/test_commands.py

Shard: `offline-control-guards`; collected: 3.

```text
PASSED tests/test_commands.py::test_command_lifecycle_reaches_completed
PASSED tests/test_commands.py::test_same_decision_generates_same_command_id
PASSED tests/test_commands.py::test_command_can_fail_closed_on_timeout
```

### tests/test_component_ablation.py

Shard: `component_ablation`; collected: 4.

```text
PASSED tests/test_component_ablation.py::test_semantic_trust_eliminates_unsafe_continuation
INTERRUPTED tests/test_component_ablation.py::test_semantic_trust_reaches_safe_state_immediately
NOT_STARTED tests/test_component_ablation.py::test_full_stack_preserves_zero_unsafe_continuation
NOT_STARTED tests/test_component_ablation.py::test_full_aegisland_recovers_no_earlier_than_pre_stabilizer
```

### tests/test_compound_scenario.py

Shard: `other-cpu-unit-and-scenarios`; collected: 1.

```text
PASSED tests/test_compound_scenario.py::test_critical_battery_collision_triggers_emergency_recovery
```

### tests/test_cuda_gray.py

Shard: `cpu-profiling-cuda-opt-in`; collected: 3.

```text
PASSED tests/test_cuda_gray.py::test_error_histogram_detects_one_level_and_unsigned_wrap
PASSED tests/test_cuda_gray.py::test_error_gate_rejects_shape_dtype_and_preserves_exact_equality
SKIPPED tests/test_cuda_gray.py::test_real_gpu_odd_size_padded_rows
```

### tests/test_degradation_metrics.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_degradation_metrics.py::test_rotation_log_recovers_axis_angle_including_near_pi
PASSED tests/test_degradation_metrics.py::test_interpolate_poses_midpoint_and_out_of_range
PASSED tests/test_degradation_metrics.py::test_forward_drift_rate_is_zero_for_identical_and_measures_extra_motion
PASSED tests/test_degradation_metrics.py::test_causal_mean_only_uses_past_values
PASSED tests/test_degradation_metrics.py::test_find_events_merges_short_gaps_and_drops_short_runs
PASSED tests/test_degradation_metrics.py::test_score_alarms_lead_miss_and_false_alarm_rate
PASSED tests/test_degradation_metrics.py::test_roc_auc_perfect_inverse_and_ties
```

### tests/test_depth_sectors.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_depth_sectors.py::test_flat_wall_gives_ray_ranges_and_center_sector_at_wall_distance
PASSED tests/test_depth_sectors.py::test_obstacle_in_one_sector_is_reported_only_there
PASSED tests/test_depth_sectors.py::test_invalid_blind_zone_and_stale_data_are_not_reported_as_free
PASSED tests/test_depth_sectors.py::test_far_scene_is_clear_to_max_range_and_inputs_are_validated
PASSED tests/test_depth_sectors.py::test_conversions_and_min_depth
```

### tests/test_depth_validation.py

Shard: `other-cpu-unit-and-scenarios`; collected: 3.

```text
PASSED tests/test_depth_validation.py::test_unbiased_wall_has_zero_bias_and_noise_shows_as_temporal_and_plane_rms
PASSED tests/test_depth_validation.py::test_bias_invalid_pixels_and_tilted_plane
PASSED tests/test_depth_validation.py::test_empty_roi_and_no_frames
```

### tests/test_domain.py

Shard: `other-cpu-unit-and-scenarios`; collected: 2.

```text
PASSED tests/test_domain.py::test_telemetry_rejects_impossible_values
PASSED tests/test_domain.py::test_jsonable_output_can_be_serialized
```

### tests/test_euroc_writer.py

Shard: `other-cpu-unit-and-scenarios`; collected: 6.

```text
PASSED tests/test_euroc_writer.py::test_stereo_imu_and_depth_round_trip_in_euroc_layout
PASSED tests/test_euroc_writer.py::test_writer_refuses_existing_directory_and_bad_images
PASSED tests/test_euroc_writer.py::test_fisheye_calibration_uses_recalibrated_cam0_relative_files
PASSED tests/test_euroc_writer.py::test_radtan_calibration_uses_body_relative_original_convention
PASSED tests/test_euroc_writer.py::test_calibration_rejects_mixed_models_and_wrong_coefficient_count
PASSED tests/test_euroc_writer.py::test_merge_imu_interpolates_accel_onto_gyro_stamps_without_extrapolation
```

### tests/test_evaluation.py

Shard: `other-cpu-unit-and-scenarios`; collected: 2.

```text
PASSED tests/test_evaluation.py::test_evaluation_returns_metrics_for_known_scenario
PASSED tests/test_evaluation.py::test_compound_emergency_scenario_records_recovery
```

### tests/test_execution.py

Shard: `offline-control-guards`; collected: 6.

```text
PASSED tests/test_execution.py::test_execution_guard_starts_healthy
PASSED tests/test_execution.py::test_timeout_latches_fail_closed
PASSED tests/test_execution.py::test_fail_closed_blocks_future_normal_autonomy
PASSED tests/test_execution.py::test_fail_closed_cannot_reset_without_operator_ack
PASSED tests/test_execution.py::test_fail_closed_cannot_reset_with_unhealthy_channel
PASSED tests/test_execution.py::test_fail_closed_resets_only_after_full_handshake
```

### tests/test_fault_timeline.py

Shard: `fault_timeline`; collected: 3.

```text
PASSED tests/test_fault_timeline.py::test_fault_timeline_covers_complete_scenario
INTERRUPTED tests/test_fault_timeline.py::test_gps_loss_precedes_camera_fault
NOT_STARTED tests/test_fault_timeline.py::test_timeline_records_navigation_observability
```

### tests/test_faults.py

Shard: `other-cpu-unit-and-scenarios`; collected: 4.

```text
PASSED tests/test_faults.py::test_ack_timeout_is_recorded
PASSED tests/test_faults.py::test_command_failure_is_recorded_separately
PASSED tests/test_faults.py::test_timeout_blocks_normal_autonomy_on_next_frame
PASSED tests/test_faults.py::test_operator_handshake_restores_autonomy_after_fail_closed
```

### tests/test_flicker_benchmark.py

Shard: `flicker_benchmark`; collected: 5.

```text
PASSED tests/test_flicker_benchmark.py::test_health_does_not_reenter_healthy_during_flicker
INTERRUPTED tests/test_flicker_benchmark.py::test_capability_policy_blocks_raw_reentry_during_flicker
NOT_STARTED tests/test_flicker_benchmark.py::test_navigation_authority_waits_for_healthy_sensor_state
NOT_STARTED tests/test_flicker_benchmark.py::test_stabilizer_delays_control_reentry_after_raw_recovery
NOT_STARTED tests/test_flicker_benchmark.py::test_recovery_pipeline_is_ordered
```

### tests/test_fusion.py

Shard: `other-cpu-unit-and-scenarios`; collected: 10.

```text
PASSED tests/test_fusion.py::test_gps_is_primary_when_healthy
PASSED tests/test_fusion.py::test_visual_takes_over_when_gps_fails
PASSED tests/test_fusion.py::test_system_degrades_when_both_sources_are_unreliable
PASSED tests/test_fusion.py::test_invalid_confidence_values_are_clamped
PASSED tests/test_fusion.py::test_visual_inertial_fallback_when_gps_is_lost
PASSED tests/test_fusion.py::test_sensor_weights_transition_smoothly_after_gps_failure
PASSED tests/test_fusion.py::test_repeated_fusion_ticks_continue_fading_failed_gps_weight
PASSED tests/test_fusion.py::test_degraded_visual_cannot_establish_gps_denied_fallback
PASSED tests/test_fusion.py::test_degraded_visual_can_assist_healthy_gps_primary
PASSED tests/test_fusion.py::test_degraded_mode_clears_stale_authority_weights
```

### tests/test_fusion_authority_ablation.py

Shard: `fusion_authority_ablation`; collected: 5.

```text
INTERRUPTED tests/test_fusion_authority_ablation.py::test_capability_policy_blocks_premature_authority
NOT_STARTED tests/test_fusion_authority_ablation.py::test_capability_policy_blocks_premature_raw_continue
NOT_STARTED tests/test_fusion_authority_ablation.py::test_capability_policy_reduces_planner_flapping
NOT_STARTED tests/test_fusion_authority_ablation.py::test_capability_policy_waits_for_health_recovery
NOT_STARTED tests/test_fusion_authority_ablation.py::test_capability_policy_trades_availability_for_authority_safety
```

### tests/test_gps_denied.py

Shard: `harness-related`; collected: 4.

```text
PASSED tests/test_gps_denied.py::test_visual_dead_reckoning_tracks_relative_camera_translation
PASSED tests/test_gps_denied.py::test_visual_dead_reckoning_accumulates_motion
PASSED tests/test_gps_denied.py::test_visual_dead_reckoning_degrades_when_visual_pose_is_unreliable
PASSED tests/test_gps_denied.py::test_active_perception_does_not_advance_visual_dead_reckoning_twice
```

### tests/test_health_hysteresis_ablation.py

Shard: `health_hysteresis_ablation`; collected: 3.

```text
INTERRUPTED tests/test_health_hysteresis_ablation.py::test_hysteresis_blocks_premature_healthy_reentry
NOT_STARTED tests/test_health_hysteresis_ablation.py::test_hysteresis_reduces_unstable_healthy_frames
NOT_STARTED tests/test_health_hysteresis_ablation.py::test_hysteresis_recovers_more_conservatively
```

### tests/test_imu_fault_timeline.py

Shard: `imu_fault_timeline`; collected: 4.

```text
PASSED tests/test_imu_fault_timeline.py::test_out_of_order_imu_packets_are_compensated
INTERRUPTED tests/test_imu_fault_timeline.py::test_stale_imu_degrades_to_visual_only_navigation
NOT_STARTED tests/test_imu_fault_timeline.py::test_imu_recovery_is_hysteretic
NOT_STARTED tests/test_imu_fault_timeline.py::test_out_of_order_counter_continues_after_recovery
```

### tests/test_kalibr_import.py

Shard: `other-cpu-unit-and-scenarios`; collected: 2.

```text
PASSED tests/test_kalibr_import.py::test_kalibr_conventions_map_to_cam0_relative_transforms
PASSED tests/test_kalibr_import.py::test_unsupported_models_and_bad_transforms_are_refused
```

### tests/test_localization_diagnostics.py

Shard: `other-cpu-unit-and-scenarios`; collected: 10.

```text
PASSED tests/test_localization_diagnostics.py::test_camera_translation_right_moves_scene_left_by_f_t_over_z
PASSED tests/test_localization_diagnostics.py::test_translation_has_no_flow_at_infinite_depth_but_rotation_does
PASSED tests/test_localization_diagnostics.py::test_vdr_image_flow_inverts_normalized_velocity
PASSED tests/test_localization_diagnostics.py::test_direction_agreement_ignores_small_reference_motion
PASSED tests/test_localization_diagnostics.py::test_direction_agreement_skips_missing_estimates
PASSED tests/test_localization_diagnostics.py::test_direction_agreement_rejects_shape_mismatch
PASSED tests/test_localization_diagnostics.py::test_estimate_time_offset_recovers_known_lag
PASSED tests/test_localization_diagnostics.py::test_angular_speed_from_poses_constant_yaw_rate
PASSED tests/test_localization_diagnostics.py::test_failure_rate_by_bin_counts_invalid_frames
PASSED tests/test_localization_diagnostics.py::test_interval_averaging_removes_aliasing_bias_against_frame_rate_stream
```

### tests/test_localization_faults.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_localization_faults.py::test_drop_removes_only_frames_inside_window
PASSED tests/test_localization_faults.py::test_outage_removes_frames_and_adds_ticks
PASSED tests/test_localization_faults.py::test_pose_jump_offsets_all_later_positions_without_reset
PASSED tests/test_localization_faults.py::test_stale_delivery_delays_publish_time_inside_window
PASSED tests/test_localization_faults.py::test_out_of_order_swaps_capture_order
PASSED tests/test_localization_faults.py::test_imu_offset_shifts_imu_stamps
PASSED tests/test_localization_faults.py::test_score_detection_reports_latency_and_false_positives
```

### tests/test_localization_message.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_localization_message.py::test_well_formed_message_has_no_errors_and_round_trips
PASSED tests/test_localization_message.py::test_publish_before_capture_is_rejected
PASSED tests/test_localization_message.py::test_non_unit_quaternion_and_non_finite_position_are_rejected
PASSED tests/test_localization_message.py::test_valid_flag_must_agree_with_failed_quality_and_lost_state
PASSED tests/test_localization_message.py::test_unknown_frames_and_negative_variance_are_rejected
PASSED tests/test_localization_message.py::test_from_dict_rejects_wrong_schema_and_missing_fields
PASSED tests/test_localization_message.py::test_quality_out_of_range_is_rejected
```

### tests/test_localization_supervisor.py

Shard: `other-cpu-unit-and-scenarios`; collected: 13.

```text
PASSED tests/test_localization_supervisor.py::test_nominal_stream_is_ok_and_never_commands
PASSED tests/test_localization_supervisor.py::test_dropped_frames_are_reported_from_sequence_gap
PASSED tests/test_localization_supervisor.py::test_stale_message_is_a_fault
PASSED tests/test_localization_supervisor.py::test_camera_outage_detected_by_tick_without_messages
PASSED tests/test_localization_supervisor.py::test_time_going_backwards_is_a_fault
PASSED tests/test_localization_supervisor.py::test_pose_jump_without_reset_is_a_fault_but_with_reset_is_relocalization
PASSED tests/test_localization_supervisor.py::test_lost_tracking_and_invalid_contract_are_faults
PASSED tests/test_localization_supervisor.py::test_imu_camera_time_offset_is_detected_only_when_injected
PASSED tests/test_localization_supervisor.py::test_imu_offset_flag_clears_when_estimate_becomes_unavailable
PASSED tests/test_localization_supervisor.py::test_rotation_consistency_tolerates_constant_gyro_bias
PASSED tests/test_localization_supervisor.py::test_rotation_inconsistency_is_degraded_not_fault
PASSED tests/test_localization_supervisor.py::test_low_texture_uses_smoothed_feature_matches_and_can_be_disabled
PASSED tests/test_localization_supervisor.py::test_rotation_check_waits_for_a_gyro_bias_estimate
```

### tests/test_loop_closure_gate.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_loop_closure_gate.py::test_continuous_when_slam_equals_odometry
PASSED tests/test_loop_closure_gate.py::test_loop_closure_correction_within_budget_is_accepted_with_reset
PASSED tests/test_loop_closure_gate.py::test_jump_without_event_oversized_and_odometry_jump_are_rejected
PASSED tests/test_loop_closure_gate.py::test_rejected_offset_does_not_leak_into_a_later_loop_closure
PASSED tests/test_loop_closure_gate.py::test_odometry_fallback_switch_ignores_slam_and_never_resets
```

### tests/test_mavlink_odometry.py

Shard: `offline-control-guards`; collected: 7.

```text
PASSED tests/test_mavlink_odometry.py::test_frd_message_maps_to_local_frd_vio_with_wxyz_quaternion
PASSED tests/test_mavlink_odometry.py::test_unknown_variance_uses_nan_first_element_and_known_variance_fills_diagonal
PASSED tests/test_mavlink_odometry.py::test_verdicts_mark_quality_or_inflate_variance
PASSED tests/test_mavlink_odometry.py::test_lost_tracking_is_sent_as_failed_quality
PASSED tests/test_mavlink_odometry.py::test_dataset_frames_are_refused_until_converted
PASSED tests/test_mavlink_odometry.py::test_dataset_to_frd_flips_z_up_world_and_preserves_yaw_sign_convention
PASSED tests/test_mavlink_odometry.py::test_dataset_to_frd_rejects_reflections
```

### tests/test_motion_compensation.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_motion_compensation.py::test_orb_homography_compensates_global_camera_translation
PASSED tests/test_motion_compensation.py::test_rejects_homography_with_excessive_corner_motion
PASSED tests/test_motion_compensation.py::test_accepts_reasonable_camera_translation
PASSED tests/test_motion_compensation.py::test_compensation_preserves_independent_foreground_motion
PASSED tests/test_motion_compensation.py::test_feature_cache_gives_identical_results_to_fresh_compensators
PASSED tests/test_motion_compensation.py::test_feature_cache_skips_recomputing_previous_frame
PASSED tests/test_motion_compensation.py::test_feature_cache_is_not_fooled_by_in_place_mutation
```

### tests/test_perception_boundary_calibration.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_perception_boundary_calibration.py::test_fine_grid_has_one_percent_resolution
PASSED tests/test_perception_boundary_calibration.py::test_boundary_calibration_is_deterministic
PASSED tests/test_perception_boundary_calibration.py::test_clean_state_has_no_authority_intervention
PASSED tests/test_perception_boundary_calibration.py::test_endpoint_faults_always_trigger_intervention
PASSED tests/test_perception_boundary_calibration.py::test_endpoint_confusion_covers_all_fault_families
```

### tests/test_perception_fault_benchmark.py

Shard: `perception_fault_benchmark`; collected: 2.

```text
PASSED tests/test_perception_fault_benchmark.py::test_perception_fault_matrix_passes
PASSED tests/test_perception_fault_benchmark.py::test_perception_fault_matrix_covers_expected_cases
```

### tests/test_perception_quality.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_perception_quality.py::test_healthy_textured_frame
PASSED tests/test_perception_quality.py::test_overexposure_is_semantically_detected
PASSED tests/test_perception_quality.py::test_underexposure_is_semantically_detected
PASSED tests/test_perception_quality.py::test_texture_degenerate_wall_is_detected
PASSED tests/test_perception_quality.py::test_blur_is_detected
PASSED tests/test_perception_quality.py::test_large_occlusion_is_detected
PASSED tests/test_perception_quality.py::test_geometry_failure_is_distinguished_from_bad_image
```

### tests/test_perception_scene_benchmark.py

Shard: `perception_scene_benchmark`; collected: 5.

```text
PASSED tests/test_perception_scene_benchmark.py::test_scene_baseline_probe_passes
PASSED tests/test_perception_scene_benchmark.py::test_scene_distribution_contains_six_healthy_scenes
PASSED tests/test_perception_scene_benchmark.py::test_clean_cross_scene_inputs_keep_full_authority
PASSED tests/test_perception_scene_benchmark.py::test_endpoint_faults_intervene_across_scenes
PASSED tests/test_perception_scene_benchmark.py::test_authority_does_not_reenter_on_coarse_sweep
```

### tests/test_perception_severity_benchmark.py

Shard: `perception_severity_benchmark`; collected: 5.

```text
PASSED tests/test_perception_severity_benchmark.py::test_severity_sweep_is_deterministic
PASSED tests/test_perception_severity_benchmark.py::test_clean_frames_do_not_trigger_intervention
PASSED tests/test_perception_severity_benchmark.py::test_maximum_fault_severity_intervenes
PASSED tests/test_perception_severity_benchmark.py::test_full_sweep_has_expected_shape
PASSED tests/test_perception_severity_benchmark.py::test_full_sweep_has_no_clean_false_authority_revokes
```

### tests/test_perception_trust.py

Shard: `other-cpu-unit-and-scenarios`; collected: 11.

```text
PASSED tests/test_perception_trust.py::test_healthy_perception_receives_full_authority
PASSED tests/test_perception_trust.py::test_hard_semantic_failures_revoke_localization[overexposed]
PASSED tests/test_perception_trust.py::test_hard_semantic_failures_revoke_localization[underexposed]
PASSED tests/test_perception_trust.py::test_hard_semantic_failures_revoke_localization[texture_degenerate]
PASSED tests/test_perception_trust.py::test_hard_semantic_failures_revoke_localization[occlusion_suspected]
PASSED tests/test_perception_trust.py::test_hard_semantic_failures_revoke_localization[geometry_unstable]
PASSED tests/test_perception_trust.py::test_blur_reduces_but_does_not_revoke_authority
PASSED tests/test_perception_trust.py::test_invalid_estimator_always_revokes_authority
PASSED tests/test_perception_trust.py::test_unknown_diagnosis_preserves_legacy_behavior
PASSED tests/test_perception_trust.py::test_healthy_visual_localization_remains_available_without_gps
PASSED tests/test_perception_trust.py::test_semantic_failure_revokes_visual_authority_same_frame
```

### tests/test_planner.py

Shard: `other-cpu-unit-and-scenarios`; collected: 10.

```text
PASSED tests/test_planner.py::test_open_cv_result_changes_the_action
PASSED tests/test_planner.py::test_collision_risk_has_priority_over_battery_plan
PASSED tests/test_planner.py::test_critical_battery_uses_least_risk_zone_without_waiting
PASSED tests/test_planner.py::test_low_confidence_is_fail_closed
PASSED tests/test_planner.py::test_low_battery_returns_home_only_when_navigation_is_available
PASSED tests/test_planner.py::test_collision_and_critical_battery_needs_emergency_recovery
PASSED tests/test_planner.py::test_high_temporal_risk_triggers_preemptive_evasion
PASSED tests/test_planner.py::test_temporal_risk_plus_critical_battery_triggers_recovery
PASSED tests/test_planner.py::test_gps_loss_uses_visual_localization_fallback_when_confident
PASSED tests/test_planner.py::test_gps_loss_holds_when_visual_localization_is_unreliable
```

### tests/test_profiling.py

Shard: `cpu-profiling-cuda-opt-in`; collected: 16.

```text
PASSED tests/test_profiling.py::test_snapshot_matches_production_with_retry_and_state
PASSED tests/test_profiling.py::test_comparison_rejects_pixel_decision_shape_and_missing_changes
PASSED tests/test_profiling.py::test_artifacts_warmup_and_state_reset
PASSED tests/test_profiling.py::test_input_validation_and_percentiles
PASSED tests/test_profiling.py::test_collector_controlled_clock_nested_residual_and_exception
PASSED tests/test_profiling.py::test_instrumentation_branches_retry_state_and_restoration
PASSED tests/test_profiling.py::test_stage_replay_exact_and_branch_summary_recomputable
PASSED tests/test_profiling.py::test_benchmark_baseline_unpatched_and_failure_restores_state
PASSED tests/test_profiling.py::test_round_failure_restores_instrumentation_and_runtime[1]
PASSED tests/test_profiling.py::test_round_failure_restores_instrumentation_and_runtime[2]
PASSED tests/test_profiling.py::test_round_failure_restores_instrumentation_and_runtime[3]
PASSED tests/test_profiling.py::test_compensation_accept_reject_and_resize_boundaries
PASSED tests/test_profiling.py::test_original_reference_gate
PASSED tests/test_profiling.py::test_real_module_cli_regression[False]
PASSED tests/test_profiling.py::test_real_module_cli_regression[True]
PASSED tests/test_profiling.py::test_capture_is_explicit_and_partial_setup_restores_overrides
```

### tests/test_px4_shadow_policy.py

Shard: `offline-control-guards`; collected: 3.

```text
PASSED tests/test_px4_shadow_policy.py::test_healthy_link_and_gps_continue
PASSED tests/test_px4_shadow_policy.py::test_gps_loss_revokes_authority
PASSED tests/test_px4_shadow_policy.py::test_failed_link_holds
```

### tests/test_px4_supervisor.py

Shard: `offline-control-guards`; collected: 3.

```text
PASSED tests/test_px4_supervisor.py::test_failure_is_immediate
PASSED tests/test_px4_supervisor.py::test_recovery_requires_three_samples
PASSED tests/test_px4_supervisor.py::test_stale_telemetry_revokes_authority
```

### tests/test_px4_telemetry.py

Shard: `offline-control-guards`; collected: 2.

```text
PASSED tests/test_px4_telemetry.py::test_px4_snapshot_maps_to_aegisland_telemetry
PASSED tests/test_px4_telemetry.py::test_px4_battery_is_clamped
```

### tests/test_px4_telemetry_recovery.py

Shard: `offline-control-guards`; collected: 4.

```text
PASSED tests/test_px4_telemetry_recovery.py::test_telemetry_degradation_revokes_immediately
PASSED tests/test_px4_telemetry_recovery.py::test_failed_telemetry_revokes_immediately
PASSED tests/test_px4_telemetry_recovery.py::test_telemetry_recovery_requires_three_samples
PASSED tests/test_px4_telemetry_recovery.py::test_cached_valid_position_cannot_override_stale_telemetry
```

### tests/test_px4_watchdog.py

Shard: `offline-control-guards`; collected: 6.

```text
PASSED tests/test_px4_watchdog.py::test_watchdog_health_transitions[0.1-healthy]
PASSED tests/test_px4_watchdog.py::test_watchdog_health_transitions[0.5-degraded]
PASSED tests/test_px4_watchdog.py::test_watchdog_health_transitions[1.0-degraded]
PASSED tests/test_px4_watchdog.py::test_watchdog_health_transitions[1.5-failed]
PASSED tests/test_px4_watchdog.py::test_watchdog_health_transitions[3.0-failed]
PASSED tests/test_px4_watchdog.py::test_watchdog_rejects_negative_age
```

### tests/test_recovery.py

Shard: `other-cpu-unit-and-scenarios`; collected: 3.

```text
PASSED tests/test_recovery.py::test_recovery_plan_contains_safe_emergency_sequence
PASSED tests/test_recovery.py::test_recovery_skips_brake_when_already_slow
PASSED tests/test_recovery.py::test_non_recovery_decision_has_no_recovery_plan
```

### tests/test_reliability_benchmark.py

Shard: `reliability_benchmark`; collected: 4.

```text
PASSED tests/test_reliability_benchmark.py::test_cascading_failure_moves_through_capability_modes
INTERRUPTED tests/test_reliability_benchmark.py::test_combined_position_sensor_failure_never_continues_mission
NOT_STARTED tests/test_reliability_benchmark.py::test_out_of_order_imu_is_time_synchronized
NOT_STARTED tests/test_reliability_benchmark.py::test_reliability_metrics_report_safe_failure_response
```

### tests/test_safety_assessment.py

Shard: `safety_assessment`; collected: 4.

```text
INTERRUPTED tests/test_safety_assessment.py::test_deterministic_safety_gates_pass
NOT_STARTED tests/test_safety_assessment.py::test_assessment_preserves_authority_ablation
NOT_STARTED tests/test_safety_assessment.py::test_report_explicitly_limits_certification_claims
NOT_STARTED tests/test_safety_assessment.py::test_assessment_artifacts_are_written
```

### tests/test_safety_dashboard.py

Shard: `safety_dashboard`; collected: 2.

```text
PASSED tests/test_safety_dashboard.py::test_dashboard_is_generated
PASSED tests/test_safety_dashboard.py::test_missing_evidence_fails_fast
```

### tests/test_sensor_failure_benchmark.py

Shard: `sensor_failure_benchmark`; collected: 4.

```text
PASSED tests/test_sensor_failure_benchmark.py::test_all_sensor_failure_matrix_cases_enter_expected_mode
PASSED tests/test_sensor_failure_benchmark.py::test_loss_of_gps_enters_visual_inertial_fallback
PASSED tests/test_sensor_failure_benchmark.py::test_loss_of_all_position_sources_degrades_safely
PASSED tests/test_sensor_failure_benchmark.py::test_gps_authority_recovers_conservatively_then_transfers
```

### tests/test_sensor_faults.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_sensor_faults.py::test_no_fault_preserves_frame
PASSED tests/test_sensor_faults.py::test_overexposure_increases_mean_brightness
PASSED tests/test_sensor_faults.py::test_underexposure_reduces_mean_brightness
PASSED tests/test_sensor_faults.py::test_occlusion_blocks_a_large_region
PASSED tests/test_sensor_faults.py::test_blur_reduces_high_frequency_image_energy
```

### tests/test_sensor_health.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_sensor_health.py::test_hard_invalid_sensor_fails_immediately
PASSED tests/test_sensor_health.py::test_low_confidence_sensor_fails_immediately
PASSED tests/test_sensor_health.py::test_medium_confidence_is_degraded_not_failed
PASSED tests/test_sensor_health.py::test_failed_sensor_requires_sustained_recovery
PASSED tests/test_sensor_health.py::test_sensor_sources_have_independent_health_state
```

### tests/test_sensor_sync.py

Shard: `other-cpu-unit-and-scenarios`; collected: 3.

```text
PASSED tests/test_sensor_sync.py::test_visual_and_imu_are_aligned_to_same_timestamp
PASSED tests/test_sensor_sync.py::test_out_of_order_imu_arrival_still_synchronizes_correctly
PASSED tests/test_sensor_sync.py::test_snapshot_can_degrade_when_visual_data_is_missing
```

### tests/test_stability.py

Shard: `other-cpu-unit-and-scenarios`; collected: 3.

```text
PASSED tests/test_stability.py::test_safety_escalation_is_immediate
PASSED tests/test_stability.py::test_single_safe_frame_does_not_immediately_cancel_emergency
PASSED tests/test_stability.py::test_action_can_deescalate_after_latch_expires
```

### tests/test_targeting.py

Shard: `other-cpu-unit-and-scenarios`; collected: 2.

```text
PASSED tests/test_targeting.py::test_target_stays_locked_when_another_zone_scores_higher
PASSED tests/test_targeting.py::test_target_releases_after_three_unsafe_frames
```

### tests/test_temporal.py

Shard: `other-cpu-unit-and-scenarios`; collected: 4.

```text
PASSED tests/test_temporal.py::test_temporal_risk_increases_for_object_approaching_target
PASSED tests/test_temporal.py::test_object_moving_away_has_low_temporal_risk
PASSED tests/test_temporal.py::test_tracker_predicts_through_one_missing_observation
PASSED tests/test_temporal.py::test_no_observation_before_initialization_has_zero_risk
```

### tests/test_time_sync.py

Shard: `other-cpu-unit-and-scenarios`; collected: 7.

```text
PASSED tests/test_time_sync.py::test_out_of_order_samples_are_stored_in_timestamp_order
PASSED tests/test_time_sync.py::test_exact_timestamp_returns_exact_sample
PASSED tests/test_time_sync.py::test_interpolates_between_sensor_samples
PASSED tests/test_time_sync.py::test_short_horizon_extrapolation_uses_recent_velocity
PASSED tests/test_time_sync.py::test_excessive_extrapolation_is_rejected
PASSED tests/test_time_sync.py::test_buffer_is_bounded
PASSED tests/test_time_sync.py::test_out_of_order_insertions_are_counted
```

### tests/test_tracking.py

Shard: `other-cpu-unit-and-scenarios`; collected: 3.

```text
PASSED tests/test_tracking.py::test_tracker_estimates_forward_motion
PASSED tests/test_tracking.py::test_tracker_smooths_noisy_measurements
PASSED tests/test_tracking.py::test_tracker_can_predict_missing_measurement
```

### tests/test_trajectory_eval.py

Shard: `harness-related`; collected: 11.

```text
PASSED tests/test_trajectory_eval.py::test_umeyama_recovers_rigid_transform_without_scale
PASSED tests/test_trajectory_eval.py::test_umeyama_recovers_scale_when_requested
PASSED tests/test_trajectory_eval.py::test_ate_is_zero_for_rigidly_transformed_copy
PASSED tests/test_trajectory_eval.py::test_ate_rejects_scale_alignment_label_as_metric
PASSED tests/test_trajectory_eval.py::test_ate_measures_known_constant_offset_error
PASSED tests/test_trajectory_eval.py::test_associate_drops_pairs_outside_time_tolerance
PASSED tests/test_trajectory_eval.py::test_associate_rejects_unsorted_timestamps
PASSED tests/test_trajectory_eval.py::test_ate_requires_minimum_number_of_pairs
PASSED tests/test_trajectory_eval.py::test_rpe_is_zero_for_rigidly_transformed_copy_and_detects_drift
PASSED tests/test_trajectory_eval.py::test_tum_round_trip_and_euroc_groundtruth_loading
PASSED tests/test_trajectory_eval.py::test_trajectory_rejects_non_finite_values
```

### tests/test_ttc.py

Shard: `other-cpu-unit-and-scenarios`; collected: 5.

```text
PASSED tests/test_ttc.py::test_object_moving_toward_target_has_finite_ttc
PASSED tests/test_ttc.py::test_object_moving_away_has_infinite_ttc
PASSED tests/test_ttc.py::test_object_crossing_sideways_is_not_closing
PASSED tests/test_ttc.py::test_imminent_collision_is_critical
PASSED tests/test_ttc.py::test_stationary_object_has_no_temporal_collision
```
