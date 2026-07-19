"""Test the single-robot navigation task state machine."""

import pytest

from fleet_gateway.operations import OperationsStore
from fleet_gateway.task_manager import NavigationTaskManager


class FakeNavigation:
    """Deterministic adapter for task lifecycle tests."""

    def __init__(self) -> None:
        self.start_result = {
            "success": True,
            "command_id": "command-1",
            "message": "accepted",
        }
        self.cancel_result = {
            "success": True,
            "message": "canceled",
        }
        self.calls = []

    def start_navigation(self, robot_id, x, y, yaw, confirm_warnings):
        self.calls.append(("start", robot_id, x, y, yaw, confirm_warnings))
        return dict(self.start_result)

    def cancel_navigation(self, robot_id, command_id):
        self.calls.append(("cancel", robot_id, command_id))
        return dict(self.cancel_result)


def _manager(tmp_path):
    store = OperationsStore(tmp_path / "operations.sqlite3")
    navigation = FakeNavigation()
    return store, navigation, NavigationTaskManager(store, navigation)


def test_create_run_cancel_and_retry_lifecycle(tmp_path) -> None:
    store, navigation, manager = _manager(tmp_path)
    created = manager.create("tb1", 0.5, 0.0, 0.25, True)

    active = manager.run(created["task_id"])
    canceled = manager.cancel(created["task_id"])
    retry = manager.retry(created["task_id"])

    assert active["state"] == "ACTIVE"
    assert active["command_id"] == "command-1"
    assert canceled["state"] == "CANCELED"
    assert retry["state"] == "CREATED"
    assert retry["attempt"] == 2
    assert [call[0] for call in navigation.calls] == ["start", "cancel"]
    assert len(store.list_events("tb1")) >= 5


def test_rejected_start_becomes_failed_and_can_retry(tmp_path) -> None:
    _, navigation, manager = _manager(tmp_path)
    navigation.start_result = {
        "success": False,
        "status_code": 409,
        "message": "Nav2 not ready",
    }
    task = manager.create("tb1", 0.5, 0.0, 0.0, False)

    failed = manager.run(task["task_id"])
    retry = manager.retry(task["task_id"])

    assert failed["state"] == "FAILED"
    assert failed["status_code"] == 409
    assert retry["attempt"] == 2


def test_duplicate_run_and_nonterminal_retry_are_rejected(tmp_path) -> None:
    _, _, manager = _manager(tmp_path)
    task = manager.create("tb1", 0.5, 0.0, 0.0, False)
    manager.run(task["task_id"])

    with pytest.raises(ValueError, match="CREATED"):
        manager.run(task["task_id"])
    with pytest.raises(ValueError, match="failed or canceled"):
        manager.retry(task["task_id"])


def test_created_task_can_be_canceled_without_robot_call(tmp_path) -> None:
    _, navigation, manager = _manager(tmp_path)
    task = manager.create("tb1", 0.25, 0.25, 0.0, False)

    canceled = manager.cancel(task["task_id"])

    assert canceled["state"] == "CANCELED"
    assert navigation.calls == []
