"""ROS subscriptions and command clients used by the fleet gateway."""

import math
import threading
from typing import Any, Dict, Mapping, Optional
from uuid import UUID as PythonUUID

from action_msgs.msg import GoalStatus
from fleet_interfaces.msg import RobotStatus
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_srvs.srv import SetBool
from unique_identifier_msgs.msg import UUID

from fleet_gateway.navigation import NavigationConflict
from fleet_gateway.navigation import NavigationRegistry
from fleet_gateway.registry import StatusRegistry


def _stamp_to_dict(stamp: Any) -> Dict[str, int]:
    return {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)}


def status_message_to_dict(message: RobotStatus) -> Dict[str, Any]:
    """Convert the ROS message to a JSON-safe, explicit API contract."""
    return {
        "stamp": _stamp_to_dict(message.header.stamp),
        "robot_id": message.robot_id,
        "hostname": message.hostname,
        "level": int(message.level),
        "battery": {
            "received": message.battery_received,
            "fresh": message.battery_fresh,
            "valid": message.battery_valid,
            "last_received": _stamp_to_dict(
                message.battery_last_received
            ),
            "age_sec": float(message.battery_age_sec),
            "percent": float(message.battery_percent),
            "voltage": float(message.battery_voltage),
            "present": message.battery_present,
        },
        "odom": {
            "received": message.odom_received,
            "fresh": message.odom_fresh,
            "valid": message.odom_valid,
            "last_received": _stamp_to_dict(message.odom_last_received),
            "age_sec": float(message.odom_age_sec),
            "x": float(message.position_x),
            "y": float(message.position_y),
            "yaw": float(message.yaw),
            "linear_velocity": float(message.linear_velocity),
            "angular_velocity": float(message.angular_velocity),
        },
        "scan": {
            "received": message.scan_received,
            "fresh": message.scan_fresh,
            "valid": message.scan_valid,
            "last_received": _stamp_to_dict(message.scan_last_received),
            "age_sec": float(message.scan_age_sec),
            "valid_points": int(message.scan_valid_points),
            "min_range": _finite_or_none(message.scan_min_range),
        },
        "system": {
            "cpu_percent": float(message.cpu_percent),
            "memory_percent": float(message.memory_percent),
            "disk_percent": float(message.disk_percent),
            "load_average_1m": float(message.load_average_1m),
            "uptime_sec": int(message.uptime_sec),
        },
        "wifi": {
            "valid": message.wifi_valid,
            "interface": message.wifi_interface,
            "signal_dbm": _finite_or_none(message.wifi_signal_dbm),
            "quality_percent": _finite_or_none(
                message.wifi_quality_percent
            ),
        },
        "fault_codes": list(message.fault_codes),
    }


def _finite_or_none(value: float) -> Any:
    number = float(value)
    return number if math.isfinite(number) else None


def navigation_goal_from_target(
    target: Mapping[str, Any],
    stamp: Any,
) -> NavigateToPose.Goal:
    """Build a map-frame Nav2 goal from the validated API target."""
    yaw = float(target["yaw"])
    goal = NavigateToPose.Goal()
    goal.pose.header.stamp = stamp
    goal.pose.header.frame_id = str(target["frame_id"])
    goal.pose.pose.position.x = float(target["x"])
    goal.pose.pose.position.y = float(target["y"])
    goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
    goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
    return goal


def navigation_feedback_to_dict(feedback: Any) -> Dict[str, Any]:
    """Convert NavigateToPose feedback into a JSON-safe contract."""
    pose = feedback.current_pose.pose
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
    navigation_time = (
        float(feedback.navigation_time.sec)
        + float(feedback.navigation_time.nanosec) / 1_000_000_000.0
    )
    remaining_time = (
        float(feedback.estimated_time_remaining.sec)
        + float(feedback.estimated_time_remaining.nanosec)
        / 1_000_000_000.0
    )
    return {
        "current_pose": {
            "frame_id": feedback.current_pose.header.frame_id,
            "x": float(pose.position.x),
            "y": float(pose.position.y),
            "yaw": yaw,
        },
        "navigation_time_sec": navigation_time,
        "estimated_time_remaining_sec": remaining_time,
        "number_of_recoveries": int(feedback.number_of_recoveries),
        "distance_remaining": float(feedback.distance_remaining),
    }


def navigation_terminal_status(
    action_status: int,
    timed_out: bool,
) -> str:
    """Map a ROS action terminal status into the web contract."""
    if action_status == GoalStatus.STATUS_SUCCEEDED:
        return "SUCCEEDED"
    if action_status == GoalStatus.STATUS_CANCELED:
        return "TIMEOUT" if timed_out else "CANCELED"
    return "ABORTED"


