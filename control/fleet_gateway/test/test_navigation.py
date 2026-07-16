import pytest

from fleet_gateway.navigation import NavigationConflict
from fleet_gateway.navigation import NavigationRegistry


class Clocks:

    def __init__(self):
        self.monotonic = 10.0
        self.wall = 1000.0


def make_registry(clocks):
    return NavigationRegistry(
        monotonic_clock=lambda: clocks.monotonic,
        wall_clock=lambda: clocks.wall,
    )


def test_begin_creates_pending_goal_and_blocks_second_active_goal():
    clocks = Clocks()
    registry = make_registry(clocks)

    goal = registry.begin(
        "tb1",
        {"x": 1.0, "y": 2.0, "yaw": 0.5, "frame_id": "map"},
        30.0,
        goal_id="first",
    )

    assert goal["status"] == "PENDING"
    assert goal["target"]["x"] == 1.0
    with pytest.raises(NavigationConflict) as error:
        registry.begin("tb1", {"x": 2.0}, 30.0, goal_id="second")
    assert error.value.goal_id == "first"


def test_running_feedback_and_success_are_recorded_defensively():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 30.0, goal_id="goal")

    assert registry.mark_running("tb1", "goal") is True
    assert registry.update_feedback(
        "tb1",
        "goal",
        {"distance_remaining": 0.7},
    ) is True
    assert registry.finish(
        "tb1",
        "goal",
        "SUCCEEDED",
        "done",
    ) is True

    result = registry.get("tb1")
    result["feedback"]["distance_remaining"] = 99.0
    assert registry.get("tb1")["feedback"]["distance_remaining"] == 0.7
    assert registry.get("tb1")["status"] == "SUCCEEDED"


def test_terminal_goal_can_be_replaced_but_stale_callback_is_ignored():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 30.0, goal_id="old")
    registry.finish("tb1", "old", "ABORTED", "failed")
    registry.begin("tb1", {"x": 2.0}, 30.0, goal_id="new")

    assert registry.finish("tb1", "old", "SUCCEEDED", "late") is False
    assert registry.get("tb1")["goal_id"] == "new"
    assert registry.get("tb1")["status"] == "PENDING"


def test_expired_goal_cannot_return_to_running_after_late_acceptance():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 1.0, goal_id="late")

    clocks.monotonic = 11.1
    registry.claim_expired()
    registry.finish("tb1", "late", "TIMEOUT", "acceptance was late")

    assert registry.mark_running("tb1", "late") is False
    assert registry.get("tb1")["status"] == "TIMEOUT"


def test_claim_expired_marks_timeout_cancel_once():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 5.0, goal_id="goal")
    registry.mark_running("tb1", "goal")

    clocks.monotonic = 15.1
    clocks.wall = 1005.1
    first = registry.claim_expired()
    second = registry.claim_expired()

    assert len(first) == 1
    assert first[0]["status"] == "CANCELING"
    assert first[0]["timeout_requested"] is True
    assert second == []


def test_user_cancel_does_not_mark_goal_as_timeout():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 30.0, goal_id="goal")
    registry.mark_running("tb1", "goal")

    assert registry.request_cancel(
        "tb1",
        "goal",
        "operator cancel",
    ) is True
    result = registry.get("tb1")

    assert result["status"] == "CANCELING"
    assert result["timeout_requested"] is False


def test_cancel_before_acceptance_prevents_goal_from_running():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb1", {"x": 1.0}, 30.0, goal_id="pending")

    assert registry.request_cancel(
        "tb1",
        "pending",
        "operator cancel",
    ) is True
    assert registry.mark_running("tb1", "pending") is False
    assert registry.get("tb1")["status"] == "CANCELING"


def test_invalid_timeout_and_terminal_status_are_rejected():
    clocks = Clocks()
    registry = make_registry(clocks)

    with pytest.raises(ValueError):
        registry.begin("tb1", {"x": 1.0}, 0.0)
    registry.begin("tb1", {"x": 1.0}, 1.0, goal_id="goal")
    with pytest.raises(ValueError):
        registry.finish("tb1", "goal", "RUNNING", "not terminal")


def test_snapshot_is_sorted_by_robot_id():
    clocks = Clocks()
    registry = make_registry(clocks)
    registry.begin("tb2", {"x": 2.0}, 30.0, goal_id="two")
    registry.begin("tb1", {"x": 1.0}, 30.0, goal_id="one")

    assert [item["robot_id"] for item in registry.snapshot()] == [
        "tb1",
        "tb2",
    ]
