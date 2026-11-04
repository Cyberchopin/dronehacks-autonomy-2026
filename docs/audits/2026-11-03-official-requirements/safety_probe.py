"""Pure-object audit observations, no transport or publisher. Not a flight test."""
from dataclasses import asdict, replace
import json
from aegisland.competition_contract import AdvisorySetpoint, GateInputs, IntegrationMode, SafetyLimits, SetpointSafetyGate
from aegisland.px4.watchdog import evaluate_telemetry_freshness
from aegisland.px4.shadow_policy import decide_shadow_action
from aegisland.px4.watchdog import LinkHealth

a = AdvisorySetpoint(1_000_000_000, "body_frd", .2, 0., 0., 0., .8, "audit only")
i = GateInputs(1_050_000_000, IntegrationMode.SIMULATION, True, True, True, True)
cases = [
    ("valid_simulation_reference", a, i, None),
    ("observer_reference", a, replace(i, mode=IntegrationMode.OBSERVER), None),
    ("unknown_mode", a, replace(i, mode="invalid"), None),
    ("nan_now", a, replace(i, now_ns=float("nan")), None),
    ("nan_timestamp", replace(a, timestamp_ns=float("nan")), i, None),
    ("truthy_invalid_health", a, replace(i, localization_valid="false", perception_valid="false", depth_known="false", offboard_heartbeat_healthy="false"), None),
    ("nan_speed_limit", replace(a, vx_m_s=100.), i, SafetyLimits(max_xy_speed_m_s=float("nan"))),
    ("unknown_depth_lateral", replace(a, vx_m_s=0., vy_m_s=.2), replace(i, depth_known=False), None),
    ("unknown_depth_negative_x", replace(a, vx_m_s=-.2), replace(i, depth_known=False), None),
    ("unknown_depth_local_ned", replace(a, frame="local_ned", vx_m_s=0., vy_m_s=.2), replace(i, depth_known=False), None),
    ("zero_confidence", replace(a, confidence=0.), i, None),
]
for name, advisory, inputs, limits in cases:
    try:
        print(json.dumps(dict(case=name, result=asdict(SetpointSafetyGate(limits).evaluate(advisory, inputs)))))
    except Exception as exc:
        print(json.dumps(dict(case=name, rejected_by_exception=type(exc).__name__, detail=str(exc))))
print(json.dumps(dict(case="executed_integer_zero", type=type(replace(a, executed=0).executed).__name__)))
w = evaluate_telemetry_freshness(float("nan"))
print(json.dumps(dict(case="nan_watchdog_age", health=w.health, stale=w.stale)))
print(json.dumps(dict(case="healthy_link_without_gps", result=asdict(decide_shadow_action(link_health=LinkHealth.HEALTHY, gps_available=False)))))
from aegisland.sensor_health import SensorHealthMonitor
monitor = SensorHealthMonitor()
for n in range(3):
    result = monitor.assess("nan_sensor", confidence=float("nan"), valid=True)
    print(json.dumps(dict(case="nan_sensor_confidence", sample=n+1, result=asdict(result))))
