"""FastAPI application for fleet status and safety commands."""

import asyncio
from contextlib import suppress
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from fleet_gateway.registry import StatusRegistry
from fleet_gateway.scan_registry import ScanRegistry
from fleet_gateway.map_registry import MapRegistry
from fleet_gateway.pose_alignment import (
    align_pose,
    alignment_is_acceptable,
    score_pose_alignment,
)
from fleet_gateway.log_mlops import incidents_from_path, status_from_path
from fleet_gateway.operations import OperationsStore
from fleet_gateway.task_manager import NavigationTaskManager
from fleet_gateway.patrol_manager import PatrolManager


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


class ManualController(Protocol):
    """Robot-local leased manual control adapter."""

    def start_manual(self, robot_id: str) -> Dict[str, Any]:
        """Start one deadman manual session."""

    def send_manual(
        self,
        robot_id: str,
        session_id: str,
        linear_x: float,
        angular_z: float,
    ) -> Dict[str, Any]:
        """Refresh one manual session with a bounded command."""

    def stop_manual(self, robot_id: str, session_id: str) -> Dict[str, Any]:
        """Stop exactly one manual session."""

    def manual_active(self, robot_id: str) -> bool:
        """Return whether Gateway still owns a fresh manual session."""


class ProfileController(Protocol):
    """TB1 operating-profile and map-save adapter."""

    def set_operating_profile(
        self,
        robot_id: str,
        profile: str,
    ) -> Dict[str, Any]:
        """Engage e-stop and switch to IDLE, MAPPING or NAVIGATION."""

    def save_map(self, robot_id: str, overwrite: bool) -> Dict[str, Any]:
        """Engage e-stop and save the current map and pose graph."""


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


class ManualSessionRequest(BaseModel):
    """Warning acknowledgement for a new manual deadman session."""

    confirm_warnings: bool = False


class ManualVelocityRequest(BaseModel):
    """Planar velocity for one already-owned manual session."""

    linear_x: float
    angular_z: float


class SaveMapRequest(BaseModel):
    """Explicit permission to replace fixed TB1 map artifacts."""

    overwrite: bool = False


class PatrolRequest(BaseModel):
    """Ordered map-frame waypoints and finite repeat policy."""

    waypoints: List[PoseRequest]
    loops: int = 1
    dwell_sec: float = 0.0
    confirm_warnings: bool = False


