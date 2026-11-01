import pytest

from aegisland.competition_contract import (
    AdvisorySetpoint,
    Authority,
    GateInputs,
    IntegrationMode,
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
