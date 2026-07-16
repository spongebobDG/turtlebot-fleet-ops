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
