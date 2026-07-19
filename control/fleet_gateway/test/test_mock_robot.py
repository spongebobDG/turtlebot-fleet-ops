"""Test deterministic helpers used by the robot-free TB1 simulator."""

import pytest

from fleet_gateway.mock_robot import interpolate_pose, navigation_duration


def test_navigation_duration_reserves_long_goal_for_cancel() -> None:
    assert navigation_duration(0.5) == 2.0
    assert navigation_duration(1.5) == 30.0


def test_interpolate_pose_clamps_progress() -> None:
    start = (0.0, 0.0, 0.0)
    target = (1.0, -1.0, 2.0)

    assert interpolate_pose(start, target, -1.0) == start
    assert interpolate_pose(start, target, 2.0) == target
    assert interpolate_pose(start, target, 0.5) == pytest.approx(
        (0.5, -0.5, 1.0)
    )
