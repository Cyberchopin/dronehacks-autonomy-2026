# Smallest high-impact plan

This is an implementation queue, not work executed in the audit. All numeric test sizes/targets below are TEAM_ASSUMPTION engineering gates. Verify them against the captured official contract. Owners are roles, not assigned people. An independent reviewer is proposed; this audit itself was performed by one Worker with no independent reviewer or sub-agent.

Every Worker must stay in a named isolated checkout of `Cyberchopin/dronehacks-autonomy-2026`, record branch/HEAD/dirty state, preserve other work, and change only its owned paths. Read the source ledger and current raw evidence first. No push, merge, deployment, credit spend, staff messages, hardware or flight commands is authorized by these tasks. Official simulation that starts a service or spends credit needs separate user authorization. Hardware always needs organizer authorization and supervision. Handoff must include exact commands/exits, failed cases, input/config/source hashes, evidence level, changed files and stop conditions. Reviewable artifact, then user integration decision; no automatic merge.

## W01 — capture issued official contract (next task)

- Requirements: G01–G05/G09, SC01–SC03, I01–I02, P14. Owner: integration with team/organizer-provided inputs. Baseline: placeholder adapter and snapshot rules; NOT_IMPLEMENTED issued contract.
- Own only new `docs/official-inputs/` documents/manifests. No source, tests, launch files, dependencies or hardware parameters.
- Inputs: user-supplied exact official starter/package, rubric/amendments, model and simulator instructions. Output one manifest with URL/origin, release/date, commit or SHA-256, license, units/axes, read-only interface inventory, actual Python/ROS/PX4/messages/DDS/DepthAI/JetPack versions, camera/range calibration, start/abort workflow and simulation cost/reset contract. Do not include tokens.
- Success: every required field has captured provenance or explicit UNKNOWN; no invented topic/QoS/version; zero runtime changes. Count known/unknown fields. Fault cases: conflicting revisions, missing license, model without declared units/axes, absent token instructions. Missing originals stay pending.
- Dependency: issued inputs; public site alone cannot close this gate. Stop before implementing any assumed interface, contacting staff or consuming credit. Artifact: manifest plus source ledger amendment. Reviewer checks 100% of captured identities against original bytes and current official text.

## W02 — harden advisory contract before integration

- Requirements: G03/P11/P13. Owner: safety/integration. Own only `src/aegisland/competition_contract.py` and `tests/test_competition_contract.py`.
- Baseline: existing 6 parametrized cases pass; audit probe exposes unknown-mode, NaN, string-flag, nonboolean executed and limit validation gaps. Evidence UNIT_TEST, no publisher.
- Success: all malformed mode, timestamp, flag, executed and limit cases reject without authority; valid observer/shadow remain nonexecuting; valid simulation has executed exactly false. Exercise at least 24 table-driven cases across modes, all four declared frames, finite/nonfinite limits, negative/future/stale/integer boundary times and false/zero/string booleans. Record numerator/denominator.
- Decide and document direction/coverage semantics with the official frame contract; do not patch `vx>0` by guessing heading or assuming full 3D coverage. Unsupported combinations reject or explicitly remain blocked.
- Fault/variation: NaN/infinities, unexpected enums, missing health, unknown depth, lateral/backward motion and zero confidence. Simulator dependency: none for validation; exact frame policy remains dependent on W01. Stop on any request to emit commands or relax authority. Artifact: before/after same-case JSON and bounded pytest output. Reviewer replays the original audit counterexamples and inspects every accepted-authority branch.

## W02b — reject invalid health/watchdog values

- Requirements: P12/G03. Owner: safety. Own only `sensor_health.py`, `px4/watchdog.py`, `tests/test_sensor_health.py`, `tests/test_px4_watchdog.py`.
- Baseline: three NaN confidence values recover to healthy/1.0; NaN age is healthy. Success: zero healthy outputs from nonfinite or wrongly typed confidence/age/validity/threshold inputs; ordinary finite hysteresis preserved. At least 20 invalid/boundary cases and 3 finite recovery sequences, with exact input/output traces.
- Variation/faults: NaN, ±inf, bool-as-number, string flags, threshold order, rollback age, alternating valid/lost observations. Dependency: pure offline, no simulator needed. Stop if semantics require weakening normal failure or recovery gates. Artifact: reproduction and regression logs; reviewer inspects clamp/comparison behavior and confirms executed semantics remain unchanged.

## W03 — resolve issued-image compatibility