class FleetGatewayNode(Node):
    """Receive fleet status and expose safety and navigation commands."""

    def __init__(self) -> None:
        super().__init__("fleet_gateway")
        self.declare_parameter("status_topic", "/fleet/robot_status")
        self.declare_parameter("online_timeout_sec", 3.0)
        self.declare_parameter("web_host", "0.0.0.0")
        self.declare_parameter("web_port", 8000)
        self.declare_parameter("robot_ids", ["tb1"])
        self.declare_parameter(
            "estop_services",
            ["/safety_watchdog/set_estop"],
        )
        self.declare_parameter(
            "navigation_actions",
            ["/navigate_to_pose"],
        )
        self.declare_parameter("navigation_server_wait_sec", 1.0)
        self.declare_parameter("navigation_response_wait_sec", 3.0)

        timeout = self.get_parameter("online_timeout_sec").value
        self.registry = StatusRegistry(online_timeout_sec=float(timeout))
        topic = str(self.get_parameter("status_topic").value)
        self._subscription = self.create_subscription(
            RobotStatus,
            topic,
            self._status_callback,
            10,
        )

        robot_ids = list(self.get_parameter("robot_ids").value)
        service_names = list(self.get_parameter("estop_services").value)
        action_names = list(
            self.get_parameter("navigation_actions").value
        )
        if not (
            len(robot_ids) == len(service_names) == len(action_names)
        ):
            raise ValueError(
                "robot_ids, estop_services, and navigation_actions must "
                "have the same length"
            )
        self._estop_clients = {
            robot_id: self.create_client(SetBool, service_name)
            for robot_id, service_name in zip(robot_ids, service_names)
        }
        self.navigation = NavigationRegistry()
        self._navigation_clients = {
            robot_id: ActionClient(self, NavigateToPose, action_name)
            for robot_id, action_name in zip(robot_ids, action_names)
        }
        self._navigation_goal_handles: Dict[str, tuple[str, Any]] = {}
        self._navigation_lock = threading.RLock()
        self._navigation_timer = self.create_timer(
            0.25,
            self._expire_navigation_goals,
        )
        self.get_logger().info(
            f"Listening for fleet status on {topic}; "
            f"online timeout={timeout:.1f}s"
        )

    @property
    def web_host(self) -> str:
        """Return the configured HTTP bind host."""
        return str(self.get_parameter("web_host").value)

    @property
    def web_port(self) -> int:
        """Return the configured HTTP bind port."""
        return int(self.get_parameter("web_port").value)

    def _status_callback(self, message: RobotStatus) -> None:
        self.registry.update(status_message_to_dict(message))

    def set_estop(self, robot_id: str, engaged: bool) -> Dict[str, Any]:
        """Call a robot watchdog service from the HTTP worker thread."""
        client = self._estop_clients.get(robot_id)
        if client is None:
            return {
                "success": False,
                "robot_id": robot_id,
                "engaged": engaged,
                "message": "No emergency-stop service configured",
            }
        if not client.wait_for_service(timeout_sec=1.0):
            return {
                "success": False,
                "robot_id": robot_id,
                "engaged": engaged,
                "message": "Emergency-stop service is unavailable",
            }

        request = SetBool.Request()
        request.data = bool(engaged)
        future = client.call_async(request)
        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        if not completed.wait(timeout=3.0):
            return {
                "success": False,
                "robot_id": robot_id,
                "engaged": engaged,
                "message": "Emergency-stop service timed out",
            }
        try:
            response = future.result()
        except Exception as error:  # noqa: B902 - ROS future boundary
            self.get_logger().error(f"Emergency-stop call failed: {error}")
            return {
                "success": False,
                "robot_id": robot_id,
                "engaged": engaged,
                "message": str(error),
            }
        if response is None:
            return {
                "success": False,
                "robot_id": robot_id,
                "engaged": engaged,
                "message": "Emergency-stop service returned no response",
            }
        return {
            "success": bool(response.success),
            "robot_id": robot_id,
            "engaged": engaged,
            "message": response.message,
        }

    def navigation_snapshot(self) -> Any:
        """Return all latest navigation states for WebSocket clients."""
        return self.navigation.snapshot()

    def get_navigation(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Return one robot's latest navigation state."""
        return self.navigation.get(robot_id)

    def send_navigation_goal(
        self,
        robot_id: str,
        target: Mapping[str, Any],
        timeout_sec: float,
    ) -> Dict[str, Any]:
        """Send a Nav2 goal and wait only for accept or reject."""
        client = self._navigation_clients.get(robot_id)
        if client is None:
            return self._navigation_failure(
                robot_id,
                "not_configured",
                "No NavigateToPose action configured",
            )
        server_wait = float(
            self.get_parameter("navigation_server_wait_sec").value
        )
        if not client.wait_for_server(timeout_sec=server_wait):
            return self._navigation_failure(
                robot_id,
                "action_unavailable",
                "NavigateToPose action server is unavailable",
            )

        try:
            record = self.navigation.begin(
                robot_id,
                target,
                timeout_sec,
            )
        except NavigationConflict as error:
            return self._navigation_failure(
                robot_id,
                "active_goal",
                str(error),
                goal_id=error.goal_id,
            )

        goal_id = str(record["goal_id"])
        goal_uuid = UUID(uuid=list(PythonUUID(goal_id).bytes))
        goal = navigation_goal_from_target(
            target,
            self.get_clock().now().to_msg(),
        )
        try:
            future = client.send_goal_async(
                goal,
                feedback_callback=lambda message: self._navigation_feedback(
                    robot_id,
                    goal_id,
                    message,
                ),
                goal_uuid=goal_uuid,
            )
        except Exception as error:  # noqa: B902 - ROS action boundary
            self.navigation.finish(
                robot_id,
                goal_id,
                "REJECTED",
                str(error),
            )
            return self._navigation_failure(
                robot_id,
                "send_failed",
                str(error),
                goal_id=goal_id,
            )

        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        response_wait = float(
            self.get_parameter("navigation_response_wait_sec").value
        )
        if not completed.wait(timeout=response_wait):
            message = "NavigateToPose acceptance timed out"
            self.navigation.finish(
                robot_id,
                goal_id,
                "REJECTED",
                message,
            )
            self._engage_estop_async(robot_id)
            future.add_done_callback(
                lambda response: self._cancel_late_accepted_goal(
                    robot_id,
                    goal_id,
                    response,
                )
            )
            return self._navigation_failure(
                robot_id,
                "acceptance_timeout",
                message,
                goal_id=goal_id,
            )
        try:
            goal_handle = future.result()
        except Exception as error:  # noqa: B902 - ROS action boundary
            self.navigation.finish(
                robot_id,
                goal_id,
                "REJECTED",
                str(error),
            )
            return self._navigation_failure(
                robot_id,
                "send_failed",
                str(error),
                goal_id=goal_id,
            )
        if goal_handle is None or not goal_handle.accepted:
            message = "NavigateToPose goal was rejected"
            self.navigation.finish(
                robot_id,
                goal_id,
                "REJECTED",
                message,
            )
            return self._navigation_failure(
                robot_id,
                "goal_rejected",
                message,
                goal_id=goal_id,
            )

        with self._navigation_lock:
            self._navigation_goal_handles[robot_id] = (
                goal_id,
                goal_handle,
            )
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda result: self._navigation_result(
                robot_id,
                goal_id,
                result,
            )
        )
        if not self.navigation.mark_running(robot_id, goal_id):
            self.get_logger().error(
                f"Canceling accepted goal that is no longer pending "
                f"robot_id={robot_id} goal_id={goal_id}"
            )
            goal_handle.cancel_goal_async()
            self._engage_estop_async(robot_id)
            return self._navigation_failure(
                robot_id,
                "goal_no_longer_pending",
                (
                    "NavigateToPose goal was accepted after its local "
                    "lifecycle had already ended"
                ),
                goal_id=goal_id,
            )
        current = self.navigation.get(robot_id) or record
        return {"success": True, **current}

    def _cancel_late_accepted_goal(
        self,
        robot_id: str,
        goal_id: str,
        future: Any,
    ) -> None:
        """Cancel a goal accepted after the HTTP acceptance deadline."""
        try:
            goal_handle = future.result()
        except Exception as error:  # noqa: B902 - ROS action boundary
            self.get_logger().error(
                f"Late goal response failed robot_id={robot_id} "
                f"goal_id={goal_id}: {error}"
            )
            return
        if goal_handle is None or not goal_handle.accepted:
            return
        self.get_logger().error(
            f"Canceling late accepted goal robot_id={robot_id} "
            f"goal_id={goal_id}; e-stop remains active"
        )
        goal_handle.cancel_goal_async()

    def cancel_navigation(self, robot_id: str) -> Dict[str, Any]:
        """Request cancellation for a robot's active Nav2 goal."""
        record = self.navigation.get(robot_id)
        if record is None or record["status"] not in {
            "PENDING",
            "RUNNING",
            "CANCELING",
        }:
            return {
                "success": True,
                "robot_id": robot_id,
                "message": "No active navigation goal",
                "status": "IDLE" if record is None else record["status"],
            }
        goal_id = str(record["goal_id"])
        goal_handle = self._matching_navigation_goal_handle(
            robot_id,
            goal_id,
        )
        if goal_handle is None:
            if record["status"] == "PENDING":
                self.navigation.request_cancel(
                    robot_id,
                    goal_id,
                    "Cancellation queued until goal acceptance",
                )
                current = self.navigation.get(robot_id) or record
                return {"success": True, **current}
            if record["status"] == "CANCELING":
                return {"success": True, **record}
            return self._navigation_failure(
                robot_id,
                "goal_handle_unavailable",
                "Navigation goal acceptance is still pending",
                goal_id=goal_id,
            )

        self.navigation.request_cancel(
            robot_id,
            goal_id,
            "Navigation cancel requested",
        )
        future = goal_handle.cancel_goal_async()
        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        response_wait = float(
            self.get_parameter("navigation_response_wait_sec").value
        )
        if not completed.wait(timeout=response_wait):
            return self._navigation_failure(
                robot_id,
                "cancel_timeout",
                "NavigateToPose cancel response timed out",
                goal_id=goal_id,
            )
        try:
            response = future.result()
        except Exception as error:  # noqa: B902 - ROS action boundary
            return self._navigation_failure(
                robot_id,
                "cancel_failed",
                str(error),
                goal_id=goal_id,
            )
        if response is None or not response.goals_canceling:
            return self._navigation_failure(
                robot_id,
                "cancel_rejected",
                "NavigateToPose cancel request was rejected",
                goal_id=goal_id,
            )
        current = self.navigation.get(robot_id) or record
        return {"success": True, **current}

    def _navigation_feedback(
        self,
        robot_id: str,
        goal_id: str,
        message: Any,
    ) -> None:
        self.navigation.update_feedback(
            robot_id,
            goal_id,
            navigation_feedback_to_dict(message.feedback),
        )

    def _navigation_result(
        self,
        robot_id: str,
        goal_id: str,
        future: Any,
    ) -> None:
        current = self.navigation.get(robot_id)
        timed_out = bool(
            current is not None and current["timeout_requested"]
        )
        try:
            result = future.result()
            status = navigation_terminal_status(result.status, timed_out)
            message = f"NavigateToPose finished with status {status}"
        except Exception as error:  # noqa: B902 - ROS action boundary
            status = "ABORTED"
            message = str(error)
        self.navigation.finish(robot_id, goal_id, status, message)
        with self._navigation_lock:
            current_handle = self._navigation_goal_handles.get(robot_id)
            if current_handle is not None and current_handle[0] == goal_id:
                self._navigation_goal_handles.pop(robot_id, None)

    def _expire_navigation_goals(self) -> None:
        for record in self.navigation.claim_expired():
            robot_id = str(record["robot_id"])
            goal_id = str(record["goal_id"])
            self.get_logger().error(
                f"Navigation timeout robot_id={robot_id} "
                f"goal_id={goal_id}; engaging e-stop"
            )
            self._engage_estop_async(robot_id)
            goal_handle = self._matching_navigation_goal_handle(
                robot_id,
                goal_id,
            )
            if goal_handle is None:
                self.navigation.finish(
                    robot_id,
                    goal_id,
                    "TIMEOUT",
                    "Navigation timed out before goal acceptance",
                )
                continue
            cancel_future = goal_handle.cancel_goal_async()
            cancel_future.add_done_callback(
                lambda future, rid=robot_id, gid=goal_id: (
                    self._timeout_cancel_response(rid, gid, future)
                )
            )

    def _matching_navigation_goal_handle(
        self,
        robot_id: str,
        goal_id: str,
    ) -> Any:
        """Return only the handle owned by the requested goal."""
        with self._navigation_lock:
            entry = self._navigation_goal_handles.get(robot_id)
            if entry is None or entry[0] != goal_id:
                return None
            return entry[1]

    def _timeout_cancel_response(
        self,
        robot_id: str,
        goal_id: str,
        future: Any,
    ) -> None:
        try:
            response = future.result()
            accepted = bool(
                response is not None and response.goals_canceling
            )
        except Exception as error:  # noqa: B902 - ROS action boundary
            accepted = False
            self.get_logger().error(
                f"Timeout cancel failed robot_id={robot_id} "
                f"goal_id={goal_id}: {error}"
            )
        if not accepted:
            self.get_logger().error(
                f"Timeout cancel rejected robot_id={robot_id} "
                f"goal_id={goal_id}; e-stop remains required"
            )

    def _engage_estop_async(self, robot_id: str) -> None:
        client = self._estop_clients.get(robot_id)
        if client is None or not client.service_is_ready():
            self.get_logger().error(
                f"Cannot engage timeout e-stop robot_id={robot_id}: "
                "service unavailable"
            )
            return
        request = SetBool.Request()
        request.data = True
        client.call_async(request)

    @staticmethod
    def _navigation_failure(
        robot_id: str,
        code: str,
        message: str,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False,
            "robot_id": robot_id,
            "code": code,
            "message": message,
        }
        if goal_id is not None:
            result["goal_id"] = goal_id
        return result
