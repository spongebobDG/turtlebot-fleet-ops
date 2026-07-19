"""Regression tests for navigation agent process shutdown."""

from navigation_agent.agent_node import NavigationAgent


def test_shutdown_skips_publish_after_ros_context_is_invalid(monkeypatch):
    """SIGTERM must not create an invalid-context traceback."""
    calls = []

    class StubAgent:
        class Context:
            @staticmethod
            def ok():
                return False

        context = Context()

        def _publish_authorization(self, *, force):
            calls.append(("authorization", force))

        def _set_motion_mode_nowait(self, mode):
            calls.append(("mode", mode))

    NavigationAgent.shutdown(StubAgent())

    assert calls == []
