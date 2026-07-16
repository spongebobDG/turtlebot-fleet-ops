"""FastAPI application for fleet status and safety commands."""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from fleet_gateway.registry import StatusRegistry


class EStopController(Protocol):
    """Interface implemented by the ROS emergency-stop adapter."""

    def set_estop(self, robot_id: str, engaged: bool) -> Dict[str, Any]:
        """Set emergency-stop state and return an operation result."""


class EStopRequest(BaseModel):
    """Emergency-stop HTTP request body."""

    engaged: bool


def create_app(
    registry: StatusRegistry,
    estop_controller: Optional[EStopController] = None,
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
