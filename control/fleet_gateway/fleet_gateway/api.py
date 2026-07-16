"""FastAPI application for fleet status and safety commands."""

import asyncio
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, validator
from starlette.concurrency import run_in_threadpool

from fleet_gateway.registry import StatusRegistry


class EStopController(Protocol):
    """Interface implemented by the ROS emergency-stop adapter."""

    def set_estop(self, robot_id: str, engaged: bool) -> Dict[str, Any]:
        """Set emergency-stop state and return an operation result."""


class NavigationController(Protocol):
    """Interface implemented by the ROS NavigateToPose adapter."""

    def send_navigation_goal(
        self,
        robot_id: str,
        target: Dict[str, Any],
        timeout_sec: float,
    ) -> Dict[str, Any]:
        """Send one goal and return after Nav2 accepts or rejects it."""

    def cancel_navigation(self, robot_id: str) -> Dict[str, Any]:
        """Request cancellation of a robot's active goal."""

    def retry_navigation(self, robot_id: str) -> Dict[str, Any]:
        """Retry the latest failed goal after ROS safety checks."""

    def get_navigation(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Return the latest navigation state for one robot."""

    def navigation_snapshot(self) -> List[Dict[str, Any]]:
        """Return the latest navigation states for all robots."""


class EStopRequest(BaseModel):
    """Emergency-stop HTTP request body."""

    engaged: bool


class NavigationGoalRequest(BaseModel):
    """Validated map-frame destination submitted by the web client."""

    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = Field(default="map", min_length=1, max_length=64)
    timeout_sec: float = Field(default=300.0, gt=0.0, le=3600.0)

    @validator("x", "y", "yaw", "timeout_sec")
    def finite_number(cls, value: float) -> float:
        """Reject NaN and infinity before they reach ROS messages."""
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("value must be finite")
        return number

    @validator("frame_id")
    def map_frame_only(cls, value: str) -> str:
        """Keep web destinations in the validated global map frame."""
        if value != "map":
            raise ValueError("frame_id must be map")
        return value


def create_app(
    registry: StatusRegistry,
    estop_controller: Optional[EStopController] = None,
    navigation_controller: Optional[NavigationController] = None,
    static_dir: Optional[Path] = None,
    websocket_interval_sec: float = 0.5,
) -> FastAPI:
    """Create a web application around a shared status registry."""
    app = FastAPI(
        title="TurtleBot Fleet Ops",
        version="0.1.0",
        description="ROS 2 fleet status and safety command gateway.",
    )

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

    @app.get("/api/robots/{robot_id}")
    def get_robot(robot_id: str) -> Dict[str, Any]:
        robot = registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        return robot

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
        if not request.engaged and navigation_controller is not None:
            navigation = navigation_controller.get_navigation(robot_id)
            if navigation is not None and navigation["status"] in {
                "PENDING",
                "RUNNING",
                "CANCELING",
            }:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cannot release emergency stop while a navigation "
                        "goal is active"
                    ),
                )
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
        if request.engaged and navigation_controller is not None:
            result["navigation_cancel"] = await run_in_threadpool(
                navigation_controller.cancel_navigation,
                robot_id,
            )
        return result

    @app.post(
        "/api/robots/{robot_id}/navigation/goals",
        status_code=202,
    )
    async def send_navigation_goal(
        robot_id: str,
        request: NavigationGoalRequest,
    ) -> Dict[str, Any]:
        robot = registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        if not robot["online"]:
            raise HTTPException(
                status_code=409,
                detail="Cannot navigate while robot is offline",
            )
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        target = {
            "x": request.x,
            "y": request.y,
            "yaw": request.yaw,
            "frame_id": request.frame_id,
        }
        result = await run_in_threadpool(
            navigation_controller.send_navigation_goal,
            robot_id,
            target,
            request.timeout_sec,
        )
        if not result.get("success", False):
            status_code = (
                409 if result.get("code") == "active_goal" else 503
            )
            raise HTTPException(
                status_code=status_code,
                detail=result.get("message", "Navigation goal failed"),
            )
        return result

    @app.get("/api/robots/{robot_id}/navigation")
    def get_navigation(robot_id: str) -> Dict[str, Any]:
        if registry.get(robot_id) is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        navigation = navigation_controller.get_navigation(robot_id)
        if navigation is None:
            return {"robot_id": robot_id, "status": "IDLE"}
        return navigation

    @app.post("/api/robots/{robot_id}/navigation/cancel")
    async def cancel_navigation(robot_id: str) -> Dict[str, Any]:
        if registry.get(robot_id) is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        result = await run_in_threadpool(
            navigation_controller.cancel_navigation,
            robot_id,
        )
        if not result.get("success", False):
            raise HTTPException(
                status_code=503,
                detail=result.get("message", "Navigation cancel failed"),
            )
        return result

    @app.post(
        "/api/robots/{robot_id}/navigation/retry",
        status_code=202,
    )
    async def retry_navigation(robot_id: str) -> Dict[str, Any]:
        robot = registry.get(robot_id)
        if robot is None:
            raise HTTPException(status_code=404, detail="Unknown robot")
        if not robot["online"]:
            raise HTTPException(
                status_code=409,
                detail="Cannot retry navigation while robot is offline",
            )
        if navigation_controller is None:
            raise HTTPException(
                status_code=503,
                detail="Navigation controller is unavailable",
            )
        result = await run_in_threadpool(
            navigation_controller.retry_navigation,
            robot_id,
        )
        if not result.get("success", False):
            conflict_codes = {
                "active_goal",
                "retry_not_allowed",
                "estop_active",
                "estop_state_unknown",
                "estop_state_stale",
            }
            status_code = (
                409 if result.get("code") in conflict_codes else 503
            )
            raise HTTPException(
                status_code=status_code,
                detail=result.get("message", "Navigation retry failed"),
            )
        return result

    @app.websocket("/ws/robots")
    async def robot_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                message: Dict[str, Any] = {
                    "robots": registry.snapshot(),
                }
                if navigation_controller is not None:
                    message["navigation"] = (
                        navigation_controller.navigation_snapshot()
                    )
                await websocket.send_json(message)
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=websocket_interval_sec,
                    )
                except asyncio.TimeoutError:
                    continue
        except (WebSocketDisconnect, KeyError):
            # Some ASGI server/client combinations omit the optional close
            # code.  Treat that malformed disconnect event as a normal close
            # instead of leaking a task exception into the gateway log.
            return

    resolved_static = Path(static_dir) if static_dir is not None else None
    if resolved_static is not None and resolved_static.is_dir():
        allowed_assets = {"app.js", "styles.css"}

        @app.get("/static/{asset_name}", include_in_schema=False)
        def static_asset(asset_name: str) -> FileResponse:
            if asset_name not in allowed_assets:
                raise HTTPException(status_code=404, detail="Unknown asset")
            return FileResponse(str(resolved_static / asset_name))

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(str(resolved_static / "index.html"))

    return app
