"""Unit tests for safety decisions that do not require a ROS graph."""

import math

import pytest

from safety_watchdog.policy import (
    SafetyLimits,
    command_is_fresh,
    sanitize_planar_command,
)


def test_command_inside_limits_is_unchanged() -> None:
    limits = SafetyLimits(max_linear_x=0.05, max_angular_z=0.3)

    assert sanitize_planar_command(0.03, -0.2, limits) == (0.03, -0.2)


def test_command_is_clamped_in_both_directions() -> None:
    limits = SafetyLimits(max_linear_x=0.05, max_angular_z=0.3)

    assert sanitize_planar_command(1.0, -2.0, limits) == (0.05, -0.3)
    assert sanitize_planar_command(-1.0, 2.0, limits) == (-0.05, 0.3)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_command_is_replaced_with_zero(value: float) -> None:
    limits = SafetyLimits(max_linear_x=0.05, max_angular_z=0.3)

    assert sanitize_planar_command(value, value, limits) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("linear_limit", "angular_limit"),
    [(0.0, 0.3), (-0.1, 0.3), (0.05, math.inf)],
)
def test_invalid_limits_are_rejected(
    linear_limit: float,
    angular_limit: float,
) -> None:
    with pytest.raises(ValueError):
        SafetyLimits(
            max_linear_x=linear_limit,
            max_angular_z=angular_limit,
        )


def test_command_freshness_includes_timeout_boundary() -> None:
    assert command_is_fresh(10.0, 10.5, 0.5)
    assert not command_is_fresh(10.0, 10.5001, 0.5)


def test_missing_or_future_command_is_not_fresh() -> None:
    assert not command_is_fresh(None, 10.0, 0.5)
    assert not command_is_fresh(11.0, 10.0, 0.5)
