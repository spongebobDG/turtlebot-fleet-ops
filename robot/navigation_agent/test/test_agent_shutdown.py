"""Regression tests for navigation agent process shutdown."""

from navigation_agent import agent_node
from navigation_agent.agent_node import NavigationAgent


def test_shutdown_skips_publish_after_ros_context_is_invalid(monkeypatch):
    """SIGTERM must not create an invalid-context traceback."""
    calls = []

    class StubAgent:
        def _publish_authorization(self, *, force):
            calls.append(("authorization", force))

        def _set_motion_mode_nowait(self, mode):
            calls.append(("mode", mode))

    monkeypatch.setattr(agent_node.rclpy, "ok", lambda: False)

    NavigationAgent.shutdown(StubAgent())

    assert calls == []
