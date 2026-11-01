from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LinkHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TelemetryWatchdogResult:
    age_s: float
    health: LinkHealth
    stale: bool


def evaluate_telemetry_freshness(
    age_s: float,
    *,
    degraded_after_s: float = 0.5,
    failed_after_s: float = 1.5,
) -> TelemetryWatchdogResult:
    if age_s < 0:
        raise ValueError("age_s cannot be negative")

    if age_s >= failed_after_s:
        return TelemetryWatchdogResult(
            age_s=age_s,
            health=LinkHealth.FAILED,
            stale=True,
        )

    if age_s >= degraded_after_s:
        return TelemetryWatchdogResult(
            age_s=age_s,
            health=LinkHealth.DEGRADED,
            stale=True,
        )

    return TelemetryWatchdogResult(
        age_s=age_s,
        health=LinkHealth.HEALTHY,
        stale=False,
    )
