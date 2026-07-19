"""ROS subscriptions and command clients used by the fleet gateway."""

import math
import threading
import time
from typing import Any, Dict, List, Tuple
import uuid

from fleet_interfaces.action import NavigateRobot
from fleet_interfaces.msg import (
    NavigationLease,
    NavigationStatus,
    RobotStatus,
    SafetyStatus,
)
from fleet_interfaces.srv import SetInitialPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import LaserScan
from std_srvs.srv import SetBool

from fleet_gateway.map_registry import MapRegistry, map_message_to_dict
from fleet_gateway.registry import StatusRegistry
from fleet_gateway.scan_registry import ScanRegistry, scan_message_to_dict


def _stamp_to_dict(stamp: Any) -> Dict[str, int]:
    return {"sec": int(stamp.sec), "nanosec": int(stamp.nanosec)}


def _duration_to_seconds(duration: Any) -> float:
    return float(duration.sec) + float(duration.nanosec) / 1_000_000_000.0


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


def navigation_status_to_dict(message: NavigationStatus) -> Dict[str, Any]:
    """Convert robot-local navigation state to the web snapshot contract."""
    state_names = {
        NavigationStatus.STATE_UNAVAILABLE: "UNAVAILABLE",
        NavigationStatus.STATE_IDLE: "IDLE",
        NavigationStatus.STATE_LOCALIZING: "LOCALIZING",
        NavigationStatus.STATE_READY: "READY",
        NavigationStatus.STATE_ACTIVE: "ACTIVE",
        NavigationStatus.STATE_SUCCEEDED: "SUCCEEDED",
        NavigationStatus.STATE_CANCELED: "CANCELED",
        NavigationStatus.STATE_FAILED: "FAILED",
        NavigationStatus.STATE_LEASE_EXPIRED: "LEASE_EXPIRED",
    }
    return {
        "robot_id": message.robot_id,
        "state": state_names.get(int(message.state), "UNKNOWN"),
        "state_code": int(message.state),
        "nav2_ready": message.nav2_ready,
        "localization_ready": message.localization_ready,
        "safety_ready": message.safety_ready,
        "active_command_id": message.active_command_id,
        "target": _pose_to_dict(message.target_pose),
        "current": _pose_to_dict(message.current_pose),
        "distance_remaining": _nonnegative_or_none(
            message.distance_remaining
        ),
        "navigation_time_sec": _duration_to_seconds(message.navigation_time),
        "estimated_time_remaining_sec": _duration_to_seconds(
            message.estimated_time_remaining
        ),
        "number_of_recoveries": int(message.number_of_recoveries),
        "lease_age_sec": _nonnegative_or_none(message.lease_age_sec),
        "nav2_error_code": int(message.nav2_error_code),
        "message": message.message,
    }


def safety_status_to_dict(message: SafetyStatus) -> Dict[str, Any]:
    """Convert watchdog safety state to the web snapshot contract."""
    mode_names = {
        SafetyStatus.MODE_TIMEOUT: "TIMEOUT",
        SafetyStatus.MODE_ACTIVE: "ACTIVE",
        SafetyStatus.MODE_ESTOP: "ESTOP",
        SafetyStatus.MODE_WAITING_NEUTRAL: "WAITING_NEUTRAL",
    }
    return {
        "robot_id": message.robot_id,
        "mode": mode_names.get(int(message.mode), "UNKNOWN"),
        "mode_code": int(message.mode),
        "estop_active": message.estop_active,
        "motion_armed": message.motion_armed,
    }


def _pose_to_dict(message: Any) -> Dict[str, Any]:
    orientation = message.pose.orientation
    return {
        "frame_id": message.header.frame_id,
        "x": float(message.pose.position.x),
        "y": float(message.pose.position.y),
        "yaw": _quaternion_to_yaw(orientation.z, orientation.w),
    }


