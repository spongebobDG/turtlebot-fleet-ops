"""Verify fail-closed map-frame Nav2 goal supervision."""

import math

import pytest

from navigation_agent.goal_progress import NavigationProgressMonitor


def _monitor() -> NavigationProgressMonitor:
    return NavigationProgressMonitor(
        started_at=10.0,
        progress_timeout_sec=5.0,
        feedback_timeout_sec=2.0,
        max_duration_sec=30.0,
        distance_progress_m=0.05,
        yaw_progress_rad=0.1,
    )


def test_missing_feedback_and_hard_duration_fail_closed() -> None:
    monitor = _monitor()
    assert monitor.failure_reason(11.9) is None
    assert "feedback timeout" in monitor.failure_reason(12.0).lower()

    monitor.update(12.0, 1.0, 0.0, 0.0, 0)
    assert "maximum duration" in monitor.failure_reason(40.0).lower()


def test_material_distance_progress_resets_stall_window() -> None:
    monitor = _monitor()
    assert not monitor.update(10.1, 1.0, 0.0, 0.0, 0)
    assert not monitor.update(12.0, 0.97, 0.0, 0.0, 0)
    assert monitor.update(13.0, 0.94, 0.0, 0.0, 0)
    assert not monitor.update(17.9, 0.94, 0.0, 0.0, 0)
    assert monitor.failure_reason(17.9) is None
    assert not monitor.update(18.0, 0.94, 0.0, 0.0, 0)
    assert "failed to make progress" in monitor.failure_reason(18.0).lower()


def test_yaw_must_improve_toward_target_across_angle_wrap() -> None:
    monitor = _monitor()
    target = math.radians(-179.0)
    assert not monitor.update(10.1, 0.0, math.radians(170.0), target, 0)
    assert monitor.update(11.0, 0.0, math.radians(-174.0), target, 0)

    stalled = _monitor()
    assert not stalled.update(10.1, 0.0, 0.0, 1.0, 0)
    assert not stalled.update(12.0, 0.0, -0.3, 1.0, 0)
    assert not stalled.update(14.9, 0.0, -0.3, 1.0, 0)
    assert "failed to make progress" in stalled.failure_reason(15.1).lower()


def test_recovery_grants_a_new_progress_window() -> None:
    monitor = _monitor()
    monitor.update(10.1, 1.0, 0.0, 0.0, 0)
    assert monitor.update(14.9, 1.1, 0.2, 0.0, 1)
    assert not monitor.update(19.8, 1.1, 0.2, 0.0, 1)
    assert monitor.failure_reason(19.8) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"progress_timeout_sec": 0.0},
        {"feedback_timeout_sec": float("nan")},
        {"max_duration_sec": 5.0},
        {"distance_progress_m": -0.1},
        {"yaw_progress_rad": 0.0},
    ],
)
def test_invalid_limits_are_rejected(changes) -> None:
    values = {
        "started_at": 10.0,
        "progress_timeout_sec": 5.0,
        "feedback_timeout_sec": 2.0,
        "max_duration_sec": 30.0,
        "distance_progress_m": 0.05,
        "yaw_progress_rad": 0.1,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        NavigationProgressMonitor(**values)
