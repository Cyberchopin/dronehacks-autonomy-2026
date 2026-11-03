import pytest

from aegisland.px4.watchdog import (
    LinkHealth,
    evaluate_telemetry_freshness,
)


@pytest.mark.parametrize(
    ("age_s", "expected"),
    [
        (0.1, LinkHealth.HEALTHY),
        (0.5, LinkHealth.DEGRADED),
        (1.0, LinkHealth.DEGRADED),
        (1.5, LinkHealth.FAILED),
        (3.0, LinkHealth.FAILED),
    ],
)
def test_watchdog_health_transitions(
    age_s,
    expected,
) -> None:
    result = evaluate_telemetry_freshness(age_s)

    assert result.health == expected


def test_watchdog_rejects_negative_age() -> None:
    with pytest.raises(ValueError):
        evaluate_telemetry_freshness(-0.1)


@pytest.mark.parametrize("age", [float("nan"), float("inf"), float("-inf")])
def test_watchdog_rejects_nonfinite_age_without_producing_a_result(age):
    with pytest.raises(ValueError):
        evaluate_telemetry_freshness(age)


@pytest.mark.parametrize("field", ["degraded_after_s", "failed_after_s"])
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), -0.1, True, "1", None]
)
def test_watchdog_rejects_invalid_thresholds(field, value):
    with pytest.raises((TypeError, ValueError)):
        evaluate_telemetry_freshness(0, **{field: value})


def test_watchdog_rejects_reversed_thresholds():
    with pytest.raises(ValueError):
        evaluate_telemetry_freshness(0, degraded_after_s=2, failed_after_s=1)


@pytest.mark.parametrize(
    ("age", "degraded", "failed", "expected"),
    [
        (0, 0, 0, LinkHealth.FAILED),
        (0, 0, 1, LinkHealth.DEGRADED),
        (0.9, 1, 1, LinkHealth.HEALTHY),
        (1, 1, 1, LinkHealth.FAILED),
    ],
)
def test_watchdog_threshold_boundaries(age, degraded, failed, expected):
    result = evaluate_telemetry_freshness(age, degraded_after_s=degraded, failed_after_s=failed)
    assert result.health is expected


@pytest.mark.parametrize("age", [True, False, "0", None, object()])
def test_watchdog_rejects_non_numeric_and_boolean_ages(age):
    with pytest.raises(TypeError):
        evaluate_telemetry_freshness(age)


@pytest.mark.parametrize("age", [10**400, -(10**400)])
def test_watchdog_rejects_unrepresentable_integer_age_without_overflow(age):
    with pytest.raises(ValueError):
        evaluate_telemetry_freshness(age)
