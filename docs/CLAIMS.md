# Claim ledger

## Implemented and retained

- Offline line/opening/low-light/local-clearance/landing geometry evidence.
- Strict benchmark contracts and immutable run evidence.
- Read-only flight forensics and conditional cross-clock inference.
- PX4 telemetry/link shadow policy and a non-publishing competition safety gate.

## Previously tested in the source repository

- Course-perception focused tests: 170 passed.
- Forensics focused tests: 79 passed, 1 skipped.
- Benchmark bounded shards: 310 passed, 1 skipped, 29 unresolved.

These counts are historical evidence. This repository must establish its own CI baseline.

## Unknown until official simulation/hardware

- Exact ROS 2 topics, QoS and message compatibility.
- OAK-D calibration, depth failure distribution and end-to-end latency.
- Metric localization quality on the competition course.
- Jetson Orin p50/p95/p99 runtime, thermals and memory.
- Full 3D traversability and safe window/gate passage.
- Real flight behavior, failsafe response and course completion.

