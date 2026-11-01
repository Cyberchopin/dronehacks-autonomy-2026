from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from aegisland.domain import Telemetry


@dataclass(frozen=True, slots=True)
class Px4TelemetrySnapshot:
    battery_percent: float
    relative_altitude_m: float

    velocity_north_mps: float
    velocity_east_mps: float

    global_position_ok: bool
    connected: bool

    timestamp_s: float


def normalize_px4_telemetry(
    snapshot: Px4TelemetrySnapshot,
) -> Telemetry:
    battery_percent = max(
        0.0,
        min(
            100.0,
            snapshot.battery_percent,
        ),
    )

    horizontal_speed = hypot(
        snapshot.velocity_north_mps,
        snapshot.velocity_east_mps,
    )

    return Telemetry(
        battery_percent=battery_percent,
        altitude_m=max(
            0.0,
            snapshot.relative_altitude_m,
        ),
        horizontal_speed_mps=horizontal_speed,
        gps_available=snapshot.global_position_ok,
        home_link_available=snapshot.connected,
        timestamp_s=snapshot.timestamp_s,
    )
