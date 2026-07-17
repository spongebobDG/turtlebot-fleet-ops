"""Test durable TB1 fault, task and audit storage."""

from fleet_gateway.operations import OperationsStore


def test_fault_transitions_are_deduplicated_and_persisted(tmp_path) -> None:
    store = OperationsStore(tmp_path / "operations.sqlite3")
    warning = {
        "robot_id": "tb1",
        "level": 1,
        "fault_codes": ["SCAN_STALE"],
    }

    store.sync_faults(warning)
    store.sync_faults(warning)
    active = store.list_faults("tb1")
    events = store.list_events("tb1")

    assert len(active) == 1
    assert active[0]["fault_code"] == "SCAN_STALE"
    assert active[0]["severity"] == "WARN"
    assert [event["event_type"] for event in events] == ["FAULT_ACTIVATED"]

    store.sync_faults({"robot_id": "tb1", "level": 0, "fault_codes": []})

    assert store.list_faults("tb1") == []
    history = store.list_faults("tb1", include_cleared=True)
    assert history[0]["active"] is False
    assert [event["event_type"] for event in store.list_events("tb1")] == [
        "FAULT_CLEARED",
        "FAULT_ACTIVATED",
    ]


def test_task_retry_and_navigation_reconciliation_survive_reopen(tmp_path) -> None:
    path = tmp_path / "operations.sqlite3"
    store = OperationsStore(path)
    task = store.create_task("tb1", 0.5, 0.25, 1.0, False)
    store.update_task(
        task["task_id"],
        "ACTIVE",
        "accepted",
        "command-1",
    )
    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "FAILED",
            "active_command_id": "command-1",
            "message": "planner failed",
        }
    )

    reopened = OperationsStore(path)
    failed = reopened.get_task(task["task_id"])
    assert failed is not None
    assert failed["state"] == "FAILED"
    assert failed["target"] == {
        "frame_id": "map",
        "x": 0.5,
        "y": 0.25,
        "yaw": 1.0,
    }

    retry = reopened.retry_task(task["task_id"])
    assert retry["state"] == "CREATED"
    assert retry["attempt"] == 2
    assert retry["parent_task_id"] == task["task_id"]


def test_lease_expiration_maps_to_failed_task(tmp_path) -> None:
    store = OperationsStore(tmp_path / "operations.sqlite3")
    task = store.create_task("tb1", 1.0, 0.0, 0.0, True)
    store.update_task(task["task_id"], "ACTIVE", "accepted", "lease-1")

    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "LEASE_EXPIRED",
            "active_command_id": "",
            "message": "Gateway lease expired",
        }
    )

    failed = store.get_task(task["task_id"])
    assert failed is not None
    assert failed["state"] == "FAILED"
    assert failed["message"] == "Gateway lease expired"
