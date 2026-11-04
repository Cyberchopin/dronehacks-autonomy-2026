import pytest

from aegisland.competition_contract import (
    AdvisorySetpoint,
    Authority,
    GateInputs,
    IntegrationMode,
    SafetyLimits,
    SetpointSafetyGate,
)


def advisory(**changes):
    values = {
        "timestamp_ns": 1_000_000_000,
        "frame": "body_frd",
        "vx_m_s": 0.2,
        "vy_m_s": 0.0,
        "vz_m_s": 0.0,
        "yaw_rate_rad_s": 0.0,
        "confidence": 0.8,
        "reason": "corridor_centering",
    }
    values.update(changes)
    return AdvisorySetpoint(**values)


def inputs(mode=IntegrationMode.SIMULATION, **changes):
    values = {
        "now_ns": 1_050_000_000,
        "mode": mode,
        "localization_valid": True,
        "perception_valid": True,
        "depth_known": True,
        "offboard_heartbeat_healthy": True,
    }
    values.update(changes)
    return GateInputs(**values)


def test_simulation_accepts_fresh_bounded_advisory():
    result = SetpointSafetyGate().evaluate(advisory(), inputs())
    assert result.accepted is True
    assert result.authority is Authority.SIMULATION_ONLY
    assert result.executed is False


@pytest.mark.parametrize("mode", [IntegrationMode.OBSERVER, IntegrationMode.SHADOW])
def test_nonexecuting_modes_always_reject(mode):
    result = SetpointSafetyGate().evaluate(advisory(), inputs(mode))
    assert result.accepted is False
    assert "non_executing_mode" in result.reasons


def test_unknown_depth_rejects_forward_motion_but_not_zero_motion():
    gate = SetpointSafetyGate()
    rejected = gate.evaluate(advisory(vx_m_s=0.1), inputs(depth_known=False))
    stopped = gate.evaluate(advisory(vx_m_s=0.0), inputs(depth_known=False))
    assert "forward_motion_without_depth" in rejected.reasons
    assert stopped.accepted is True


def test_hardware_needs_explicit_staff_gate():
    result = SetpointSafetyGate().evaluate(advisory(), inputs(IntegrationMode.HARDWARE))
    assert result.accepted is False
    assert "staff_hardware_gate_missing" in result.reasons


def test_contract_cannot_claim_execution():
    with pytest.raises(ValueError, match="cannot represent an executed"):
        advisory(executed=True)


@pytest.mark.parametrize("mode", ["unknown", "hardware", object()])
def test_unrecognized_modes_are_rejected_at_construction(mode):
    with pytest.raises((ValueError, TypeError)):
        inputs(mode, staff_hardware_gate=True)


@pytest.mark.parametrize(
    "timestamp", [float("nan"), float("inf"), float("-inf"), -1, True, False, 1.5, 1.0]
)
@pytest.mark.parametrize("field", ["advisory", "now"])
def test_timestamps_require_nonnegative_integers(field, timestamp):
    with pytest.raises((ValueError, TypeError)):
        if field == "advisory":
            advisory(timestamp_ns=timestamp)
        else:
            inputs(now_ns=timestamp)


@pytest.mark.parametrize(
    ("mode", "staff_gate", "accepted", "authority"),
    [
        (IntegrationMode.OBSERVER, False, False, Authority.NONE),
        (IntegrationMode.SHADOW, False, False, Authority.NONE),
        (IntegrationMode.SIMULATION, False, True, Authority.SIMULATION_ONLY),
        (IntegrationMode.HARDWARE, False, False, Authority.HARDWARE_GATED),
        (IntegrationMode.HARDWARE, True, True, Authority.HARDWARE_GATED),
    ],
)
def test_valid_modes_preserve_authority_without_execution(mode, staff_gate, accepted, authority):
    result = SetpointSafetyGate().evaluate(advisory(), inputs(mode, staff_hardware_gate=staff_gate))
    assert result.accepted is accepted
    assert result.authority is authority
    assert result.executed is False


@pytest.mark.parametrize(
    ("now_ns", "reason"),
    [(999_999_999, "timestamp_from_future"), (1_150_000_001, "stale_advisory")],
)
def test_integer_timestamps_preserve_freshness_reasons(now_ns, reason):
    result = SetpointSafetyGate().evaluate(advisory(), inputs(now_ns=now_ns))
    assert reason in result.reasons
    assert result.executed is False


@pytest.mark.parametrize(
    "field",
    [
        "localization_valid",
        "perception_valid",
        "depth_known",
        "offboard_heartbeat_healthy",
        "staff_hardware_gate",
    ],
)
@pytest.mark.parametrize("value", ["false", 0, 1, None, float("nan")])
def test_gate_boolean_fields_reject_truthy_and_falsy_non_booleans(field, value):
    with pytest.raises((TypeError, ValueError)):
        inputs(IntegrationMode.HARDWARE, **{field: value})


@pytest.mark.parametrize(
    "field", ["max_age_ms", "max_xy_speed_m_s", "max_z_speed_m_s", "max_yaw_rate_rad_s"]
)
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), -0.1, True, "1", None]
)
def test_safety_limits_reject_invalid_values(field, value):
    with pytest.raises((TypeError, ValueError)):
        SafetyLimits(**{field: value})


def test_zero_limits_allow_only_zero_motion_at_same_timestamp():
    gate = SetpointSafetyGate(SafetyLimits(0, 0, 0, 0))
    stopped = gate.evaluate(advisory(vx_m_s=0), inputs(now_ns=1_000_000_000))
    moving = gate.evaluate(advisory(), inputs(now_ns=1_000_000_001))
    assert stopped.accepted and not stopped.executed
    assert {"stale_advisory", "xy_speed_limit"} <= set(moving.reasons)
    assert not moving.accepted and not moving.executed


@pytest.mark.parametrize("future", [False, True])
def test_extremely_large_timestamp_difference_is_rejected_without_overflow(future):
    huge = 10**400
    result = SetpointSafetyGate().evaluate(
        advisory(timestamp_ns=huge if future else 0),
        inputs(now_ns=0 if future else huge),
    )
    assert not result.accepted and not result.executed
    assert ("timestamp_from_future" if future else "stale_advisory") in result.reasons
