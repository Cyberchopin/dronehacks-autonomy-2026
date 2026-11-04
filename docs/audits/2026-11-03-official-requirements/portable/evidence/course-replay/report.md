# Offline course perception report

Samples: 36. CONTROL OUTPUT=DISABLED; COMMAND EXECUTED=FALSE.

Heuristic scores are not calibrated probabilities. No real-flight validation.
Gap support means local camera-z plane width only; full 3-D traversability is UNKNOWN. Authority change=NONE; executed=False. Window/return navigation remain unimplemented.

| Input | Line / score | Opening / depth-supported | Depth valid | Recovery | Clearance at probe (m) | Pad / geometry suitable | Rejections (line; gap; landing) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic:line | True / 1.000 | 0 / False | True | False | 2.1785714285714284 | False / False | ; ; no_outer_ring |
| synthetic:maze | True / 1.000 | 0 / False | True | False | 2.1785714285714284 | False / False | ; ; no_outer_ring |
| synthetic:opening | False / 0.000 | 1 / True | True | False | 2.1785714285714284 | False / False | branched_or_insufficient_geometry; ; no_outer_ring |
| synthetic:dim_recoverable | True / 0.560 | 0 / False | True | True | 2.1785714285714284 | False / False | ; ; no_outer_ring, low_light_raw_evidence |
| synthetic:dim_line | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | insufficient_line_support; ; no_outer_ring, low_light_raw_evidence |
| synthetic:blackout | False / 0.000 | 0 / False | False | False | unknown | False / False | insufficient_line_support; depth_sector_degraded, local_depth_insufficient; no_outer_ring, low_light_raw_evidence |
| synthetic:chicane | False / 0.000 | 1 / True | True | False | 1.0625 | False / False | branched_or_insufficient_geometry; ; no_outer_ring |
| synthetic:narrow_gap | False / 0.000 | 1 / False | True | False | 0.2857142857142857 | False / False | branched_or_insufficient_geometry; insufficient_observed_clearance; no_outer_ring |
| synthetic:blocked_opening | False / 0.000 | 1 / False | True | False | 0.0 | False / False | branched_or_insufficient_geometry; insufficient_observed_clearance; no_outer_ring |
| synthetic:unknown_opening | False / 0.000 | 1 / False | True | False | unknown | False / False | branched_or_insufficient_geometry; local_depth_insufficient; no_outer_ring |
| synthetic:pad | False / 0.000 | 0 / False | True | False | unknown | True / True | branched_or_insufficient_geometry; camera_view_not_forward;  |
| synthetic:intruded_pad | False / 0.000 | 0 / False | True | False | unknown | True / False | branched_or_insufficient_geometry; camera_view_not_forward; landing_footprint_too_small, landing_surface_not_planar |
| synthetic:solid_disk | False / 0.000 | 0 / False | True | False | unknown | False / False | branched_or_insufficient_geometry; camera_view_not_forward; no_outer_ring |
| synthetic:ellipse | False / 0.000 | 0 / False | True | False | unknown | False / False | branched_or_insufficient_geometry; camera_view_not_forward; no_outer_ring |
| synthetic:parallel_lines | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | competing_lines; ; no_outer_ring |
| synthetic:branch | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | branched_or_insufficient_geometry; ; no_outer_ring |
| synthetic:broken_line | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | branched_or_insufficient_geometry; ; no_outer_ring |
| synthetic:blank | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | insufficient_line_support; ; no_outer_ring |
| synthetic:tilted_pad | False / 0.000 | 0 / False | True | False | unknown | True / False | branched_or_insufficient_geometry; camera_view_not_forward; landing_footprint_too_small, landing_surface_tilted |
| synthetic:clipped_pad | False / 0.000 | 0 / False | True | False | unknown | False / False | branched_or_insufficient_geometry; camera_view_not_forward; no_outer_ring |
| synthetic:dark_pad | False / 0.000 | 0 / False | True | False | unknown | True / True | insufficient_line_support; camera_view_not_forward;  |
| synthetic:two_pads | False / 0.000 | 0 / False | True | False | unknown | True / False | branched_or_insufficient_geometry; camera_view_not_forward; competing_outer_rings |
| synthetic:stale_depth | True / 1.000 | 0 / False | False | False | unknown | False / False | ; depth_stale_or_future, image_depth_unsynchronized; no_outer_ring |
| synthetic:unsynchronized_depth | True / 1.000 | 0 / False | False | False | unknown | False / False | ; image_depth_unsynchronized; no_outer_ring |
| synthetic:missing_depth | True / 1.000 | 0 / False | False | False | unknown | False / False | ; depth_missing; no_outer_ring |
| synthetic:blind_zone | True / 1.000 | 0 / False | False | False | unknown | False / False | ; depth_sector_degraded, local_depth_insufficient, local_depth_blind_zone; no_outer_ring |
| synthetic:adversarial:partial_ring | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | line_shape_inconsistent; ; no_outer_ring |
| synthetic:adversarial:curved_shadow | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | insufficient_line_support; ; no_outer_ring |
| synthetic:adversarial:wall_edge | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | line_cropped_at_side, line_wall_edge_ambiguous; ; no_outer_ring |
| synthetic:adversarial:wall_highlight | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | line_wall_edge_ambiguous; ; no_outer_ring |
| synthetic:adversarial:short_fragment | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | branched_or_insufficient_geometry; ; no_outer_ring |
| synthetic:adversarial:slanted_line | True / 0.951 | 0 / False | True | False | 2.1785714285714284 | False / False | ; ; no_outer_ring |
| synthetic:adversarial:rgb_blocker_depth_far | False / 0.000 | 2 / False | True | False | unknown | False / False | branched_or_insufficient_geometry; rgb_depth_conflict_suspected; no_outer_ring |
| synthetic:adversarial:rgb_opening_depth_wall | False / 0.000 | 1 / False | True | False | 0.0 | False / False | branched_or_insufficient_geometry; insufficient_observed_clearance; no_outer_ring |
| synthetic:adversarial:outside_roi_obstacle | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | insufficient_line_support; ; no_outer_ring |
| synthetic:adversarial:beyond_probe_obstacle | False / 0.000 | 0 / False | True | False | 2.1785714285714284 | False / False | insufficient_line_support; ; no_outer_ring |

CPU observe latency: p50=4.538 ms, p95=7.498 ms, max=12.895 ms. One pass, cold first sample included, no disk I/O. Not an Orin benchmark.

- synthetic results are not field detection accuracy
- no hardware, Orin, flight or full-route validation
- no semantic exit/pad identity or temporal obstacle tracking
- clearance is projected at the configured camera-z probe plane; not a physical gate width or swept 3-D vehicle volume
- landing suitability covers observed geometry/depth only; motion, gravity alignment and full 3-D vehicle footprint remain unassessed
- window and return stretch goals are not implemented
