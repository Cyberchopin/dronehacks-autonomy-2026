from __future__ import annotations

from dataclasses import dataclass

from aegisland.domain import Action
from aegisland.px4.shadow_policy import (
    ShadowAuthority,
    ShadowNavigationMode,
)
from aegisland.px4.watchdog import LinkHealth
from aegisland.sensor_health import (
    SensorHealthMonitor,
    SensorHealthState,
)


@dataclass(frozen=True, slots=True)
class Px4ShadowDecision:
    navigation_mode: ShadowNavigationMode
    authority: ShadowAuthority
    action: Action
    executed: bool

    # Raw PX4/global-position estimator health.
    global_position_state: SensorHealthState
    recovery_streak: int

    # Effective telemetry freshness health after hysteresis.
    telemetry_state: SensorHealthState
    telemetry_recovery_streak: int

    reason: str


class Px4ShadowSupervisor:
    """
    Read-only PX4 safety supervisor.

    Layers are intentionally separate:

        transport
        -> raw telemetry freshness
        -> telemetry health hysteresis
        -> estimator validity
        -> navigation authority

    Failure is fast.
    Recovery is conservative.
    """

    def __init__(
        self,
        *,
        recovery_samples: int = 3,
        telemetry_recovery_samples: int = 3,
    ) -> None:
        self._position_health = SensorHealthMonitor(
            recovery_samples=recovery_samples,
        )

        self._telemetry_health = SensorHealthMonitor(
            recovery_samples=telemetry_recovery_samples,
        )

    def step(
        self,
        *,
        telemetry_health: LinkHealth,
        global_position_valid: bool,
    ) -> Px4ShadowDecision:
        # Convert raw watchdog state into the same stateful
        # health abstraction used by the rest of AegisLand.
        if telemetry_health == LinkHealth.HEALTHY:
            telemetry_confidence = 1.0
            telemetry_valid = True

        elif telemetry_health == LinkHealth.DEGRADED:
            telemetry_confidence = 0.5
            telemetry_valid = True

        else:
            telemetry_confidence = 0.0
            telemetry_valid = False

        effective_telemetry = self._telemetry_health.assess(
            "px4_navigation_telemetry",
            confidence=telemetry_confidence,
            valid=telemetry_valid,
        )

        position_health = self._position_health.assess(
            "px4_global_position",
            confidence=(
                1.0
                if global_position_valid
                else 0.0
            ),
            valid=global_position_valid,
        )

        # Telemetry freshness authority comes first.
        #
        # Even if cached position still looks valid,
        # navigation cannot rely on stale data.
        if (
            effective_telemetry.state
            != SensorHealthState.HEALTHY
        ):
            return Px4ShadowDecision(
                navigation_mode=(
                    ShadowNavigationMode.DEGRADED
                ),
                authority=ShadowAuthority.REVOKED,
                action=Action.HOLD_AND_SCAN,
                executed=False,
                global_position_state=(
                    position_health.state
                ),
                recovery_streak=(
                    position_health.recovery_streak
                ),
                telemetry_state=(
                    effective_telemetry.state
                ),
                telemetry_recovery_streak=(
                    effective_telemetry.recovery_streak
                ),
                reason=effective_telemetry.reason,
            )

        # Fresh telemetry alone is insufficient:
        # estimator validity must also be healthy.
        if (
            position_health.state
            != SensorHealthState.HEALTHY
        ):
            return Px4ShadowDecision(
                navigation_mode=(
                    ShadowNavigationMode.DEGRADED
                ),
                authority=ShadowAuthority.REVOKED,
                action=Action.HOLD_AND_SCAN,
                executed=False,
                global_position_state=(
                    position_health.state
                ),
                recovery_streak=(
                    position_health.recovery_streak
                ),
                telemetry_state=(
                    effective_telemetry.state
                ),
                telemetry_recovery_streak=(
                    effective_telemetry.recovery_streak
                ),
                reason=position_health.reason,
            )

        return Px4ShadowDecision(
            navigation_mode=(
                ShadowNavigationMode.GPS_PRIMARY
            ),
            authority=ShadowAuthority.GRANTED,
            action=Action.CONTINUE_MISSION,
            executed=False,
            global_position_state=(
                position_health.state
            ),
            recovery_streak=(
                position_health.recovery_streak
            ),
            telemetry_state=(
                effective_telemetry.state
            ),
            telemetry_recovery_streak=(
                effective_telemetry.recovery_streak
            ),
            reason=(
                "Telemetry and navigation capability are healthy."
            ),
        )
