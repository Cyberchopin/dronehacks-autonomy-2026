# DroneHacks Autonomy 2026

Competition-focused autonomy core for the Stanford DroneHacks indoor GPS-denied course.

This repository is a deliberately small migration from
[`Cyberchopin/aegisland-agentic-vision`](https://github.com/Cyberchopin/aegisland-agentic-vision)
at upstream commit `28d36ded36e8f1132eeb71a772e74ef0570c2a05`.

## What stays

- Offline course perception for line, rectangular opening, low-light recovery,
  local depth clearance and landing-ring geometry.
- Depth-sector evidence and a normalized visual dead-reckoning baseline.
- Sensor-health hysteresis and PX4 shadow/watchdog policy.
- A strict benchmark contract with immutable run evidence.
- Read-only PX4 ULog + Jetson JSONL flight forensics.
- Provenance and redistribution decisions for evaluated upstream methods.

## What does not stay

- The old AWS/OpenCV competition application, dashboard, grant and deployment code.
- Historical benchmark result payloads and bulky generated outputs.
- Fast-FoundationStereo competition integration (license decision: NO-GO).
- Unactivated Kimera fallback and unverified target binaries.
- Real flight control. No ROS 2/PX4 publisher exists here yet.

## Safety boundary

The current code is offline, replay or shadow-only. Course perception and forensics
do not send commands. Local gap evidence is a projection on a declared sensing plane,
not proof of full 3D traversability. The visual dead-reckoning baseline reports
normalized image motion, not metric position.

The official DroneHacks starter repository will be the flight-capable shell. Integrate
this repository into it in four gates:

1. **Observer:** subscribe and record; no setpoint output.
2. **Shadow:** compute advisories with `executed=False`.
3. **Simulation:** publish bounded setpoints through the official Offboard node.
4. **Hardware:** only under event staff procedures after simulation evidence.

See [architecture](docs/ARCHITECTURE.md), [migration manifest](docs/MIGRATION_MANIFEST.md),
and [starter integration plan](docs/STARTER_INTEGRATION.md).

## Local verification

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,vision,forensics]'
pytest -q
ruff check src tests
ruff format --check src tests
```

On Jetson, prefer the event image's system OpenCV/DepthAI packages. Do not replace
JetPack-provided packages merely to match desktop pip wheels.

## Current evidence, not claims

- Course-perception focused suite was previously reported as 170 passed.
- Forensics CI was previously reported as 79 passed, 1 skipped.
- The old monorepo full suite timed out at 300 seconds; this slim repository exists in
  part to remove unrelated slow legacy replay tests.
- No Orin, OAK-D S2, Pixhawk 6C or real-flight validation is claimed yet.

