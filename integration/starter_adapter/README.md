# Starter adapter placeholder

Do not implement a guessed ROS 2/PX4 publisher here.

When the official starter repository arrives, add it as a documented upstream or copy this
pure core into its workspace. The adapter must be written against the actual message
versions, topic names, QoS, frames and launch files.

Required mapping:

```text
official sensor topics -> immutable core input -> perception/health -> AdvisorySetpoint
AdvisorySetpoint -> SetpointSafetyGate -> official simulation-only Offboard publisher
```

The first PR must remain simulation-only. A later, separately reviewed change may enable
the event-provided hardware path under staff rules.

