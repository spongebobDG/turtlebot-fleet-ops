"""ROS integration tests for the local web-manual deadman adapter."""

import time

from fleet_interfaces.srv import ManualCommand
from geometry_msgs.msg import Twist
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter

from navigation_agent.arbiter_node import MotionArbiter
from navigation_agent.manual_control_node import (
    ManualControlNode,
    _cleanup_manual_control,
)


def spin_until(executor, condition, timeout=2.0):
    """Spin a bounded ROS graph until a test condition becomes true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.02)
        if condition():
            return
    raise AssertionError("condition was not met before timeout")


def test_manual_session_clamps_and_expires_to_idle_zero():
    rclpy.init()
    arbiter = MotionArbiter(
        parameter_overrides=[
            Parameter("manual_input_topic", value="/test/manual/input"),
            Parameter("navigation_input_topic", value="/test/manual/nav"),
            Parameter("output_topic", value="/test/manual/output"),
            Parameter("authorization_topic", value="/test/manual/auth"),
            Parameter("mode_service", value="/test/manual/mode"),
            Parameter("default_mode", value=0),
            Parameter("input_timeout_sec", value=0.5),
            Parameter("authorization_timeout_sec", value=0.5),
            Parameter("publish_rate_hz", value=50.0),
        ]
    )
    manual = ManualControlNode(
        parameter_overrides=[
            Parameter("command_service", value="/test/manual/command"),
            Parameter("manual_output_topic", value="/test/manual/input"),
            Parameter("motion_mode_service", value="/test/manual/mode"),
            Parameter("command_timeout_sec", value=0.2),
            Parameter("publish_rate_hz", value=50.0),
            Parameter("max_linear_x", value=0.05),
            Parameter("max_angular_z", value=0.3),
        ]
    )
    probe = Node("manual_control_test_probe")
    outputs = []
    subscription = probe.create_subscription(
        Twist,
        "/test/manual/output",
        outputs.append,
        10,
    )
    client = probe.create_client(ManualCommand, "/test/manual/command")
    executor = SingleThreadedExecutor()
    for node in (arbiter, manual, probe):
        executor.add_node(node)
    try:
        spin_until(executor, client.service_is_ready)
        request = ManualCommand.Request()
        request.session_id = "session-1"
        request.command.linear.x = 0.2
        request.command.angular.z = -0.9
        response = client.call_async(request)
        spin_until(executor, response.done)
        assert response.result().success
        spin_until(
            executor,
            lambda: any(
                message.linear.x == 0.05
                and message.angular.z == -0.3
                for message in outputs
            ),
        )
        spin_until(
            executor,
            lambda: bool(outputs)
            and outputs[-1].linear.x == 0.0
            and outputs[-1].angular.z == 0.0,
            timeout=1.0,
        )
        spin_until(executor, lambda: arbiter._mode == 0)

        wrong_stop = ManualCommand.Request()
        wrong_stop.session_id = "wrong"
        wrong_stop.stop = True
        rejected = client.call_async(wrong_stop)
        spin_until(executor, rejected.done)
        assert not rejected.result().success
    finally:
        probe.destroy_subscription(subscription)
        for node in (probe, manual, arbiter):
            executor.remove_node(node)
            node.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def test_zero_session_gets_startup_grace_then_short_deadman_timeout():
    rclpy.init()
    arbiter = MotionArbiter(
        parameter_overrides=[
            Parameter("manual_input_topic", value="/test/startup/input"),
            Parameter("navigation_input_topic", value="/test/startup/nav"),
            Parameter("output_topic", value="/test/startup/output"),
            Parameter("authorization_topic", value="/test/startup/auth"),
            Parameter("mode_service", value="/test/startup/mode"),
            Parameter("publish_rate_hz", value=50.0),
        ]
    )
    manual = ManualControlNode(
        parameter_overrides=[
            Parameter("command_service", value="/test/startup/command"),
            Parameter("manual_output_topic", value="/test/startup/input"),
            Parameter("motion_mode_service", value="/test/startup/mode"),
            Parameter("command_timeout_sec", value=0.2),
            Parameter("session_start_timeout_sec", value=1.5),
            Parameter("publish_rate_hz", value=50.0),
        ]
    )
    probe = Node("manual_startup_grace_probe")
    client = probe.create_client(ManualCommand, "/test/startup/command")
    executor = SingleThreadedExecutor()
    executor.add_node(arbiter)
    executor.add_node(manual)
    executor.add_node(probe)
    try:
        spin_until(executor, client.service_is_ready)
        start = ManualCommand.Request()
        start.session_id = "web-session"
        started = client.call_async(start)
        spin_until(executor, started.done)
        assert started.result().success

        grace_deadline = time.monotonic() + 0.35
        while time.monotonic() < grace_deadline:
            executor.spin_once(timeout_sec=0.02)
        assert manual._session_id == "web-session"

        refresh = ManualCommand.Request()
        refresh.session_id = "web-session"
        refreshed = client.call_async(refresh)
        spin_until(executor, refreshed.done)
        assert refreshed.result().success
        spin_until(executor, lambda: manual._session_id == "", timeout=0.6)
    finally:
        executor.remove_node(probe)
        executor.remove_node(manual)
        executor.remove_node(arbiter)
        probe.destroy_node()
        manual.destroy_node()
        arbiter.destroy_node()
        executor.shutdown()
        rclpy.shutdown()


def test_destroy_after_context_shutdown_does_not_publish():
    rclpy.init()
    manual = ManualControlNode(
        parameter_overrides=[
            Parameter("command_service", value="/test/shutdown/command"),
            Parameter("manual_output_topic", value="/test/shutdown/input"),
            Parameter("motion_mode_service", value="/test/shutdown/mode"),
        ]
    )
    rclpy.shutdown()

    manual.destroy_node()


def test_process_cleanup_tolerates_repeated_launch_interrupts(monkeypatch):
    calls = []

    class StubManual:

        def destroy_node(self):
            calls.append("destroy")
            raise KeyboardInterrupt

    monkeypatch.setattr(
        "navigation_agent.manual_control_node.rclpy.ok", lambda: True
    )

    def interrupted_shutdown():
        calls.append("rclpy")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "navigation_agent.manual_control_node.rclpy.shutdown",
        interrupted_shutdown,
    )

    _cleanup_manual_control(StubManual())

    assert calls == ["destroy", "rclpy"]
