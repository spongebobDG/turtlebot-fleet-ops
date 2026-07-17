#!/usr/bin/env python3
"""Drive the real Gateway/Nav2 stack through its HTTP API without hardware."""

import json
import sys
import time
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000"


def _request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> tuple[int, Dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_for(
    description: str,
    predicate: Callable[[], Optional[Dict[str, Any]]],
    timeout_sec: float = 45.0,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result is not None:
                print(f"PASS: {description}")
                return result
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            last_error = str(error)
        time.sleep(0.25)
    raise AssertionError(f"Timed out waiting for {description}: {last_error}")


def _robot() -> Dict[str, Any]:
    status, payload = _request("GET", "/api/robots/tb1")
    if status != 200:
        raise AssertionError(f"robot snapshot returned {status}: {payload}")
    return payload


def _wait_navigation_state(*states: str) -> Dict[str, Any]:
    def predicate() -> Optional[Dict[str, Any]]:
        robot = _robot()
        navigation = robot.get("navigation") or {}
        if navigation.get("state") in states:
            return robot
        return None

    return _wait_for(f"navigation state in {states}", predicate)


def _start_goal(x_value: float) -> str:
    deadline = time.monotonic() + 5.0
    last_payload: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, payload = _request(
            "POST",
            "/api/robots/tb1/navigation/goals",
            {"x": x_value, "y": 0.0, "yaw": 0.0},
        )
        last_payload = payload
        if status == 202:
            return str(payload["command_id"])
        time.sleep(0.2)
    raise AssertionError(f"goal was not accepted: {last_payload}")


def main() -> None:
    """Exercise initial pose, success, cancel, and e-stop transitions."""
    _wait_for(
        "Gateway, robot heartbeat, and map",
        lambda: (
            _robot()
            if _request("GET", "/api/robots/tb1/map")[0] == 200
            and _robot().get("online")
            else None
        ),
        timeout_sec=60.0,
    )
    status, payload = _request(
        "PUT",
        "/api/robots/tb1/localization/initial-pose",
        {"x": 0.0, "y": 0.0, "yaw": 0.0},
    )
    assert status == 202, (status, payload)
    _wait_navigation_state("READY")

    success_command = _start_goal(0.4)
    _wait_navigation_state("ACTIVE", "SUCCEEDED")
    success_robot = _wait_navigation_state("SUCCEEDED")
    assert not success_robot["navigation"]["active_command_id"]
    print(f"PASS: Nav2 success through HTTP command {success_command}")

    cancel_command = _start_goal(-0.4)
    _wait_navigation_state("ACTIVE")
    status, payload = _request(
        "DELETE",
        f"/api/robots/tb1/navigation/goals/{cancel_command}",
    )
    assert status == 202, (status, payload)
    _wait_navigation_state("CANCELED")
    print(f"PASS: explicit cancellation for {cancel_command}")

    estop_command = _start_goal(0.4)
    _wait_navigation_state("ACTIVE")
    status, payload = _request(
        "POST",
        "/api/robots/tb1/estop",
        {"engaged": True},
    )
    assert status == 200, (status, payload)

    def estop_canceled() -> Optional[Dict[str, Any]]:
        robot = _robot()
        navigation = robot.get("navigation") or {}
        safety = robot.get("safety") or {}
        if (
            safety.get("estop_active")
            and navigation.get("state") == "CANCELED"
            and not navigation.get("active_command_id")
        ):
            return robot
        return None

    _wait_for("e-stop cancellation", estop_canceled)
    status, payload = _request(
        "POST",
        "/api/robots/tb1/estop",
        {"engaged": False},
    )
    assert status == 200, (status, payload)

    def rearmed_without_resume() -> Optional[Dict[str, Any]]:
        robot = _robot()
        navigation = robot.get("navigation") or {}
        safety = robot.get("safety") or {}
        if (
            safety.get("motion_armed")
            and not safety.get("estop_active")
            and not navigation.get("active_command_id")
        ):
            return robot
        return None

    _wait_for("neutral rearm without goal resume", rearmed_without_resume)
    time.sleep(1.0)
    final_robot = _robot()
    assert not final_robot["navigation"]["active_command_id"]
    print(f"PASS: e-stop canceled {estop_command} without automatic resume")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: B902 - smoke-test boundary
        print(f"ROBOTLESS SMOKE FAILED: {error}", file=sys.stderr)
        raise
