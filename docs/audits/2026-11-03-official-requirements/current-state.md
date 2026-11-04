# Current repository state

Audit date: 2026-11-03. Source checkout: `<original checkout outside this repository>`, branch `main`, clean, HEAD `cf4dfae5cae8e4ce63b94bd77a715013ed5c141a`, origin `https://github.com/Cyberchopin/dronehacks-autonomy-2026.git`.

Writable audit clone: `.`, branch `audit/official-requirements-2026-11-03`, same HEAD and origin. Created with `git clone --no-hardlinks` from the clean same-repository source because the mount is outside writable roots. Original checkout preserved. No applicable AGENTS.md or `.codegraph/` was present. This new clone is isolated from existing agent worktrees. At audit time, dirtiness consisted solely of the untracked audit directory; environment/cache files were ignored. Nothing had then been committed or pushed. `git ls-remote` failed DNS resolution, exit 128; `origin/main` is a copied local ref, not freshly verified remote main.

## Observed architecture and actual paths

- `pyproject.toml` → `dronehacks-course-replay` → `course_replay.main/run` → `OfflineFrame.validate` → `CoursePerception.observe` → grayscale/line/CLAHE, `sector_report`, `_clearance`, `_openings`, `_landing` → `JsonlTraceStore.write`. All outputs are advisory. Course CLI does not call SetpointSafetyGate, a planner, a ROS adapter or a publisher.
- `benchmark_harness.main/run` → native `benchmark_adapters.synthetic/euroc_inputs/run_vdr` or recorded/legacy adapters → strict `benchmark_contract` validation → source/environment/input hashes and seal. Adapter names for cuVSLAM/FFS are artifact readers, not active vendor algorithms. `VisualDeadReckoner.update` accumulates normalized image displacement; no metric trajectory, sensor fusion or drift estimate.
- `dronehacks-forensics` → `forensics.cli.main` → ULog/JSONL ingest and conditional clock alignment → `analysis.analyze` → report. Integration CLI → `integration.audit_bundle` → `recorder.record_run/verify_run`; sensor bundles are local recordings, not subscriptions.
- `SetpointSafetyGate.evaluate` and `SensorHealthMonitor.assess` are pure objects. `Px4ShadowSupervisor.step` consumes caller-provided telemetry/global-position health; `decide_shadow_action` retains a GPS-dependent policy. These are not a GPS-denied mission state machine.
- `integration/starter_adapter/README.md` is the sole starter adapter artifact. No live sensor ingester, ROS package/launch, full-course planner, command publisher, arm/land/disarm executor or physical-run evidence is present.
- `trace.CloudTraceStore` retains a lazy AWS upload path despite README's migration narrative. Static search found no current caller. `course_replay` uses the local store. No cloud path was invoked; its existence should be documented or removed in a later scoped cleanup, not treated as an active offboard loop.

## Current evidence by level

| Level | Evidence observed | Limits |
| --- | --- | --- |
| STATIC_REVIEW | 77 tracked files hashed; source entry points and 60 provenance CSV rows inspected | Historical provenance PASS cannot be reproduced with missing migrated inputs |
| UNIT_TEST | 358/358 current tests passed across four bounded groups; no skips | Tests validate implemented conditions, not completeness or flight safety; audit probes found accepted malformed inputs |
| SYNTHETIC_REPLAY | 36-frame course replay including adversarial scenes; synthetic integration/log fixtures exercised in tests | No recorded camera, official simulator or hardware data |
| RECORDED_REAL_DATA | NONE | NPZ loading and ULog parsing tests use generated fixtures |
| OFFICIAL_SIMULATION | NONE | No issued starter/sim package, reset/scoring trace or spend authority |
| SHADOW_HARDWARE | NONE | Shadow-named pure tests are not connected hardware evidence |
| AUTHORIZED_PHYSICAL_RUN | NONE | No hardware access or commands |

All 36 replay rows retain `full_3d_traversability=UNKNOWN`; local projection width cannot establish gate/tunnel or swept-volume safety. Outside-ROI and beyond-probe obstacle scenes still return local support by design. `capabilities` explicitly says window/return unimplemented and metric VIO/SLAM not provided. Confidence values are heuristics, not calibrated probabilities. Landing geometry requires a downward view; the issued camera mounting/orientation and how to obtain such a view are unknown.

Single-pass desktop observe latency: median 4.538 ms, p95 7.498 ms, max 12.895 ms, n=36. Includes cold first frame, input hashing and stage instrumentation; excludes disk I/O. This is WSL x86_64 CPU data, not Orin latency, throughput, field accuracy or a baseline/treatment comparison.

## Bounded commands and environment

Environment: Linux WSL2 x86_64, Python 3.12.3, NumPy 2.5.4, OpenCV 5.0.0, pytest 8.4.2, PyULog 1.2.2, Ruff 0.14.3. Dependencies installed only into this clone's ignored `.venv` with `python3 -m venv .venv` and `.venv/bin/python -m pip install --retries 0 --timeout 20 -e '.[dev,vision,forensics]'` (both exit 0). Windows `.deps` contains Windows binary extensions and was not reused. No dependency pin changed. Installation output was observed in the tool transcript; it was not captured as a timed audit run. Test/replay commands below have timed raw stdout/stderr and metadata.

