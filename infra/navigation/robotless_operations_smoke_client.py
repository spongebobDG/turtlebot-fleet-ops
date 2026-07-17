#!/usr/bin/env python3
"""Exercise TB1 task, fault and audit APIs against the lightweight mock."""

import json
import os
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("ROBOTLESS_BASE_URL", "http://127.0.0.1:8000")


def request_json(
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send one JSON request and fail with the response body."""
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        BASE_URL + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5.0) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AssertionError(
            f"{method} {path} returned {error.code}: {detail}"
        ) from error


def wait_task(task_id: str, state: str, timeout_sec: float = 8.0) -> Dict[str, Any]:
    """Wait until a durable task reaches the expected state."""
    deadline = time.monotonic() + timeout_sec
    latest = {}
    while time.monotonic() < deadline:
        latest = request_json(f"/api/tasks/{task_id}")
        if latest.get("state") == state:
            return latest
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} did not reach {state}: {latest}")


def create_task(x_value: float) -> Dict[str, Any]:
    """Create one map-valid TB1 task."""
    return request_json(
        "/api/robots/tb1/tasks",
        "POST",
        {
            "x": x_value,
            "y": 0.0,
            "yaw": 0.0,
            "confirm_warnings": False,
        },
    )


def wait_robot_ready(localized: bool, timeout_sec: float = 5.0) -> None:
    """Wait for the WebSocket-equivalent snapshot to observe mock transitions."""
    deadline = time.monotonic() + timeout_sec
    latest = {}
    while time.monotonic() < deadline:
        latest = request_json("/api/robots/tb1")
        navigation = latest.get("navigation") or {}
        safety = latest.get("safety") or {}
        if (
            latest.get("level") == 0
            and safety.get("motion_armed") is True
            and (
                not localized
                or (
                    navigation.get("nav2_ready") is True
                    and navigation.get("localization_ready") is True
                )
            )
        ):
            return
        time.sleep(0.1)
    raise AssertionError(f"mock robot did not become ready: {latest}")


def main() -> None:
    """Run success, cancel, failure, retry, fault and audit scenarios."""
    request_json("/api/robots/tb1/estop", "POST", {"engaged": False})
    wait_robot_ready(localized=False)
    request_json(
        "/api/robots/tb1/localization/initial-pose",
        "PUT",
        {"x": 0.0, "y": 0.0, "yaw": 0.0},
    )
    wait_robot_ready(localized=True)

    succeeded = create_task(0.5)
    request_json(f"/api/tasks/{succeeded['task_id']}/run", "POST")
    wait_task(succeeded["task_id"], "SUCCEEDED")

    canceled = create_task(1.5)
    request_json(f"/api/tasks/{canceled['task_id']}/run", "POST")
    wait_task(canceled["task_id"], "ACTIVE")
    request_json(f"/api/tasks/{canceled['task_id']}", "DELETE")
    wait_task(canceled["task_id"], "CANCELED")
    retry = request_json(
        f"/api/tasks/{canceled['task_id']}/retry",
        "POST",
    )
    assert retry["state"] == "CREATED"
    assert retry["attempt"] == 2

    failed = create_task(-0.5)
    request_json(f"/api/tasks/{failed['task_id']}/run", "POST")
    wait_task(failed["task_id"], "FAILED")

    faults = request_json(
        "/api/robots/tb1/faults?include_cleared=true"
    )["faults"]
    assert any(fault["fault_code"] == "MOCK_ESTOP_ACTIVE" for fault in faults)
    events = request_json("/api/events?robot_id=tb1&limit=100")["events"]
    event_types = {event["event_type"] for event in events}
    assert "FAULT_ACTIVATED" in event_types
    assert "FAULT_CLEARED" in event_types
    assert "TASK_SUCCEEDED" in event_types
    assert "TASK_CANCELED" in event_types
    assert "TASK_FAILED" in event_types

    request_json("/api/robots/tb1/estop", "POST", {"engaged": True})
    print(
        "ROBOTLESS_OPERATIONS_SMOKE_OK "
        f"tasks={len(request_json('/api/tasks')['tasks'])} "
        f"events={len(events)} final_estop=true"
    )


if __name__ == "__main__":
    main()
