import pytest

from fleet_gateway.registry import StatusRegistry


def test_registry_rejects_non_positive_timeout():
    with pytest.raises(ValueError):
        StatusRegistry(online_timeout_sec=0.0)


def test_registry_requires_robot_id():
    registry = StatusRegistry()
    with pytest.raises(ValueError):
        registry.update({"level": 0}, now=10.0)


def test_registry_infers_online_then_offline_from_heartbeat_age():
    registry = StatusRegistry(online_timeout_sec=3.0)
    registry.update({"robot_id": "tb1", "level": 0}, now=10.0)

    online = registry.get("tb1", now=12.5)
    offline = registry.get("tb1", now=13.1)

    assert online["online"] is True
    assert online["heartbeat_age_sec"] == 2.5
    assert offline["online"] is False
    assert offline["heartbeat_age_sec"] == 3.1


def test_registry_returns_sorted_defensive_snapshots():
    registry = StatusRegistry()
    registry.update({"robot_id": "tb2", "fault_codes": []}, now=1.0)
    registry.update({"robot_id": "tb1", "fault_codes": []}, now=1.0)

    first = registry.snapshot(now=1.0)
    first[0]["fault_codes"].append("MUTATED")
    second = registry.snapshot(now=1.0)

    assert [robot["robot_id"] for robot in first] == ["tb1", "tb2"]
    assert second[0]["fault_codes"] == []


def test_registry_merges_navigation_and_safety_status():
    registry = StatusRegistry(clock=lambda: 12.0)
    registry.update({"robot_id": "tb1", "level": 0}, now=10.0)
    registry.update_navigation(
        {"robot_id": "tb1", "state": "READY", "nav2_ready": True},
        now=11.0,
    )
    registry.update_safety(
        {"robot_id": "tb1", "motion_armed": True},
        now=11.5,
    )
    registry.update_mapping(
        {"robot_id": "tb1", "profile": "NAVIGATION"},
        now=11.75,
    )
    registry.update_map_pose(
        {"robot_id": "tb1", "frame_id": "map", "x": 0.2, "y": 0.3},
        now=11.9,
    )

    robot = registry.get("tb1", now=12.0)

    assert robot["navigation"]["state"] == "READY"
    assert robot["navigation"]["status_age_sec"] == 1.0
    assert robot["navigation"]["fresh"] is True
    assert robot["safety"]["motion_armed"] is True
    assert robot["safety"]["status_age_sec"] == 0.5
    assert robot["safety"]["fresh"] is True
    assert robot["mapping"]["profile"] == "NAVIGATION"
    assert robot["mapping"]["status_age_sec"] == 0.25
    assert robot["map_pose"]["frame_id"] == "map"
    assert robot["map_pose"]["status_age_sec"] == pytest.approx(0.1)


def test_registry_marks_auxiliary_status_stale_independently():
    registry = StatusRegistry(online_timeout_sec=3.0)
    registry.update({"robot_id": "tb1", "level": 0}, now=10.0)
    registry.update_navigation({"robot_id": "tb1"}, now=7.0)
    registry.update_safety({"robot_id": "tb1"}, now=8.0)
    registry.update_mapping({"robot_id": "tb1"}, now=6.0)

    robot = registry.get("tb1", now=10.1)

    assert robot["online"] is True
    assert robot["navigation"]["fresh"] is False
    assert robot["safety"]["fresh"] is True
    assert robot["mapping"]["fresh"] is False
