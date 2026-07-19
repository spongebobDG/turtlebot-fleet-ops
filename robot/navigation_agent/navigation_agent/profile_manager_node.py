"""Robot-local systemd profile and map-save control services."""

from pathlib import Path
import subprocess
import threading
from typing import List, Optional, Tuple

from fleet_interfaces.msg import MappingStatus
from fleet_interfaces.srv import SaveMap, SetOperatingProfile
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


class ProfileManagerNode(Node):
    """Switch mutually exclusive mapping/navigation units fail-closed."""

    def __init__(self, **kwargs) -> None:
        super().__init__("profile_manager", **kwargs)
        self._declare_parameters()
        self._lock = threading.RLock()
        self._transitioning = False
        self._message = "Profile manager ready"
        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._publisher = self.create_publisher(
            MappingStatus,
            str(self.get_parameter("status_topic").value),
            qos,
        )
        self._profile_service = self.create_service(
            SetOperatingProfile,
            str(self.get_parameter("profile_service").value),
            self._set_profile,
        )
        self._save_service = self.create_service(
            SaveMap,
            str(self.get_parameter("save_map_service").value),
            self._save_map,
        )
        rate = float(self.get_parameter("status_rate_hz").value)
        if rate <= 0.0:
            raise ValueError("status_rate_hz must be positive")
        self._timer = self.create_timer(1.0 / rate, self._publish_status)
        self._publish_status()

    def _declare_parameters(self) -> None:
        self.declare_parameter("robot_id", "tb1")
        self.declare_parameter("status_topic", "/fleet/mapping_status")
        self.declare_parameter(
            "profile_service", "/tb1/navigation/set_operating_profile"
        )
        self.declare_parameter("save_map_service", "/tb1/navigation/save_map")
        self.declare_parameter("mapping_unit", "tb1-mapping.service")
        self.declare_parameter("navigation_unit", "tb1-navigation.service")
        self.declare_parameter(
            "map_file",
            "~/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml",
        )
        self.declare_parameter(
            "save_map_script",
            "~/turtlebot-fleet-ops/infra/navigation/save-tb1-map.sh",
        )
        self.declare_parameter("status_rate_hz", 1.0)

    def _set_profile(
        self,
        request: SetOperatingProfile.Request,
        response: SetOperatingProfile.Response,
    ) -> SetOperatingProfile.Response:
        requested = int(request.profile)
        valid = {
            SetOperatingProfile.Request.PROFILE_IDLE,
            SetOperatingProfile.Request.PROFILE_MAPPING,
            SetOperatingProfile.Request.PROFILE_NAVIGATION,
        }
        if requested not in valid:
            response.message = "Unknown operating profile"
            response.active_profile = self._active_profile()
            return response
        with self._lock:
            if self._transitioning:
                response.message = "Another profile transition is active"
                response.active_profile = self._active_profile()
                return response
            self._transitioning = True
            self._message = "Stopping prior motion profile"
        self._publish_status()
        try:
            success, message = self._apply_profile(requested)
        finally:
            with self._lock:
                self._transitioning = False
        with self._lock:
            self._message = message
        response.success = success
        response.active_profile = self._active_profile()
        response.message = message
        self._publish_status()
        return response

    def _apply_profile(self, requested: int) -> Tuple[bool, str]:
        mapping = str(self.get_parameter("mapping_unit").value)
        navigation = str(self.get_parameter("navigation_unit").value)
        stopped = self._systemctl("stop", mapping, navigation)
        if not stopped[0]:
            return stopped
        if requested == SetOperatingProfile.Request.PROFILE_IDLE:
            return True, "Operating profile is IDLE; motion will not resume"
        target = (
            mapping
            if requested == SetOperatingProfile.Request.PROFILE_MAPPING
            else navigation
        )
        started = self._systemctl("start", target)
        if not started[0]:
            self._systemctl("stop", mapping, navigation)
            return False, f"Profile start failed; left IDLE: {started[1]}"
        name = "MAPPING" if target == mapping else "NAVIGATION"
        return True, f"Operating profile changed to {name}; e-stop remains active"

    def _save_map(
        self,
        request: SaveMap.Request,
        response: SaveMap.Response,
    ) -> SaveMap.Response:
        if self._active_profile() != MappingStatus.PROFILE_MAPPING:
            response.message = "Map can only be saved in MAPPING profile"
            return response
        map_file = Path(
            str(self.get_parameter("map_file").value)
        ).expanduser()
        if map_file.exists() and not request.overwrite:
            response.message = "A saved map already exists; confirm overwrite"
            return response
        script = Path(
            str(self.get_parameter("save_map_script").value)
        ).expanduser()
        if not script.is_file():
            response.message = f"Map-save script is missing: {script}"
            return response
        completed = subprocess.run(
            ["/usr/bin/bash", str(script)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            response.message = f"Map save failed: {detail[-500:]}"
            return response
        response.success = True
        response.message = "Map and pose graph saved and validated"
        with self._lock:
            self._message = response.message
        self._publish_status()
        return response

    def _active_profile(self) -> int:
        mapping = self._is_active(str(self.get_parameter("mapping_unit").value))
        navigation = self._is_active(
            str(self.get_parameter("navigation_unit").value)
        )
        if mapping and not navigation:
            return MappingStatus.PROFILE_MAPPING
        if navigation and not mapping:
            return MappingStatus.PROFILE_NAVIGATION
        return MappingStatus.PROFILE_IDLE

    @staticmethod
    def _is_active(unit: str) -> bool:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            timeout=3,
            check=False,
        )
        return completed.returncode == 0

    @staticmethod
    def _systemctl(operation: str, *units: str) -> Tuple[bool, str]:
        completed = subprocess.run(
            ["systemctl", "--user", operation, *units],
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        detail = (completed.stderr or completed.stdout).strip()
        return completed.returncode == 0, detail or f"systemctl {operation} complete"

    def _publish_status(self) -> None:
        message = MappingStatus()
        message.header.stamp = self.get_clock().now().to_msg()
        message.robot_id = str(self.get_parameter("robot_id").value)
        message.profile = self._active_profile()
        with self._lock:
            message.transitioning = self._transitioning
            message.message = self._message
        message.map_available = Path(
            str(self.get_parameter("map_file").value)
        ).expanduser().is_file()
        self._publisher.publish(message)


def main(args: Optional[List[str]] = None) -> None:
    """Run the TB1 operating-profile manager."""
    rclpy.init(args=args)
    node = ProfileManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
