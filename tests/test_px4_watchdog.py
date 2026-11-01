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
    result = evaluate_telemetry_freshness(
        age_s
    )

    assert result.health == expected


def test_watchdog_rejects_negative_age() -> None:
    with pytest.raises(ValueError):
        evaluate_telemetry_freshness(
            -0.1
        )
