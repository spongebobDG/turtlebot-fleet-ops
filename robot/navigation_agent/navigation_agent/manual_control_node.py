"""Fail-closed robot-local adapter for web manual driving."""

import math
import threading
import time
from typing import List, Optional

from fleet_interfaces.srv import ManualCommand, SetMotionMode
from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node


class ManualControlNode(Node):
    """Turn leased service calls into local manual velocity commands."""

    def __init__(self, **kwargs) -> None:
        super().__init__("manual_control", **kwargs)
        self._declare_parameters()
        self._timeout = float(self.get_parameter("command_timeout_sec").value)
        self._max_linear = float(self.get_parameter("max_linear_x").value)
        self._max_angular = float(self.get_parameter("max_angular_z").value)
        rate = float(self.get_parameter("publish_rate_hz").value)
        if self._timeout <= 0.0 or rate <= 0.0:
            raise ValueError("manual control timeout and rate must be positive")
        if self._max_linear <= 0.0 or self._max_angular <= 0.0:
            raise ValueError("manual control velocity limits must be positive")
        self._lock = threading.RLock()
        self._session_id = ""
        self._last_command_at: Optional[float] = None
        self._command = Twist()
        self._mode_request_pending = False
        self._desired_mode = SetMotionMode.Request.MODE_IDLE
        self._applied_mode: Optional[int] = None
        self._next_mode_retry_at = 0.0
        self._publisher = self.create_publisher(
            Twist,
            str(self.get_parameter("manual_output_topic").value),
            10,
        )
        self._mode_client = self.create_client(
            SetMotionMode,
            str(self.get_parameter("motion_mode_service").value),
        )
        self._service = self.create_service(
            ManualCommand,
            str(self.get_parameter("command_service").value),
            self._on_command,
        )
        self._timer = self.create_timer(1.0 / rate, self._publish)

    def _declare_parameters(self) -> None:
        self.declare_parameter(
            "command_service", "/tb1/navigation/manual_command"
        )
        self.declare_parameter(
            "manual_output_topic", "/motion/manual/cmd_vel"
        )
        self.declare_parameter(
            "motion_mode_service", "/tb1/navigation/set_motion_mode"
        )
        self.declare_parameter("command_timeout_sec", 0.35)
        self.declare_parameter("publish_rate_hz", 20.0)
        self.declare_parameter("max_linear_x", 0.05)
        self.declare_parameter("max_angular_z", 0.3)

    def _on_command(
        self,
        request: ManualCommand.Request,
        response: ManualCommand.Response,
    ) -> ManualCommand.Response:
        session_id = request.session_id.strip()
        if not session_id:
            response.message = "session_id is required"
            return response
        now = time.monotonic()
        with self._lock:
            self._expire_locked(now)
            if request.stop:
                if session_id != self._session_id:
                    response.message = "No matching manual session"
                    return response
                self._stop_locked("Manual session stopped")
                response.success = True
                response.message = "Manual session stopped"
                return response
            if self._session_id and self._session_id != session_id:
                response.message = "Another manual session is active"
                return response
            values = (
                float(request.command.linear.x),
                float(request.command.linear.y),
                float(request.command.linear.z),
                float(request.command.angular.x),
                float(request.command.angular.y),
                float(request.command.angular.z),
            )
            if not all(math.isfinite(value) for value in values):
                response.message = "Manual command must be finite"
                return response
            if any(abs(value) > 1.0e-9 for value in values[1:5]):
                response.message = "Only linear.x and angular.z are supported"
                return response
            new_session = not self._session_id
            self._session_id = session_id
            self._last_command_at = now
            self._command = Twist()
            self._command.linear.x = max(
                -self._max_linear,
                min(self._max_linear, values[0]),
            )
            self._command.angular.z = max(
                -self._max_angular,
                min(self._max_angular, values[5]),
            )
            if new_session:
                self._request_mode(SetMotionMode.Request.MODE_MANUAL)
        response.success = True
        response.message = "Manual command accepted"
        return response

    def _publish(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._expire_locked(now)
            command = self._copy_twist(self._command)
            self._request_mode(self._desired_mode)
        self._publisher.publish(command)

    def _expire_locked(self, now: float) -> None:
        if (
            self._session_id
            and self._last_command_at is not None
            and now - self._last_command_at > self._timeout
        ):
            self._stop_locked("Manual command lease expired")

    def _stop_locked(self, reason: str) -> None:
        had_session = bool(self._session_id)
        self._session_id = ""
        self._last_command_at = None
        self._command = Twist()
        context_ok = self.context.ok()
        if context_ok:
            self._publisher.publish(Twist())
        if had_session:
            self.get_logger().warning(reason)
            if context_ok:
                self._request_mode(SetMotionMode.Request.MODE_IDLE)

    def _request_mode(self, mode: int) -> None:
        self._desired_mode = int(mode)
        now = time.monotonic()
        if (
            self._mode_request_pending
            or self._applied_mode == self._desired_mode
            or now < self._next_mode_retry_at
        ):
            return
        if not self._mode_client.service_is_ready():
            self._mode_client.wait_for_service(timeout_sec=0.05)
        if not self._mode_client.service_is_ready():
            self.get_logger().error("Motion-mode service is unavailable")
            self._next_mode_retry_at = now + 0.25
            return
        request = SetMotionMode.Request()
        request.mode = self._desired_mode
        requested_mode = request.mode
        self._mode_request_pending = True
        future = self._mode_client.call_async(request)

        def complete(done) -> None:
            with self._lock:
                self._mode_request_pending = False
                try:
                    result = done.result()
                except Exception as error:  # noqa: B902
                    self._next_mode_retry_at = time.monotonic() + 0.25
                    self.get_logger().error(
                        f"Motion-mode request failed: {error}"
                    )
                    return
                if result.success:
                    self._applied_mode = requested_mode
                    self._next_mode_retry_at = 0.0
                else:
                    self._applied_mode = None
                    self._next_mode_retry_at = time.monotonic() + 0.25
                    self.get_logger().error(result.message)
                if self._desired_mode != self._applied_mode:
                    self._request_mode(self._desired_mode)

        future.add_done_callback(complete)

    @staticmethod
    def _copy_twist(source: Twist) -> Twist:
        target = Twist()
        target.linear.x = source.linear.x
        target.angular.z = source.angular.z
        return target

    def destroy_node(self) -> bool:
        with self._lock:
            self._stop_locked("Manual control node stopped")
        return super().destroy_node()


def main(args: Optional[List[str]] = None) -> None:
    """Run the robot-local manual control adapter."""
    rclpy.init(args=args)
    node = ManualControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup_manual_control(node)


def _cleanup_manual_control(node) -> None:
    """Suppress launch SIGINT races while still releasing ROS entities."""
    try:
        node.destroy_node()
    except (KeyboardInterrupt, RuntimeError):
        pass
    try:
        if rclpy.ok():
            rclpy.shutdown()
    except (KeyboardInterrupt, RuntimeError):
        pass
