"""Pure competition integration contract; no ROS or flight-control dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class IntegrationMode(StrEnum):
    OBSERVER = "observer"
    SHADOW = "shadow"
    SIMULATION = "simulation"
    HARDWARE = "hardware"


class Authority(StrEnum):
    NONE = "NONE"
    SIMULATION_ONLY = "SIMULATION_ONLY"
    HARDWARE_GATED = "HARDWARE_GATED"


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
        values = (self.vx_m_s, self.vy_m_s, self.vz_m_s, self.yaw_rate_rad_s, self.confidence)
        if self.timestamp_ns < 0 or not all(math.isfinite(value) for value in values):
            raise ValueError("setpoint values and timestamp must be finite and non-negative")
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


class SetpointSafetyGate:
    """Rejects unsafe advisories; it never publishes or marks them executed."""

    def __init__(self, limits: SafetyLimits | None = None) -> None:
        self.limits = limits or SafetyLimits()

    def evaluate(self, advisory: AdvisorySetpoint, inputs: GateInputs) -> GateResult:
        reasons: list[str] = []
        age_ms = (inputs.now_ns - advisory.timestamp_ns) / 1_000_000
        if age_ms < 0:
            reasons.append("timestamp_from_future")
        elif age_ms > self.limits.max_age_ms:
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
        else:
            authority = Authority.HARDWARE_GATED

        return GateResult(not reasons, authority, tuple(reasons))

