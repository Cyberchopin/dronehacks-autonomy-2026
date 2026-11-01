# Migration manifest

Source repository: `Cyberchopin/aegisland-agentic-vision`

Source commit: `28d36ded36e8f1132eeb71a772e74ef0570c2a05`

Migration date: 2026-11-01

## Retained

| Area | Files | Reason |
| --- | --- | --- |
| Course perception | `course_*`, `depth_sectors.py` | Directly maps to corridor, maze, tunnel, opening and landing evidence |
| GPS-denied baseline | `gps_denied.py` | Useful normalized-motion baseline and adversarial test dependency |
| Health | `sensor_health.py`, `perception_quality.py` | Fail-fast/recover-slow evidence gates |
| PX4 shadow | `px4/watchdog.py`, `telemetry.py`, `shadow_policy.py`, `supervisor.py` | Read-only link/telemetry policy; no command client |
| Benchmark | `benchmark_*` | Strict adapters, immutable run directories and result contract |
| Forensics | `forensics/` | Read-only ULog/Jetson evidence and time alignment |
| Provenance | selected audit files | License and artifact decisions remain reviewable |

## Excluded

| Area | Reason |
| --- | --- |
| AWS/infra/dashboard/grant | Not part of the DroneHacks onboard autonomy path |
| Old end-to-end emergency-landing agent | Carries unrelated competition narrative and simulated command stack |
| Generated benchmark results | Large historical evidence stays in the source repository; new runs start clean |
| Fast-FoundationStereo runner/results | Competition delivery NO-GO under reviewed license terms |
| Kimera | Fallback was not activated and would increase integration risk |
| cuVSLAM binary payloads | No target ARM64/JetPack compatibility proof; integrate only from official packages |
| C++/CUDA side experiments | No demonstrated DroneHacks target benefit yet |
| Presentation assets | Engineering first; regenerate from current evidence later |
| Legacy timeout/handoff notes | They describe the old monorepo/worktrees, not the slim competition repository |

## Compatibility rule

The Python import namespace remains `aegisland` for the first migration so the retained,
already-tested modules do not undergo a risky mass rename. Rename only after the official
starter integration is green and bounded by tests.

