"""Robot-local operating-profile manager tests without systemd mutation."""

from types import SimpleNamespace
import subprocess

from fleet_interfaces.msg import MappingStatus
from fleet_interfaces.srv import SaveMap, SetOperatingProfile
import rclpy
from rclpy.parameter import Parameter

from navigation_agent.profile_manager_node import ProfileManagerNode


def test_profile_transition_stops_both_units_before_start(monkeypatch):
    active = {"tb1-navigation.service"}
    calls = []

    def is_active(unit):
        return unit in active

    def systemctl(operation, *units):
        calls.append((operation, *units))
        if operation == "stop":
            active.difference_update(units)
        elif operation == "start":
            active.update(units)
        return True, "ok"

    monkeypatch.setattr(
        ProfileManagerNode,
        "_is_active",
        staticmethod(is_active),
    )
    monkeypatch.setattr(
        ProfileManagerNode,
        "_systemctl",
        staticmethod(systemctl),
    )
    rclpy.init()
    node = ProfileManagerNode()
    try:
        request = SetOperatingProfile.Request()
        request.profile = SetOperatingProfile.Request.PROFILE_MAPPING
        response = node._set_profile(
            request,
            SetOperatingProfile.Response(),
        )

        assert response.success
        assert response.active_profile == MappingStatus.PROFILE_MAPPING
        assert calls == [
            (
                "stop",
                "tb1-mapping.service",
                "tb1-navigation.service",
            ),
            ("start", "tb1-mapping.service"),
        ]
        assert active == {"tb1-mapping.service"}
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_map_save_requires_mapping_and_calls_fixed_script(
    monkeypatch,
    tmp_path,
):
    active = {"tb1-mapping.service"}
    script = tmp_path / "save-map.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    completed_calls = []

    monkeypatch.setattr(
        ProfileManagerNode,
        "_is_active",
        staticmethod(lambda unit: unit in active),
    )

    def run(arguments, **kwargs):
        completed_calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=0, stdout="saved", stderr="")

    monkeypatch.setattr(
        "navigation_agent.profile_manager_node.subprocess.run",
        run,
    )
    rclpy.init()
    node = ProfileManagerNode(
        parameter_overrides=[
            Parameter("map_file", value=str(tmp_path / "map.yaml")),
            Parameter("save_map_script", value=str(script)),
        ]
    )
    try:
        request = SaveMap.Request()
        response = node._save_map(request, SaveMap.Response())

        assert response.success
        assert response.message == "Map and pose graph saved and validated"
        assert node._message.startswith(
            "Map and pose graph saved and validated; completion_ns="
        )
        assert completed_calls[0][0] == ["/usr/bin/bash", str(script)]
        assert completed_calls[0][1]["timeout"] == 90
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_map_save_timeout_is_reported_in_status(monkeypatch, tmp_path):
    script = tmp_path / "save-map.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(
        ProfileManagerNode,
        "_is_active",
        staticmethod(lambda unit: unit == "tb1-mapping.service"),
    )

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("save-map.sh", 90)

    monkeypatch.setattr(
        "navigation_agent.profile_manager_node.subprocess.run",
        time_out,
    )
    rclpy.init()
    node = ProfileManagerNode(
        parameter_overrides=[
            Parameter("map_file", value=str(tmp_path / "map.yaml")),
            Parameter("save_map_script", value=str(script)),
        ]
    )
    try:
        response = node._save_map(SaveMap.Request(), SaveMap.Response())
        assert not response.success
        assert response.message == "Map save failed: save script timed out"
        assert node._message == response.message
    finally:
        node.destroy_node()
        rclpy.shutdown()
