import threading

from fleet_interfaces.msg import RobotStatus

from navigation_agent.agent_node import NavigationAgent


class StubAgent:
    _robot_id = "tb1"
    _navigation_min_clearance_m = 0.20

    def __init__(self):
        self._lock = threading.RLock()
        self._robot_status = None
        self._robot_status_received_at = None
        self._active_command_id = ""
        self.stop_reasons = []

    def _request_stop(self, reason):
        self.stop_reasons.append(reason)

    def _scan_clearance_ready(self):
        return NavigationAgent._scan_clearance_ready(self)

    def _scan_clearance_failure(self):
        return NavigationAgent._scan_clearance_failure(self)


def scan_status(distance):
    status = RobotStatus()
    status.robot_id = "tb1"
    status.scan_received = True
    status.scan_fresh = True
    status.scan_valid = True
    status.scan_min_range = distance
    return status


def test_navigation_clearance_requires_fresh_valid_scan_above_limit():
    agent = StubAgent()

    NavigationAgent._on_robot_status(agent, scan_status(0.25))
    assert agent._scan_clearance_ready()

    NavigationAgent._on_robot_status(agent, scan_status(0.19))
    assert not agent._scan_clearance_ready()
    assert "0.190m < 0.200m" in agent._scan_clearance_failure()


def test_active_goal_is_stopped_when_clearance_falls_below_limit():
    agent = StubAgent()
    agent._active_command_id = "goal-1"

    NavigationAgent._on_robot_status(agent, scan_status(0.19))

    assert len(agent.stop_reasons) == 1
    assert "clearance fell below" in agent.stop_reasons[0]
