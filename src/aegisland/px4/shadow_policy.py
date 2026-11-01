from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aegisland.domain import Action
from aegisland.px4.watchdog import LinkHealth


class ShadowAuthority(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class ShadowNavigationMode(StrEnum):
    GPS_PRIMARY = "gps_primary"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    navigation_mode: ShadowNavigationMode
    authority: ShadowAuthority
    action: Action
    executed: bool
    reason: str


def decide_shadow_action(
    *,
    link_health: LinkHealth,
    gps_available: bool,
) -> ShadowDecision:
    if link_health == LinkHealth.FAILED:
        return ShadowDecision(
            navigation_mode=(
                ShadowNavigationMode.DEGRADED
            ),
            authority=(
                ShadowAuthority.REVOKED
            ),
            action=Action.HOLD_AND_SCAN,
            executed=False,
            reason="telemetry link failed",
        )

    if not gps_available:
        return ShadowDecision(
            navigation_mode=(
                ShadowNavigationMode.DEGRADED
            ),
            authority=(
                ShadowAuthority.REVOKED
            ),
            action=Action.HOLD_AND_SCAN,
            executed=False,
            reason="gps unavailable",
        )

    if link_health == LinkHealth.DEGRADED:
        return ShadowDecision(
            navigation_mode=(
                ShadowNavigationMode.DEGRADED
            ),
            authority=(
                ShadowAuthority.REVOKED
            ),
            action=Action.HOLD_AND_SCAN,
            executed=False,
            reason="telemetry link degraded",
        )

    return ShadowDecision(
        navigation_mode=(
            ShadowNavigationMode.GPS_PRIMARY
        ),
        authority=ShadowAuthority.GRANTED,
        action=Action.CONTINUE_MISSION,
        executed=False,
        reason="gps and telemetry healthy",
    )
