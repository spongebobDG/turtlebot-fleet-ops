"""Robot-local proxy that owns Nav2 goals and enforces fleet leases."""

import math
import threading
import time
from typing import Optional

from action_msgs.msg import GoalStatus
from action_msgs.srv import CancelGoal
from builtin_interfaces.msg import Duration as DurationMessage
from fleet_interfaces.action import NavigateRobot
from fleet_interfaces.msg import (
    NavigationLease,
    NavigationStatus,
    RobotStatus,
    SafetyStatus,
)
from fleet_interfaces.srv import SetInitialPose, SetMotionMode
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
import rclpy
from rclpy.action import (
    ActionClient,
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.task import Future
from std_msgs.msg import Bool

from navigation_agent.model import (
    GridMap,
    MODE_IDLE,
    MODE_NAVIGATION,
    pose_is_on_free_cell,
    pose_values_are_finite,
    quaternion_to_yaw,
    value_is_fresh,
)


TERMINAL_STATES = {
    NavigationStatus.STATE_SUCCEEDED,
    NavigationStatus.STATE_CANCELED,
    NavigationStatus.STATE_FAILED,
    NavigationStatus.STATE_LEASE_EXPIRED,
}


class NavigationAgent(Node):
    """Own a Nav2 action and stop it when local safety or fleet lease fails."""

    def __init__(self, **node_kwargs) -> None:
        super().__init__("navigation_agent", **node_kwargs)
        self._callback_group = ReentrantCallbackGroup()
        self._declare_parameters()
        self._load_parameters()
        self._validate_parameters()

        self._lock = threading.RLock()
        self._grid: Optional[GridMap] = None
        self._robot_status: Optional[RobotStatus] = None
        self._robot_status_received_at: Optional[float] = None
        self._safety_status: Optional[SafetyStatus] = None
        self._safety_status_received_at: Optional[float] = None
        self._initial_pose_sent_at: Optional[float] = None
        self._amcl_received_at: Optional[float] = None
        self._active_command_id = ""
        self._reserved_command_id = ""
        self._last_lease_received_at: Optional[float] = None
        self._nav_goal_handle = None
        self._nav_result_waiter: Optional[Future] = None
        self._nav2_unavailable_since: Optional[float] = None
        self._nav2_lifecycle_active = False
        self._nav2_lifecycle_query_in_flight = False
        self._lease_expired = False
        self._cancel_requested = False
        self._cancel_reason = ""
        self._state = NavigationStatus.STATE_UNAVAILABLE
        self._target_pose = PoseStamped()
        self._current_pose = PoseStamped()
        self._distance_remaining = -1.0
        self._navigation_time = DurationMessage()
        self._estimated_time_remaining = DurationMessage()
        self._number_of_recoveries = 0
        self._nav2_error_code = 0
        self._message = "Waiting for map, Nav2, safety, and localization"
        self._startup_motion_idle_sent = False
        self._startup_motion_idle_in_flight = False
        self._startup_cancel_sent = False
        self._startup_cancel_in_flight = False

        transient_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._status_publisher = self.create_publisher(
            NavigationStatus,
            self._status_topic,
            10,
        )
        self._authorization_publisher = self.create_publisher(
            Bool,
            self._authorization_topic,
            10,
        )
        self._initial_pose_publisher = self.create_publisher(
            PoseWithCovarianceStamped,
            self._initial_pose_topic,
            10,
        )
        self._lease_subscription = self.create_subscription(
            NavigationLease,
            self._lease_topic,
            self._on_lease,
            10,
            callback_group=self._callback_group,
        )
        self._robot_status_subscription = self.create_subscription(
            RobotStatus,
            self._robot_status_topic,
            self._on_robot_status,
            10,
            callback_group=self._callback_group,
        )
        self._safety_status_subscription = self.create_subscription(
            SafetyStatus,
            self._safety_status_topic,
            self._on_safety_status,
            10,
            callback_group=self._callback_group,
        )
        self._amcl_subscription = self.create_subscription(
            PoseWithCovarianceStamped,
            self._amcl_pose_topic,
            self._on_amcl_pose,
            10,
            callback_group=self._callback_group,
        )
        self._map_subscription = self.create_subscription(
            OccupancyGrid,
            self._map_topic,
            self._on_map,
            transient_qos,
            callback_group=self._callback_group,
        )

        self._motion_mode_client = self.create_client(
            SetMotionMode,
            self._motion_mode_service,
            callback_group=self._callback_group,
        )
        self._nav_cancel_client = self.create_client(
            CancelGoal,
            self._nav2_cancel_service,
            callback_group=self._callback_group,
        )
        self._nav2_lifecycle_client = self.create_client(
            GetState,
            self._nav2_lifecycle_service,
            callback_group=self._callback_group,
        )
        self._nav_client = ActionClient(
            self,
            NavigateToPose,
            self._nav2_action,
            callback_group=self._callback_group,
        )
        self._initial_pose_service_handle = self.create_service(
            SetInitialPose,
            self._initial_pose_service,
            self._on_set_initial_pose,
            callback_group=self._callback_group,
        )
        self._action_server = ActionServer(
            self,
            NavigateRobot,
            self._command_action,
            execute_callback=self._execute_navigation,
            goal_callback=self._on_goal,
            cancel_callback=self._on_cancel,
            callback_group=self._callback_group,
        )

        self._lease_timer = self.create_timer(
            0.1,
            self._check_lease,
            callback_group=self._callback_group,
        )
        self._authorization_timer = self.create_timer(
            1.0 / self._authorization_rate_hz,
            self._publish_authorization,
            callback_group=self._callback_group,
        )
        self._status_timer = self.create_timer(
            1.0 / self._status_rate_hz,
            self._publish_status,
            callback_group=self._callback_group,
        )
        self._startup_timer = self.create_timer(
            0.5,
            self._startup_fail_closed,
            callback_group=self._callback_group,
        )
        self._nav2_lifecycle_timer = self.create_timer(
            0.2,
            self._poll_nav2_lifecycle,
            callback_group=self._callback_group,
        )
        self.get_logger().info(
            f"Navigation agent ready: robot={self._robot_id}, "
            f"lease timeout={self._lease_timeout_sec:.1f}s"
        )

    def _declare_parameters(self) -> None:
        defaults = {
            "robot_id": "tb1",
            "command_action": "/tb1/navigation/navigate",
            "lease_topic": "/fleet/navigation_lease",
            "status_topic": "/fleet/navigation_status",
            "robot_status_topic": "/fleet/robot_status",
            "safety_status_topic": "/fleet/safety_status",
            "initial_pose_service": "/tb1/navigation/set_initial_pose",
            "motion_mode_service": "/tb1/navigation/set_motion_mode",
            "authorization_topic": "/navigation/motion_authorized",
            "nav2_action": "/navigate_to_pose",
            "nav2_cancel_service": "/navigate_to_pose/_action/cancel_goal",
            "nav2_lifecycle_service": "/bt_navigator/get_state",
            "initial_pose_topic": "/initialpose",
            "amcl_pose_topic": "/amcl_pose",
            "map_topic": "/map",
            "lease_timeout_sec": 2.0,
            "nav2_unavailable_timeout_sec": 1.0,
            "localization_timeout_sec": 2.0,
            "robot_status_timeout_sec": 3.0,
            "safety_status_timeout_sec": 1.5,
            "authorization_rate_hz": 10.0,
            "status_rate_hz": 2.0,
            "map_free_value_max": 0,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

    def _load_parameters(self) -> None:
        def text(name: str) -> str:
            return str(self.get_parameter(name).value).strip()

        self._robot_id = text("robot_id")
        self._command_action = text("command_action")
        self._lease_topic = text("lease_topic")
        self._status_topic = text("status_topic")
        self._robot_status_topic = text("robot_status_topic")
        self._safety_status_topic = text("safety_status_topic")
        self._initial_pose_service = text("initial_pose_service")
        self._motion_mode_service = text("motion_mode_service")
        self._authorization_topic = text("authorization_topic")
        self._nav2_action = text("nav2_action")
        self._nav2_cancel_service = text("nav2_cancel_service")
        self._nav2_lifecycle_service = text("nav2_lifecycle_service")
        self._initial_pose_topic = text("initial_pose_topic")
        self._amcl_pose_topic = text("amcl_pose_topic")
        self._map_topic = text("map_topic")
        self._lease_timeout_sec = float(
            self.get_parameter("lease_timeout_sec").value
        )
        self._nav2_unavailable_timeout_sec = float(
            self.get_parameter("nav2_unavailable_timeout_sec").value
        )
        self._localization_timeout_sec = float(
            self.get_parameter("localization_timeout_sec").value
        )
        self._robot_status_timeout_sec = float(
            self.get_parameter("robot_status_timeout_sec").value
        )
        self._safety_status_timeout_sec = float(
            self.get_parameter("safety_status_timeout_sec").value
        )
        self._authorization_rate_hz = float(
            self.get_parameter("authorization_rate_hz").value
        )
        self._status_rate_hz = float(
            self.get_parameter("status_rate_hz").value
        )
        self._map_free_value_max = int(
            self.get_parameter("map_free_value_max").value
        )

    def _validate_parameters(self) -> None:
        text_values = (
            self._robot_id,
            self._command_action,
            self._lease_topic,
            self._status_topic,
            self._initial_pose_service,
            self._nav2_action,
            self._nav2_lifecycle_service,
            self._map_topic,
        )
        if any(not value for value in text_values):
            raise ValueError("navigation names and robot_id must be non-empty")
        for name, value in (
            ("lease_timeout_sec", self._lease_timeout_sec),
            (
                "nav2_unavailable_timeout_sec",
                self._nav2_unavailable_timeout_sec,
            ),
            ("localization_timeout_sec", self._localization_timeout_sec),
            ("robot_status_timeout_sec", self._robot_status_timeout_sec),
            ("safety_status_timeout_sec", self._safety_status_timeout_sec),
            ("authorization_rate_hz", self._authorization_rate_hz),
            ("status_rate_hz", self._status_rate_hz),
        ):
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if not 0 <= self._map_free_value_max <= 100:
            raise ValueError("map_free_value_max must be within 0..100")

    def _on_map(self, message: OccupancyGrid) -> None:
        if message.header.frame_id != "map":
            self.get_logger().error("Rejected occupancy map outside map frame")
            return
        try:
            grid = GridMap(
                width=int(message.info.width),
                height=int(message.info.height),
                resolution=float(message.info.resolution),
                origin_x=float(message.info.origin.position.x),
                origin_y=float(message.info.origin.position.y),
                origin_yaw=quaternion_to_yaw(
                    message.info.origin.orientation.z,
                    message.info.origin.orientation.w,
                ),
                data=tuple(message.data),
            )
        except ValueError as error:
            self.get_logger().error(f"Rejected invalid occupancy map: {error}")
            return
        with self._lock:
            self._grid = grid

    def _on_amcl_pose(self, message: PoseWithCovarianceStamped) -> None:
        pose = message.pose.pose
        if message.header.frame_id != "map" or not pose_values_are_finite(
            pose.position.x,
            pose.position.y,
            pose.orientation.z,
            pose.orientation.w,
        ):
            return
        now = time.monotonic()
        with self._lock:
            if self._initial_pose_sent_at is None:
                return
            self._amcl_received_at = now
            self._current_pose.header = message.header
            self._current_pose.pose = message.pose.pose
            if self._active_command_id == "":
                self._state = NavigationStatus.STATE_READY
                self._message = "Localization ready"

    def _on_robot_status(self, message: RobotStatus) -> None:
        if message.robot_id != self._robot_id:
            return
        with self._lock:
            self._robot_status = message
            self._robot_status_received_at = time.monotonic()
            if (
                message.level == RobotStatus.LEVEL_ERROR
                and self._active_command_id
            ):
                self._request_stop("Robot status entered ERROR")

    def _on_safety_status(self, message: SafetyStatus) -> None:
        if message.robot_id != self._robot_id:
            return
        with self._lock:
            self._safety_status = message
            self._safety_status_received_at = time.monotonic()
            if self._active_command_id and (
                message.estop_active or not message.motion_armed
            ):
                reason = (
                    "Emergency stop activated"
                    if message.estop_active
                    else "Motion safety became unarmed"
                )
                self._request_stop(reason)

    def _on_lease(self, message: NavigationLease) -> None:
        if message.robot_id != self._robot_id:
            return
        with self._lock:
            if (
                self._active_command_id
                and message.command_id == self._active_command_id
            ):
                self._last_lease_received_at = time.monotonic()

    def _on_set_initial_pose(
        self,
        request: SetInitialPose.Request,
        response: SetInitialPose.Response,
    ) -> SetInitialPose.Response:
        pose = request.pose
        if pose.header.frame_id not in ("", "map"):
            response.success = False
            response.message = "Initial pose frame must be map"
            return response
        if not self._pose_is_valid_and_free(pose.pose.pose):
            response.success = False
            response.message = "Initial pose must be finite and on a free map cell"
            return response
        with self._lock:
            if self._active_command_id:
                response.success = False
                response.message = "Cannot relocalize while navigation is active"
                return response
            pose.header.frame_id = "map"
            pose.header.stamp = self.get_clock().now().to_msg()
            if not any(abs(value) > 0.0 for value in pose.pose.covariance):
                pose.pose.covariance[0] = 0.25
                pose.pose.covariance[7] = 0.25
                pose.pose.covariance[35] = 0.0685389
            self._initial_pose_publisher.publish(pose)
            self._initial_pose_sent_at = time.monotonic()
            self._amcl_received_at = None
            self._state = NavigationStatus.STATE_LOCALIZING
            self._message = "Initial pose accepted; waiting for fresh AMCL pose"
        response.success = True
        response.message = self._message
        return response

    def _on_goal(self, goal: NavigateRobot.Goal) -> GoalResponse:
        now = time.monotonic()
        with self._lock:
            if not goal.command_id.strip():
                return GoalResponse.REJECT
            if self._active_command_id or self._reserved_command_id:
                return GoalResponse.REJECT
            if goal.target_pose.header.frame_id != "map":
                return GoalResponse.REJECT
            if not self._pose_is_valid_and_free(goal.target_pose.pose):
                return GoalResponse.REJECT
            if not self._ready_for_goal(now, goal.confirm_warnings):
                return GoalResponse.REJECT
            self._lease_expired = False
            self._cancel_requested = False
            self._cancel_reason = ""
            self._reserved_command_id = goal.command_id
            return GoalResponse.ACCEPT

    def _on_cancel(self, goal_handle) -> CancelResponse:
        with self._lock:
            command_id = goal_handle.request.command_id
            if command_id not in (
                self._active_command_id,
                self._reserved_command_id,
            ):
                return CancelResponse.REJECT
            self._request_stop("Navigation canceled by operator")
            return CancelResponse.ACCEPT

    async def _execute_navigation(self, goal_handle) -> NavigateRobot.Result:
        request = goal_handle.request
        with self._lock:
            self._reserved_command_id = ""
            self._active_command_id = request.command_id
            self._target_pose = request.target_pose
            self._last_lease_received_at = time.monotonic()
            self._state = NavigationStatus.STATE_ACTIVE
            self._message = "Navigation goal accepted"
            self._distance_remaining = -1.0
            self._nav2_error_code = 0
            canceled_before_start = self._cancel_requested

        if canceled_before_start:
            result = NavigateRobot.Result()
            result.outcome = NavigateRobot.Result.OUTCOME_CANCELED
            result.message = self._cancel_reason or "Navigation canceled"
            goal_handle.canceled()
            self._finish_goal(
                NavigationStatus.STATE_CANCELED,
                result.message,
            )
            return result

        try:
            motion_mode_set = await self._set_motion_mode(MODE_NAVIGATION)
        except Exception as error:  # noqa: B902 - ROS service boundary
            return self._abort_goal(
                goal_handle,
                f"Motion arbiter request failed: {error}",
            )
        if not motion_mode_set:
            return self._abort_goal(
                goal_handle,
                "Motion arbiter is unavailable",
            )
        if not self._nav_client.wait_for_server(timeout_sec=1.0):
            return self._abort_goal(goal_handle, "Nav2 action is unavailable")

        nav_goal = NavigateToPose.Goal()
        nav_goal.pose = request.target_pose
        try:
            send_future = self._nav_client.send_goal_async(
                nav_goal,
                feedback_callback=lambda feedback: self._on_nav_feedback(
                    goal_handle,
                    feedback,
                ),
            )
            nav_goal_handle = await send_future
        except Exception as error:  # noqa: B902 - ROS action boundary
            return self._abort_goal(
                goal_handle,
                f"Nav2 goal request failed: {error}",
            )
        if not nav_goal_handle.accepted:
            return self._abort_goal(goal_handle, "Nav2 rejected the goal")
        with self._lock:
            self._nav_goal_handle = nav_goal_handle
            cancel_immediately = self._cancel_requested or self._lease_expired
        if cancel_immediately:
            nav_goal_handle.cancel_goal_async()

        nav_result_future = nav_goal_handle.get_result_async()
        nav_result_waiter = Future()
        with self._lock:
            self._nav_result_waiter = nav_result_waiter
            self._nav2_unavailable_since = None
        nav_result_future.add_done_callback(
            lambda future: self._forward_nav_result(
                future,
                nav_result_waiter,
            )
        )
        try:
            wrapped_result = await nav_result_waiter
        except Exception as error:  # noqa: B902 - ROS action boundary
            return self._abort_goal(
                goal_handle,
                f"Nav2 result failed: {error}",
            )
        nav_result = wrapped_result.result
        nav_status = wrapped_result.status
        nav_error_code = int(getattr(nav_result, "error_code", 0))
        nav_error_message = str(getattr(nav_result, "error_msg", "")).strip()
        with self._lock:
            self._nav2_error_code = nav_error_code
            lease_expired = self._lease_expired
            cancel_requested = self._cancel_requested
            cancel_reason = self._cancel_reason

        result = NavigateRobot.Result()
        result.nav2_error_code = nav_error_code
        if lease_expired:
            result.outcome = NavigateRobot.Result.OUTCOME_LEASE_EXPIRED
            result.message = "Fleet navigation lease expired"
            goal_handle.abort()
            final_state = NavigationStatus.STATE_LEASE_EXPIRED
        elif cancel_requested or nav_status == GoalStatus.STATUS_CANCELED:
            result.outcome = NavigateRobot.Result.OUTCOME_CANCELED
            result.message = cancel_reason or "Navigation canceled"
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
            else:
                goal_handle.abort()
            final_state = NavigationStatus.STATE_CANCELED
        elif nav_status == GoalStatus.STATUS_SUCCEEDED and nav_error_code == 0:
            result.outcome = NavigateRobot.Result.OUTCOME_SUCCEEDED
            result.message = "Navigation succeeded"
            goal_handle.succeed()
            final_state = NavigationStatus.STATE_SUCCEEDED
        else:
            result.outcome = NavigateRobot.Result.OUTCOME_ABORTED
            result.message = nav_error_message or (
                f"Nav2 failed with error code {nav_error_code}"
                if nav_error_code
                else f"Nav2 action failed with status {nav_status}"
            )
            goal_handle.abort()
            final_state = NavigationStatus.STATE_FAILED

        self._finish_goal(final_state, result.message)
        return result

    def _abort_goal(self, goal_handle, message: str) -> NavigateRobot.Result:
        result = NavigateRobot.Result()
        result.outcome = NavigateRobot.Result.OUTCOME_ABORTED
        result.nav2_error_code = 0
        result.message = message
        goal_handle.abort()
        self._finish_goal(NavigationStatus.STATE_FAILED, message)
        return result

    def _finish_goal(self, state: int, message: str) -> None:
        with self._lock:
            self._state = state
            self._message = message
            self._active_command_id = ""
            self._reserved_command_id = ""
            self._last_lease_received_at = None
            self._nav_goal_handle = None
            self._nav_result_waiter = None
            self._nav2_unavailable_since = None
        self._publish_authorization(force=False)
        self._set_motion_mode_nowait(MODE_IDLE)

    def _on_nav_feedback(self, goal_handle, wrapped_feedback) -> None:
        nav_feedback = wrapped_feedback.feedback
        feedback = NavigateRobot.Feedback()
        feedback.current_pose = nav_feedback.current_pose
        feedback.distance_remaining = float(nav_feedback.distance_remaining)
        feedback.navigation_time = nav_feedback.navigation_time
        feedback.estimated_time_remaining = (
            nav_feedback.estimated_time_remaining
        )
        feedback.number_of_recoveries = int(nav_feedback.number_of_recoveries)
        with self._lock:
            feedback.lease_age_sec = self._lease_age(time.monotonic())
            self._current_pose = nav_feedback.current_pose
            self._distance_remaining = feedback.distance_remaining
            self._navigation_time = feedback.navigation_time
            self._estimated_time_remaining = feedback.estimated_time_remaining
            self._number_of_recoveries = feedback.number_of_recoveries
        goal_handle.publish_feedback(feedback)

    def _check_lease(self) -> None:
        now = time.monotonic()
        with self._lock:
            if not self._active_command_id or self._lease_expired:
                return
            if not self._safety_ready(now):
                self._request_stop("Safety status became unavailable or stale")
                return
            if not self._robot_ready(now):
                self._request_stop("Robot status became unavailable or stale")
                return
            if not self._localization_ready(now):
                self._request_stop("Localization became unavailable or stale")
                return
            if not self._nav2_is_ready():
                if self._nav2_unavailable_since is None:
                    self._nav2_unavailable_since = now
                elif (
                    now - self._nav2_unavailable_since
                    >= self._nav2_unavailable_timeout_sec
                ):
                    reason = "Nav2 action server remained unavailable"
                    self._state = NavigationStatus.STATE_FAILED
                    self._request_stop(reason)
                    waiter = self._nav_result_waiter
                    if waiter is not None and not waiter.done():
                        waiter.set_exception(RuntimeError(reason))
                return
            self._nav2_unavailable_since = None
            if value_is_fresh(
                self._last_lease_received_at,
                now,
                self._lease_timeout_sec,
            ):
                return
            self._lease_expired = True
            self._state = NavigationStatus.STATE_LEASE_EXPIRED
            self._message = "Fleet navigation lease expired; canceling Nav2"
            self._request_downstream_cancel()
        self._publish_authorization(force=False)
        self._set_motion_mode_nowait(MODE_IDLE)
        self.get_logger().error(self._message)

    def _forward_nav_result(self, source: Future, waiter: Future) -> None:
        with self._lock:
            if self._nav_result_waiter is not waiter or waiter.done():
                return
            try:
                result = source.result()
            except Exception as error:  # noqa: B902 - ROS action boundary
                waiter.set_exception(error)
            else:
                waiter.set_result(result)

    def _request_stop(self, reason: str) -> None:
        self._cancel_requested = True
        self._cancel_reason = reason
        self._message = reason
        self._request_downstream_cancel()
        self._publish_authorization(force=False)
        self._set_motion_mode_nowait(MODE_IDLE)

    def _request_downstream_cancel(self) -> None:
        handle = self._nav_goal_handle
        if handle is not None:
            handle.cancel_goal_async()

    async def _set_motion_mode(self, mode: int) -> bool:
        if not self._motion_mode_client.wait_for_service(timeout_sec=1.0):
            return False
        request = SetMotionMode.Request()
        request.mode = mode
        response = await self._motion_mode_client.call_async(request)
        return response is not None and bool(response.success)

    def _set_motion_mode_nowait(self, mode: int) -> None:
        if not self._motion_mode_client.service_is_ready():
            return
        request = SetMotionMode.Request()
        request.mode = mode
        self._motion_mode_client.call_async(request)

    def _publish_authorization(self, force: Optional[bool] = None) -> None:
        now = time.monotonic()
        with self._lock:
            authorized = bool(self._active_command_id) and value_is_fresh(
                self._last_lease_received_at,
                now,
                self._lease_timeout_sec,
            )
            if self._lease_expired or self._cancel_requested:
                authorized = False
        if force is not None:
            authorized = force
        message = Bool()
        message.data = authorized
        self._authorization_publisher.publish(message)

    def _publish_status(self) -> None:
        now = time.monotonic()
        with self._lock:
            startup_safe = (
                self._startup_motion_idle_sent and self._startup_cancel_sent
            )
            nav2_ready = (
                self._grid is not None
                and self._nav2_is_ready()
                and startup_safe
            )
            localization_ready = self._localization_ready(now)
            safety_ready = self._safety_ready(now)
            robot_ready = self._robot_ready(now)
            if not self._active_command_id and self._state not in TERMINAL_STATES:
                if nav2_ready and localization_ready and safety_ready and robot_ready:
                    self._state = NavigationStatus.STATE_READY
                    self._message = "Navigation ready"
                elif nav2_ready and self._initial_pose_sent_at is not None:
                    self._state = NavigationStatus.STATE_LOCALIZING
                    self._message = "Waiting for a fresh AMCL pose"
                elif nav2_ready and safety_ready and robot_ready:
                    self._state = NavigationStatus.STATE_IDLE
                    self._message = "Set the initial pose to enable navigation"
                else:
                    self._state = NavigationStatus.STATE_UNAVAILABLE
                    self._message = (
                        "Waiting for map, Nav2, safety, and robot status"
                    )

            message = NavigationStatus()
            message.header.stamp = self.get_clock().now().to_msg()
            message.robot_id = self._robot_id
            message.state = self._state
            message.nav2_ready = nav2_ready
            message.localization_ready = localization_ready
            message.safety_ready = safety_ready
            message.active_command_id = self._active_command_id
            message.target_pose = self._target_pose
            message.current_pose = self._current_pose
            message.distance_remaining = self._distance_remaining
            message.navigation_time = self._navigation_time
            message.estimated_time_remaining = self._estimated_time_remaining
            message.number_of_recoveries = self._number_of_recoveries
            message.lease_age_sec = self._lease_age(now)
            message.nav2_error_code = self._nav2_error_code
            message.message = self._message
        self._status_publisher.publish(message)

    def _startup_fail_closed(self) -> None:
        if (
            not self._startup_motion_idle_sent
            and not self._startup_motion_idle_in_flight
            and self._motion_mode_client.service_is_ready()
        ):
            request = SetMotionMode.Request()
            request.mode = MODE_IDLE
            self._startup_motion_idle_in_flight = True
            try:
                future = self._motion_mode_client.call_async(request)
            except Exception as error:  # noqa: B902 - retry on next timer
                self._startup_motion_idle_in_flight = False
                self.get_logger().error(
                    f"Could not send startup IDLE request: {error}"
                )
            else:
                future.add_done_callback(
                    self._on_startup_motion_idle_response
                )
        if (
            not self._startup_cancel_sent
            and not self._startup_cancel_in_flight
            and self._nav_cancel_client.service_is_ready()
        ):
            self._startup_cancel_in_flight = True
            try:
                future = self._nav_cancel_client.call_async(
                    CancelGoal.Request()
                )
            except Exception as error:  # noqa: B902 - retry on next timer
                self._startup_cancel_in_flight = False
                self.get_logger().error(
                    f"Could not send startup Nav2 cancellation: {error}"
                )
            else:
                future.add_done_callback(self._on_startup_cancel_response)
        if self._startup_motion_idle_sent and self._startup_cancel_sent:
            self._startup_timer.cancel()

    def _poll_nav2_lifecycle(self) -> None:
        """Cache whether bt_navigator reached its ACTIVE lifecycle state."""
        if not self._nav2_lifecycle_client.service_is_ready():
            with self._lock:
                self._nav2_lifecycle_active = False
            return
        with self._lock:
            if self._nav2_lifecycle_query_in_flight:
                return
            self._nav2_lifecycle_query_in_flight = True
        try:
            future = self._nav2_lifecycle_client.call_async(GetState.Request())
        except Exception as error:  # noqa: B902 - retry on the next timer
            with self._lock:
                self._nav2_lifecycle_query_in_flight = False
                self._nav2_lifecycle_active = False
            self.get_logger().warning(
                f"Nav2 lifecycle query could not be sent: {error}"
            )
            return
        future.add_done_callback(self._on_nav2_lifecycle_response)

    def _on_nav2_lifecycle_response(self, future) -> None:
        try:
            response = future.result()
            active = (
                response is not None
                and int(response.current_state.id)
                == State.PRIMARY_STATE_ACTIVE
            )
        except Exception:  # noqa: B902 - readiness fails closed
            active = False
        with self._lock:
            self._nav2_lifecycle_query_in_flight = False
            self._nav2_lifecycle_active = active

    def _on_startup_motion_idle_response(self, future) -> None:
        try:
            response = future.result()
            succeeded = response is not None and bool(response.success)
        except Exception as error:  # noqa: B902 - retry on the next timer
            self.get_logger().error(f"Startup IDLE request failed: {error}")
            succeeded = False
        with self._lock:
            self._startup_motion_idle_in_flight = False
            self._startup_motion_idle_sent = succeeded
        if not succeeded:
            self.get_logger().error("Startup IDLE request was rejected; retrying")

    def _on_startup_cancel_response(self, future) -> None:
        try:
            response = future.result()
            succeeded = (
                response is not None
                and int(response.return_code)
                == CancelGoal.Response.ERROR_NONE
            )
        except Exception as error:  # noqa: B902 - retry on the next timer
            self.get_logger().error(f"Startup Nav2 cancellation failed: {error}")
            succeeded = False
        with self._lock:
            self._startup_cancel_in_flight = False
            self._startup_cancel_sent = succeeded
        if succeeded:
            self.get_logger().warning(
                "Nav2 acknowledged cancellation of goals left by a prior agent"
            )
        else:
            self.get_logger().error(
                "Startup Nav2 cancellation was not acknowledged; retrying"
            )

    def _pose_is_valid_and_free(self, pose) -> bool:
        if not pose_values_are_finite(
            pose.position.x,
            pose.position.y,
            pose.orientation.z,
            pose.orientation.w,
        ):
            return False
        if self._grid is None:
            return False
        return pose_is_on_free_cell(
            self._grid,
            pose.position.x,
            pose.position.y,
            self._map_free_value_max,
        )

    def _ready_for_goal(self, now: float, confirm_warnings: bool) -> bool:
        if not self._startup_motion_idle_sent or not self._startup_cancel_sent:
            return False
        if not self._nav2_is_ready():
            return False
        if not self._localization_ready(now) or not self._safety_ready(now):
            return False
        if not self._robot_ready(now):
            return False
        if self._robot_status is None:
            return False
        if self._robot_status.level == RobotStatus.LEVEL_ERROR:
            return False
        if (
            self._robot_status.level == RobotStatus.LEVEL_WARN
            and not confirm_warnings
        ):
            return False
        return True

    def _nav2_is_ready(self) -> bool:
        return (
            self._nav2_lifecycle_active
            and self._nav_client.server_is_ready()
        )

    def _robot_ready(self, now: float) -> bool:
        return (
            self._robot_status is not None
            and value_is_fresh(
                self._robot_status_received_at,
                now,
                self._robot_status_timeout_sec,
            )
            and self._robot_status.level != RobotStatus.LEVEL_ERROR
        )

    def _safety_ready(self, now: float) -> bool:
        return (
            self._safety_status is not None
            and value_is_fresh(
                self._safety_status_received_at,
                now,
                self._safety_status_timeout_sec,
            )
            and not self._safety_status.estop_active
            and self._safety_status.motion_armed
        )

    def _localization_ready(self, now: float) -> bool:
        return (
            self._initial_pose_sent_at is not None
            and self._amcl_received_at is not None
            and self._amcl_received_at >= self._initial_pose_sent_at
            and value_is_fresh(
                self._amcl_received_at,
                now,
                self._localization_timeout_sec,
            )
        )

    def _lease_age(self, now: float) -> float:
        if self._last_lease_received_at is None:
            return -1.0
        return max(0.0, now - self._last_lease_received_at)

    def shutdown(self) -> None:
        """Fail closed before executor shutdown."""
        self._publish_authorization(force=False)
        self._set_motion_mode_nowait(MODE_IDLE)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = NavigationAgent()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()
