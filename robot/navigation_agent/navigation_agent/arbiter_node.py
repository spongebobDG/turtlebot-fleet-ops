"""Select one motion source before the final safety watchdog."""

import math
import time
from typing import Optional

from fleet_interfaces.srv import SetMotionMode
from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool

from navigation_agent.model import (
    MODE_IDLE,
    MODE_MANUAL,
    MODE_NAVIGATION,
    ZERO_COMMAND,
    choose_command,
)


class MotionArbiter(Node):
    """Gate manual and Nav2 commands with an explicit operating mode."""

    def __init__(self, **node_kwargs) -> None:
        super().__init__("motion_arbiter", **node_kwargs)
        self.declare_parameter("manual_input_topic", "/motion/manual/cmd_vel")
        self.declare_parameter(
            "navigation_input_topic",
            "/motion/navigation/cmd_vel",
        )
        self.declare_parameter("output_topic", "/safety/cmd_vel_in")
        self.declare_parameter(
            "authorization_topic",
            "/navigation/motion_authorized",
        )
        self.declare_parameter(
            "mode_service",
            "/tb1/navigation/set_motion_mode",
        )
        self.declare_parameter("default_mode", MODE_IDLE)
        self.declare_parameter("input_timeout_sec", 0.5)
        self.declare_parameter("authorization_timeout_sec", 0.5)
        self.declare_parameter("publish_rate_hz", 20.0)

        self._mode = int(self.get_parameter("default_mode").value)
        self._input_timeout_sec = float(
            self.get_parameter("input_timeout_sec").value
        )
        self._authorization_timeout_sec = float(
            self.get_parameter("authorization_timeout_sec").value
        )
        publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)
        self._validate_parameters(publish_rate_hz)

        self._manual_command = ZERO_COMMAND
        self._manual_received_at: Optional[float] = None
        self._navigation_command = ZERO_COMMAND
        self._navigation_received_at: Optional[float] = None
        self._authorization_received_at: Optional[float] = None

        self._publisher = self.create_publisher(
            Twist,
            str(self.get_parameter("output_topic").value),
            10,
        )
        self._manual_subscription = self.create_subscription(
            Twist,
            str(self.get_parameter("manual_input_topic").value),
            self._on_manual_command,
            10,
        )
        self._navigation_subscription = self.create_subscription(
            Twist,
            str(self.get_parameter("navigation_input_topic").value),
            self._on_navigation_command,
            10,
        )
        self._authorization_subscription = self.create_subscription(
            Bool,
            str(self.get_parameter("authorization_topic").value),
            self._on_authorization,
            10,
        )
        self._mode_service = self.create_service(
            SetMotionMode,
            str(self.get_parameter("mode_service").value),
            self._on_set_mode,
        )
        self._timer = self.create_timer(
            1.0 / publish_rate_hz,
            self._on_timer,
        )
        self._publish(*ZERO_COMMAND)
        self.get_logger().info(
            f"Motion arbiter ready in mode={self._mode}; "
            "all unselected or stale sources produce zero"
        )

    def _validate_parameters(self, publish_rate_hz: float) -> None:
        if self._mode not in (MODE_IDLE, MODE_MANUAL, MODE_NAVIGATION):
            raise ValueError("default_mode must be IDLE, MANUAL, or NAVIGATION")
        for name, value in (
            ("input_timeout_sec", self._input_timeout_sec),
            ("authorization_timeout_sec", self._authorization_timeout_sec),
            ("publish_rate_hz", publish_rate_hz),
        ):
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be positive and finite")

    def _on_manual_command(self, message: Twist) -> None:
        self._manual_command = (message.linear.x, message.angular.z)
        self._manual_received_at = time.monotonic()

    def _on_navigation_command(self, message: Twist) -> None:
        self._navigation_command = (message.linear.x, message.angular.z)
        self._navigation_received_at = time.monotonic()

    def _on_authorization(self, message: Bool) -> None:
        self._authorization_received_at = (
            time.monotonic() if message.data else None
        )

    def _on_set_mode(
        self,
        request: SetMotionMode.Request,
        response: SetMotionMode.Response,
    ) -> SetMotionMode.Response:
        mode = int(request.mode)
        if mode not in (MODE_IDLE, MODE_MANUAL, MODE_NAVIGATION):
            response.success = False
            response.message = "Unknown motion mode"
            return response
        self._mode = mode
        self._manual_command = ZERO_COMMAND
        self._manual_received_at = None
        self._navigation_command = ZERO_COMMAND
        self._navigation_received_at = None
        self._authorization_received_at = None
        self._publish(*ZERO_COMMAND)
        response.success = True
        response.message = f"Motion mode set to {mode}"
        self.get_logger().info(response.message)
        return response

    def _on_timer(self) -> None:
        command = choose_command(
            mode=self._mode,
            now=time.monotonic(),
            input_timeout_sec=self._input_timeout_sec,
            authorization_timeout_sec=self._authorization_timeout_sec,
            manual_command=self._manual_command,
            manual_received_at=self._manual_received_at,
            navigation_command=self._navigation_command,
            navigation_received_at=self._navigation_received_at,
            authorization_received_at=self._authorization_received_at,
        )
        self._publish(*command)

    def _publish(self, linear_x: float, angular_z: float) -> None:
        message = Twist()
        message.linear.x = linear_x
        message.angular.z = angular_z
        self._publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MotionArbiter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._publish(*ZERO_COMMAND)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
