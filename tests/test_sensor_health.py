from aegisland.sensor_health import (
    SensorHealthMonitor,
    SensorHealthState,
)


def test_hard_invalid_sensor_fails_immediately() -> None:
    monitor = SensorHealthMonitor(
        recovery_samples=3,
    )

    result = monitor.assess(
        "visual",
        confidence=0.95,
        valid=False,
    )

    assert result.state == SensorHealthState.FAILED
    assert result.effective_confidence == 0.0


def test_low_confidence_sensor_fails_immediately() -> None:
    monitor = SensorHealthMonitor()

    result = monitor.assess(
        "visual",
        confidence=0.10,
        valid=True,
    )

    assert result.state == SensorHealthState.FAILED
    assert result.effective_confidence == 0.0


def test_medium_confidence_is_degraded_not_failed() -> None:
    monitor = SensorHealthMonitor()

    result = monitor.assess(
        "imu",
        confidence=0.55,
        valid=True,
    )

    assert result.state == SensorHealthState.DEGRADED
    assert 0.0 < result.effective_confidence < 0.55


def test_failed_sensor_requires_sustained_recovery() -> None:
    monitor = SensorHealthMonitor(
        recovery_samples=3,
    )

    monitor.assess(
        "visual",
        confidence=0.10,
        valid=True,
    )

    first = monitor.assess(
        "visual",
        confidence=0.90,
        valid=True,
    )

    second = monitor.assess(
        "visual",
        confidence=0.90,
        valid=True,
    )

    third = monitor.assess(
        "visual",
        confidence=0.90,
        valid=True,
    )

    assert first.state == SensorHealthState.DEGRADED
    assert second.state == SensorHealthState.DEGRADED
    assert third.state == SensorHealthState.HEALTHY


def test_sensor_sources_have_independent_health_state() -> None:
    monitor = SensorHealthMonitor(
        recovery_samples=2,
    )

    visual = monitor.assess(
        "visual",
        confidence=0.10,
        valid=True,
    )

    imu = monitor.assess(
        "imu",
        confidence=0.95,
        valid=True,
    )

    assert visual.state == SensorHealthState.FAILED

    # First good observation is still recovery because the source starts
    # conservatively in FAILED state.
    assert imu.state == SensorHealthState.DEGRADED

    imu = monitor.assess(
        "imu",
        confidence=0.95,
        valid=True,
    )

    assert imu.state == SensorHealthState.HEALTHY
