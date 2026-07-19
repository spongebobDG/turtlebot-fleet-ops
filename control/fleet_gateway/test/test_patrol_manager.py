"""Waypoint patrol lifecycle tests using a fake navigation adapter."""

from fleet_gateway.operations import OperationsStore
from fleet_gateway.patrol_manager import PatrolManager


class FakeNavigation:

    def __init__(self) -> None:
        self.goals = []
        self.cancels = []

    def start_navigation(
        self,
        robot_id,
        x,
        y,
        yaw,
        confirm_warnings,
    ):
        command_id = f"goal-{len(self.goals) + 1}"
        self.goals.append(
            (robot_id, x, y, yaw, confirm_warnings, command_id)
        )
        return {
            "success": True,
            "command_id": command_id,
            "message": "accepted",
        }

    def cancel_navigation(self, robot_id, command_id):
        self.cancels.append((robot_id, command_id))
        return {"success": True, "message": "canceling"}


def make_patrol(manager):
    return manager.create(
        "tb1",
        [
            {"x": 0.1, "y": 0.2, "yaw": 0.3},
            {"x": 0.4, "y": 0.5, "yaw": 0.6},
        ],
        loops=1,
        dwell_sec=0.0,
        confirm_warnings=False,
    )


def terminal(patrol, state="SUCCEEDED"):
    point = patrol["waypoints"][patrol["current_waypoint"]]
    return {
        "robot_id": "tb1",
        "state": state,
        "target": point,
        "message": state.lower(),
    }


def test_patrol_advances_matching_waypoints_and_completes(tmp_path):
    store = OperationsStore(tmp_path / "operations.sqlite3")
    navigation = FakeNavigation()
    manager = PatrolManager(store, navigation)
    try:
        patrol = make_patrol(manager)
        active = manager.run(patrol["patrol_id"])
        assert active["state"] == "ACTIVE"
        manager._handle_terminal(terminal(active))
        second = store.get_patrol(patrol["patrol_id"])
        assert second["state"] == "ACTIVE"
        assert second["current_waypoint"] == 1
        manager._handle_terminal(terminal(second))
        completed = store.get_patrol(patrol["patrol_id"])
        assert completed["state"] == "COMPLETED"
        assert len(navigation.goals) == 2
    finally:
        manager.close()


def test_patrol_failure_and_cancel_never_start_next_waypoint(tmp_path):
    store = OperationsStore(tmp_path / "operations.sqlite3")
    navigation = FakeNavigation()
    manager = PatrolManager(store, navigation)
    try:
        patrol = make_patrol(manager)
        active = manager.run(patrol["patrol_id"])
        manager._handle_terminal(terminal(active, "LEASE_EXPIRED"))
        failed = store.get_patrol(patrol["patrol_id"])
        assert failed["state"] == "FAILED"
        assert len(navigation.goals) == 1

        second = make_patrol(manager)
        active = manager.run(second["patrol_id"])
        canceled = manager.cancel(second["patrol_id"])
        assert canceled["state"] == "CANCELED"
        assert navigation.cancels[-1] == ("tb1", active["command_id"])
    finally:
        manager.close()


def test_safety_stop_closes_active_patrol_without_second_cancel(tmp_path):
    store = OperationsStore(tmp_path / "operations.sqlite3")
    navigation = FakeNavigation()
    manager = PatrolManager(store, navigation)
    try:
        patrol = make_patrol(manager)
        active = manager.run(patrol["patrol_id"])

        stopped = manager.stop_for_safety("tb1", "Emergency stop engaged")

        assert stopped == 1
        current = store.get_patrol(active["patrol_id"])
        assert current["state"] == "CANCELED"
        assert "no waypoint will resume" in current["message"]
        assert navigation.cancels == []
    finally:
        manager.close()
