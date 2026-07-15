"""ROS 2 node that is the only software publisher to the robot velocity topic."""

import math
import time
from typing import Optional, Tuple

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_srvs.srv import SetBool

from safety_watchdog.policy import (
    SafetyLimits,
    command_is_neutral,
    command_is_fresh,
    sanitize_planar_command,
)


class SafetyWatchdog(Node):
    """Limit velocity and publish zero when commands expire or e-stop is active."""

    def __init__(self, **node_kwargs) -> None:
        super().__init__("safety_watchdog", **node_kwargs)

        self.declare_parameter("input_topic", "/safety/cmd_vel_in")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("timeout_sec", 0.5)
        self.declare_parameter("max_linear_x", 0.05)
        self.declare_parameter("max_angular_z", 0.3)
        self.declare_parameter("neutral_epsilon", 0.001)
        self.declare_parameter("publish_rate_hz", 20.0)

        input_topic = self.get_parameter("input_topic").value
        output_topic = self.get_parameter("output_topic").value
        self._timeout_sec = float(self.get_parameter("timeout_sec").value)
        publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)
        self._neutral_epsilon = float(
            self.get_parameter("neutral_epsilon").value
        )
        self._limits = SafetyLimits(
            max_linear_x=float(self.get_parameter("max_linear_x").value),
            max_angular_z=float(self.get_parameter("max_angular_z").value),
        )

        if not isinstance(input_topic, str) or not input_topic.strip():
            raise ValueError("input_topic must be a non-empty string")
        if not isinstance(output_topic, str) or not output_topic.strip():
            raise ValueError("output_topic must be a non-empty string")
        if input_topic == output_topic:
            raise ValueError("input_topic and output_topic must be different")
        if not math.isfinite(self._timeout_sec) or self._timeout_sec <= 0.0:
            raise ValueError("timeout_sec must be a positive finite value")
        if not math.isfinite(publish_rate_hz) or publish_rate_hz <= 0.0:
            raise ValueError("publish_rate_hz must be a positive finite value")
        if (
            not math.isfinite(self._neutral_epsilon)
            or self._neutral_epsilon < 0.0
        ):
            raise ValueError("neutral_epsilon must be a finite non-negative value")

        self._last_command: Tuple[float, float] = (0.0, 0.0)
        self._last_received_at: Optional[float] = None
        self._estop_active = False
        self._awaiting_neutral = False
        self._last_mode: Optional[str] = None

        self._publisher = self.create_publisher(Twist, output_topic, 10)
        self._subscription = self.create_subscription(
            Twist,
            input_topic,
            self._on_command,
            10,
        )
        self._estop_service = self.create_service(
            SetBool,
            "~/set_estop",
            self._on_set_estop,
        )
        self._timer = self.create_timer(
            1.0 / publish_rate_hz,
            self._on_timer,
        )

        self.publish_stop()
        self.get_logger().info(
            "Safety watchdog ready: "
            f"input={input_topic}, output={output_topic}, "
            f"timeout={self._timeout_sec:.3f}s, "
            f"max_linear_x={self._limits.max_linear_x:.3f}m/s, "
            f"max_angular_z={self._limits.max_angular_z:.3f}rad/s"
        )

    def _on_command(self, message: Twist) -> None:
        if self._estop_active:
            return

        if self._awaiting_neutral:
            if command_is_neutral(
                message.linear.x,
                message.angular.z,
                self._neutral_epsilon,
            ):
                self._awaiting_neutral = False
                self._last_command = (0.0, 0.0)
                self._last_received_at = time.monotonic()
                self.get_logger().info(
                    "Neutral command received; motion re-armed"
                )
            return

        command = sanitize_planar_command(
            message.linear.x,
            message.angular.z,
            self._limits,
        )

        self._last_command = command
        self._last_received_at = time.monotonic()

    def _on_timer(self) -> None:
        now = time.monotonic()

        if self._estop_active:
            mode = "ESTOP"
            command = (0.0, 0.0)
        elif self._awaiting_neutral:
            mode = "WAITING_NEUTRAL"
            command = (0.0, 0.0)
        elif command_is_fresh(
            self._last_received_at,
            now,
            self._timeout_sec,
        ):
            mode = "ACTIVE"
            command = self._last_command
        else:
            mode = "TIMEOUT"
            command = (0.0, 0.0)

        self._publish_command(*command)
        self._log_mode_transition(mode)

    def _on_set_estop(
        self,
        request: SetBool.Request,
        response: SetBool.Response,
    ) -> SetBool.Response:
        self._estop_active = bool(request.data)
        self._awaiting_neutral = not self._estop_active
        self._last_command = (0.0, 0.0)
        self._last_received_at = None
        self.publish_stop()

        response.success = True
        if self._estop_active:
            response.message = "Emergency stop activated"
        else:
            response.message = (
                "Emergency stop released; waiting for a neutral command"
            )
        return response

    def _publish_command(self, linear_x: float, angular_z: float) -> None:
        message = Twist()
        message.linear.x = linear_x
        message.angular.z = angular_z
        self._publisher.publish(message)

    def publish_stop(self, repeat: int = 1) -> None:
        """Publish one or more explicit zero-velocity commands."""
        for _ in range(max(1, repeat)):
            self._publish_command(0.0, 0.0)

    def _log_mode_transition(self, mode: str) -> None:
        if mode == self._last_mode:
            return

        if mode == "ACTIVE":
            self.get_logger().info("Fresh command received; motion enabled")
        elif mode == "ESTOP":
            self.get_logger().error("Emergency stop active; publishing zero")
        elif mode == "WAITING_NEUTRAL":
            self.get_logger().warning(
                "Emergency stop released; waiting for neutral command"
            )
        else:
            self.get_logger().warning(
                "Command timeout; publishing zero velocity"
            )
        self._last_mode = mode


def main(args=None) -> None:
    rclpy.init(args=args)
    node: Optional[SafetyWatchdog] = None

    try:
        node = SafetyWatchdog()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            if rclpy.ok():
                node.publish_stop(repeat=3)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
