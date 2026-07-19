"""FastAPI application for fleet status and safety commands."""

import asyncio
from contextlib import suppress
import math
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from fleet_gateway.registry import StatusRegistry
from fleet_gateway.map_registry import MapRegistry
from fleet_gateway.log_mlops import status_from_path
from fleet_gateway.operations import OperationsStore
from fleet_gateway.task_manager import NavigationTaskManager


class EStopController(Protocol):
    """Interface implemented by the ROS emergency-stop adapter."""

    def set_estop(self, robot_id: str, engaged: bool) -> Dict[str, Any]:
        """Set emergency-stop state and return an operation result."""


class NavigationController(Protocol):
    """ROS adapter used by the asynchronous navigation HTTP routes."""

    def set_initial_pose(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
    ) -> Dict[str, Any]:
        """Set a robot's map-frame initial pose."""

    def start_navigation(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
    ) -> Dict[str, Any]:
        """Start one leased navigation action."""

    def cancel_navigation(
        self,
        robot_id: str,
        command_id: str,
    ) -> Dict[str, Any]:
        """Cancel one matching navigation action."""


class EStopRequest(BaseModel):
    """Emergency-stop HTTP request body."""

    engaged: bool


class PoseRequest(BaseModel):
    """Planar map-frame pose supplied by the dashboard."""

    x: float
    y: float
    yaw: float


class NavigationGoalRequest(PoseRequest):
    """Navigation goal plus explicit warning acknowledgement."""

    confirm_warnings: bool = False


