# Official starter integration plan

## Gate 0 — inventory

Record the starter repository commit, PX4 version, `px4_msgs` branch, ROS 2 distribution,
DepthAI versions, JetPack, OpenCV, camera calibration, topic names, QoS and frames.

## Gate 1 — observer

Add a ROS 2 node that subscribes to RGB, aligned depth, PX4 local state and rangefinder.
It may only write a timestamped local recording. Verify rates, timestamps and frame IDs.

Exit criteria:

- no publisher to `/fmu/in/*`;
- no arm/mode/parameter client;
- recorded RGB/depth pairs can be replayed;
- missing depth remains unknown, never infinity or free space.

## Gate 2 — shadow

Convert recordings into `CoursePerception` input and emit `AdvisorySetpoint` with
`executed=False`. Compare overlays and rejection reasons against the simulator scene.

Exit criteria:

- stale, invalid localization and unknown forward depth are rejected;
- NED/ENU and FRD/FLU transforms have numeric unit tests;
- evidence includes commit, config and input hashes.

## Gate 3 — simulation Offboard

Implement a small adapter inside the starter repository, not in the pure core. It converts
an accepted advisory into the exact official `OffboardControlMode` and
`TrajectorySetpoint` messages. The starter project's watchdog and mode workflow remain
authoritative.

Exit criteria:

- heartbeat stays comfortably above PX4's approximate 2 Hz minimum;
- setpoints are bounded and become zero/hold on stale input;
- Offboard loss, DDS loss, perception loss and localization loss are injected;
- every scenario has ULog + Jetson evidence and a deterministic reset.

## Gate 4 — hardware

Hardware testing occurs only under event staff procedures. Start with props removed or the
event's designated safe setup, then low-speed/tethered tests if instructed. Do not change
PX4 safety parameters to make integration easier.

