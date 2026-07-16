import time

from fleet_interfaces.msg import RobotStatus
import pytest
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from fleet_gateway.mock_robot import interpolate_pose
from fleet_gateway.mock_robot import MockRobotNode
from fleet_gateway.mock_robot import navigation_duration


def test_interpolate_pose_clamps_progress():
    start = (0.0, 1.0, -1.0)
    target = (2.0, 3.0, 1.0)

    assert interpolate_pose(start, target, -0.5) == start
    assert interpolate_pose(start, target, 1.5) == target
    assert interpolate_pose(start, target, 0.5) == pytest.approx(
        (1.0, 2.0, 0.0)
    )


def test_long_target_enables_cancel_and_timeout_practice():
    assert navigation_duration(1.0) == 2.0
    assert navigation_duration(5.0) == 30.0


def test_mock_robot_publishes_tb1_status():
    rclpy.init()
    mock = MockRobotNode()
    observer = Node("mock_robot_test_observer")
    messages = []
    subscription = observer.create_subscription(
        RobotStatus,
        "/fleet/robot_status",
        messages.append,
        10,
    )
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(mock)
    executor.add_node(observer)
    deadline = time.monotonic() + 2.0

    try:
        while not messages and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert messages
        assert messages[-1].robot_id == "tb1"
        assert messages[-1].battery_valid is True
    finally:
        observer.destroy_subscription(subscription)
        executor.shutdown(timeout_sec=1.0)
        observer.destroy_node()
        mock.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
