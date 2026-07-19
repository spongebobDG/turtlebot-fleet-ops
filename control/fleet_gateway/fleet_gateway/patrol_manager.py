"""Durable, fail-closed sequential waypoint patrol orchestration."""

import math
import queue
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from fleet_gateway.operations import OperationsStore


class PatrolNavigationAdapter(Protocol):
    """Navigation operations used by the waypoint patrol manager."""

    def start_navigation(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Start one robot-local goal."""

    def cancel_navigation(
        self,
        robot_id: str,
        command_id: str,
    ) -> Dict[str, Any]:
        """Cancel one exact goal."""


class PatrolManager:
    """Advance persisted patrols only after matching goal success."""

    def __init__(
        self,
        store: OperationsStore,
        navigation: PatrolNavigationAdapter,
        current_pose_provider: Optional[
            Callable[[str], Optional[Mapping[str, Any]]]
        ] = None,
    ) -> None:
        self.store = store
        self.navigation = navigation
        self.current_pose_provider = current_pose_provider
        self._goal_lock = threading.RLock()
        self._goal_phase: Dict[str, str] = {}
        self._expected_target: Dict[str, Dict[str, float]] = {}
        self._updates: queue.Queue = queue.Queue()
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            name="fleet-patrol-manager",
            daemon=True,
        )
        self._thread.start()

    def create(
        self,
        robot_id: str,
        waypoints,
        loops: int,
        dwell_sec: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Persist a patrol definition without starting motion."""
        return self.store.create_patrol(
            robot_id,
            waypoints,
            loops,
            dwell_sec,
            confirm_warnings,
        )

    def run(self, patrol_id: str) -> Dict[str, Any]:
        """Start the first waypoint of a CREATED patrol."""
        patrol = self._patrol(patrol_id)
        if patrol["state"] != "CREATED":
            raise ValueError("Only a CREATED patrol can be run")
        active = [
            candidate
            for candidate in self.store.list_patrols(patrol["robot_id"], 500)
            if candidate["patrol_id"] != patrol_id
            and candidate["state"] in {"STARTING", "ACTIVE"}
        ]
        if active:
            raise ValueError("Another patrol is already active")
        self.store.update_patrol(
            patrol_id,
            "STARTING",
            "Starting patrol waypoint 1",
            current_loop=0,
            current_waypoint=0,
            clear_command=True,
        )
        return self._start_current_waypoint(patrol_id)

    def cancel(self, patrol_id: str) -> Dict[str, Any]:
        """Cancel a created, waiting or active patrol without replacement."""
        patrol = self._patrol(patrol_id)
        if patrol["state"] == "CREATED":
            return self.store.update_patrol(
                patrol_id,
                "CANCELED",
                "Patrol canceled before execution",
                clear_command=True,
            )
        if patrol["state"] not in {"STARTING", "ACTIVE"}:
            raise ValueError("Only a created or active patrol can be canceled")
        command_id = str(patrol.get("command_id") or "")
        if command_id:
            result = self.navigation.cancel_navigation(
                patrol["robot_id"],
                command_id,
            )
            if not result.get("success", False):
                failed = self.store.update_patrol(
                    patrol_id,
                    "FAILED",
                    result.get("message", "Patrol cancellation failed"),
                    clear_command=True,
                )
                failed["status_code"] = int(result.get("status_code", 503))
                self._forget_goal(patrol_id)
                return failed
        canceled = self.store.update_patrol(
            patrol_id,
            "CANCELED",
            "Patrol canceled; no waypoint will resume",
            clear_command=True,
        )
        self._forget_goal(patrol_id)
        return canceled

    def stop_for_safety(self, robot_id: str, reason: str) -> int:
        """Close patrol ownership after e-stop already stopped motion."""
        active = [
            patrol
            for patrol in self.store.list_patrols(robot_id, 500)
            if patrol["state"] in {"STARTING", "ACTIVE"}
        ]
        for patrol in active:
            self.store.update_patrol(
                patrol["patrol_id"],
                "CANCELED",
                f"{reason}; no waypoint will resume",
                clear_command=True,
            )
            self._forget_goal(patrol["patrol_id"])
        return len(active)

    def observe(self, kind: str, status: Mapping[str, Any]) -> None:
        """Queue terminal navigation states outside ROS callback threads."""
        if kind != "navigation":
            return
        if str(status.get("state", "")).upper() in {
            "SUCCEEDED",
            "CANCELED",
            "FAILED",
            "LEASE_EXPIRED",
        }:
            self._updates.put(dict(status))

    def close(self) -> None:
        """Stop the background worker without changing robot state."""
        self._closed.set()
        self._updates.put(None)
        self._thread.join(timeout=2.0)

    def _worker(self) -> None:
        while not self._closed.is_set():
            status = self._updates.get()
            if status is None:
                return
            try:
                self._handle_terminal(status)
            except Exception as error:  # noqa: B902
                self._fail_active_after_worker_error(status, error)

    def _handle_terminal(self, status: Mapping[str, Any]) -> None:
        robot_id = str(status.get("robot_id", ""))
        patrol = next(
            (
                candidate
                for candidate in self.store.list_patrols(robot_id, 500)
                if candidate["state"] == "ACTIVE"
            ),
            None,
        )
        if patrol is None or not self._target_matches(status, patrol):
            return
        state = str(status.get("state", "")).upper()
        if state != "SUCCEEDED":
            self.store.update_patrol(
                patrol["patrol_id"],
                "FAILED",
                str(status.get("message") or f"Waypoint {state.lower()}"),
                clear_command=True,
            )
            self._forget_goal(patrol["patrol_id"])
            return
        with self._goal_lock:
            phase = self._goal_phase.get(patrol["patrol_id"], "waypoint")
        if phase == "translation":
            self._start_orientation(patrol["patrol_id"])
            return
        self._forget_goal(patrol["patrol_id"])
        next_waypoint = int(patrol["current_waypoint"]) + 1
        next_loop = int(patrol["current_loop"])
        if next_waypoint >= len(patrol["waypoints"]):
            next_waypoint = 0
            next_loop += 1
        if next_loop >= int(patrol["loops"]):
            self.store.update_patrol(
                patrol["patrol_id"],
                "COMPLETED",
                "All patrol loops completed",
                clear_command=True,
            )
            return
        self.store.update_patrol(
            patrol["patrol_id"],
            "STARTING",
            "Waiting for next patrol waypoint",
            current_loop=next_loop,
            current_waypoint=next_waypoint,
            clear_command=True,
        )
        deadline = time.monotonic() + float(patrol["dwell_sec"])
        while time.monotonic() < deadline and not self._closed.is_set():
            current = self._patrol(patrol["patrol_id"])
            if current["state"] != "STARTING":
                return
            self._closed.wait(min(0.1, deadline - time.monotonic()))
        current = self._patrol(patrol["patrol_id"])
        if current["state"] == "STARTING" and not self._closed.is_set():
            self._start_current_waypoint(patrol["patrol_id"])

    def _start_current_waypoint(self, patrol_id: str) -> Dict[str, Any]:
        patrol = self._patrol(patrol_id)
        point = patrol["waypoints"][int(patrol["current_waypoint"])]
        pose = self._current_pose(patrol["robot_id"])
        yaw = float(point["yaw"])
        phase = "waypoint"
        if pose is not None:
            delta_x = float(point["x"]) - float(pose["x"])
            delta_y = float(point["y"]) - float(pose["y"])
            if math.hypot(delta_x, delta_y) > 0.02:
                approach_yaw = math.atan2(delta_y, delta_x)
                if self._yaw_difference(approach_yaw, yaw) > 0.15:
                    yaw = approach_yaw
                    phase = "translation"
        return self._start_goal(patrol, point["x"], point["y"], yaw, phase)

    def _start_orientation(self, patrol_id: str) -> Dict[str, Any]:
        """Finish one waypoint yaw with an orientation-only Nav2 goal."""
        patrol = self._patrol(patrol_id)
        point = patrol["waypoints"][int(patrol["current_waypoint"])]
        pose = self._current_pose(patrol["robot_id"])
        x_value = float(point["x"])
        y_value = float(point["y"])
        if pose is not None:
            x_value = float(pose["x"])
            y_value = float(pose["y"])
        self.store.update_patrol(
            patrol_id,
            "STARTING",
            "Aligning patrol waypoint yaw",
            clear_command=True,
        )
        patrol = self._patrol(patrol_id)
        return self._start_goal(
            patrol,
            x_value,
            y_value,
            float(point["yaw"]),
            "orientation",
        )

    def _start_goal(
        self,
        patrol: Mapping[str, Any],
        x_value: float,
        y_value: float,
        yaw: float,
        phase: str,
    ) -> Dict[str, Any]:
        patrol_id = str(patrol["patrol_id"])
        expected = {
            "x": float(x_value),
            "y": float(y_value),
            "yaw": float(yaw),
        }
        with self._goal_lock:
            self._goal_phase[patrol_id] = phase
            self._expected_target[patrol_id] = expected
        result = self.navigation.start_navigation(
            patrol["robot_id"],
            expected["x"],
            expected["y"],
            expected["yaw"],
            patrol["confirm_warnings"],
        )
        if not result.get("success", False):
            failed = self.store.update_patrol(
                patrol_id,
                "FAILED",
                result.get("message", "Patrol waypoint was rejected"),
                clear_command=True,
            )
            failed["status_code"] = int(result.get("status_code", 503))
            self._forget_goal(patrol_id)
            return failed
        return self.store.update_patrol(
            patrol_id,
            "ACTIVE",
            result.get("message", "Patrol waypoint active"),
            command_id=str(result.get("command_id", "")),
        )

    def _current_pose(self, robot_id: str) -> Optional[Mapping[str, Any]]:
        if self.current_pose_provider is None:
            return None
        pose = self.current_pose_provider(robot_id)
        if not isinstance(pose, Mapping):
            return None
        try:
            values = tuple(float(pose[key]) for key in ("x", "y", "yaw"))
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in values):
            return None
        return {"x": values[0], "y": values[1], "yaw": values[2]}

    def _forget_goal(self, patrol_id: str) -> None:
        with self._goal_lock:
            self._goal_phase.pop(patrol_id, None)
            self._expected_target.pop(patrol_id, None)

    def _fail_active_after_worker_error(
        self,
        status: Mapping[str, Any],
        error: Exception,
    ) -> None:
        robot_id = str(status.get("robot_id", ""))
        for patrol in self.store.list_patrols(robot_id, 500):
            if patrol["state"] not in {"STARTING", "ACTIVE"}:
                continue
            self.store.update_patrol(
                patrol["patrol_id"],
                "FAILED",
                f"Patrol orchestration error: {type(error).__name__}",
                clear_command=True,
            )
            self._forget_goal(patrol["patrol_id"])

    def _patrol(self, patrol_id: str) -> Dict[str, Any]:
        patrol = self.store.get_patrol(patrol_id)
        if patrol is None:
            raise KeyError(patrol_id)
        return patrol

    def _target_matches(
        self,
        status: Mapping[str, Any],
        patrol: Mapping[str, Any],
    ) -> bool:
        target = status.get("target")
        if not isinstance(target, Mapping):
            return True
        patrol_id = str(patrol["patrol_id"])
        with self._goal_lock:
            point = self._expected_target.get(patrol_id)
        if point is None:
            point = patrol["waypoints"][int(patrol["current_waypoint"])]
        try:
            yaw_delta = float(target["yaw"]) - float(point["yaw"])
            return (
                abs(float(target["x"]) - float(point["x"])) <= 1.0e-4
                and abs(float(target["y"]) - float(point["y"])) <= 1.0e-4
                and abs(math.atan2(math.sin(yaw_delta), math.cos(yaw_delta)))
                <= 1.0e-4
            )
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _yaw_difference(first: float, second: float) -> float:
        delta = first - second
        return abs(math.atan2(math.sin(delta), math.cos(delta)))