All checks use [capture.py](capture.py): `python3 docs/audits/2026-11-03-official-requirements/capture.py LABEL TIMEOUT COMMAND...`. Metadata records exact argv, timeout, duration, HEAD, environment overrides and raw-output hashes. `PYTHONPATH=src`, bytecode disabled, external pytest plugin autoload disabled, OMP/OpenBLAS threads set to one. Course replay itself sets OpenCV threads to one. The [portable evidence](portable/README.md) contains labeled derivatives under `portable/evidence/`; raw originals remain local. Commands are historical, and should not overwrite the preserved copies.

| Label | Command after capture wrapper | Timeout | Exit / result |
| --- | --- | --- | --- |
| safety-tests | `.venv/bin/python -m pytest -o addopts= -q tests/test_competition_contract.py tests/test_sensor_health.py tests/test_px4_watchdog.py tests/test_px4_telemetry.py tests/test_px4_supervisor.py` | 60 s | 0; 22 passed |
| perception-tests | `.venv/bin/python -m pytest -o addopts= -q tests/test_course_perception.py tests/test_course_adversarial.py tests/test_depth_sectors.py tests/test_perception_quality.py tests/test_gps_denied.py` | 120 s | 0; 135 passed |
| forensics-tests | `.venv/bin/python -m pytest -o addopts= -q tests/test_forensics.py tests/test_forensics_integration.py` | 120 s | 0; 163 passed |
| benchmark-tests | `.venv/bin/python -m pytest -o addopts= -q tests/test_benchmark_contract.py` | 120 s | 0; 38 passed |
| course-replay | `.venv/bin/python -m aegisland.course_replay --adversarial --output docs/audits/2026-11-03-official-requirements/evidence/course-replay` | 90 s | 0; 36 synthetic frames |
| ruff-check / ruff-format | `.venv/bin/ruff check src tests`; `.venv/bin/ruff format --check src tests` | 30 s each | 0 / 0; 51 files formatted |
| safety-probe-expanded | `.venv/bin/python docs/audits/2026-11-03-official-requirements/safety_probe.py` | 30 s | 0 means observations captured, **not safety passed** |
| static-inventory-v2 | `.venv/bin/python docs/audits/2026-11-03-official-requirements/static_inventory.py` | 30 s | 0; hashes, symbols, broken links, package metadata |
| remote-main | `git ls-remote origin refs/heads/main` | 30 s | 128; DNS failure |

Initial `static-inventory` failed (exit 1) because the audit helper assumed setuptools remained installed after isolated build. The helper now records missing optional metadata; both the failure and v2 output are preserved. Runtime and tests were not edited. The original safety probe output remains local; the expanded sensor-health probe is included as a derivative. No broad repeated suite was run.

## Negative observations and inferences

`safety-probe-expanded.stdout.txt` records an invalid mode accepted as HARDWARE_GATED; NaN current/advisory time accepted; string health flags accepted; NaN speed limit admits 100 m/s; unknown depth admits lateral/negative-x/local-NED motion; zero confidence is not gated; integer zero is accepted for executed. NaN watchdog age is healthy. Three consecutive NaN sensor confidences become healthy with effective confidence 1.0. These are input-validation/policy defects in pure code; none emits a command.

The gate applies `vx>0` without a frame transform. A local-NED velocity does not determine camera-forward motion; coverage must be defined in a validated sensing frame before publishing. Existing speed and envelope values are engineering defaults, not official limits. With healthy telemetry and no GPS the legacy policy always recommends hold; it cannot be used unchanged as the indoor mission authority model.

Python >=3.11/StrEnum versus Humble's documented Jammy Python 3.10 baseline is a conditional integration blocker, not proof of the issued image's version. Eight broken Markdown references and two missing provenance-verifier inputs are observed. Its fixed output path would overwrite canonical historical evidence, so the original verifier was **not run**. No external historical cache was accessed.

## Historical reports, reproducibility and unknowns

README/CLAIMS report 170 course, 79+1 forensics, 310+1/29 benchmark and 195 Windows migration results. Those remain historical; the new 358-test baseline has a different scope. `CURRENT_STATUS.md` still says no remote was created, contradicted by this checkout's origin. No historical upstream binaries/data were recovered from other repositories.

Tracked assets contain no NPZ/ULog/bag/model/binary/course model. The 60-row provenance manifest references 44 small evidence records, 14 release-asset metadata records and two excluded assets; it is not evidence that those bytes ship here. Missing `provenance/audit-evidence.json` and `docs/handoffs/provenance-HANDOFF.md` prevent replaying the retained verifier. No top-level LICENSE file is tracked although pyproject declares Apache-2.0; review attribution/notice completeness before distribution.

Synthetic low-light noise is seeded (41); benchmark texture defaults to seed 7. Motion compensation uses OpenCV RANSAC without an explicit local RNG seed. Timing is environment-sensitive; no repeatability distribution or independent held-out validation was measured. Fresh replay includes source/config/input hashes; tracked source hashes and unchanged Git diff bind this audit to HEAD, while the dirty flag truthfully includes newly generated audit artifacts.
