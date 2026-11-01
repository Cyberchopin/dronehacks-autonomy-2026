from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SensorHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SensorHealthResult:
    source: str
    state: SensorHealthState
    raw_confidence: float
    effective_confidence: float
    valid: bool
    recovery_streak: int
    reason: str


@dataclass(slots=True)
class _SensorState:
    state: SensorHealthState = SensorHealthState.FAILED
    recovery_streak: int = 0


class SensorHealthMonitor:
    """
    Stateful sensor-health classifier with asymmetric hysteresis.

    Failure:
        fast

    Recovery:
        deliberately slower

    This prevents a noisy sensor from repeatedly entering and leaving
    the navigation solution on adjacent frames.
    """

    def __init__(
        self,
        *,
        healthy_gate: float = 0.70,
        failed_gate: float = 0.30,
        recovery_samples: int = 3,
        degraded_confidence_scale: float = 0.70,
    ) -> None:
        if not 0.0 <= failed_gate <= healthy_gate <= 1.0:
            raise ValueError(
                "Expected 0 <= failed_gate <= healthy_gate <= 1"
            )

        if recovery_samples < 1:
            raise ValueError(
                "recovery_samples must be at least 1"
            )

        self.healthy_gate = healthy_gate
        self.failed_gate = failed_gate
        self.recovery_samples = recovery_samples
        self.degraded_confidence_scale = max(
            0.0,
            min(1.0, degraded_confidence_scale),
        )

        self._states: dict[str, _SensorState] = {}

    def assess(
        self,
        source: str,
        *,
        confidence: float,
        valid: bool,
    ) -> SensorHealthResult:
        confidence = self._clamp(confidence)

        state = self._states.setdefault(
            source,
            _SensorState(),
        )

        # Hard invalidity or critically poor confidence fails immediately.
        if not valid:
            state.state = SensorHealthState.FAILED
            state.recovery_streak = 0

            return self._result(
                source,
                state,
                confidence,
                valid=False,
                effective_confidence=0.0,
                reason="Sensor reported invalid data.",
            )

        if confidence < self.failed_gate:
            state.state = SensorHealthState.FAILED
            state.recovery_streak = 0

            return self._result(
                source,
                state,
                confidence,
                valid=True,
                effective_confidence=0.0,
                reason="Confidence fell below the hard failure gate.",
            )

        # Recovery from FAILED must be sustained.
        if state.state == SensorHealthState.FAILED:
            if confidence >= self.healthy_gate:
                state.recovery_streak += 1

                if state.recovery_streak >= self.recovery_samples:
                    state.state = SensorHealthState.HEALTHY
                    state.recovery_streak = 0

                    return self._result(
                        source,
                        state,
                        confidence,
                        valid=True,
                        effective_confidence=confidence,
                        reason="Sensor completed sustained recovery.",
                    )

                state.state = SensorHealthState.DEGRADED

                return self._result(
                    source,
                    state,
                    confidence,
                    valid=True,
                    effective_confidence=(
                        confidence
                        * self.degraded_confidence_scale
                    ),
                    reason="Sensor is recovering but has not satisfied hysteresis.",
                )

            state.state = SensorHealthState.DEGRADED
            state.recovery_streak = 0

            return self._result(
                source,
                state,
                confidence,
                valid=True,
                effective_confidence=(
                    confidence
                    * self.degraded_confidence_scale
                ),
                reason="Sensor remains below the healthy confidence gate.",
            )

        # Already healthy: moderate quality becomes degraded immediately.
        if confidence < self.healthy_gate:
            state.state = SensorHealthState.DEGRADED
            state.recovery_streak = 0

            return self._result(
                source,
                state,
                confidence,
                valid=True,
                effective_confidence=(
                    confidence
                    * self.degraded_confidence_scale
                ),
                reason="Sensor confidence is usable but degraded.",
            )

        # DEGRADED -> HEALTHY also requires sustained good observations.
        if state.state == SensorHealthState.DEGRADED:
            state.recovery_streak += 1

            if state.recovery_streak < self.recovery_samples:
                return self._result(
                    source,
                    state,
                    confidence,
                    valid=True,
                    effective_confidence=(
                        confidence
                        * self.degraded_confidence_scale
                    ),
                    reason="Healthy observations are accumulating for recovery.",
                )

        state.state = SensorHealthState.HEALTHY
        state.recovery_streak = 0

        return self._result(
            source,
            state,
            confidence,
            valid=True,
            effective_confidence=confidence,
            reason="Sensor health is stable.",
        )

    def reset(
        self,
        source: str | None = None,
    ) -> None:
        if source is None:
            self._states.clear()
        else:
            self._states.pop(source, None)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(
            0.0,
            min(1.0, float(value)),
        )

    @staticmethod
    def _result(
        source: str,
        state: _SensorState,
        raw_confidence: float,
        *,
        valid: bool,
        effective_confidence: float,
        reason: str,
    ) -> SensorHealthResult:
        return SensorHealthResult(
            source=source,
            state=state.state,
            raw_confidence=raw_confidence,
            effective_confidence=round(
                effective_confidence,
                4,
            ),
            valid=valid,
            recovery_streak=state.recovery_streak,
            reason=reason,
        )
