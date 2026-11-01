import pytest

from aegisland.px4.telemetry import (
    Px4TelemetrySnapshot,
    normalize_px4_telemetry,
)


def test_px4_snapshot_maps_to_aegisland_telemetry() -> None:
    snapshot = Px4TelemetrySnapshot(
        battery_percent=82.0,
        relative_altitude_m=12.5,
        velocity_north_mps=3.0,
        velocity_east_mps=4.0,
        global_position_ok=True,
        connected=True,
        timestamp_s=42.0,
    )

    telemetry = normalize_px4_telemetry(snapshot)

    assert telemetry.battery_percent == pytest.approx(82.0)
    assert telemetry.altitude_m == pytest.approx(12.5)
    assert telemetry.horizontal_speed_mps == pytest.approx(5.0)
    assert telemetry.gps_available
    assert telemetry.home_link_available
    assert telemetry.timestamp_s == pytest.approx(42.0)


def test_px4_battery_is_clamped() -> None:
    snapshot = Px4TelemetrySnapshot(
        battery_percent=120.0,
        relative_altitude_m=0.0,
        velocity_north_mps=0.0,
        velocity_east_mps=0.0,
        global_position_ok=False,
        connected=True,
        timestamp_s=0.0,
    )

    telemetry = normalize_px4_telemetry(snapshot)

    assert telemetry.battery_percent == 100.0
    assert not telemetry.gps_available
