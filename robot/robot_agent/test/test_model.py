"""Unit tests for Robot Agent normalization and health policy."""

import math

import pytest

from robot_agent.model import (
    Freshness,
    HealthInput,
    HealthThresholds,
    LEVEL_ERROR,
    LEVEL_OK,
    LEVEL_WARN,
    UNKNOWN_VALUE,
    evaluate_health,
    normalize_battery_percent,
    quaternion_to_yaw,
    scan_statistics,
    source_freshness,
)


def _thresholds() -> HealthThresholds:
    return HealthThresholds(20.0, 90.0, 90.0, 90.0)


def _healthy_facts(**changes) -> HealthInput:
    values = {
        "battery": Freshness(True, True, 0.1),
        "battery_valid": True,
        "battery_percent": 75.0,
        "odom": Freshness(True, True, 0.1),
        "odom_valid": True,
        "scan": Freshness(True, True, 0.1),
        "scan_valid": True,
        "cpu_percent": 10.0,
        "memory_percent": 20.0,
        "disk_percent": 30.0,
    }
    values.update(changes)
    return HealthInput(**values)


def test_missing_source_has_unknown_age() -> None:
    result = source_freshness(None, 10.0, 1.0)
    assert result == Freshness(False, False, UNKNOWN_VALUE)


def test_source_freshness_includes_timeout_boundary() -> None:
    assert source_freshness(10.0, 11.0, 1.0).fresh
    assert not source_freshness(10.0, 11.001, 1.0).fresh


def test_future_source_is_not_fresh() -> None:
    result = source_freshness(11.0, 10.0, 1.0)
    assert result == Freshness(True, False, UNKNOWN_VALUE)


@pytest.mark.parametrize("timeout", [0.0, -1.0, math.inf])
def test_invalid_freshness_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError):
        source_freshness(1.0, 1.0, timeout)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.0, 0.0), (0.75, 75.0), (1.0, 100.0), (86.66, 86.66)],
)
def test_battery_percentage_formats_are_normalized(
    raw: float,
    expected: float,
) -> None:
    assert normalize_battery_percent(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [-0.1, 100.1, math.nan, math.inf])
def test_invalid_battery_percentage_is_unknown(raw: float) -> None:
    assert normalize_battery_percent(raw) == UNKNOWN_VALUE


def test_identity_quaternion_has_zero_yaw() -> None:
    yaw, valid = quaternion_to_yaw(0.0, 0.0, 0.0, 1.0)
    assert valid
    assert yaw == pytest.approx(0.0)


def test_quaternion_is_normalized_before_yaw_conversion() -> None:
    yaw, valid = quaternion_to_yaw(0.0, 0.0, 2.0, 2.0)
    assert valid
    assert yaw == pytest.approx(math.pi / 2.0)


@pytest.mark.parametrize(
    "quaternion",
    [(0.0, 0.0, 0.0, 0.0), (math.nan, 0.0, 0.0, 1.0)],
)
def test_invalid_quaternion_is_rejected(quaternion) -> None:
    yaw, valid = quaternion_to_yaw(*quaternion)
    assert not valid
    assert yaw == 0.0


def test_scan_statistics_filter_invalid_and_out_of_range_points() -> None:
    count, nearest = scan_statistics(
        [math.inf, math.nan, 0.05, 0.8, 2.0, 11.0],
        0.1,
        10.0,
    )
    assert count == 2
    assert nearest == pytest.approx(0.8)


def test_scan_without_valid_points_uses_unknown_sentinel() -> None:
    assert scan_statistics([math.inf, 0.01], 0.1, 10.0) == (
        0,
        UNKNOWN_VALUE,
    )


@pytest.mark.parametrize(
    "thresholds",
    [(-1.0, 90.0, 90.0, 90.0), (20.0, 101.0, 90.0, 90.0)],
)
def test_invalid_health_threshold_is_rejected(thresholds) -> None:
    with pytest.raises(ValueError):
        HealthThresholds(*thresholds)


def test_healthy_snapshot_is_ok() -> None:
    result = evaluate_health(_healthy_facts(), _thresholds())
    assert result.level == LEVEL_OK
    assert result.fault_codes == ()


def test_missing_critical_sources_are_errors() -> None:
    missing = Freshness(False, False, UNKNOWN_VALUE)
    result = evaluate_health(
        _healthy_facts(odom=missing, scan=missing),
        _thresholds(),
    )
    assert result.level == LEVEL_ERROR
    assert result.fault_codes == (
        "ODOM_NOT_RECEIVED",
        "SCAN_NOT_RECEIVED",
    )


def test_invalid_source_precedes_stale_fault() -> None:
    stale = Freshness(True, False, 5.0)
    result = evaluate_health(
        _healthy_facts(odom=stale, odom_valid=False),
        _thresholds(),
    )
    assert result.level == LEVEL_ERROR
    assert result.fault_codes == ("ODOM_INVALID",)


def test_battery_and_resource_conditions_are_warnings() -> None:
    result = evaluate_health(
        _healthy_facts(
            battery_percent=20.0,
            cpu_percent=90.0,
            memory_percent=91.0,
            disk_percent=92.0,
        ),
        _thresholds(),
    )
    assert result.level == LEVEL_WARN
    assert result.fault_codes == (
        "LOW_BATTERY",
        "HIGH_CPU",
        "HIGH_MEMORY",
        "HIGH_DISK",
    )