- Requirements: I03/E01. Owner: integration. Own new `docs/official-inputs-compatibility/` only; no broad StrEnum replacement or pin changes in this task.
- Baseline STATIC_REVIEW: Python >=3.11/StrEnum; current desktop 3.12; Humble Jammy baseline 3.10. Actual target unknown.
- Success: one explicit compatibility decision for every required Python/native/ROS component using the issued image/package metadata; 0 unexplained ABI/version substitutions. Capture a bounded import smoke command for the actual supported environment when available without hardware access. Test mismatched Python, architecture and missing native package as negative metadata cases.
- Dependency W01; stop on absent image evidence, global installs or replacement of organizer packages. Artifact: compatibility table with exact package identities and minimal follow-up scope. Reviewer verifies the decision against versioned upstream and package metadata. Any compatibility code change becomes a separate atomic task after this decision, with paths reserved after W02/W02b complete.

## W04 — observer-only sensor adapter

- Requirements: P01–P03/G06. Owner: integration. Own new `integration/starter_adapter/observer/` and new `tests/test_starter_observer.py`; maintain existing placeholder README only after W01 specifies real layout. No changes to core perception or safety files.
- Baseline NOT_IMPLEMENTED live capture; offline arrays and four-stream records tested. Success: 3 recordings of at least 300 synchronized RGB/depth samples each, with range/local-state coverage explicitly counted; source age/skew distributions in ms, rates in Hz, dropped count, frame IDs, units, transforms and calibration hashes. Acceptance limits come from the captured interface/requirements, not defaults guessed here. 100% invalid inputs marked unknown/rejected.
- Faults: missing/corrupt depth, stale/out-of-order/future time, clock reset, QoS incompatibility, calibration mismatch, corrupt transform and dropped messages. Numeric NED/ENU and FRD/FLU round trips must match documented conventions.
- Dependencies W01/W03 and an authorized local simulation or supplied recorded dataset. Zero command publishers, mode/arm/parameter clients or `/fmu/in/*` outputs. Stop on unavailable calibrations or acquisition requiring hardware/service authority. Artifact: immutable local recordings and replay evidence. Reviewer checks topic graph, import/call paths, transforms and 10 sampled records per stream.

## W05 — reproducible official-simulation baseline

- Requirements SC01–SC03/I02/P15/E02. Owner: harness/integration. Own new `docs/simulation-baseline/` experiment protocol and resulting local evidence; no publisher implementation in this task.
- Baseline: zero official trials. After separate simulation/cost authorization, run 3 fixed official scenarios ×3 repeats (9 runs) with identical reset, starter revision, inputs and configuration. Record completion/checkpoints out of attempted runs, penalty-adjusted seconds, touches, resets, aborts, loss, latency median/p95 and memory; preserve every failure. No invented accuracy target before baseline exists.
- Variations: nominal, low light and sensor-loss cases only if the issued simulator supports them; unsupported cases remain UNKNOWN. Fault: disconnect/reset failure or missing logs stops the series. W01/W03 and authorized issued simulator are prerequisites. Stop on cost cap, runtime authority change or incomplete reset proof. Reviewer independently recomputes checkpoint/penalty metrics from official logs and checks all 9 run identities. Do not claim this audit's synthetic replay as that baseline.

## W06 — GPS-denied localization evidence

- Requirements G07/P09/P10. Owner: perception. Own new `integration/localization_evidence/`, new `tests/test_localization_evidence.py` and new `docs/localization-evaluation/`. No vendor binaries or replacement framework in this task.
- Baseline: normalized VDR only; metric evaluator UNIT_TEST; issued estimator unknown. Prefer evaluating the official local estimator before adding a dependency.
- Success: at least 3 held-out sequences, each ≥300 valid timestamp opportunities; report coverage denominator, tracking-loss episodes, recovery seconds, scale/frame contract and metric ATE/RPE in m where independent reference exists. If reference is absent, metric drift stays UNKNOWN; normalized baseline never gets metric scores. Fix same inputs/preprocessing/environment for comparisons.
- Faults: low texture/light, blur, IMU/depth loss, timestamp rollback, invalid pose and frame mismatch. Dependencies W01/W03/W04; simulated reference must be labeled official simulation. Stop if package rights/ABI, scale or reference alignment unresolved. Artifact: sealed inputs/outputs and explicit metric availability. Reviewer recomputes associations and score definitions from preserved data.

## W07 — one perception reliability improvement at a time

