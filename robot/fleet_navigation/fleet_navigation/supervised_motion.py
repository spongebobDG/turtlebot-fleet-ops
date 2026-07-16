"""Execute one fail-closed odometry-bounded motion for mapping tests."""

import math
import time
from typing import Optional

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_srvs.srv import SetBool

from fleet_navigation.motion_guard import is_neutral
from fleet_navigation.motion_guard import RotationProgress
from fleet_navigation.motion_guard import sector_minimum
from fleet_navigation.motion_guard import TranslationProgress
from fleet_navigation.motion_guard import validate_motion_request


class SupervisedMotion(Node):
    """Own the safe input exclusively for one bounded calibration move."""

    def __init__(self, parameter_overrides=None) -> None:
        super().__init__(
            "supervised_motion",
            parameter_overrides=parameter_overrides,
        )
        self.declare_parameter("mode", "translate")
        self.declare_parameter("target_distance_m", 0.10)
        self.declare_parameter("target_angle_rad", math.pi / 2.0)
        self.declare_parameter("speed", 0.03)
        self.declare_parameter("timeout_sec", 8.0)
        self.declare_parameter("publish_rate_hz", 20.0)
        self.declare_parameter("preflight_sec", 1.5)
        self.declare_parameter("minimum_clearance_m", 0.30)
        self.declare_parameter("clearance_half_angle_rad", math.radians(15))
        self.declare_parameter("max_linear_speed", 0.05)
        self.declare_parameter("max_angular_speed", 0.30)
        self.declare_parameter("reverse_translation_limit_m", 0.02)
        self.declare_parameter("lateral_translation_limit_m", 0.05)
        self.declare_parameter("reverse_rotation_limit_rad", 0.10)
        self.declare_parameter("neutral_epsilon", 1.0e-3)
        self.declare_parameter("input_topic", "/safety/cmd_vel_in")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("scan_topic", "/scan_normalized")
        self.declare_parameter(
            "estop_service",
            "/safety_watchdog/set_estop",
        )

        self._mode = str(self.get_parameter("mode").value)
        self._target = float(
            self.get_parameter(
                "target_distance_m"
                if self._mode == "translate"
                else "target_angle_rad"
            ).value
        )
        self._speed = float(self.get_parameter("speed").value)
        self._timeout_sec = float(
            self.get_parameter("timeout_sec").value
        )
        self._publish_rate_hz = float(
            self.get_parameter("publish_rate_hz").value
        )
        self._preflight_sec = float(
            self.get_parameter("preflight_sec").value
        )
        self._minimum_clearance_m = float(
            self.get_parameter("minimum_clearance_m").value
        )
        self._clearance_half_angle = float(
            self.get_parameter("clearance_half_angle_rad").value
        )
        self._max_linear_speed = float(
            self.get_parameter("max_linear_speed").value
        )
        self._max_angular_speed = float(
            self.get_parameter("max_angular_speed").value
        )
        self._reverse_translation_limit = float(
            self.get_parameter("reverse_translation_limit_m").value
        )
        self._lateral_translation_limit = float(
            self.get_parameter("lateral_translation_limit_m").value
        )
        self._reverse_rotation_limit = float(
            self.get_parameter("reverse_rotation_limit_rad").value
        )
        self._neutral_epsilon = float(
            self.get_parameter("neutral_epsilon").value
        )
        self._input_topic = str(
            self.get_parameter("input_topic").value
        )
        self._output_topic = str(
            self.get_parameter("output_topic").value
        )
        self._odom_topic = str(self.get_parameter("odom_topic").value)
        self._scan_topic = str(self.get_parameter("scan_topic").value)
        self._estop_service = str(
            self.get_parameter("estop_service").value
        )

        validate_motion_request(
            self._mode,
            self._target,
            self._speed,
            self._timeout_sec,
            self._max_linear_speed,
            self._max_angular_speed,
        )
        if self._publish_rate_hz < 10.0:
            raise ValueError("publish_rate_hz must be at least 10")
        if self._preflight_sec < 1.0:
            raise ValueError("preflight_sec must be at least 1 second")
        if self._minimum_clearance_m <= 0.0:
            raise ValueError("minimum_clearance_m must be positive")
        if self._reverse_translation_limit <= 0.0:
            raise ValueError("reverse translation limit must be positive")
        if self._lateral_translation_limit <= 0.0:
            raise ValueError("lateral translation limit must be positive")
        if self._reverse_rotation_limit <= 0.0:
            raise ValueError("reverse rotation limit must be positive")

        self._odom: Optional[Odometry] = None
        self._scan: Optional[LaserScan] = None
        self._output: Optional[Twist] = None
        self._odom_received_at = 0.0
        self._scan_received_at = 0.0
        self._output_received_at = 0.0
        self._input_nonzero_seen = False

        self._publisher = self.create_publisher(
            Twist,
            self._input_topic,
            10,
        )
        self._input_subscription = self.create_subscription(
            Twist,
            self._input_topic,
            self._on_input,
            10,
        )
        self._output_subscription = self.create_subscription(
            Twist,
            self._output_topic,
            self._on_output,
            10,
        )
        self._odom_subscription = self.create_subscription(
            Odometry,
            self._odom_topic,
            self._on_odom,
            10,
        )
        self._scan_subscription = self.create_subscription(
            LaserScan,
            self._scan_topic,
            self._on_scan,
            qos_profile_sensor_data,
        )
        self._estop_client = self.create_client(
            SetBool,
            self._estop_service,
        )

    def _on_input(self, message: Twist) -> None:
        if not is_neutral(
            message.linear.x,
            message.angular.z,
            self._neutral_epsilon,
        ):
            self._input_nonzero_seen = True

    def _on_output(self, message: Twist) -> None:
        self._output = message
        self._output_received_at = time.monotonic()

    def _on_odom(self, message: Odometry) -> None:
        self._odom = message
        self._odom_received_at = time.monotonic()

    def _on_scan(self, message: LaserScan) -> None:
        self._scan = message
        self._scan_received_at = time.monotonic()

    def _spin_for(self, duration_sec: float) -> None:
        end = time.monotonic() + duration_sec
        while rclpy.ok() and time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.03)

    def _set_estop(self, active: bool) -> None:
        if not self._estop_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("e-stop service is unavailable")
        request = SetBool.Request()
        request.data = active
        future = self._estop_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=8.0)
        if not future.done() or future.result() is None:
            raise RuntimeError("e-stop service timed out")
        response = future.result()
        if not response.success:
            raise RuntimeError(f"e-stop rejected request: {response.message}")
        state = "active" if active else "released"
        self.get_logger().info(f"e-stop {state}: {response.message}")

    def _publish_zero(self, frame_count: int) -> None:
        zero = Twist()
        period = 1.0 / self._publish_rate_hz
        for _ in range(frame_count):
            self._publisher.publish(zero)
            self._spin_for(period)

    def _endpoint_names(self, topic: str, publishers: bool) -> set:
        endpoints = (
            self.get_publishers_info_by_topic(topic)
            if publishers
            else self.get_subscriptions_info_by_topic(topic)
        )
        return {endpoint.node_name.lstrip("/") for endpoint in endpoints}

    def _check_exclusive_graph(self) -> None:
        input_publishers = self._endpoint_names(self._input_topic, True)
        expected_input = {self.get_name()}
        if input_publishers != expected_input:
            raise RuntimeError(
                "safe input is not exclusively owned: "
                f"expected={sorted(expected_input)} "
                f"actual={sorted(input_publishers)}"
            )

        output_publishers = self._endpoint_names(self._output_topic, True)
        if output_publishers != {"safety_watchdog"}:
            raise RuntimeError(
                "unexpected final velocity publisher set: "
                f"{sorted(output_publishers)}"
            )

        output_subscribers = self._endpoint_names(self._output_topic, False)
        expected_output_subscribers = {
            self.get_name(),
            "turtlebot3_node",
        }
        if output_subscribers != expected_output_subscribers:
            raise RuntimeError(
                "unexpected final velocity subscriber set: "
                f"{sorted(output_subscribers)}"
            )

    def _wait_for_fresh_data(self) -> None:
        end = time.monotonic() + 8.0
        while rclpy.ok() and time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)
            now = time.monotonic()
            if (
                self._odom is not None
                and self._scan is not None
                and self._output is not None
                and now - self._odom_received_at < 0.5
                and now - self._scan_received_at < 0.5
                and now - self._output_received_at < 0.5
            ):
                return
        raise RuntimeError("required odom, scan, or output data is stale")

    def _require_zero_output(self) -> None:
        if self._output is None:
            raise RuntimeError("no final velocity output received")
        if not is_neutral(
            self._output.linear.x,
            self._output.angular.z,
            self._neutral_epsilon,
        ):
            raise RuntimeError("final velocity output is not neutral")

    def _preflight(self) -> None:
        self._input_nonzero_seen = False
        end = time.monotonic() + self._preflight_sec
        period = 1.0 / self._publish_rate_hz
        while rclpy.ok() and time.monotonic() < end:
            self._publisher.publish(Twist())
            self._spin_for(period)
        self._check_exclusive_graph()
        self._wait_for_fresh_data()
        self._require_zero_output()
        if self._input_nonzero_seen:
            raise RuntimeError("non-neutral safe input observed in preflight")

    def _clearance(self) -> float:
        if self._scan is None:
            raise RuntimeError("scan is unavailable")
        center = 0.0 if self._speed > 0.0 else math.pi
        clearance = sector_minimum(
            self._scan.ranges,
            self._scan.angle_min,
            self._scan.angle_increment,
            self._scan.range_min,
            self._scan.range_max,
            center,
            self._clearance_half_angle,
        )
        if clearance is None:
            raise RuntimeError("no valid scan samples in travel direction")
        return clearance

    def _make_progress_tracker(self):
        if self._odom is None:
            raise RuntimeError("odom is unavailable")
        pose = self._odom.pose.pose
        if self._mode == "translate":
            orientation = pose.orientation
            yaw = math.atan2(
                2.0
                * (
                    orientation.w * orientation.z
                    + orientation.x * orientation.y
                ),
                1.0
                - 2.0
                * (
                    orientation.y * orientation.y
                    + orientation.z * orientation.z
                ),
            )
            direction = 1 if self._speed > 0.0 else -1
            return TranslationProgress(
                pose.position.x,
                pose.position.y,
                yaw,
                direction,
            )
        orientation = pose.orientation
        yaw = math.atan2(
            2.0 * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        direction = 1 if self._speed > 0.0 else -1
        return RotationProgress(yaw, direction)

    def _progress(self, tracker) -> float:
        if self._odom is None:
            raise RuntimeError("odom became unavailable")
        pose = self._odom.pose.pose
        if self._mode == "translate":
            progress = tracker.update(pose.position.x, pose.position.y)
            if (
                tracker.reverse_distance(
                    pose.position.x,
                    pose.position.y,
                )
                > self._reverse_translation_limit
            ):
                raise RuntimeError("translation moved opposite to command")
            if (
                tracker.lateral_distance(
                    pose.position.x,
                    pose.position.y,
                )
                > self._lateral_translation_limit
            ):
                raise RuntimeError("translation exceeded lateral limit")
            return progress
        orientation = pose.orientation
        yaw = math.atan2(
            2.0 * (
                orientation.w * orientation.z
                + orientation.x * orientation.y
            ),
            1.0
            - 2.0
            * (
                orientation.y * orientation.y
                + orientation.z * orientation.z
            ),
        )
        progress = tracker.update(yaw)
        if tracker.reverse_rotation > self._reverse_rotation_limit:
            raise RuntimeError("rotation moved opposite to command")
        return progress

    def _execute(self) -> tuple:
        tracker = self._make_progress_tracker()
        command = Twist()
        if self._mode == "translate":
            command.linear.x = self._speed
        else:
            command.angular.z = self._speed

        started = time.monotonic()
        next_graph_check = started
        period = 1.0 / self._publish_rate_hz
        progress = 0.0
        while rclpy.ok():
            now = time.monotonic()
            if now - self._odom_received_at > 0.5:
                raise RuntimeError("odom became stale during motion")
            if now - self._scan_received_at > 0.5:
                raise RuntimeError("scan became stale during motion")
            if now >= next_graph_check:
                self._check_exclusive_graph()
                next_graph_check = now + 0.25
            if self._mode == "translate":
                clearance = self._clearance()
                if clearance < self._minimum_clearance_m:
                    raise RuntimeError(
                        f"clearance dropped to {clearance:.3f} m"
                    )
            progress = self._progress(tracker)
            if progress >= self._target:
                return progress, time.monotonic() - started
            if now - started >= self._timeout_sec:
                raise RuntimeError(
                    f"motion timed out at progress {progress:.4f}"
                )
            self._publisher.publish(command)
            self._spin_for(period)
        raise RuntimeError("ROS context stopped during motion")

    def fail_closed(self) -> None:
        """Best-effort emergency stop used by every failure path."""
        try:
            self._set_estop(True)
        except Exception as error:  # noqa: B902
            self.get_logger().error(f"failed to activate e-stop: {error}")
        try:
            self._publish_zero(5)
        except Exception as error:  # noqa: B902
            self.get_logger().error(f"failed to publish zero: {error}")

    def run_once(self) -> bool:
        """Run preflight, one motion, and a verified fail-closed stop."""
        try:
            self._set_estop(True)
            self._publish_zero(5)
            self._preflight()
            self._set_estop(False)
            self._input_nonzero_seen = False
            self._publish_zero(10)
            self._check_exclusive_graph()
            self._require_zero_output()
            if self._input_nonzero_seen:
                raise RuntimeError("non-neutral input observed while arming")
            progress, elapsed = self._execute()
            self._publisher.publish(Twist())
            self._spin_for(0.05)
            self._set_estop(True)
            self._publish_zero(5)
            self._require_zero_output()
            unit = "m" if self._mode == "translate" else "rad"
            self.get_logger().info(
                f"SUPERVISED_MOTION_SUCCESS mode={self._mode} "
                f"progress={progress:.4f}{unit} elapsed={elapsed:.2f}s"
            )
            return True
        except Exception as error:  # noqa: B902
            self.get_logger().error(f"SUPERVISED_MOTION_FAILED: {error}")
            self.fail_closed()
            return False


def main(args=None) -> None:
    """Run exactly one supervised motion and return a process exit code."""
    rclpy.init(args=args)
    node = SupervisedMotion()
    success = False
    try:
        success = node.run_once()
    except KeyboardInterrupt:
        node.get_logger().error("supervised motion interrupted")
        node.fail_closed()
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if not success:
        raise SystemExit(1)
