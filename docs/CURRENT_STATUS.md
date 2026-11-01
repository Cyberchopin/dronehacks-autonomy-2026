# Current status — 2026-11-01

## Ready now

- Slim, initialized Git repository with a clean root commit.
- Competition-only perception, depth, health, PX4 shadow policy, benchmark and forensics.
- Pure `AdvisorySetpoint` and `SetpointSafetyGate` contract with no publisher dependency.
- 195 selected tests passing on the local Windows verification environment.
- Ubuntu CI configured for the complete selected suite.

## Waiting for the official toolkit

- Exact ROS 2 package layout and launch files.
- Actual OAK-D and PX4 topic names, rates, QoS and frames.
- Exact `px4_msgs`/firmware compatibility.
- GCP simulator login token and agent bootstrap script.

## First implementation after release

Create an adapter in the official starter workspace that only subscribes and records.
Do not begin with Offboard publishing. Once replay and shadow evidence are green, add a
simulation-only bounded publisher behind `SetpointSafetyGate`.

## Remote repository

No remote was created and nothing was pushed by this migration. Recommended target:
`Cyberchopin/dronehacks-autonomy-2026`, private until event data and rules are confirmed.

