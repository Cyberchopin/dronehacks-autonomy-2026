from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    CONTINUE_MISSION = "continue_mission"
    RETURN_HOME = "return_home"
    HOLD_AND_SCAN = "hold_and_scan"
    EVADE_AND_HOLD = "evade_and_hold"
    REQUEST_HUMAN_APPROVAL = "request_human_approval"
    LAND = "land"
    EMERGENCY_LAND = "emergency_land"

    # Compound failsafe:
    # avoid immediate collision while transitioning toward
    # the fastest viable emergency landing.
    EMERGENCY_RECOVERY = "emergency_recovery"


class SafetyLevel(StrEnum):
    NOMINAL = "nominal"
    CAUTION = "caution"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Telemetry:
    battery_percent: float
    altitude_m: float
    horizontal_speed_mps: float = 0.0
    gps_available: bool = True
    home_link_available: bool = True
    timestamp_s: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.battery_percent <= 100:
            raise ValueError("battery_percent must be in [0, 100]")
        if self.altitude_m < 0:
            raise ValueError("altitude_m cannot be negative")


@dataclass(frozen=True, slots=True)
class ZoneCandidate:
    zone_id: str
    bbox_xywh: tuple[int, int, int, int]
    score: float
    edge_density: float
    motion_occupancy: float
    texture_risk: float
    appearance_occupancy: float
    clearance: float
    safe: bool


@dataclass(frozen=True, slots=True)
class VisionEvidence:
    evidence_id: str
    frame_index: int
    confidence: float
    obstacle_risk: float
    motion_risk: float
    candidates: tuple[ZoneCandidate, ...] = ()
    active_perception_used: bool = False
    processing_ms: float = 0.0
    camera_compensation_used: bool = False
    camera_match_count: int = 0
    camera_inlier_count: int = 0
    camera_inlier_ratio: float = 0.0
    raw_motion_risk: float = 0.0
    motion_suppression_ratio: float = 0.0
    motion_object_center: tuple[float, float] | None = None
    temporal_risk: float = 0.0
    ttc_frames: float | None = None
    visual_localization_valid: bool = False
    visual_localization_confidence: float = 0.0
    visual_relative_x: float = 0.0
    visual_relative_y: float = 0.0
    visual_velocity_x: float = 0.0
    visual_velocity_y: float = 0.0
    navigation_mode: str = "unknown"
    fused_navigation_confidence: float = 0.0
    navigation_gps_weight: float = 0.0
    navigation_visual_weight: float = 0.0
    navigation_imu_weight: float = 0.0
    healthy_navigation_sources: tuple[str, ...] = ()
    degraded_navigation_sources: tuple[str, ...] = ()
    imu_sync_valid: bool = False
    imu_sync_method: str = "unavailable"
    imu_confidence: float = 0.0

    gps_health_state: str = "unknown"
    visual_health_state: str = "unknown"
    imu_health_state: str = "unknown"

    gps_effective_confidence: float = 0.0
    visual_effective_confidence: float = 0.0
    imu_effective_confidence: float = 0.0

    perception_quality_score: float = 1.0
    perception_failure_type: str = "unknown"

    perception_mean_brightness: float = 0.0
    perception_bright_ratio: float = 0.0
    perception_dark_ratio: float = 0.0
    perception_sharpness: float = 0.0
    perception_entropy_bits: float = 0.0
    perception_feature_count: int = 0
    perception_largest_dark_region_ratio: float = 0.0
    perception_geometry_score: float = 0.0
    perception_failure_reasons: tuple[str, ...] = ()

    visual_localization_authority: str = "unknown"
    visual_localization_trusted: bool = False
    visual_trust_confidence: float = 0.0
    visual_trust_reason: str = ""

    notes: tuple[str, ...] = ()

    @property
    def best_zone(self) -> ZoneCandidate | None:
        return max(self.candidates, key=lambda candidate: candidate.score, default=None)


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    safety_level: SafetyLevel
    risk_score: float
    requires_human_approval: bool
    reasons: tuple[str, ...]
    evidence_id: str
    target_zone_id: str | None = None
    command_executed: bool = False


@dataclass(frozen=True, slots=True)
class TraceEvent:
    trace_id: str
    sequence: int
    telemetry: Telemetry
    evidence: VisionEvidence
    decision: Decision
    raw_decision: Decision | None = None
    command: dict[str, Any] = field(default_factory=dict)


def jsonable(value: Any) -> Any:
    """Convert nested dataclasses, tuples and enums into JSON-safe values."""
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
