"""Pure competition integration contract; no ROS or flight-control dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from numbers import Real


class IntegrationMode(StrEnum):
    OBSERVER = "observer"
    SHADOW = "shadow"
    SIMULATION = "simulation"
    HARDWARE = "hardware"


class Authority(StrEnum):
    NONE = "NONE"
    SIMULATION_ONLY = "SIMULATION_ONLY"
    HARDWARE_GATED = "HARDWARE_GATED"


def _validate_timestamp_ns(value: int) -> None:
    if type(value) is not int:
        raise TypeError("timestamp must be an integer number of nanoseconds")
    if value < 0:
        raise ValueError("timestamp must be non-negative")


@dataclass(frozen=True)
class AdvisorySetpoint:
    """A coordinate-labelled request before any ROS/PX4 conversion."""

    timestamp_ns: int
    frame: str
    vx_m_s: float
    vy_m_s: float
    vz_m_s: float
    yaw_rate_rad_s: float
    confidence: float
    reason: str
    executed: bool = False

    def __post_init__(self) -> None:
        _validate_timestamp_ns(self.timestamp_ns)
        values = (self.vx_m_s, self.vy_m_s, self.vz_m_s, self.yaw_rate_rad_s, self.confidence)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("setpoint values must be finite")
        if self.frame not in {"body_frd", "body_flu", "local_ned", "local_enu"}:
            raise ValueError("setpoint frame must be explicit")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if self.executed:
            raise ValueError("the core contract cannot represent an executed setpoint")
        if not self.reason.strip():
            raise ValueError("a setpoint reason is required")


@dataclass(frozen=True)
class GateInputs:
    now_ns: int
    mode: IntegrationMode
    localization_valid: bool
    perception_valid: bool
    depth_known: bool
    offboard_heartbeat_healthy: bool
    staff_hardware_gate: bool = False

    def __post_init__(self) -> None:
        _validate_timestamp_ns(self.now_ns)
        if not isinstance(self.mode, IntegrationMode):
            raise TypeError("mode must be a recognized IntegrationMode")
        for name in (
            "localization_valid",
            "perception_valid",
            "depth_known",
            "offboard_heartbeat_healthy",
            "staff_hardware_gate",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")


@dataclass(frozen=True)
class GateResult:
    accepted: bool
    authority: Authority
    reasons: tuple[str, ...]
    executed: bool = False


@dataclass(frozen=True)
class SafetyLimits:
    max_age_ms: float = 150.0
    max_xy_speed_m_s: float = 0.50
    max_z_speed_m_s: float = 0.25
    max_yaw_rate_rad_s: float = 0.50

    def __post_init__(self) -> None:
        for name in ("max_age_ms", "max_xy_speed_m_s", "max_z_speed_m_s", "max_yaw_rate_rad_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be a real number")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


class SetpointSafetyGate:
    """Rejects unsafe advisories; it never publishes or marks them executed."""

    def __init__(self, limits: SafetyLimits | None = None) -> None:
        self.limits = limits or SafetyLimits()

    def evaluate(self, advisory: AdvisorySetpoint, inputs: GateInputs) -> GateResult:
        reasons: list[str] = []
        age_ns = inputs.now_ns - advisory.timestamp_ns
        if age_ns < 0:
            reasons.append("timestamp_from_future")
        else:
            try:
                age_ms = age_ns / 1_000_000
            except OverflowError:
                # Every permitted age limit is finite; this age exceeds it.
                reasons.append("stale_advisory")
            else:
                if age_ms > self.limits.max_age_ms:
                    reasons.append("stale_advisory")
        if not inputs.localization_valid:
            reasons.append("localization_invalid")
        if not inputs.perception_valid:
            reasons.append("perception_invalid")
        if not inputs.depth_known and advisory.vx_m_s > 0:
            reasons.append("forward_motion_without_depth")
        if math.hypot(advisory.vx_m_s, advisory.vy_m_s) > self.limits.max_xy_speed_m_s:
            reasons.append("xy_speed_limit")
        if abs(advisory.vz_m_s) > self.limits.max_z_speed_m_s:
            reasons.append("z_speed_limit")
        if abs(advisory.yaw_rate_rad_s) > self.limits.max_yaw_rate_rad_s:
            reasons.append("yaw_rate_limit")
        if inputs.mode in {IntegrationMode.SIMULATION, IntegrationMode.HARDWARE}:
            if not inputs.offboard_heartbeat_healthy:
                reasons.append("offboard_heartbeat_unhealthy")
        if inputs.mode == IntegrationMode.HARDWARE and not inputs.staff_hardware_gate:
            reasons.append("staff_hardware_gate_missing")

        if inputs.mode in {IntegrationMode.OBSERVER, IntegrationMode.SHADOW}:
            reasons.append("non_executing_mode")
            authority = Authority.NONE
        elif inputs.mode == IntegrationMode.SIMULATION:
            authority = Authority.SIMULATION_ONLY
        elif inputs.mode == IntegrationMode.HARDWARE:
            authority = Authority.HARDWARE_GATED
        else:
            raise ValueError("unrecognized integration mode")

        return GateResult(not reasons, authority, tuple(reasons))
