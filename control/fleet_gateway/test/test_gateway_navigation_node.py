"""ROS graph checks for Gateway navigation leases and fail-closed cancel."""

import time
from types import SimpleNamespace
from typing import Callable, List

from fleet_interfaces.msg import NavigationLease, NavigationStatus
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.task import Future

from fleet_gateway.ros_node import FleetGatewayNode


def _spin_until(
    executor: SingleThreadedExecutor,
    condition: Callable[[], bool],
    timeout_sec: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
        if condition():
            return
    raise AssertionError("condition was not met before timeout")


class _FakeGoalHandle:
    """Minimal cancelable goal handle used by the lease graph test."""

    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel_goal_async(self) -> Future:
        self.cancel_calls += 1
        future = Future()
        future.set_result(SimpleNamespace(goals_canceling=[object()]))
        return future


def test_gateway_publishes_half_second_leases_and_cancel_stops_them() -> None:
    rclpy.init()
    gateway = FleetGatewayNode()
    probe = Node("fleet_gateway_navigation_test_probe")
    executor = SingleThreadedExecutor()
    leases: List[tuple] = []
    subscription = probe.create_subscription(
        NavigationLease,
        "/fleet/navigation_lease",
        lambda message: leases.append((time.monotonic(), message)),
        10,
    )
    executor.add_node(gateway)
    executor.add_node(probe)
    fake_handle = _FakeGoalHandle()
    # Keep this lease-only fixture independent of real tb1 status traffic.
    robot_id = "lease-test-robot"

    try:
        _spin_until(
            executor,
            lambda: gateway._lease_publisher.get_subscription_count() > 0,
        )
        with gateway._navigation_lock:
            gateway._active_navigation[robot_id] = (
                "lease-test-command",
                fake_handle,
            )
            gateway._confirmed_navigation[robot_id] = "lease-test-command"
        _spin_until(executor, lambda: len(leases) >= 3, timeout_sec=2.5)

        assert all(item[1].robot_id == robot_id for item in leases)
        assert all(
            item[1].command_id == "lease-test-command" for item in leases
        )
        intervals = [
            leases[index][0] - leases[index - 1][0]
            for index in range(1, len(leases))
        ]
        assert all(0.2 <= interval <= 1.0 for interval in intervals)
        assert 0.35 <= sum(intervals) / len(intervals) <= 0.75

        result = gateway.cancel_navigation(robot_id, "lease-test-command")
        assert result["success"] is True
        assert result["state"] == "CANCELING"
        assert fake_handle.cancel_calls == 1
        with gateway._navigation_lock:
            assert robot_id not in gateway._active_navigation

        lease_count = len(leases)
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.02)
        assert len(leases) == lease_count
        assert (
            gateway.cancel_navigation(
                robot_id,
                "wrong-command",
            )["status_code"]
            == 409
        )

        with gateway._navigation_lock:
            gateway._active_navigation[robot_id] = (
                "restart-test-command",
                fake_handle,
            )
            gateway._confirmed_navigation[robot_id] = "restart-test-command"
        restarted_status = NavigationStatus()
        restarted_status.robot_id = robot_id
        restarted_status.state = NavigationStatus.STATE_UNAVAILABLE
        gateway._navigation_status_callback(restarted_status)
        with gateway._navigation_lock:
            assert robot_id not in gateway._active_navigation
            assert robot_id not in gateway._confirmed_navigation

        unconfirmed_handle = _FakeGoalHandle()
        with gateway._navigation_lock:
            gateway._active_navigation[robot_id] = (
                "unconfirmed-command",
                unconfirmed_handle,
            )
            gateway._navigation_accepted_at[robot_id] = (
                time.monotonic() - 3.0
            )
        gateway._publish_navigation_leases()
        with gateway._navigation_lock:
            assert robot_id not in gateway._active_navigation
            assert robot_id not in gateway._navigation_accepted_at
        assert unconfirmed_handle.cancel_calls == 1
    finally:
        probe.destroy_subscription(subscription)
        executor.remove_node(probe)
        executor.remove_node(gateway)
        probe.destroy_node()
        gateway.destroy_node()
        executor.shutdown()
        rclpy.shutdown()
