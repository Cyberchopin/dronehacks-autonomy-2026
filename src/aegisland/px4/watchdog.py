from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from numbers import Real


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
    """Reject invalid ages and invalid, unordered freshness thresholds.

    Unrepresentable numeric ages raise ValueError rather than OverflowError.
    """
    for name, value in (("degraded_after_s", degraded_after_s), ("failed_after_s", failed_after_s)):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a real number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if degraded_after_s > failed_after_s:
        raise ValueError("degraded_after_s must not exceed failed_after_s")
    if isinstance(age_s, bool) or not isinstance(age_s, Real):
        raise TypeError("age_s must be a real number")
    try:
        finite = math.isfinite(age_s)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("age_s must be finite")
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
