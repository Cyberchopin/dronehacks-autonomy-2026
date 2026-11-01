# Later B harness / D perception integration

This is a review plan, not an installed bridge or live integration. No modules,
results or dependencies were copied from sibling worktrees. Only their handoffs,
contract documentation and relevant source definitions were read.

The **latest B and D HANDOFF files were reread before finalizing this contract**.
Reference bytes at that refresh:

| Read-only source | SHA-256 |
| --- | --- |
| `../harness/HANDOFF.md` | `e944592ba8d0dbcdc00488a47bc7694740fa22d443f364bf9c11abfe205a85f5` |
| `../perception/HANDOFF.md` | `ae134ec733f224d879c2ef8c7da808c049a6c03f60bcd87107a4c2e2af78b46c` |
| `<agent-output>/baseline-audit/HANDOFF.md` | `78cf9e417f6540f2b485451e98d7417868f354d61f3d5e8f239f92c0df0cd020` |

B's refreshed handoff distinguishes its 38 new tests from 15 related existing
tests and leaves the complete-suite timeout unresolved. D's refreshed handoff is
the v2 adversarial, 36-frame delivery; its v1 examples are historical snapshots.
Those reported test counts were **not rerun or added to this worktree's counts**.
No B/D runtime, hardware performance or flight validation is claimed here.

The provenance audit remains pending final exit-0 verification regardless of
earlier handoff wording. All shared dependency/version decisions remain provisional.
Do not merge a CUDA/JetPack/DepthAI/OpenCV dependency choice from these documents
until the audit is complete and the actual target environment is reviewed.

## B harness bridge after contract review

1. Add a versioned, local-file-only importer in this worktree after the contract
   owners agree on revisions. Do not import a runner, device adapter or vendor
   subprocess. Preserve producer HEAD/config/environment/platform and raw bytes.
2. Require B's metadata schedule and one explicit slot per expected input,
   including dropped/lost/error slots and a final newline. Preserve the difference
   between upstream capture loss and the logged replay denominator. Do not turn
   our salvaged diagnostic prefixes into successful canonical B results.
3. OAK depth-only records can contribute depth coverage and slot diagnostics;
   they cannot claim a localization pose, tracking recovery or ATE. Keep recorded
   latency scope, cold/warm policy and unavailable values. Import time is not
   producer throughput. Set `valid_for_performance_claims=false`.
4. Map B `orin` only through its preserved hardware/machine/model declaration.
   Require explicit Nano identity for `jetson_orin_nano`; an unspecified Orin/NX
   remains unknown here. Keep origin measurement metadata separate from this
   replay host. Desktop, replay and SITL evidence do not become Orin evidence.
5. Check both producer integrity and the new independent run seal. A bridge
   acceptance test must reject schedule truncation, hash/count conflicts and
   resealed inconsistent summaries. No mission/map/trajectory export is added.

## D perception bridge after contract review

1. Consume the v2 `aegisland.course-perception.v1` recorded trace and its full
   configuration snapshot. Preserve exact source/image/depth/mask array hash
   algorithm, config hash and raw trace. Our NPZ **file** SHA-256 differs from D's
   dtype/shape/array-content digest; compute and store both, never substitute one.
2. Bind `frame_index`, timestamp, explicit evaluation time, declared camera view,
   calibration and actual aligned image/depth/mask. D uses BGR and optical-axis z
   metres for local geometry; its sector report uses ray range. Converting RGB to
   BGR is an explicit replay transform with an independently hashed result, not
   a change of an existing source snapshot. Do not compare z with ray range.
3. Preserve **every** top-level and opening-embedded clearance object with an
   `evidence_path`, including sampled ROI, probe z, local width, rejection reasons,
   RGB/depth ambiguity and all unassessed volume limits. Canonical
   `local_sensing_planes` never maps legacy `supported` to 3D or path support.
4. Preserve `scope=local_camera_z_probe_plane`,
   `supported_meaning=observed_local_plane_width_only`, and local_plane_supported.
   `full_3d_traversability=UNKNOWN`, `supports_3d_traversal=false`,
   `authority_change=NONE`, `executed=false` remain mandatory for each nested
   plane, the advisory, run summary and report. Positive local support can coexist
   with obstacles outside the ROI/probe plane; this must not become traversability.
5. Preserve `rgb_depth_conflict_suspected`, local support rejection and unknown
   width for ambiguous evidence. Stale evidence cannot retain a usable width.
   Low-light retry success still means degraded and authority NONE. Neither
   `line_supported`, a high confidence nor `descent_geometry_suitable=true`
   permits traversal, descent or landing. Do not feed ZoneCandidate to a planner.
6. Keep window/return navigation `unimplemented` and metric VIO/SLAM
   `not_provided`. Existing VDR is dimensionless image motion, not metric VIO.
   No route state, fixed competition coordinates or hidden action objects are added.

The current reader **does not claim native D trace compatibility**; it accepts
only the canonical observational subset documented in integration-replay.md.
Raw producer data and all additional gaps must be preserved when the bridge is
later implemented, rather than silently dropped to fit this subset.

## Bridge acceptance gate

Use synthetic and already recorded data only. Compare source bytes before/after;
check complete schedules, units, domain/session IDs, quaternion orders, static
transform/calibration binding, NPZ file and array hashes, raw configuration, and
recorded platform. Required negative cases include missing/future/stale depth,
unbound advisory, conflicting RGB/depth, obstacles outside a supported local plane,
ROI clipping, wrong calibration and contradictory downward ranges. Recursively
assert false execution flags, NONE authority and UNKNOWN 3D traversability.

Do not run B/D hardware runners, query a connected autopilot, change device groups,
upload a mission, change a PX4 parameter, or add a shared dependency to perform
these checks. Any later actual device measurement needs a separate scope and must
not be inferred from this workbench's offline validation.