def create_app(
    registry: StatusRegistry,
    estop_controller: Optional[EStopController] = None,
    navigation_controller: Optional[NavigationController] = None,
    manual_controller: Optional[ManualController] = None,
    profile_controller: Optional[ProfileController] = None,
    map_registry: Optional[MapRegistry] = None,
    scan_registry: Optional[ScanRegistry] = None,
    operations_store: Optional[OperationsStore] = None,
    task_manager: Optional[NavigationTaskManager] = None,
    patrol_manager: Optional[PatrolManager] = None,
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

    @app.get("/api/mlops/ros2-logs/incidents")
    def ros2_log_incidents() -> Dict[str, Any]:
        return incidents_from_path(log_mlops_status_path)

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

    @app.get("/api/patrols")
    def list_patrols(
        robot_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        return {"patrols": store.list_patrols(robot_id, limit)}

    @app.get("/api/patrols/{patrol_id}")
    def get_patrol(patrol_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        return _patrol_or_404(store, patrol_id)

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

    @app.get("/api/robots/{robot_id}/scan")
    def get_robot_scan(robot_id: str) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        if scan_registry is None:
            raise HTTPException(
                status_code=503,
                detail="LiDAR registry unavailable",
            )
        snapshot = scan_registry.get(robot_id)
        if snapshot is None:
            raise HTTPException(status_code=503, detail="LiDAR scan unavailable")
        return snapshot

    @app.post(
        "/api/robots/{robot_id}/localization/align-pose",
    )
    async def align_initial_pose(
        robot_id: str,
        request: PoseRequest,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        _validate_pose_request(request)
        _require_free_map_pose(map_registry, robot_id, request.x, request.y)
        occupancy_map, scan = _alignment_inputs(
            map_registry,
            scan_registry,
            robot_id,
        )
        try:
            result = await run_in_threadpool(
                align_pose,
                occupancy_map,
                scan,
                request.x,
                request.y,
                request.yaw,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not result["acceptable"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    "LiDAR-map auto alignment is not reliable enough "
                    f"(match {result['matched_ratio']:.0%}, "
                    f"inside {result['inside_ratio']:.0%})"
                ),
            )
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "LOCALIZATION",
                "INITIAL_POSE_AUTO_ALIGNED",
                "LiDAR-map alignment produced a verified pose candidate",
                details=result,
            )
        return result

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
        _require_no_active_patrol(operations_store, robot_id)
        _require_no_active_manual(manual_controller, robot_id)
        if scan_registry is not None:
            occupancy_map, scan = _alignment_inputs(
                map_registry,
                scan_registry,
                robot_id,
            )
            try:
                alignment = await run_in_threadpool(
                    score_pose_alignment,
                    occupancy_map,
                    scan,
                    request.x,
                    request.y,
                    request.yaw,
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if not alignment_is_acceptable(alignment):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Initial pose does not align with the current LiDAR "
                        f"(match {alignment['matched_ratio']:.0%}, "
                        f"inside {alignment['inside_ratio']:.0%}); "
                        "run LiDAR auto alignment first"
                    ),
                )
        _require_navigation_profile(robot)
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
        _require_no_active_patrol(operations_store, robot_id)
        _require_no_active_manual(manual_controller, robot_id)
        _require_free_current_pose(map_registry, robot_id, robot)
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
        "/api/robots/{robot_id}/manual/sessions",
        status_code=202,
    )
    async def start_manual_session(
        robot_id: str,
        request: ManualSessionRequest,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _require_manual_ready(robot, request.confirm_warnings)
        _require_no_active_patrol(operations_store, robot_id)
        if manual_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Manual controller is unavailable",
            )
        result = await run_in_threadpool(
            manual_controller.start_manual,
            robot_id,
        )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "MANUAL",
                "MANUAL_SESSION_STARTED",
                accepted.get("message", "Manual session started"),
                details={"session_id": accepted.get("session_id")},
            )
        return accepted

    @app.put(
        "/api/robots/{robot_id}/manual/sessions/{session_id}",
        status_code=202,
    )
    async def send_manual_command(
        robot_id: str,
        session_id: str,
        request: ManualVelocityRequest,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _require_manual_ready(robot, True)
        _validate_manual_velocity(request)
        if manual_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Manual controller is unavailable",
            )
        result = await run_in_threadpool(
            manual_controller.send_manual,
            robot_id,
            session_id,
            request.linear_x,
            request.angular_z,
        )
        return _require_controller_success(result)

    @app.delete(
        "/api/robots/{robot_id}/manual/sessions/{session_id}",
        status_code=202,
    )
    async def stop_manual_session(
        robot_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        if manual_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Manual controller is unavailable",
            )
        result = await run_in_threadpool(
            manual_controller.stop_manual,
            robot_id,
            session_id,
        )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "MANUAL",
                "MANUAL_SESSION_STOPPED",
                accepted.get("message", "Manual session stopped"),
            )
        return accepted

    @app.post(
        "/api/robots/{robot_id}/profiles/{profile}",
        status_code=202,
    )
    async def set_operating_profile(
        robot_id: str,
        profile: str,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _require_online_and_no_error(robot)
        normalized = profile.strip().upper()
        if normalized not in {"IDLE", "MAPPING", "NAVIGATION"}:
            raise HTTPException(status_code=422, detail="Unknown profile")
        if profile_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Operating-profile controller is unavailable",
            )
        result = await run_in_threadpool(
            profile_controller.set_operating_profile,
            robot_id,
            normalized,
        )
        if result.get("estop_engaged") and patrol_manager is not None:
            patrol_manager.stop_for_safety(
                robot_id,
                "Operating profile change engaged e-stop",
            )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "PROFILE",
                f"PROFILE_{normalized}_REQUESTED",
                accepted.get("message", "Profile transition accepted"),
                severity="WARN",
            )
        return accepted

    @app.post(
        "/api/robots/{robot_id}/mapping/save",
        status_code=202,
    )
    async def save_mapping(
        robot_id: str,
        request: SaveMapRequest,
    ) -> Dict[str, Any]:
        robot = _robot_or_404(registry, robot_id)
        _require_online_and_no_error(robot)
        mapping = robot.get("mapping") or {}
        if not mapping.get("fresh", False):
            raise HTTPException(status_code=409, detail="Profile status is stale")
        if mapping.get("profile") != "MAPPING":
            raise HTTPException(status_code=409, detail="MAPPING profile required")
        if profile_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Operating-profile controller is unavailable",
            )
        result = await run_in_threadpool(
            profile_controller.save_map,
            robot_id,
            request.overwrite,
        )
        if result.get("estop_engaged") and patrol_manager is not None:
            patrol_manager.stop_for_safety(
                robot_id,
                "Map save engaged e-stop",
            )
        accepted = _require_controller_success(result)
        if operations_store is not None:
            operations_store.record_event(
                robot_id,
                "MAPPING",
                "MAP_SAVED",
                accepted.get("message", "Map saved"),
                details={"overwrite": request.overwrite},
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

    @app.post(
        "/api/robots/{robot_id}/patrols",
        status_code=201,
    )
    def create_patrol(
        robot_id: str,
        request: PatrolRequest,
    ) -> Dict[str, Any]:
        _robot_or_404(registry, robot_id)
        _validate_patrol_request(request)
        for point in request.waypoints:
            _validate_pose_request(point)
            _require_free_map_pose(
                map_registry,
                robot_id,
                point.x,
                point.y,
            )
        manager = _patrol_manager_or_503(patrol_manager)
        return manager.create(
            robot_id,
            [point.dict() for point in request.waypoints],
            request.loops,
            request.dwell_sec,
            request.confirm_warnings,
        )

    @app.post("/api/patrols/{patrol_id}/run", status_code=202)
    async def run_patrol(patrol_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        patrol = _patrol_or_404(store, patrol_id)
        robot = _robot_or_404(registry, patrol["robot_id"])
        _require_goal_ready(robot, patrol["confirm_warnings"])
        _require_no_active_manual(
            manual_controller,
            patrol["robot_id"],
        )
        _require_free_current_pose(map_registry, patrol["robot_id"], robot)
        for point in patrol["waypoints"]:
            _require_free_map_pose(
                map_registry,
                patrol["robot_id"],
                point["x"],
                point["y"],
            )
        manager = _patrol_manager_or_503(patrol_manager)
        try:
            result = await run_in_threadpool(manager.run, patrol_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _require_patrol_operation_success(result)

    @app.delete("/api/patrols/{patrol_id}", status_code=202)
    async def cancel_patrol(patrol_id: str) -> Dict[str, Any]:
        store = _operations_or_503(operations_store)
        _patrol_or_404(store, patrol_id)
        manager = _patrol_manager_or_503(patrol_manager)
        try:
            result = await run_in_threadpool(manager.cancel, patrol_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _require_patrol_operation_success(result)

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
        _require_no_active_patrol(operations_store, task["robot_id"])
        _require_no_active_manual(manual_controller, task["robot_id"])
        _require_free_current_pose(map_registry, task["robot_id"], robot)
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
        if request.engaged and patrol_manager is not None:
            patrol_manager.stop_for_safety(
                robot_id,
                "Emergency stop engaged",
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
            "robot_display.js",
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
    _require_navigation_profile(robot)


def _require_navigation_profile(robot: Dict[str, Any]) -> None:
    mapping = robot.get("mapping") or {}
    if not mapping.get("fresh", False):
        raise HTTPException(status_code=409, detail="Profile status is stale")
    if mapping.get("transitioning", False):
        raise HTTPException(status_code=409, detail="Profile is transitioning")
    if mapping.get("profile") != "NAVIGATION":
        raise HTTPException(status_code=409, detail="NAVIGATION profile required")


def _require_manual_ready(
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
    safety = robot.get("safety") or {}
    if not safety.get("fresh", False):
        raise HTTPException(status_code=409, detail="Safety status is stale")
    if safety.get("estop_active", False):
        raise HTTPException(status_code=409, detail="Emergency stop is active")
    if not safety.get("motion_armed", False):
        raise HTTPException(status_code=409, detail="Motion is not armed")
    mapping = robot.get("mapping") or {}
    if not mapping.get("fresh", False):
        raise HTTPException(status_code=409, detail="Profile status is stale")
    if mapping.get("transitioning", False):
        raise HTTPException(status_code=409, detail="Profile is transitioning")
    if mapping.get("profile") not in {"MAPPING", "NAVIGATION"}:
        raise HTTPException(status_code=409, detail="Motion profile is IDLE")


def _require_no_active_patrol(
    store: Optional[OperationsStore],
    robot_id: str,
) -> None:
    if store is None:
        return
    if any(
        patrol["state"] in {"STARTING", "ACTIVE"}
        for patrol in store.list_patrols(robot_id, 500)
    ):
        raise HTTPException(status_code=409, detail="A patrol is active")


def _require_no_active_manual(
    controller: Optional[ManualController],
    robot_id: str,
) -> None:
    checker = getattr(controller, "manual_active", None)
    if callable(checker) and checker(robot_id):
        raise HTTPException(status_code=409, detail="A manual session is active")


def _validate_manual_velocity(request: ManualVelocityRequest) -> None:
    values = (request.linear_x, request.angular_z)
    if not all(math.isfinite(value) for value in values):
        raise HTTPException(
            status_code=422,
            detail="Manual velocity must be finite",
        )
    if abs(request.linear_x) > 0.05 or abs(request.angular_z) > 0.3:
        raise HTTPException(
            status_code=422,
            detail="Manual velocity exceeds 0.05 m/s or 0.3 rad/s",
        )


def _validate_patrol_request(request: PatrolRequest) -> None:
    if not 2 <= len(request.waypoints) <= 20:
        raise HTTPException(
            status_code=422,
            detail="Patrol requires 2 to 20 waypoints",
        )
    if not 1 <= request.loops <= 100:
        raise HTTPException(status_code=422, detail="loops must be 1 to 100")
    if (
        not math.isfinite(request.dwell_sec)
        or not 0.0 <= request.dwell_sec <= 300.0
    ):
        raise HTTPException(
            status_code=422,
            detail="dwell_sec must be between 0 and 300",
        )


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


def _require_free_current_pose(
    registry: Optional[MapRegistry],
    robot_id: str,
    robot: Dict[str, Any],
) -> None:
    navigation = robot.get("navigation") or {}
    current = navigation.get("current") or {}
    if current.get("frame_id") != "map":
        raise HTTPException(
            status_code=409,
            detail="Current localization is not available in map frame",
        )
    if registry is None:
        raise HTTPException(status_code=503, detail="Map registry unavailable")
    valid, detail = registry.validate_pose(
        robot_id,
        float(current.get("x", math.nan)),
        float(current.get("y", math.nan)),
    )
    if not valid:
        raise HTTPException(
            status_code=409,
            detail=f"Current localization is unsafe: {detail}",
        )


def _alignment_inputs(
    map_registry: Optional[MapRegistry],
    scan_registry: Optional[ScanRegistry],
    robot_id: str,
) -> tuple:
    if map_registry is None:
        raise HTTPException(status_code=503, detail="Map registry unavailable")
    if scan_registry is None:
        raise HTTPException(status_code=503, detail="LiDAR registry unavailable")
    occupancy_map = map_registry.get(robot_id)
    scan = scan_registry.get(robot_id)
    if occupancy_map is None:
        raise HTTPException(status_code=503, detail="Map is unavailable")
    if scan is None:
        raise HTTPException(status_code=503, detail="LiDAR scan unavailable")
    if not scan.get("fresh", False):
        raise HTTPException(status_code=409, detail="LiDAR scan is stale")
    return occupancy_map, scan


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


def _patrol_manager_or_503(
    manager: Optional[PatrolManager],
) -> PatrolManager:
    if manager is None:
        raise HTTPException(status_code=503, detail="Patrol manager unavailable")
    return manager


def _task_or_404(store: OperationsStore, task_id: str) -> Dict[str, Any]:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task")
    return task


def _patrol_or_404(
    store: OperationsStore,
    patrol_id: str,
) -> Dict[str, Any]:
    patrol = store.get_patrol(patrol_id)
    if patrol is None:
        raise HTTPException(status_code=404, detail="Unknown patrol")
    return patrol


def _require_task_operation_success(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("state") != "FAILED" or "status_code" not in result:
        return result
    raise HTTPException(
        status_code=int(result["status_code"]),
        detail=result.get("message", "Task operation failed"),
    )


def _require_patrol_operation_success(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("state") != "FAILED" or "status_code" not in result:
        return result
    raise HTTPException(
        status_code=int(result["status_code"]),
        detail=result.get("message", "Patrol operation failed"),
    )