def create_app(
    registry: StatusRegistry,
    estop_controller: Optional[EStopController] = None,
    navigation_controller: Optional[NavigationController] = None,
    map_registry: Optional[MapRegistry] = None,
    operations_store: Optional[OperationsStore] = None,
    task_manager: Optional[NavigationTaskManager] = None,
    log_mlops_status_path: Optional[Path] = None,
    static_dir: Optional[Path] = None,
    websocket_interval_sec: float = 0.5,
) -> FastAPI:
    """Create a web application around a shared status registry."""
    app = FastAPI(
        title="TurtleBot Fleet Ops",
        version="0.1.0",
        description="ROS 2 fleet status and safety command gateway.",
    )

    async def monitor_connectivity() -> None:
        """Persist heartbeat timeout and recovery transitions without a UI client."""
        interval = max(0.1, min(float(websocket_interval_sec), 1.0))
        while True:
            for robot in registry.snapshot():
                operations_store.sync_connectivity(robot)
            await asyncio.sleep(interval)

    if operations_store is not None:
        @app.on_event("startup")
        async def start_connectivity_monitor() -> None:
            app.state.connectivity_monitor = asyncio.create_task(
                monitor_connectivity()
            )

        @app.on_event("shutdown")
        async def stop_connectivity_monitor() -> None:
            task = getattr(app.state, "connectivity_monitor", None)
            if task is None:
                return
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        robots = registry.snapshot()
        return {
            "status": "ok",
            "known_robots": len(robots),
            "online_robots": sum(robot["online"] for robot in robots),
        }

    @app.get("/api/robots")
    def list_robots() -> Dict[str, Any]:
        return {"robots": registry.snapshot()}

    @app.get("/api/mlops/ros2-logs")
    def ros2_log_mlops_status() -> Dict[str, Any]:
        return status_from_path(log_mlops_status_path)

    @app.get("/api/events")
    def list_events(
        robot_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        return {"events": store.list_events(robot_id, limit)}

    @app.get("/api/robots/{robot_id}/faults")
    def list_faults(
        robot_id: str,
        include_cleared: bool = False,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        store = _operations_or_503(operations_store)
        return {
            "faults": store.list_faults(robot_id, include_cleared),
        }

    @app.get("/api/tasks")
    def list_tasks(
        robot_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        return {"tasks": store.list_tasks(robot_id, limit)}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        return _task_or_404(store, task_id)

    @app.get("/api/robots/{robot_id}")
    def get_robot(robot_id: str) -> Dict[str, Any]:
        robot = registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        return robot

    @app.get("/api/robots/{robot_id}/map")
    def get_robot_map(robot_id: str) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        if map_registry is None:
            raise HTTPException(status_code=503, detail="Map registry unavailable")
        snapshot = map_registry.get(robot_id)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="Map is unavailable")
        return snapshot

    @app.put(
        "/api/robots/{robot_id}/localization/initial-pose",
        status_code=202,
    )
    async def set_initial_pose(
        robot_id: str,
        request: PoseRequest,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _validate_pose_request(request)
        _require_free_map_pose(map_registry, robot_id, request.x, request.y)
        _require_online_and_no_error(robot)
        _require_no_active_goal(robot)
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        result = await run_in_threadpool(
            navigation_controller.set_initial_pose,
            robot_id,
            request.x,
            request.y,
            request.yaw,
        )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "LOCALIZATION",
                "INITIAL_POSE_REQUESTED",
                accepted.get("message", "Initial pose accepted"),
                details={"x": request.x, "y": request.y, "yaw": request.yaw},
            )
        return accepted

    @app.post(
        "/api/robots/{robot_id}/navigation/goals",
        status_code=202,
    )
    async def start_navigation(
        robot_id: str,
        request: NavigationGoalRequest,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _validate_pose_request(request)
        _require_free_map_pose(map_registry, robot_id, request.x, request.y)
        _require_goal_ready(robot, request.confirm_warnings)
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        result = await run_in_threadpool(
            navigation_controller.start_navigation,
            robot_id,
            request.x,
            request.y,
            request.yaw,
            request.confirm_warnings,
        )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "NAVIGATION",
                "GOAL_ACCEPTED",
                accepted.get("message", "Navigation goal accepted"),
                command_id=accepted.get("command_id"),
                details={"x": request.x, "y": request.y, "yaw": request.yaw},
            )
        return accepted

    @app.delete(
        "/api/robots/{robot_id}/navigation/goals/{command_id}",
        status_code=202,
    )
    async def cancel_navigation(
        robot_id: str,
        command_id: str,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        if not command_id.strip():
            raise HTTPException(status_code=422, detail="command_id is required")
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        result = await run_in_threadpool(
            navigation_controller.cancel_navigation,
            robot_id,
            command_id,
        )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "NAVIGATION",
                "GOAL_CANCEL_REQUESTED",
                accepted.get("message", "Navigation cancellation accepted"),
                command_id=command_id,
            )
        return accepted

    @app.post(
        "/api/robots/{robot_id}/tasks",
        status_code=201,
    )
    def create_navigation_task(
        robot_id: str,
        request: NavigationGoalRequest,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        _validate_pose_request(request)
        _require_free_map_pose(map_registry, robot_id, request.x, request.y)
        manager = _task_manager_or_503(task_manager)
        return manager.create(
            robot_id,
            request.x,
            request.y,
            request.yaw,
            request.confirm_warnings,
        )

    @app.post("/api/tasks/{task_id}/run", status_code=202)
    async def run_navigation_task(task_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        task = _task_or_404(store, task_id)
        robot = _robot_or_404(registry, task["robot_id"])
        target = task["target"]
        _require_free_map_pose(
            map_registry,
            task["robot_id"],
            target["x"],
            target["y"],
        )
        _require_goal_ready(robot, task["confirm_warnings"])
        manager = _task_manager_or_503(task_manager)
        try:
            result = await run_in_threadpool(manager.run, task_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _require_task_operation_success(result)

    @app.delete("/api/tasks/{task_id}", status_code=202)
    async def cancel_navigation_task(task_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        _task_or_404(store, task_id)
        manager = _task_manager_or_503(task_manager)
        try:
            result = await run_in_threadpool(manager.cancel, task_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _require_task_operation_success(result)

    @app.post("/api/tasks/{task_id}/retry", status_code=201)
    def retry_navigation_task(task_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        _task_or_404(store, task_id)
        manager = _task_manager_or_503(task_manager)
        try:
            return manager.retry(task_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/robots/{robot_id}/estop")
    async def set_estop(
        robot_id: str,
        request: EStopRequest,
    ) -> Dict[str, Any]:
        robot = registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        if not request.engaged and not robot["online"]:
            raise HTTPException(
                status_code=409,
                detail="Cannot release emergency stop while robot is offline",
            )
        if not request.engaged:
            _require_no_active_goal(robot)
        if estop_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Emergency-stop controller is unavailable",
            )
        result = await run_in_threadpool(
            estop_controller.set_estop,
            robot_id,
            request.engaged,
        )
        if not result.get("success", False):
            raise HTTPException(
                status_code=503,
                detail=result.get("message", "Emergency-stop request failed"),
            )
        if operations_store is not None:
            event_type = "ESTOP_ENGAGED" if request.engaged else "ESTOP_RELEASED"
            operations_store.record_event(
                robot_id,
                "SAFETY",
                event_type,
                result.get("message", event_type),
                severity="WARN" if request.engaged else "INFO",
            )
        return result

    @app.websocket("/ws/robots")
    async def robot_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json({"robots": registry.snapshot()})
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=websocket_interval_sec,
                    )
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            return

    resolved_static = Path(static_dir) if static_dir is not None else None
    if resolved_static is not None and resolved_static.is_dir():
        allowed_assets = {
            "app.js",
            "map_math.js",
            "map_viewport.js",
            "styles.css",
        }

        @app.get("/static/{asset_name}", include_in_schema=False)
        def static_asset(asset_name: str) -> FileResponse:
            if asset_name not in allowed_assets:
                raise HTTPException(status_code=404, detail="Unknown asset")
            return FileResponse(str(resolved_static / asset_name))

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(str(resolved_static / "index.html"))

    return app


def _robot_or_404(
    registry: StatusRegistry,
    robot_id: str,
) -> Dict[str, Any]:
    robot = registry.get(robot_id)
    if robot is None:
        raise HTTPException(status_code=404, detail="Unknown robot")
    return robot


def _validate_pose_request(request: PoseRequest) -> None:
    if not all(math.isfinite(value) for value in (request.x, request.y, request.yaw)):
        raise HTTPException(status_code=422, detail="Pose values must be finite")


def _require_online_and_no_error(robot: Dict[str, Any]) -> None:
    if not robot.get("online", False):
        raise HTTPException(status_code=409, detail="Robot is offline")
    if int(robot.get("level", 0)) >= 2:
        raise HTTPException(
            status_code=409,
            detail="Robot has an active error",
        )


def _require_no_active_goal(robot: Dict[str, Any]) -> None:
    navigation = robot.get("navigation") or {}
    if navigation.get("active_command_id"):
        raise HTTPException(
            status_code=409,
            detail="Cancel the active navigation goal first",
        )


def _require_goal_ready(
    robot: Dict[str, Any],
    confirm_warnings: bool,
) -> None:
    _require_online_and_no_error(robot)
    if int(robot.get("level", 0)) == 1 and not confirm_warnings:
        faults = robot.get("fault_codes", [])
        detail = "Robot warnings require confirmation"
        if faults:
            detail += f": {', '.join(faults)}"
        raise HTTPException(status_code=409, detail=detail)
    _require_no_active_goal(robot)
    navigation = robot.get("navigation") or {}
    if not navigation.get("fresh", False):
        raise HTTPException(
            status_code=409,
            detail="Navigation status is unavailable or stale",
        )
    if not navigation.get("nav2_ready", False):
        raise HTTPException(status_code=409, detail="Nav2 is not ready")
    if not navigation.get("localization_ready", False):
        raise HTTPException(status_code=409, detail="Localization is not ready")
    if not navigation.get("safety_ready", False):
        raise HTTPException(status_code=409, detail="Motion safety is not ready")
    safety = robot.get("safety") or {}
    if not safety.get("fresh", False):
        raise HTTPException(
            status_code=409,
            detail="Safety status is unavailable or stale",
        )
    if safety.get("estop_active", False):
        raise HTTPException(status_code=409, detail="Emergency stop is active")
    if safety and not safety.get("motion_armed", False):
        raise HTTPException(status_code=409, detail="Motion is not armed")


def _require_free_map_pose(
    registry: Optional[MapRegistry],
    robot_id: str,
    x: float,
    y: float,
) -> None:
    if registry is None:
        raise HTTPException(status_code=503, detail="Map registry unavailable")
    valid, detail = registry.validate_pose(robot_id, x, y)
    if valid:
        return
    status_code = 503 if detail == "Map is unavailable" else 422
    raise HTTPException(status_code=status_code, detail=detail)


def _require_controller_success(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("success", False):
        return result
    raise HTTPException(
        status_code=int(result.get("status_code", 503)),
        detail=result.get("message", "Navigation request failed"),
    )


def _operations_or_503(
    store: Optional[OperationsStore],
) -> OperationsStore:
    if store is None:
        raise HTTPException(status_code=503, detail="Operations store unavailable")
    return store


def _task_manager_or_503(
    manager: Optional[NavigationTaskManager],
) -> NavigationTaskManager:
    if manager is None:
        raise HTTPException(status_code=503, detail="Task manager unavailable")
    return manager


def _task_or_404(store: OperationsStore, task_id: str) -> Dict[str, Any]:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    return task


def _require_task_operation_success(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("state") != "FAILED" or "status_code" not in result:
        return result
    raise HTTPException(
        status_code=int(result["status_code"]),
        detail=result.get("message", "Task operation failed"),
    )
