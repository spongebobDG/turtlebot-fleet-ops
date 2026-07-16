"""ROS graph integration test for watchdog output and emergency stop."""

import math
import time
from typing import Callable, List

from geometry_msgs.msg import Twist
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool
from std_srvs.srv import SetBool

from safety_watchdog.node import SafetyWatchdog


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


def test_watchdog_ros_flow() -> None:
    rclpy.init()
    watchdog = SafetyWatchdog(
        parameter_overrides=[
            Parameter("input_topic", value="/test/safety/cmd_vel_in"),
            Parameter("output_topic", value="/test/safety/cmd_vel_out"),
            Parameter(
                "estop_status_topic",
                value="/test/safety/estop_active",
            ),
            Parameter("timeout_sec", value=0.15),
            Parameter("publish_rate_hz", value=50.0),
            Parameter("estop_status_rate_hz", value=20.0),
            Parameter("max_linear_x", value=0.05),
            Parameter("max_angular_z", value=0.3),
            Parameter("neutral_epsilon", value=0.001),
        ]
    )
    probe = Node("safety_watchdog_test_probe")
    executor = SingleThreadedExecutor()
    outputs: List[Twist] = []
    statuses: List[Bool] = []

    publisher = probe.create_publisher(
        Twist,
        "/test/safety/cmd_vel_in",
        10,
    )
    subscription = probe.create_subscription(
        Twist,
        "/test/safety/cmd_vel_out",
        outputs.append,
        10,
    )
    status_qos = QoSProfile(
        depth=1,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        reliability=ReliabilityPolicy.RELIABLE,
    )
    status_subscription = probe.create_subscription(
        Bool,
        "/test/safety/estop_active",
        statuses.append,
        status_qos,
    )
    estop_client = probe.create_client(
        SetBool,
        "/safety_watchdog/set_estop",
    )

    executor.add_node(watchdog)
    executor.add_node(probe)

    try:
        _spin_until(executor, lambda: len(outputs) > 0)
        _spin_until(executor, lambda: len(statuses) > 0)
        assert outputs[-1].linear.x == 0.0
        assert outputs[-1].angular.z == 0.0
        assert statuses[-1].data is True

        assert estop_client.wait_for_service(timeout_sec=1.0)
        request = SetBool.Request()
        request.data = False
        future = estop_client.call_async(request)
        _spin_until(executor, future.done)
        assert future.result().success
        _spin_until(executor, lambda: statuses[-1].data is False)

        neutral_command = Twist()
        publisher.publish(neutral_command)
        _spin_until(executor, lambda: len(outputs) >= 2)

        outputs.clear()
        unsafe_command = Twist()
        unsafe_command.linear.x = 1.0
        unsafe_command.angular.z = -2.0
        publisher.publish(unsafe_command)

        _spin_until(
            executor,
            lambda: any(
                message.linear.x == 0.05
                and message.angular.z == -0.3
                for message in outputs
            ),
        )

        _spin_until(
            executor,
            lambda: bool(outputs)
            and outputs[-1].linear.x == 0.0
            and outputs[-1].angular.z == 0.0,
        )

        request.data = True
        future = estop_client.call_async(request)
        _spin_until(executor, future.done)
        assert future.result().success
        assert "activated" in future.result().message
        _spin_until(executor, lambda: statuses[-1].data is True)

        outputs.clear()
        publisher.publish(unsafe_command)
        _spin_until(executor, lambda: len(outputs) >= 2)
        assert all(message.linear.x == 0.0 for message in outputs)
        assert all(message.angular.z == 0.0 for message in outputs)

        request = SetBool.Request()
        request.data = False
        future = estop_client.call_async(request)
        _spin_until(executor, future.done)
        assert future.result().success
        assert "neutral command" in future.result().message
        _spin_until(executor, lambda: statuses[-1].data is False)

        outputs.clear()
        publisher.publish(unsafe_command)
        _spin_until(executor, lambda: len(outputs) >= 2)
        assert all(message.linear.x == 0.0 for message in outputs)
        assert all(message.angular.z == 0.0 for message in outputs)

        outputs.clear()
        invalid_command = Twist()
        invalid_command.linear.x = math.nan
        publisher.publish(invalid_command)
        _spin_until(executor, lambda: len(outputs) >= 2)
        assert all(message.linear.x == 0.0 for message in outputs)

        outputs.clear()
        publisher.publish(unsafe_command)
        _spin_until(executor, lambda: len(outputs) >= 2)
        assert all(message.linear.x == 0.0 for message in outputs)
        assert all(message.angular.z == 0.0 for message in outputs)

        publisher.publish(neutral_command)
        _spin_until(executor, lambda: len(outputs) >= 3)

        outputs.clear()
        publisher.publish(unsafe_command)
        _spin_until(
            executor,
            lambda: any(message.linear.x == 0.05 for message in outputs),
        )
    finally:
        probe.destroy_subscription(subscription)
        probe.destroy_subscription(status_subscription)
        executor.remove_node(probe)
        executor.remove_node(watchdog)
        probe.destroy_node()
        watchdog.destroy_node()
        executor.shutdown()
        rclpy.shutdown()
