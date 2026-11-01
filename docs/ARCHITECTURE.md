# Competition architecture

## Runtime target

```text
OAK-D RGB/depth ─┐
VL53L1X height ──┼─> official ROS 2 starter adapters ─> perception evidence
PX4 state ───────┘                                  │
                                                     v
localization/health ─> bounded planner ─> safety gate ─> official Offboard publisher
                                   │
                                   └─> evidence recorder ─> ULog/JSONL forensics
```

The official starter repository owns ROS 2 launch, PX4 message versions, DDS setup,
and the flight-capable publisher. This repository owns pure perception, health,
contracts, replay, benchmark and post-run evidence.

## Non-negotiable boundaries

- `course_perception` is advisory and offline-capable.
- `competition_contract` can validate a setpoint but cannot publish one or claim execution.
- `forensics` is read-only and always emits `executed=False`.
- Normalized visual dead reckoning is not metric localization.
- Local probe-plane clearance is not full 3D traversability.
- Hardware authority requires a separate adapter plus an explicit staff gate.

## Why the execution adapter is intentionally absent

PX4/ROS message versions, topic names, QoS, coordinate frames and event safety procedures
come from the official starter kit. Implementing a guessed publisher now would create code
that looks complete but may be incompatible or unsafe. The first integration PR should be
based on the exact starter commit and simulation script.

