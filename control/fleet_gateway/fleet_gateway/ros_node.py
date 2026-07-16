"""ROS subscriptions and command clients used by the fleet gateway."""

import math
import threading
from typing import Any, Dict

from fleet_interfaces.msg import RobotStatus
from rclpy.node import Node
from std_srvs.srv import SetBool

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


class FleetGatewayNode(Node):
    """Receive fleet status and expose safety service calls."""

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
        if len(robot_ids) != len(service_names):
            raise ValueError(
                "robot_ids and estop_services must have the same length"
            )
        self._estop_clients = {
            robot_id: self.create_client(SetBool, service_name)
            for robot_id, service_name in zip(robot_ids, service_names)
        }
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
