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


def test_connectivity_transitions_record_loss_and_recovery_once(tmp_path) -> None:
    store = OperationsStore(tmp_path / "operations.sqlite3")
    online = {
        "robot_id": "tb1",
        "online": True,
        "heartbeat_age_sec": 0.2,
    }
    offline = {
        "robot_id": "tb1",
        "online": False,
        "heartbeat_age_sec": 3.1,
    }

    store.sync_connectivity(online)
    store.sync_connectivity(online)
    assert store.list_events("tb1") == []

    store.sync_connectivity(offline)
    store.sync_connectivity(offline)
    store.sync_connectivity(online)

    events = store.list_events("tb1")
    assert [event["event_type"] for event in events] == [
        "ROBOT_ONLINE",
        "ROBOT_OFFLINE",
    ]
    assert events[0]["severity"] == "INFO"
    assert events[1]["severity"] == "ERROR"
    assert "전원·네트워크·Agent" in events[1]["message"]


def test_task_retry_and_navigation_reconciliation_survive_reopen(
    tmp_path,
) -> None:
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
            "state": "ACTIVE",
            "active_command_id": "lease-1",
            "message": "navigating",
        }
    )

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


def test_stale_terminal_status_cannot_close_the_next_task(tmp_path) -> None:
    store = OperationsStore(tmp_path / "operations.sqlite3")
    first = store.create_task("tb1", 1.0, 0.0, 0.0, False)
    store.update_task(first["task_id"], "ACTIVE", "accepted", "goal-1")
    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "ACTIVE",
            "active_command_id": "goal-1",
        }
    )
    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "CANCELED",
            "active_command_id": "",
            "message": "first goal canceled",
        }
    )

    second = store.create_task("tb1", -0.5, 0.0, 0.0, False)
    store.update_task(second["task_id"], "ACTIVE", "accepted", "goal-2")
    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "CANCELED",
            "active_command_id": "",
            "message": "late first-goal status",
        }
    )
    assert store.get_task(second["task_id"])["state"] == "ACTIVE"

    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "ACTIVE",
            "active_command_id": "goal-2",
        }
    )
    store.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "FAILED",
            "active_command_id": "",
            "message": "second goal failed",
        }
    )
    assert store.get_task(second["task_id"])["state"] == "FAILED"


def test_agent_restart_fails_persisted_active_task(tmp_path) -> None:
    path = tmp_path / "operations.sqlite3"
    store = OperationsStore(path)
    task = store.create_task("tb1", 1.0, 0.0, 0.0, False)
    store.update_task(task["task_id"], "ACTIVE", "accepted", "goal-1")

    reopened = OperationsStore(path)
    reopened.sync_navigation(
        {
            "robot_id": "tb1",
            "state": "UNAVAILABLE",
            "active_command_id": "",
            "message": "Startup cancellation in progress",
        }
    )

    failed = reopened.get_task(task["task_id"])
    assert failed is not None
    assert failed["state"] == "FAILED"
    assert "prior task will not resume" in failed["message"]


def test_gateway_restart_fails_every_persisted_nonterminal_task(
    tmp_path,
) -> None:
    path = tmp_path / "operations.sqlite3"
    store = OperationsStore(path)
    starting = store.create_task("tb1", 0.5, 0.0, 0.0, False)
    active = store.create_task("tb1", 1.0, 0.0, 0.0, False)
    finished = store.create_task("tb1", 1.5, 0.0, 0.0, False)
    store.update_task(starting["task_id"], "STARTING", "sending")
    store.update_task(active["task_id"], "ACTIVE", "accepted", "goal-1")
    store.update_task(finished["task_id"], "SUCCEEDED", "arrived")

    reopened = OperationsStore(path)
    recovered_count = reopened.reconcile_gateway_restart()

    assert recovered_count == 2
    assert reopened.get_task(starting["task_id"])["state"] == "FAILED"
    assert reopened.get_task(active["task_id"])["state"] == "FAILED"
    assert reopened.get_task(finished["task_id"])["state"] == "SUCCEEDED"
    assert reopened.reconcile_gateway_restart() == 0
    failed_events = [
        event
        for event in reopened.list_events("tb1")
        if event["event_type"] == "TASK_FAILED"
    ]
    assert len(failed_events) == 2
