"""Robot-free TB1 simulator for dashboard and task lifecycle development."""

import math
import threading
import time
from typing import List, Optional, Tuple

from fleet_interfaces.action import NavigateRobot
from fleet_interfaces.msg import (
    NavigationLease,
    NavigationStatus,
    RobotStatus,
    SafetyStatus,
)
from fleet_interfaces.srv import SetInitialPose
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.action import (
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_srvs.srv import SetBool


TB1_RAW_SCAN_YAW_OFFSET_RAD = math.pi


def navigation_duration(target_x: float) -> float:
    """Return deterministic mock duration for success and cancel exercises."""
    return 30.0 if target_x >= 1.5 else 2.0


def interpolate_pose(
    start: Tuple[float, float, float],
    target: Tuple[float, float, float],
    progress: float,
) -> Tuple[float, float, float]:
    """Linearly interpolate a planar pose for mock feedback."""
    ratio = max(0.0, min(1.0, float(progress)))
    return tuple(begin + (end - begin) * ratio for begin, end in zip(start, target))


def square_room_scan_ranges(
    pose: Tuple[float, float, float],
    sample_count: int = 360,
    wall_coordinate: float = 1.975,
    sensor_yaw_rad: float = TB1_RAW_SCAN_YAW_OFFSET_RAD,
) -> List[float]:
    """Ray-cast raw TB1 scan angles against the mock map boundary."""
    x_value, y_value, yaw = pose
    ranges = []
    increment = 2.0 * math.pi / max(1, sample_count - 1)
    for index in range(sample_count):
        angle = yaw - math.pi + index * increment + sensor_yaw_rad
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        candidates = []
        if abs(direction_x) > 1.0e-12:
            wall_x = wall_coordinate if direction_x > 0.0 else -wall_coordinate
            candidates.append((wall_x - x_value) / direction_x)
        if abs(direction_y) > 1.0e-12:
            wall_y = wall_coordinate if direction_y > 0.0 else -wall_coordinate
            candidates.append((wall_y - y_value) / direction_y)
        ranges.append(min(value for value in candidates if value > 0.0))
    return ranges


def _yaw(z_value: float, w_value: float) -> float:
    norm = math.hypot(z_value, w_value)
    if norm <= 1.0e-12:
        return 0.0
    z_value /= norm
    w_value /= norm
    return math.atan2(
        2.0 * z_value * w_value,
        1.0 - 2.0 * z_value * z_value,
    )


class MockRobotNode(Node):
    """Emulate TB1 status, safety, map and the custom leased action."""

    def __init__(self) -> None:
        """Create all mock publishers, services and the leased action server."""
        super().__init__("mock_tb1")
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("publish_rate_hz", 5.0)
        self._robot_id = str(self.get_parameter("robot_id").value)
        publish_rate = float(self.get_parameter("publish_rate_hz").value)
        if publish_rate <= 0.0:
            raise ValueError("publish_rate_hz must be positive")

        self._callback_group = ReentrantCallbackGroup()
        self._lock = threading.RLock()
        self._estop_active = True
        self._motion_armed = False
        self._localization_ready = False
        self._pose = (0.0, 0.0, 0.0)
        self._target = (0.0, 0.0, 0.0)
        self._state = NavigationStatus.STATE_IDLE
        self._active_command = ""
        self._message = "Set an initial pose after releasing mock e-stop"
        self._lease_received_at = 0.0
        self._lease_command = ""
        self._started_at = time.monotonic()
        self._navigation_started_at = 0.0
        self._distance_remaining = math.nan

        latched_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._robot_publisher = self.create_publisher(
            RobotStatus,
            "/fleet/robot_status",
            10,
        )
        self._navigation_publisher = self.create_publisher(
            NavigationStatus,
            "/fleet/navigation_status",
            10,
        )
        self._safety_publisher = self.create_publisher(
            SafetyStatus,
            "/fleet/safety_status",
            10,
        )
        self._map_publisher = self.create_publisher(
            OccupancyGrid,
            "/map",
            latched_qos,
        )
        self._scan_publisher = self.create_publisher(
            LaserScan,
            "/scan",
            10,
        )
        self.create_subscription(
            NavigationLease,
            "/fleet/navigation_lease",
            self._lease_callback,
            10,
            callback_group=self._callback_group,
        )
        self._estop_service = self.create_service(
            SetBool,
            "/safety_watchdog/set_estop",
            self._set_estop,
            callback_group=self._callback_group,
        )
        self._initial_pose_service = self.create_service(
            SetInitialPose,
            "/tb1/navigation/set_initial_pose",
            self._set_initial_pose,
            callback_group=self._callback_group,
        )
        self._action_server = ActionServer(
            self,
            NavigateRobot,
            "/tb1/navigation/navigate",
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
        self._publish_map()
        self._publish_state()
        self.get_logger().warning(
            "MOCK TB1 started; no sensor, motor or physical safety evidence"
        )

    def _set_estop(self, request, response):
        with self._lock:
            self._estop_active = bool(request.data)
            self._motion_armed = not self._estop_active
            if self._estop_active:
                self._message = "Mock emergency stop active"
            elif self._localization_ready:
                self._state = NavigationStatus.STATE_READY
                self._message = "Mock motion rearmed; previous goals stay canceled"
            else:
                self._message = "Mock e-stop released; set initial pose"
        response.success = True
        response.message = self._message
        self._publish_state()
        return response

    def _set_initial_pose(self, request, response):
        pose = request.pose.pose.pose
        with self._lock:
            self._pose = (
                float(pose.position.x),
                float(pose.position.y),
                _yaw(float(pose.orientation.z), float(pose.orientation.w)),
            )
            self._localization_ready = True
            self._state = (
                NavigationStatus.STATE_READY
                if not self._estop_active and self._motion_armed
                else NavigationStatus.STATE_LOCALIZING
            )
            self._message = "Mock initial pose applied"
        response.success = True
        response.message = self._message
        self._publish_state()
        return response

    def _accept_navigation(self, _request):
        with self._lock:
            ready = (
                not self._estop_active
                and self._motion_armed
                and self._localization_ready
                and not self._active_command
            )
        return GoalResponse.ACCEPT if ready else GoalResponse.REJECT

    def _lease_callback(self, message: NavigationLease) -> None:
        if message.robot_id != self._robot_id or not message.command_id:
            return
        with self._lock:
            self._lease_command = message.command_id
            self._lease_received_at = time.monotonic()

    def _execute_navigation(self, goal_handle):
        request = goal_handle.request
        pose = request.target_pose.pose
        destination = (
            float(pose.position.x),
            float(pose.position.y),
            _yaw(float(pose.orientation.z), float(pose.orientation.w)),
        )
        with self._lock:
            start = self._pose
            self._target = destination
            self._active_command = request.command_id
            self._state = NavigationStatus.STATE_ACTIVE
            self._message = "Mock navigation active"
            self._navigation_started_at = time.monotonic()
        self._publish_state()

        if destination[0] < 0.0:
            return self._finish(
                goal_handle,
                NavigationStatus.STATE_FAILED,
                NavigateRobot.Result.OUTCOME_ABORTED,
                "Mock planner failure for negative x",
            )

        duration = navigation_duration(destination[0])
        while rclpy.ok():
            now = time.monotonic()
            elapsed = now - self._navigation_started_at
            with self._lock:
                estop = self._estop_active
                lease_age = (
                    now - self._lease_received_at
                    if self._lease_command == request.command_id
                    else math.inf
                )
            if goal_handle.is_cancel_requested or estop:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_CANCELED,
                    NavigateRobot.Result.OUTCOME_CANCELED,
                    "Mock navigation canceled",
                )
            if elapsed > 2.0 and lease_age > 2.0:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_LEASE_EXPIRED,
                    NavigateRobot.Result.OUTCOME_LEASE_EXPIRED,
                    "Mock Gateway lease expired",
                )

            progress = min(1.0, elapsed / duration)
            current = interpolate_pose(start, destination, progress)
            distance = math.hypot(
                destination[0] - current[0],
                destination[1] - current[1],
            )
            with self._lock:
                self._pose = current
                self._distance_remaining = distance
            feedback = NavigateRobot.Feedback()
            self._fill_pose(feedback.current_pose, current)
            feedback.distance_remaining = distance
            feedback.navigation_time.sec = int(elapsed)
            feedback.estimated_time_remaining.sec = int(
                max(0.0, duration - elapsed)
            )
            feedback.lease_age_sec = float(min(lease_age, 999.0))
            goal_handle.publish_feedback(feedback)
            self._publish_state()
            if progress >= 1.0:
                return self._finish(
                    goal_handle,
                    NavigationStatus.STATE_SUCCEEDED,
                    NavigateRobot.Result.OUTCOME_SUCCEEDED,
                    "Mock navigation succeeded",
                )
            time.sleep(0.1)
        return self._finish(
            goal_handle,
            NavigationStatus.STATE_FAILED,
            NavigateRobot.Result.OUTCOME_ABORTED,
            "Mock ROS shutdown",
        )

    def _finish(self, goal_handle, state, outcome, message):
        result = NavigateRobot.Result()
        result.outcome = outcome
        result.message = message
        if state == NavigationStatus.STATE_SUCCEEDED:
            goal_handle.succeed()
        elif state == NavigationStatus.STATE_CANCELED:
            goal_handle.canceled()
        else:
            goal_handle.abort()
        with self._lock:
            self._state = state
            self._active_command = ""
            self._message = message
            self._distance_remaining = 0.0
        self._publish_state()
        return result

    def _fill_pose(self, target, pose: Tuple[float, float, float]) -> None:
        target.header.stamp = self.get_clock().now().to_msg()
        target.header.frame_id = "map"
        target.pose.position.x = pose[0]
        target.pose.position.y = pose[1]
        target.pose.orientation.z = math.sin(pose[2] / 2.0)
        target.pose.orientation.w = math.cos(pose[2] / 2.0)

    def _publish_map(self) -> None:
        message = OccupancyGrid()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "map"
        message.info.resolution = 0.05
        message.info.width = 80
        message.info.height = 80
        message.info.origin.position.x = -2.0
        message.info.origin.position.y = -2.0
        message.info.origin.orientation.w = 1.0
        width = int(message.info.width)
        height = int(message.info.height)
        message.data = [
            100
            if row in (0, height - 1) or column in (0, width - 1)
            else 0
            for row in range(height)
            for column in range(width)
        ]
        self._map_publisher.publish(message)

    def _publish_state(self) -> None:
        stamp = self.get_clock().now().to_msg()
        now = time.monotonic()
        with self._lock:
            estop = self._estop_active
            armed = self._motion_armed
            localization = self._localization_ready
            pose = self._pose
            target = self._target
            state = self._state
            command = self._active_command
            message_text = self._message
            distance = self._distance_remaining
            lease_age = (
                now - self._lease_received_at
                if command and self._lease_command == command
                else math.nan
            )

        scan_ranges = square_room_scan_ranges(pose)
        scan = LaserScan()
        scan.header.stamp = stamp
        scan.header.frame_id = "base_scan"
        scan.angle_min = -math.pi
        scan.angle_max = math.pi
        scan.angle_increment = 2.0 * math.pi / 359.0
        scan.scan_time = 0.2
        scan.range_min = 0.12
        scan.range_max = 3.5
        scan.ranges = scan_ranges
        self._scan_publisher.publish(scan)

        robot = RobotStatus()
        robot.header.stamp = stamp
        robot.robot_id = self._robot_id
        robot.hostname = "robotless-mock"
        robot.level = RobotStatus.LEVEL_WARN if estop else RobotStatus.LEVEL_OK
        robot.battery_received = True
        robot.battery_fresh = True
        robot.battery_valid = True
        robot.battery_last_received = stamp
        robot.battery_percent = 82.0
        robot.battery_voltage = 12.1
        robot.battery_present = True
        robot.odom_received = True
        robot.odom_fresh = True
        robot.odom_valid = True
        robot.odom_last_received = stamp
        robot.position_x, robot.position_y, robot.yaw = pose
        robot.scan_received = True
        robot.scan_fresh = True
        robot.scan_valid = True
        robot.scan_last_received = stamp
        robot.scan_valid_points = 360
        robot.scan_min_range = min(scan_ranges)
        robot.cpu_percent = 18.0
        robot.memory_percent = 24.0
        robot.disk_percent = 31.0
        robot.load_average_1m = 0.4
        robot.uptime_sec = int(now - self._started_at)
        robot.wifi_valid = True
        robot.wifi_interface = "mock0"
        robot.wifi_signal_dbm = -42.0
        robot.wifi_quality_percent = 92.0
        robot.fault_codes = ["MOCK_ESTOP_ACTIVE"] if estop else []
        self._robot_publisher.publish(robot)

        safety = SafetyStatus()
        safety.header.stamp = stamp
        safety.robot_id = self._robot_id
        safety.mode = (
            SafetyStatus.MODE_ESTOP if estop else SafetyStatus.MODE_ACTIVE
        )
        safety.estop_active = estop
        safety.motion_armed = armed
        self._safety_publisher.publish(safety)

        navigation = NavigationStatus()
        navigation.header.stamp = stamp
        navigation.robot_id = self._robot_id
        navigation.state = state
        navigation.nav2_ready = True
        navigation.localization_ready = localization
        navigation.safety_ready = armed and not estop
        navigation.active_command_id = command
        self._fill_pose(navigation.current_pose, pose)
        self._fill_pose(navigation.target_pose, target)
        navigation.distance_remaining = float(distance)
        navigation.lease_age_sec = float(lease_age)
        navigation.message = message_text
        self._navigation_publisher.publish(navigation)
        self._publish_map()

    def destroy_node(self):
        """Destroy the action server before its owning ROS node."""
        self._action_server.destroy()
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
