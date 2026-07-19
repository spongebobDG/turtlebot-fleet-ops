"""Single-TB1 navigation task lifecycle orchestration."""

from typing import Any, Dict, Protocol

from fleet_gateway.operations import OperationsStore


class NavigationAdapter(Protocol):
    """Minimal navigation command interface required by task management."""

    def start_navigation(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Start a robot-local leased navigation action."""

    def cancel_navigation(
        self,
        robot_id: str,
        command_id: str,
    ) -> Dict[str, Any]:
        """Cancel exactly one active navigation action."""


class NavigationTaskManager:
    """Drive durable tasks through the existing navigation adapter."""

    def __init__(
        self,
        store: OperationsStore,
        navigation: NavigationAdapter,
    ) -> None:
        """Bind durable task storage to the existing navigation adapter."""
        self.store = store
        self.navigation = navigation

    def create(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Create but do not automatically run a task."""
        return self.store.create_task(
            robot_id,
            x,
            y,
            yaw,
            confirm_warnings,
        )

    def run(self, task_id: str) -> Dict[str, Any]:
        """Start a CREATED task and persist adapter acceptance or failure."""
        task = self._task(task_id)
        if task["state"] != "CREATED":
            raise ValueError("Only a CREATED task can be run")
        active = [
            candidate
            for candidate in self.store.list_tasks(task["robot_id"], 500)
            if candidate["task_id"] != task_id
            and candidate["state"] in {"STARTING", "ACTIVE"}
        ]
        if active:
            raise ValueError("Another task is already active")
        self.store.update_task(task_id, "STARTING", "Sending navigation goal")
        target = task["target"]
        result = self.navigation.start_navigation(
            task["robot_id"],
            target["x"],
            target["y"],
            target["yaw"],
            task["confirm_warnings"],
        )
        if not result.get("success", False):
            message = result.get("message", "Navigation task was rejected")
            failed = self.store.update_task(task_id, "FAILED", message)
            failed["status_code"] = int(result.get("status_code", 503))
            return failed
        command_id = str(result.get("command_id", "")).strip()
        if not command_id:
            failed = self.store.update_task(
                task_id,
                "FAILED",
                "Navigation adapter returned no command_id",
            )
            failed["status_code"] = 503
            return failed
        active = self.store.update_task(
            task_id,
            "ACTIVE",
            result.get("message", "Navigation goal accepted"),
            command_id,
        )
        self.store.register_navigation_command(task["robot_id"], command_id)
        return active

    def cancel(self, task_id: str) -> Dict[str, Any]:
        """Cancel a task locally or stop its active robot lease."""
        task = self._task(task_id)
        if task["state"] == "CREATED":
            return self.store.update_task(
                task_id,
                "CANCELED",
                "Task canceled before execution",
            )
        if task["state"] not in {"STARTING", "ACTIVE"}:
            raise ValueError("Only a created or active task can be canceled")
        command_id = str(task.get("command_id") or "")
        if not command_id:
            return self.store.update_task(
                task_id,
                "FAILED",
                "Active task has no navigation command_id",
            )
        result = self.navigation.cancel_navigation(
            task["robot_id"],
            command_id,
        )
        if not result.get("success", False):
            failed = self.store.update_task(
                task_id,
                "FAILED",
                result.get("message", "Navigation cancellation failed"),
            )
            failed["status_code"] = int(result.get("status_code", 503))
            return failed
        return self.store.update_task(
            task_id,
            "CANCELED",
            result.get("message", "Navigation task canceled"),
            command_id,
        )

    def retry(self, task_id: str) -> Dict[str, Any]:
        """Create a new task attempt from a failed or canceled task."""
        return self.store.retry_task(task_id)

    def _task(self, task_id: str) -> Dict[str, Any]:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return task
