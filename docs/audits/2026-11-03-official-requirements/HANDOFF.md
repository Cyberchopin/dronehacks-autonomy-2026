# Official-requirements audit handoff — 2026-11-03

**Audit deliverables complete; integration/flight readiness remains blocked.** Audited mainline is `cf4dfae5cae8e4ce63b94bd77a715013ed5c141a`. Original checkout on `main` was clean. Audit work lives in `.`, branch `audit/official-requirements-2026-11-03`, same audited HEAD at the time; the audit directory was then untracked. Origin is `https://github.com/Cyberchopin/dronehacks-autonomy-2026.git`. Remote-main verification failed DNS resolution; current remote HEAD is UNKNOWN.

The five highest-priority gaps are:

1. Missing issued official starter/simulator/rule/model contract, including current amendments and deadlines.
2. Safety validation defects: invalid modes can receive HARDWARE_GATED; NaN time/limits/health bypass validation; NaN sensor confidence becomes healthy/1.0.
3. No live sensor adapter or proven target Python/ABI/QoS/frame/time/calibration compatibility.
4. No metric GPS-denied localization; legacy shadow policy depends on GPS/global-position health.
5. No official end-to-end course evidence: local detectors do not establish 3D traversal, landing/disarm, mission progress or target latency.

See [prioritized gaps](prioritized-gaps.md) for exact evidence and [implementation plan](smallest-high-impact-plan.md) for bounded ownership, measures, failure cases, dependencies and stop conditions.

## Sources and claim limits

[Official event page](https://dronehacks.groups.stanford.edu/) and [Code of Conduct](https://dronehacks.groups.stanford.edu/coc) were accessible. Detailed challenge/rules/hardware retrievals failed; supplied scoring, geometry and architecture rules remain OFFICIAL_SNAPSHOT. Simulation credit/token notice remains a relayed ORGANIZER_MESSAGE. No current staff amendments, original model, starter commit/license, simulator bootstrap/API, device image/calibration or physical authorization was available. [Ledger](official-source-ledger.md) records sources, access date, volatility and conflicts; [input manifest](portable/INPUTS.md) hashes the supplied snapshots.

**Observed:** 358/358 tests across four bounded groups passed, Ruff check/format passed, and a 36-frame synthetic replay completed. All replay authority remained NONE, executed false, full 3D traversability UNKNOWN. Desktop observe median 4.538 ms and p95 7.498 ms over 36 generated frames are not target or flight metrics. Expanded pure-object safety probes preserve the counterexamples despite green existing tests. **Inference:** those gaps must close before connecting an execution adapter. **Unknown:** actual target compatibility, course performance, metric localization drift and safety response. Historical Windows/upstream test counts and provenance PASS remain historical.

Exact commands, environment, duration, exit status and raw-output paths are in [current state](current-state.md) and `portable/evidence/*.command.json` (sanitized derivatives; see [manifest](portable/derivative-manifest.json)). Group results: safety 22, perception 135, forensics 163, benchmark 38. Timeouts were 60/120/120/120 seconds; all completed in under two seconds of captured wall time in this environment. The course replay timeout was 90 seconds. The initial audit inventory-helper failure (missing setuptools metadata) and remote DNS failure are preserved. The corrected helper records missing optional metadata; it does not alter runtime behavior. Original provenance verifier was not run: it requires two missing files and writes the canonical historical report. Eight broken Markdown references remain documented.

## Deliverables and file boundary

- [official-source-ledger.md](official-source-ledger.md): tiered sources, snapshot rule inventory and missing/conflicting originals.
- [current-state.md](current-state.md): exact checkout, call paths, capabilities, historical/current evidence and reproducibility limits.
- [requirements-evidence-matrix.csv](requirements-evidence-matrix.csv): 35 requirements with all 16 fields, including exact implementation/test/artifact or NONE, owner and stop condition.
- [prioritized-gaps.md](prioritized-gaps.md): competition-ranked gaps and counterexamples.
- [smallest-high-impact-plan.md](smallest-high-impact-plan.md): atomic follow-up tasks with isolated path ownership and no implicit execution authority.
- This handoff; [input availability](portable/INPUTS.md), sanitized test/probe captures, 36-frame replay evidence and audit-only capture/inventory/probe helpers. Original input copies and raw captures remain local.

All additions are under `docs/audits/2026-11-03-official-requirements/`. Existing runtime source, tests, dependency pins, launch/configuration files and canonical handoffs are unchanged. Ignored `.venv`, build metadata and test caches were generated locally. No other repository's source, cache, binaries or historical results were copied. No push, merge, deployment, cloud spend, organizer message, hardware connection or flight command occurred. Only offline checks/probes/replay were executed. No independent review is claimed.

## Smallest next gate

**W01: capture the issued official contract in documentation only.** Team/user must supply the current authorized starter/package, detailed rules/amendments, simulator instructions and model release. Obtain actual Python/firmware/messages/calibration/interface facts before deciding compatibility or observer implementation. Do not request a token or spend credit under this prompt. The next self-contained code task after the audit is W02 advisory-contract validation; it can be done without hardware and without guessing organizer interfaces. This audit does not implement it.

```text
Status Card
Current mainline: local main cf4dfae5cae8e4ce63b94bd77a715013ed5c141a; remote currency UNKNOWN
Accepted evidence: 358 unit tests, 36-frame synthetic replay, static inventory, preserved safety counterexamples
Unresolved official inputs: current detailed rules/amendments, starter/simulator/model release, target image/interfaces/calibration
Next atomic Worker task: W01 documentation-only issued-contract capture; W02 is the first bounded code follow-up
Authority level: observer/read-only
```
