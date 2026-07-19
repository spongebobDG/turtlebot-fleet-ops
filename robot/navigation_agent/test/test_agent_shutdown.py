"""Regression tests for navigation agent process shutdown."""

from navigation_agent.agent_node import NavigationAgent, _cleanup_navigation_agent


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


def test_process_cleanup_tolerates_launch_interrupts(monkeypatch):
    """Concurrent launch shutdown must not escape as a child traceback."""
    calls = []

    class StubAgent:
        def shutdown(self):
            calls.append("shutdown")
            raise KeyboardInterrupt

        def destroy_node(self):
            calls.append("destroy")
            raise KeyboardInterrupt

    class StubExecutor:
        def remove_node(self, _node):
            calls.append("remove")
            raise RuntimeError("context closed")

        def shutdown(self):
            calls.append("executor")
            raise KeyboardInterrupt

    monkeypatch.setattr("navigation_agent.agent_node.rclpy.ok", lambda: True)

    def interrupted_shutdown():
        calls.append("rclpy")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "navigation_agent.agent_node.rclpy.shutdown", interrupted_shutdown
    )

    _cleanup_navigation_agent(StubAgent(), StubExecutor())

    assert calls == ["shutdown", "remove", "destroy", "executor", "rclpy"]