def _quaternion_to_yaw(z: float, w: float) -> float:
    norm = math.hypot(float(z), float(w))
    if norm <= 1.0e-12 or not math.isfinite(norm):
        return 0.0
    z_value = float(z) / norm
    w_value = float(w) / norm
    return math.atan2(2.0 * w_value * z_value, 1.0 - 2.0 * z_value**2)


def _finite_or_none(value: float) -> Any:
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_or_none(value: float) -> Any:
    number = _finite_or_none(value)
    return number if number is not None and number >= 0.0 else None


class FleetGatewayNode(Node):
    """Receive fleet status and expose safety and navigation calls."""

    def __init__(self) -> None:
        super().__init__("fleet_gateway")
        self._callback_group = ReentrantCallbackGroup()
        self._declare_parameters()

        timeout = float(self.get_parameter("online_timeout_sec").value)
        self.registry = StatusRegistry(online_timeout_sec=timeout)
        self.map_registry = MapRegistry(free_value_max=0)
        self.scan_registry = ScanRegistry(freshness_timeout_sec=1.0)
        topic = str(self.get_parameter("status_topic").value)
        self._status_subscription = self.create_subscription(
            RobotStatus,
            topic,
            self._status_callback,
            10,
            callback_group=self._callback_group,
        )
        self._navigation_subscription = self.create_subscription(
            NavigationStatus,
            str(self.get_parameter("navigation_status_topic").value),
            self._navigation_status_callback,
            10,
            callback_group=self._callback_group,
        )
        self._safety_subscription = self.create_subscription(
            SafetyStatus,
            str(self.get_parameter("safety_status_topic").value),
            self._safety_status_callback,
            10,
            callback_group=self._callback_group,
        )
        self._lease_publisher = self.create_publisher(
            NavigationLease,
            str(self.get_parameter("navigation_lease_topic").value),
            10,
        )

        robot_ids = list(self.get_parameter("robot_ids").value)
        estop_names = list(self.get_parameter("estop_services").value)
        action_names = list(self.get_parameter("navigation_actions").value)
        initial_pose_names = list(
            self.get_parameter("initial_pose_services").value
        )
        map_topics = list(self.get_parameter("map_topics").value)
        scan_topics = list(self.get_parameter("scan_topics").value)
        scan_sensor_x = list(self.get_parameter("scan_sensor_x_m").value)
        scan_sensor_y = list(self.get_parameter("scan_sensor_y_m").value)
        scan_sensor_yaw = list(
            self.get_parameter("scan_sensor_yaw_rad").value
        )
        self._validate_aligned_lists(
            robot_ids,
            estop_names,
            action_names,
            initial_pose_names,
            map_topics,
            scan_topics,
            scan_sensor_x,
            scan_sensor_y,
            scan_sensor_yaw,
        )
        self._estop_clients = {
            robot_id: self.create_client(
                SetBool,
                service_name,
                callback_group=self._callback_group,
            )
            for robot_id, service_name in zip(robot_ids, estop_names)
        }
        self._navigation_clients = {
            robot_id: ActionClient(
                self,
                NavigateRobot,
                action_name,
                callback_group=self._callback_group,
            )
            for robot_id, action_name in zip(robot_ids, action_names)
        }
        self._initial_pose_clients = {
            robot_id: self.create_client(
                SetInitialPose,
                service_name,
                callback_group=self._callback_group,
            )
            for robot_id, service_name in zip(robot_ids, initial_pose_names)
        }
        map_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._map_subscriptions = [
            self.create_subscription(
                OccupancyGrid,
                map_topic,
                lambda message, identifier=robot_id: self._map_callback(
                    identifier,
                    message,
                ),
                map_qos,
                callback_group=self._callback_group,
            )
            for robot_id, map_topic in zip(robot_ids, map_topics)
        ]
        self._scan_subscriptions = [
            self.create_subscription(
                LaserScan,
                scan_topic,
                lambda message, identifier=robot_id, x=sensor_x,
                y=sensor_y, yaw=sensor_yaw: self._scan_callback(
                    identifier,
                    message,
                    float(x),
                    float(y),
                    float(yaw),
                ),
                qos_profile_sensor_data,
                callback_group=self._callback_group,
            )
            for robot_id, scan_topic, sensor_x, sensor_y, sensor_yaw in zip(
                robot_ids,
                scan_topics,
                scan_sensor_x,
                scan_sensor_y,
                scan_sensor_yaw,
            )
        ]

        self._navigation_lock = threading.RLock()
        self._active_navigation: Dict[str, Tuple[str, Any]] = {}
        self._confirmed_navigation: Dict[str, str] = {}
        self._navigation_accepted_at: Dict[str, float] = {}
        self._pending_navigation = set()
        self._estop_engaged = {robot_id: False for robot_id in robot_ids}
        lease_interval = float(
            self.get_parameter("lease_publish_interval_sec").value
        )
        if not math.isfinite(lease_interval) or lease_interval <= 0.0:
            raise ValueError("lease_publish_interval_sec must be positive")
        self._navigation_confirmation_timeout_sec = float(
            self.get_parameter(
                "navigation_confirmation_timeout_sec"
            ).value
        )
        if (
            not math.isfinite(self._navigation_confirmation_timeout_sec)
            or self._navigation_confirmation_timeout_sec <= 0.0
        ):
            raise ValueError(
                "navigation_confirmation_timeout_sec must be positive"
            )
        self._lease_timer = self.create_timer(
            lease_interval,
            self._publish_navigation_leases,
            callback_group=self._callback_group,
        )
        self.get_logger().info(
            f"Listening for fleet status on {topic}; "
            f"online timeout={timeout:.1f}s"
        )

    def _declare_parameters(self) -> None:
        self.declare_parameter("status_topic", "/fleet/robot_status")
        self.declare_parameter(
            "navigation_status_topic",
            "/fleet/navigation_status",
        )
        self.declare_parameter("safety_status_topic", "/fleet/safety_status")
        self.declare_parameter(
            "navigation_lease_topic",
            "/fleet/navigation_lease",
        )
        self.declare_parameter("online_timeout_sec", 3.0)
        self.declare_parameter("web_host", "0.0.0.0")
        self.declare_parameter("web_port", 8000)
        self.declare_parameter("lease_publish_interval_sec", 0.5)
        self.declare_parameter("navigation_confirmation_timeout_sec", 2.0)
        self.declare_parameter("robot_ids", ["tb1"])
        self.declare_parameter(
            "estop_services",
            ["/safety_watchdog/set_estop"],
        )
        self.declare_parameter(
            "navigation_actions",
            ["/tb1/navigation/navigate"],
        )
        self.declare_parameter(
            "initial_pose_services",
            ["/tb1/navigation/set_initial_pose"],
        )
        self.declare_parameter("map_topics", ["/map"])
        self.declare_parameter("scan_topics", ["/scan"])
        self.declare_parameter("scan_sensor_x_m", [-0.032])
        self.declare_parameter("scan_sensor_y_m", [0.0])
        self.declare_parameter("scan_sensor_yaw_rad", [0.0])

    @staticmethod
    def _validate_aligned_lists(*values: List[Any]) -> None:
        if not values or len({len(value) for value in values}) != 1:
            raise ValueError("per-robot parameter lists must have equal lengths")

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

    def _navigation_status_callback(self, message: NavigationStatus) -> None:
        self.registry.update_navigation(navigation_status_to_dict(message))
        robot_id = message.robot_id
        reported_command = message.active_command_id
        with self._navigation_lock:
            active = self._active_navigation.get(robot_id)
            if active is None:
                return
            command_id = active[0]
            if reported_command == command_id:
                self._confirmed_navigation[robot_id] = command_id
                self._navigation_accepted_at.pop(robot_id, None)
            elif self._confirmed_navigation.get(robot_id) == command_id:
                self._active_navigation.pop(robot_id, None)
                self._confirmed_navigation.pop(robot_id, None)
                self._navigation_accepted_at.pop(robot_id, None)
                self.get_logger().warning(
                    f"Stopped stale lease {command_id} after {robot_id} "
                    "reported no matching active goal"
                )

    def _safety_status_callback(self, message: SafetyStatus) -> None:
        self.registry.update_safety(safety_status_to_dict(message))

    def _map_callback(self, robot_id: str, message: OccupancyGrid) -> None:
        try:
            self.map_registry.update(robot_id, map_message_to_dict(message))
        except ValueError as error:
            self.get_logger().error(f"Rejected {robot_id} map: {error}")

    def _scan_callback(
        self,
        robot_id: str,
        message: LaserScan,
        sensor_x: float,
        sensor_y: float,
        sensor_yaw: float,
    ) -> None:
        try:
            self.scan_registry.update(
                robot_id,
                scan_message_to_dict(
                    message,
                    sensor_x,
                    sensor_y,
                    sensor_yaw,
                ),
            )
        except ValueError as error:
            self.get_logger().error(f"Rejected {robot_id} scan: {error}")

    def set_estop(self, robot_id: str, engaged: bool) -> Dict[str, Any]:
        """Call a robot watchdog service from the HTTP worker thread."""
        client = self._estop_clients.get(robot_id)
        if client is None:
            if engaged:
                self._engage_gateway_estop(robot_id)
            return self._failure(
                robot_id,
                engaged,
                "No emergency-stop service configured",
            )
        if not client.wait_for_service(timeout_sec=1.0):
            if engaged:
                self._engage_gateway_estop(robot_id)
            return self._failure(
                robot_id,
                engaged,
                "Emergency-stop service is unavailable",
            )
        request = SetBool.Request()
        request.data = bool(engaged)
        try:
            response = self._future_result(client.call_async(request), 3.0)
        except Exception:  # noqa: B902 - ROS client boundary
            response = None
        if response is None:
            if engaged:
                self._engage_gateway_estop(robot_id)
            return self._failure(
                robot_id,
                engaged,
                "Emergency-stop service timed out",
            )
        result = {
            "success": bool(response.success),
            "robot_id": robot_id,
            "engaged": engaged,
            "message": response.message,
        }
        if response.success:
            with self._navigation_lock:
                self._estop_engaged[robot_id] = bool(engaged)
            if engaged:
                cancel_result = self._cancel_active_for_estop(robot_id)
                if cancel_result.get("command_id"):
                    result["message"] += "; navigation lease stopped"
        elif engaged:
            self._engage_gateway_estop(robot_id)
        return result

    def set_initial_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
    ) -> Dict[str, Any]:
        """Send one acknowledged map-frame initial pose to a robot agent."""
        client = self._initial_pose_clients.get(robot_id)
        if client is None or not client.wait_for_service(timeout_sec=1.0):
            return {
                "success": False,
                "status_code": 503,
                "message": "Initial-pose service is unavailable",
            }
        request = SetInitialPose.Request()
        request.pose.header.stamp = self.get_clock().now().to_msg()
        request.pose.header.frame_id = "map"
        request.pose.pose.pose.position.x = x
        request.pose.pose.pose.position.y = y
        request.pose.pose.pose.orientation.z = math.sin(yaw / 2.0)
        request.pose.pose.pose.orientation.w = math.cos(yaw / 2.0)
        request.pose.pose.covariance[0] = 0.25
        request.pose.pose.covariance[7] = 0.25
        request.pose.pose.covariance[35] = 0.0685389
        try:
            response = self._future_result(client.call_async(request), 3.0)
        except Exception:  # noqa: B902 - ROS client boundary
            response = None
        if response is None:
            return {
                "success": False,
                "status_code": 503,
                "message": "Initial-pose service timed out",
            }
        return {
            "success": bool(response.success),
            "status_code": 409 if not response.success else 202,
            "robot_id": robot_id,
            "message": response.message,
        }

    def start_navigation(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Submit a robot-local action and begin its fleet lease."""
        client = self._navigation_clients.get(robot_id)
        if client is None or not client.wait_for_server(timeout_sec=1.0):
            return {
                "success": False,
                "status_code": 503,
                "message": "Navigation action is unavailable",
            }
        with self._navigation_lock:
            if self._estop_engaged.get(robot_id, False):
                return {
                    "success": False,
                    "status_code": 409,
                    "message": "Emergency stop is active",
                }
            if (
                robot_id in self._active_navigation
                or robot_id in self._pending_navigation
            ):
                return {
                    "success": False,
                    "status_code": 409,
                    "message": "Cancel the active navigation goal first",
                }
            self._pending_navigation.add(robot_id)
        command_id = uuid.uuid4().hex
        goal = NavigateRobot.Goal()
        goal.command_id = command_id
        goal.target_pose.header.stamp = self.get_clock().now().to_msg()
        goal.target_pose.header.frame_id = "map"
        goal.target_pose.pose.position.x = x
        goal.target_pose.pose.position.y = y
        goal.target_pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal.target_pose.pose.orientation.w = math.cos(yaw / 2.0)
        goal.confirm_warnings = bool(confirm_warnings)
        try:
            try:
                handle = self._future_result(
                    client.send_goal_async(goal),
                    3.0,
                )
            except Exception:  # noqa: B902 - ROS action boundary
                handle = None
        finally:
            with self._navigation_lock:
                self._pending_navigation.discard(robot_id)
        if handle is None:
            return {
                "success": False,
                "status_code": 503,
                "message": "Navigation action timed out",
            }
        if not handle.accepted:
            return {
                "success": False,
                "status_code": 409,
                "message": "Robot rejected the navigation goal",
            }
        with self._navigation_lock:
            estop_engaged = self._estop_engaged.get(robot_id, False)
            if not estop_engaged:
                self._active_navigation[robot_id] = (command_id, handle)
                self._confirmed_navigation.pop(robot_id, None)
                self._navigation_accepted_at[robot_id] = time.monotonic()
        if estop_engaged:
            try:
                self._future_result(handle.cancel_goal_async(), 3.0)
            except Exception:  # noqa: B902 - fail closed without a lease
                pass
            return {
                "success": False,
                "status_code": 409,
                "message": "Emergency stop activated while goal was pending",
            }
        handle.get_result_async().add_done_callback(
            lambda future, identifier=robot_id, command=command_id: (
                self._on_navigation_result(identifier, command, future)
            )
        )
        self._publish_one_lease(robot_id, command_id)
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": command_id,
            "state": "ACCEPTED",
            "message": "Navigation goal accepted",
        }

    def cancel_navigation(
        self,
        robot_id: str,
        command_id: str,
    ) -> Dict[str, Any]:
        """Cancel exactly the active command identified by the HTTP route."""
        with self._navigation_lock:
            active = self._active_navigation.get(robot_id)
            if active is None or active[0] != command_id:
                return {
                    "success": False,
                    "status_code": 409,
                    "message": "No matching active navigation goal",
                }
            self._active_navigation.pop(robot_id, None)
            self._confirmed_navigation.pop(robot_id, None)
            self._navigation_accepted_at.pop(robot_id, None)
        try:
            response = self._future_result(
                active[1].cancel_goal_async(),
                3.0,
            )
        except Exception:  # noqa: B902 - lease is already stopped
            response = None
        if response is None:
            return {
                "success": True,
                "robot_id": robot_id,
                "command_id": command_id,
                "state": "LEASE_STOPPED",
                "message": (
                    "Navigation lease stopped; local timeout will enforce "
                    "cancellation"
                ),
            }
        if not response.goals_canceling:
            return {
                "success": True,
                "robot_id": robot_id,
                "command_id": command_id,
                "state": "LEASE_STOPPED",
                "message": (
                    "Navigation lease stopped; robot reported no canceling "
                    "goal"
                ),
            }
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": command_id,
            "state": "CANCELING",
            "message": "Navigation cancellation accepted",
        }

    def _cancel_active_for_estop(self, robot_id: str) -> Dict[str, Any]:
        with self._navigation_lock:
            active = self._active_navigation.pop(robot_id, None)
            self._confirmed_navigation.pop(robot_id, None)
            self._navigation_accepted_at.pop(robot_id, None)
        if active is None:
            return {"success": False, "message": "No active navigation"}
        try:
            response = self._future_result(
                active[1].cancel_goal_async(),
                3.0,
            )
        except Exception:  # noqa: B902 - lease is already stopped
            response = None
        accepted = response is not None and bool(response.goals_canceling)
        return {
            "success": accepted,
            "robot_id": robot_id,
            "command_id": active[0],
            "message": (
                "Navigation cancellation accepted"
                if accepted
                else "Lease stopped; cancellation will be enforced locally"
            ),
        }

    def _engage_gateway_estop(self, robot_id: str) -> None:
        """Stop navigation authority even if watchdog acknowledgement fails."""
        with self._navigation_lock:
            self._estop_engaged[robot_id] = True
        self._cancel_active_for_estop(robot_id)

    def _publish_navigation_leases(self) -> None:
        now = time.monotonic()
        unconfirmed = []
        with self._navigation_lock:
            for robot_id, accepted_at in list(
                self._navigation_accepted_at.items()
            ):
                if (
                    now - accepted_at
                    < self._navigation_confirmation_timeout_sec
                ):
                    continue
                active = self._active_navigation.pop(robot_id, None)
                self._navigation_accepted_at.pop(robot_id, None)
                self._confirmed_navigation.pop(robot_id, None)
                if active is not None:
                    unconfirmed.append((robot_id, active))
            commands = [
                (robot_id, active[0])
                for robot_id, active in self._active_navigation.items()
            ]
        for robot_id, active in unconfirmed:
            try:
                active[1].cancel_goal_async()
            except Exception:  # noqa: B902 - lease is already stopped
                pass
            self.get_logger().error(
                f"Stopped unconfirmed navigation lease {active[0]} for "
                f"{robot_id}"
            )
        for robot_id, command_id in commands:
            self._publish_one_lease(robot_id, command_id)

    def _publish_one_lease(self, robot_id: str, command_id: str) -> None:
        lease = NavigationLease()
        lease.header.stamp = self.get_clock().now().to_msg()
        lease.robot_id = robot_id
        lease.command_id = command_id
        self._lease_publisher.publish(lease)

    def _on_navigation_result(self, robot_id: str, command_id: str, future) -> None:
        try:
            future.result()
        except Exception as error:  # noqa: B902 - ROS future boundary
            self.get_logger().error(f"Navigation result failed: {error}")
        with self._navigation_lock:
            active = self._active_navigation.get(robot_id)
            if active is not None and active[0] == command_id:
                self._active_navigation.pop(robot_id, None)
                self._confirmed_navigation.pop(robot_id, None)
                self._navigation_accepted_at.pop(robot_id, None)

    @staticmethod
    def _future_result(future, timeout_sec: float):
        completed = threading.Event()
        future.add_done_callback(lambda _: completed.set())
        if not completed.wait(timeout=timeout_sec):
            return None
        try:
            return future.result()
        except Exception:  # noqa: B902 - normalized at the ROS boundary
            return None

    @staticmethod
    def _failure(robot_id: str, engaged: bool, message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "robot_id": robot_id,
            "engaged": engaged,
            "message": message,
        }