- Requirements P04–P08/P14. Owner: perception. Own `course_perception.py`, `course_config.py`, `tests/test_course_perception.py`, `tests/test_course_adversarial.py`; reserve these paths for one Worker at a time. Do not change safety/adapter/localization files.
- Baseline SYNTHETIC_REPLAY: 36 cases with documented failure/unknown limits. Choose one worst verified checkpoint failure from W05; no broad detector rewrite.
- Proposed measurement set: ≥30 independently labeled held-out examples per affected class (line, opening, tunnel visibility, obstacle or pad), ≥30 negative/ambiguous examples, with ≥3 lighting/geometry conditions. Report precision/recall/abstention with numerator/denominator and localization/clearance error in m only when reference exists. Candidate must reduce the selected baseline error without adding any false supported/safe assertion on the locked negative set. If sample scarcity prevents this, report it rather than claim generality.
- Faults: black frame, blur, depth holes/NaN/zero, stale/missing pairs, narrow opening, ROI-external obstacle, calibration error, clipped/competing rings. Dependencies W04/W05 and annotation provenance. Stop if identity, 3D coverage or actual camera orientation is unknown; keep advisory scope. Artifact: fixed split manifest, per-case baseline/treatment outputs, latency distribution and failures. Reviewer blinds the held-out labels during tuning and reviews false positives individually.

## W08 — GPS-denied advisory mission integration

- Requirements G04/G07/SC03/P11/P13. Owner: control/integration. Own new `src/aegisland/course_mission.py`, new `tests/test_course_mission.py`, and `px4/shadow_policy.py`, `px4/supervisor.py`, `tests/test_px4_supervisor.py`. Do not modify W02/W02b files; consume their completed contract.
- Baseline: no course FSM; GPS-dependent shadow policy. Success: ≥12 table-driven sequences covering each ordered checkpoint, uncertain/no progress, localization/depth loss, repeated candidate, timeout and abort latch; zero invalid advances and all outputs executed exactly false. Local-plane evidence alone cannot approve passage; retained GPS-oriented behavior must be explicitly separated or retired with migration notes.
- Dependencies W01/W02/W02b/W04/W06/W07. Actual motion/abort publishers remain outside this task. Faults: stale repeated frames, disconnected health, implausible stage jump, wrong pad, missing whole-drone crossing evidence. Stop when adequate progression evidence or emergency contract is missing. Artifact: transition traces linked to inputs; reviewer checks every authority/advance condition and all 12 sequences.

## W09 — comparable experiment and ablation

- Requirements SC04/P15/E02. Owner: harness. Own new `docs/comparison-protocol/` and local experiment artifacts. Baseline from W05; treatment from a single completed W07/W08 change.
- Run same 3 scenarios ×3 repeats for baseline, treatment and one ablation (27 runs total), only under separately authorized simulator budget. Report all outcomes, paired differences, median/p95 latency and failures; no best-run-only engineering claim. Lock metric definition, reset, data/preprocessing and environment. Stop on drift in those controls or spend cap. Reviewer recalculates results from hashes/raw logs, with full negative-result review.

## W09a — restore repository evidence portability

- Requirements E01/E03/G09. Owner: team/integration. Own `provenance/verify_consistency.py`, `provenance/verification-report.json`, the three existing provenance review documents, `docs/CURRENT_STATUS.md`, `docs/CLAIMS.md`, and broken-link source documents. No importing another repository's artifacts without a separately authorized source handoff.
- Baseline: eight broken references, two absent verifier inputs, historical PASS, no license text tracked. Success: zero unresolved links presented as current evidence; missing originals explicitly classified; offline verifier can produce a new report without overwriting historical provenance and without requiring an outside checkout. Preserve FFS NO-GO and inactive fallback. License/NOTICE completeness is a review outcome, not an inferred license grant.
- Faults: absent cache, corrupt hash, duplicate/malformed CSV row, missing source provenance and unavailable original documents. Dependency: exact upstream evidence handoff if recovery is needed. Stop rather than fabricate/recreate original evidence. Reviewer compares all changed claims to retained sources and reruns the portable check on a fresh checkout.

## W10 — separately authorized target validation

- Requirements G02/G05/P15. Owner: organizer/safety/integration. Own only new target-validation evidence and procedures; no flight-control or failsafe changes.
- Baseline: zero target/physical runs. After staff authorization, begin with the required safe observer setup, collect 3×300-frame shadow sessions, record device/image/calibration/power/temperature/memory and end-to-end latency/drop distributions. No physical trial count or speed target is set before organizer constraints are known.
- Faults only those staff explicitly authorize; no bench propeller or command testing under this plan. Stop on kill order, geofence/battery issue, loss of supervision or missing authorization. Independent safety reviewer signs evidence before any next physical gate. Simulator success alone does not grant flight authority.
