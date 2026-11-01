from aegisland.domain import Action
from aegisland.px4.shadow_policy import (
    ShadowAuthority,
)
from aegisland.px4.supervisor import (
    Px4ShadowSupervisor,
)
from aegisland.px4.watchdog import (
    LinkHealth,
)
from aegisland.sensor_health import (
    SensorHealthState,
)


def test_failure_is_immediate() -> None:
    supervisor = Px4ShadowSupervisor(
        recovery_samples=3
    )

    # Establish healthy state.
    for _ in range(3):
        decision = supervisor.step(
            telemetry_health=LinkHealth.HEALTHY,
            global_position_valid=True,
        )

    assert (
        decision.authority
        == ShadowAuthority.GRANTED
    )

    # One invalid observation must revoke immediately.
    decision = supervisor.step(
        telemetry_health=LinkHealth.HEALTHY,
        global_position_valid=False,
    )

    assert (
        decision.global_position_state
        == SensorHealthState.FAILED
    )
    assert (
        decision.authority
        == ShadowAuthority.REVOKED
    )
    assert decision.action == Action.HOLD_AND_SCAN


def test_recovery_requires_three_samples() -> None:
    supervisor = Px4ShadowSupervisor(
        recovery_samples=3
    )

    # Put estimator into failed state.
    supervisor.step(
        telemetry_health=LinkHealth.HEALTHY,
        global_position_valid=False,
    )

    first = supervisor.step(
        telemetry_health=LinkHealth.HEALTHY,
        global_position_valid=True,
    )

    second = supervisor.step(
        telemetry_health=LinkHealth.HEALTHY,
        global_position_valid=True,
    )

    third = supervisor.step(
        telemetry_health=LinkHealth.HEALTHY,
        global_position_valid=True,
    )

    assert (
        first.global_position_state
        == SensorHealthState.DEGRADED
    )
    assert first.recovery_streak == 1
    assert (
        first.authority
        == ShadowAuthority.REVOKED
    )

    assert (
        second.global_position_state
        == SensorHealthState.DEGRADED
    )
    assert second.recovery_streak == 2
    assert (
        second.authority
        == ShadowAuthority.REVOKED
    )

    assert (
        third.global_position_state
        == SensorHealthState.HEALTHY
    )
    assert (
        third.authority
        == ShadowAuthority.GRANTED
    )
    assert third.action == Action.CONTINUE_MISSION


def test_stale_telemetry_revokes_authority() -> None:
    supervisor = Px4ShadowSupervisor(
        recovery_samples=3
    )

    for _ in range(3):
        supervisor.step(
            telemetry_health=LinkHealth.HEALTHY,
            global_position_valid=True,
        )

    decision = supervisor.step(
        telemetry_health=LinkHealth.FAILED,
        global_position_valid=True,
    )

    assert (
        decision.authority
        == ShadowAuthority.REVOKED
    )
    assert decision.action == Action.HOLD_AND_SCAN
