"""Robot-free TB1 simulator for local dashboard development."""

import math
import threading
import time
from typing import List, Optional, Tuple

from fleet_interfaces.msg import RobotStatus
from nav2_msgs.action import NavigateToPose
import rclpy
from rclpy.action import ActionServer
from rclpy.action import CancelResponse
from rclpy.action import GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from std_msgs.msg import Bool
from std_srvs.srv import SetBool


def navigation_duration(target_x: float) -> float:
    """Return a deterministic mock duration for a target."""
    return 30.0 if target_x >= 5.0 else 2.0


def interpolate_pose(
    start: Tuple[float, float, float],
    target: Tuple[float, float, float],
    progress: float,
) -> Tuple[float, float, float]:
    """Linearly interpolate the mock planar pose."""
    ratio = max(0.0, min(1.0, float(progress)))
    return tuple(
        begin + (end - begin) * ratio
        for begin, end in zip(start, target)
    )


class MockRobotNode(Node):
    """Publish TB1 health and emulate e-stop and NavigateToPose."""

    def __init__(self) -> None:
        super().__init__("mock_tb1")
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("publish_rate_hz", 2.0)
        self.declare_parameter("battery_percent", 82.0)

        self._robot_id = str(self.get_parameter("robot_id").value)
        publish_rate = float(
            self.get_parameter("publish_rate_hz").value
        )
        if publish_rate <= 0.0:
            raise ValueError("publish_rate_hz must be positive")

        self._callback_group = ReentrantCallbackGroup()
        self._lock = threading.RLock()
        self._estop_active = True
        self._pose = (0.0, 0.0, 0.0)
        self._started_at = time.monotonic()

        estop_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._status_publisher = self.create_publisher(
            RobotStatus,
            "/fleet/robot_status",
            10,
        )
        self._estop_publisher = self.create_publisher(
            Bool,
            "/safety/estop_active",
            estop_qos,
        )
        self._estop_service = self.create_service(
            SetBool,
            "/safety_watchdog/set_estop",
            self._set_estop,
            callback_group=self._callback_group,
        )
        self._navigation_server = ActionServer(
            self,
            NavigateToPose,
            "/navigate_to_pose",
            execute_callback=self._execute_navigation,
            goal_callback=self._accept_navigation,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=self._callback_group,
        )
        self._timer = self.create_timer(
            1.0 / publish_rate,
            self._publish_state,
            callback_group=self._callback_group,
        )
        self._publish_state()
        self.get_logger().warning(
            "MOCK TB1 started: no physical robot is connected; "
            "e-stop defaults to active"
        )

    def _set_estop(self, request, response):
        with self._lock:
            self._estop_active = bool(request.data)
        self._publish_estop()
        response.success = True
        response.message = (
            "Mock emergency stop activated"
            if request.data
            else "Mock emergency stop released"
        )
        return response

    def _accept_navigation(self, _request):
        with self._lock:
            estop_active = self._estop_active
        return (
            GoalResponse.REJECT
            if estop_active
            else GoalResponse.ACCEPT
        )

    def _execute_navigation(self, goal_handle):
        target = goal_handle.request.pose.pose
        target_x = float(target.position.x)
        target_y = float(target.position.y)
        target_yaw = math.atan2(
            2.0 * target.orientation.w * target.orientation.z,
            1.0 - 2.0 * target.orientation.z**2,
        )

        if target_x < 0.0:
            goal_handle.abort()
            return NavigateToPose.Result()

        with self._lock:
            start = self._pose
        destination = (target_x, target_y, target_yaw)
        duration = navigation_duration(target_x)
        started_at = time.monotonic()

        while True:
            elapsed = time.monotonic() - started_at
            progress = min(1.0, elapsed / duration)
            with self._lock:
                estop_active = self._estop_active
                self._pose = interpolate_pose(
                    start,
                    destination,
                    progress,
                )
                current = self._pose

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                return NavigateToPose.Result()
            if estop_active:
                goal_handle.abort()
                return NavigateToPose.Result()

            feedback = NavigateToPose.Feedback()
            feedback.current_pose.header.stamp = (
                self.get_clock().now().to_msg()
            )
            feedback.current_pose.header.frame_id = "map"
            feedback.current_pose.pose.position.x = current[0]
            feedback.current_pose.pose.position.y = current[1]
            feedback.current_pose.pose.orientation.z = math.sin(
                current[2] / 2.0
            )
            feedback.current_pose.pose.orientation.w = math.cos(
                current[2] / 2.0
            )
            feedback.navigation_time.sec = int(elapsed)
            remaining = max(0.0, duration - elapsed)
            feedback.estimated_time_remaining.sec = int(remaining)
            feedback.distance_remaining = math.hypot(
                destination[0] - current[0],
                destination[1] - current[1],
            )
            goal_handle.publish_feedback(feedback)

            if progress >= 1.0:
                goal_handle.succeed()
                return NavigateToPose.Result()
            time.sleep(0.1)

    def _publish_estop(self) -> None:
        with self._lock:
            active = self._estop_active
        self._estop_publisher.publish(Bool(data=active))

    def _publish_state(self) -> None:
        now = self.get_clock().now().to_msg()
        with self._lock:
            estop_active = self._estop_active
            x, y, yaw = self._pose

        message = RobotStatus()
        message.header.stamp = now
        message.robot_id = self._robot_id
        message.hostname = "weekend-mock"
        message.level = RobotStatus.LEVEL_OK
        message.battery_received = True
        message.battery_fresh = True
        message.battery_valid = True
        message.battery_last_received = now
        message.battery_percent = float(
            self.get_parameter("battery_percent").value
        )
        message.battery_voltage = 12.1
        message.battery_present = True
        message.odom_received = True
        message.odom_fresh = True
        message.odom_valid = True
        message.odom_last_received = now
        message.position_x = x
        message.position_y = y
        message.yaw = yaw
        message.scan_received = True
        message.scan_fresh = True
        message.scan_valid = True
        message.scan_last_received = now
        message.scan_valid_points = 360
        message.scan_min_range = 0.8
        message.cpu_percent = 18.0
        message.memory_percent = 24.0
        message.disk_percent = 31.0
        message.load_average_1m = 0.4
        message.uptime_sec = int(time.monotonic() - self._started_at)
        message.wifi_valid = True
        message.wifi_interface = "mock0"
        message.wifi_signal_dbm = -42.0
        message.wifi_quality_percent = 92.0
        message.fault_codes = (
            ["MOCK_ESTOP_ACTIVE"] if estop_active else []
        )
        self._status_publisher.publish(message)
        self._publish_estop()

    def destroy_node(self):
        self._navigation_server.destroy()
        return super().destroy_node()


def main(args: Optional[List[str]] = None) -> None:
    """Run the mock robot with a multithreaded executor."""
    rclpy.init(args=args)
    node = MockRobotNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
