"""ROS graph integration test for fail-closed motion arbitration."""

import time
from typing import Callable, List

from fleet_interfaces.srv import SetMotionMode
from geometry_msgs.msg import Twist
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import Bool

from navigation_agent.arbiter_node import MotionArbiter
from navigation_agent.model import MODE_IDLE, MODE_MANUAL, MODE_NAVIGATION


def _spin_until(
    executor: SingleThreadedExecutor,
    condition: Callable[[], bool],
    timeout_sec: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
        if condition():
            return
    raise AssertionError("condition was not met before timeout")


def _set_mode(
    executor: SingleThreadedExecutor,
    client,
    mode: int,
) -> None:
    request = SetMotionMode.Request()
    request.mode = mode
    future = client.call_async(request)
    _spin_until(executor, future.done)
    assert future.result().success


def test_arbiter_ros_flow_and_authorization_expiry() -> None:
    rclpy.init()
    arbiter = MotionArbiter(
        parameter_overrides=[
            Parameter("manual_input_topic", value="/test/motion/manual"),
            Parameter("navigation_input_topic", value="/test/motion/nav"),
            Parameter("output_topic", value="/test/motion/safety_in"),
            Parameter("authorization_topic", value="/test/motion/auth"),
            Parameter("mode_service", value="/test/motion/set_mode"),
            Parameter("default_mode", value=MODE_IDLE),
            Parameter("input_timeout_sec", value=0.15),
            Parameter("authorization_timeout_sec", value=0.15),
            Parameter("publish_rate_hz", value=50.0),
        ]
    )
    probe = Node("motion_arbiter_test_probe")
    executor = SingleThreadedExecutor()
    outputs: List[Twist] = []
    manual_publisher = probe.create_publisher(
        Twist,
        "/test/motion/manual",
        10,
    )
    navigation_publisher = probe.create_publisher(
        Twist,
        "/test/motion/nav",
        10,
    )
    authorization_publisher = probe.create_publisher(
        Bool,
        "/test/motion/auth",
        10,
    )
    output_subscription = probe.create_subscription(
        Twist,
        "/test/motion/safety_in",
        outputs.append,
        10,
    )
    mode_client = probe.create_client(
        SetMotionMode,
        "/test/motion/set_mode",
    )
    executor.add_node(arbiter)
    executor.add_node(probe)

    try:
        _spin_until(executor, lambda: bool(outputs))
        _spin_until(executor, lambda: mode_client.service_is_ready())
        assert outputs[-1].linear.x == 0.0

        _set_mode(executor, mode_client, MODE_NAVIGATION)
        outputs.clear()
        command = Twist()
        command.linear.x = 0.05
        command.angular.z = -0.2
        navigation_publisher.publish(command)
        _spin_until(executor, lambda: len(outputs) >= 2)
        assert all(message.linear.x == 0.0 for message in outputs)

        outputs.clear()
        authorization = Bool()
        authorization.data = True
        authorization_publisher.publish(authorization)
        navigation_publisher.publish(command)
        _spin_until(
            executor,
            lambda: any(message.linear.x == 0.05 for message in outputs),
        )
        _spin_until(
            executor,
            lambda: bool(outputs) and outputs[-1].linear.x == 0.0,
            timeout_sec=1.0,
        )

        _set_mode(executor, mode_client, MODE_MANUAL)
        outputs.clear()
        manual = Twist()
        manual.linear.x = 0.03
        manual.angular.z = 0.1
        manual_publisher.publish(manual)
        _spin_until(
            executor,
            lambda: any(message.linear.x == 0.03 for message in outputs),
        )

        _set_mode(executor, mode_client, MODE_IDLE)
        _spin_until(
            executor,
            lambda: bool(outputs) and outputs[-1].linear.x == 0.0,
        )
    finally:
        probe.destroy_subscription(output_subscription)
        executor.remove_node(probe)
        executor.remove_node(arbiter)
        probe.destroy_node()
        arbiter.destroy_node()
        executor.shutdown()
        rclpy.shutdown()
