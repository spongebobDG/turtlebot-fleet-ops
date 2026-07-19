#!/usr/bin/env python3
"""Serve a ROS-free seeded dashboard for local visual inspection."""

import os
from pathlib import Path
import sys
import tempfile

import uvicorn


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "control" / "fleet_gateway"))

from fleet_gateway.api import create_app  # noqa: E402
from fleet_gateway.map_registry import MapRegistry  # noqa: E402
from fleet_gateway.operations import OperationsStore  # noqa: E402
from fleet_gateway.registry import StatusRegistry  # noqa: E402
from fleet_gateway.task_manager import NavigationTaskManager  # noqa: E402


class PreviewController:
    """Accept dashboard commands without ROS or physical motion."""

    def set_initial_pose(self, robot_id, x, y, yaw):
        """Return a deterministic preview acknowledgement."""
        return {
            "success": True,
            "robot_id": robot_id,
            "message": "Preview accepted",
        }

    def start_navigation(self, robot_id, x, y, yaw, confirm_warnings):
        """Return an accepted preview command."""
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": "preview-command",
            "message": "Preview navigation accepted",
        }

    def cancel_navigation(self, robot_id, command_id):
        """Return a deterministic preview cancellation."""
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": command_id,
            "message": "Preview navigation canceled",
        }

    def set_estop(self, robot_id, engaged):
        """Return a deterministic preview safety acknowledgement."""
        return {
            "success": True,
            "robot_id": robot_id,
            "engaged": engaged,
            "message": "Preview e-stop updated",
        }


def build_app():
    """Create a seeded ROS-free version of the production dashboard."""
    # A preview has no ROS heartbeat publisher. Keep the seeded snapshot fresh
    # long enough for an unhurried browser review without weakening production
    # timeout behavior.
    registry = StatusRegistry(online_timeout_sec=3600.0)
    registry.update(
        {
            "robot_id": "tb1",
            "hostname": "current-pc-preview",
            "level": 1,
            "battery": {"percent": 82.0, "voltage": 12.1},
            "odom": {"x": 0.1, "y": -0.1, "yaw": 0.25},
            "scan": {"min_range": 0.8, "valid_points": 360},
            "system": {"cpu_percent": 18.0, "memory_percent": 24.0},
            "wifi": {"signal_dbm": -42.0},
            "fault_codes": ["PREVIEW_LOW_BATTERY"],
        }
    )
    registry.update_navigation(
        {
            "robot_id": "tb1",
            "state": "READY",
            "nav2_ready": True,
            "localization_ready": True,
            "safety_ready": True,
            "active_command_id": "",
            "current": {"frame_id": "map", "x": 0.1, "y": -0.1, "yaw": 0.25},
            "target": {"frame_id": "", "x": 0.0, "y": 0.0, "yaw": 0.0},
            "message": "ROS-free visual preview",
        }
    )
    registry.update_safety(
        {
            "robot_id": "tb1",
            "mode": "ACTIVE",
            "estop_active": False,
            "motion_armed": True,
        }
    )
    maps = MapRegistry()
    width = 80
    height = 60
    data = [0] * (width * height)
    for x_value in range(width):
        data[x_value] = 100
        data[(height - 1) * width + x_value] = 100
    for y_value in range(height):
        data[y_value * width] = 100
        data[y_value * width + width - 1] = 100
    maps.update(
        "tb1",
        {
            "frame_id": "map",
            "width": width,
            "height": height,
            "resolution": 0.05,
            "origin": {"x": -2.0, "y": -1.5, "yaw": 0.0},
            "data": data,
        },
    )

    configured_database = os.environ.get("FLEET_OPERATIONS_DB")
    database_path = Path(
        configured_database
        or str(Path(tempfile.gettempdir()) / "tb1-web-preview.sqlite3")
    )
    reset_default = "0" if configured_database else "1"
    if os.environ.get("PREVIEW_RESET", reset_default) == "1":
        database_path.unlink(missing_ok=True)
    store = OperationsStore(database_path)
    store.sync_faults(
        {
            "robot_id": "tb1",
            "level": 1,
            "fault_codes": ["PREVIEW_LOW_BATTERY"],
        }
    )
    task = store.create_task("tb1", 0.5, 0.25, 0.0, True)
    store.update_task(task["task_id"], "SUCCEEDED", "Preview task succeeded")
    controller = PreviewController()
    return create_app(
        registry,
        estop_controller=controller,
        navigation_controller=controller,
        map_registry=maps,
        operations_store=store,
        task_manager=NavigationTaskManager(store, controller),
        static_dir=REPOSITORY_ROOT / "control" / "fleet_gateway" / "web",
    )


def main() -> None:
    """Run the preview on a loopback-only development port."""
    port = int(os.environ.get("WEB_PORT", "18080"))
    uvicorn.run(build_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
