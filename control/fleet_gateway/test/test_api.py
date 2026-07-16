from fastapi.testclient import TestClient

from fleet_gateway.api import create_app
from fleet_gateway.registry import StatusRegistry


class FakeEStopController:

    def __init__(self):
        self.calls = []

    def set_estop(self, robot_id, engaged):
        self.calls.append((robot_id, engaged))
        return {
            "success": True,
            "robot_id": robot_id,
            "engaged": engaged,
            "message": "accepted",
        }


class FakeNavigationController:

    def __init__(self):
        self.goal_calls = []
        self.cancel_calls = []
        self.retry_calls = []
        self.retry_result = None
        self.current = None

    def send_navigation_goal(self, robot_id, target, timeout_sec):
        self.goal_calls.append((robot_id, target, timeout_sec))
        self.current = {
            "robot_id": robot_id,
            "goal_id": "goal-1",
            "target": target,
            "status": "RUNNING",
            "feedback": {},
        }
        return {"success": True, **self.current}

    def cancel_navigation(self, robot_id):
        self.cancel_calls.append(robot_id)
        if self.current is not None:
            self.current["status"] = "CANCELING"
        return {
            "success": True,
            "robot_id": robot_id,
            "status": "CANCELING",
        }

    def retry_navigation(self, robot_id):
        self.retry_calls.append(robot_id)
        if self.retry_result is not None:
            return dict(self.retry_result)
        previous = self.current or {}
        self.current = {
            "robot_id": robot_id,
            "goal_id": "goal-retry",
            "target": previous.get("target", {}),
            "status": "RUNNING",
            "feedback": {},
            "retry_count": 1,
            "retried_from_goal_id": previous.get("goal_id"),
        }
        return {"success": True, **self.current}

    def get_navigation(self, robot_id):
        if self.current is None or self.current["robot_id"] != robot_id:
            return None
        return dict(self.current)

    def navigation_snapshot(self):
        return [] if self.current is None else [dict(self.current)]


def make_registry():
    registry = StatusRegistry(clock=lambda: 10.0)
    registry.update(
        {"robot_id": "tb1", "hostname": "tb1", "level": 0},
        now=10.0,
    )
    return registry


def test_health_and_robot_routes():
    client = TestClient(create_app(make_registry()))

    health = client.get("/api/health")
    robots = client.get("/api/robots")
    missing = client.get("/api/robots/missing")

    assert health.status_code == 200
    assert health.json()["online_robots"] == 1
    assert robots.json()["robots"][0]["robot_id"] == "tb1"
    assert missing.status_code == 404


def test_estop_route_calls_controller():
    controller = FakeEStopController()
    app = create_app(make_registry(), estop_controller=controller)
    client = TestClient(app)

    response = client.post(
        "/api/robots/tb1/estop",
        json={"engaged": True},
    )

    assert response.status_code == 200
    assert response.json()["engaged"] is True
    assert controller.calls == [("tb1", True)]


def test_estop_engage_also_cancels_navigation_goal():
    estop = FakeEStopController()
    navigation = FakeNavigationController()
    navigation.send_navigation_goal(
        "tb1",
        {"x": 1.0, "y": 0.0, "yaw": 0.0, "frame_id": "map"},
        30.0,
    )
    client = TestClient(
        create_app(
            make_registry(),
            estop_controller=estop,
            navigation_controller=navigation,
        )
    )

    response = client.post(
        "/api/robots/tb1/estop",
        json={"engaged": True},
    )

    assert response.status_code == 200
    assert response.json()["navigation_cancel"]["success"] is True
    assert navigation.cancel_calls == ["tb1"]


def test_estop_release_is_rejected_while_navigation_is_active():
    navigation = FakeNavigationController()
    navigation.send_navigation_goal(
        "tb1",
        {"x": 1.0, "y": 0.0, "yaw": 0.0, "frame_id": "map"},
        30.0,
    )
    client = TestClient(
        create_app(
            make_registry(),
            estop_controller=FakeEStopController(),
            navigation_controller=navigation,
        )
    )

    response = client.post(
        "/api/robots/tb1/estop",
        json={"engaged": False},
    )

    assert response.status_code == 409


def test_estop_route_is_unavailable_without_controller():
    client = TestClient(create_app(make_registry()))
    response = client.post(
        "/api/robots/tb1/estop",
        json={"engaged": True},
    )
    assert response.status_code == 503


def test_estop_release_is_rejected_when_robot_is_offline():
    registry = StatusRegistry(online_timeout_sec=3.0, clock=lambda: 20.0)
    registry.update({"robot_id": "tb1", "level": 0}, now=10.0)
    controller = FakeEStopController()
    client = TestClient(
        create_app(registry, estop_controller=controller)
    )

    response = client.post(
        "/api/robots/tb1/estop",
        json={"engaged": False},
    )

    assert response.status_code == 409
    assert controller.calls == []


def test_websocket_sends_current_snapshot():
    app = create_app(make_registry(), websocket_interval_sec=0.01)
    client = TestClient(app)

    with client.websocket_connect("/ws/robots") as websocket:
        message = websocket.receive_json()

    assert message["robots"][0]["robot_id"] == "tb1"
    assert message["robots"][0]["online"] is True


def test_navigation_goal_status_and_cancel_routes():
    navigation = FakeNavigationController()
    client = TestClient(
        create_app(make_registry(), navigation_controller=navigation)
    )

    sent = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 1.5, "y": -0.2, "yaw": 0.4, "timeout_sec": 20},
    )
    status = client.get("/api/robots/tb1/navigation")
    canceled = client.post("/api/robots/tb1/navigation/cancel")

    assert sent.status_code == 202
    assert sent.json()["goal_id"] == "goal-1"
    assert navigation.goal_calls[0][1]["frame_id"] == "map"
    assert status.json()["status"] == "RUNNING"
    assert canceled.status_code == 200
    assert navigation.cancel_calls == ["tb1"]


def test_navigation_retry_route_returns_goal_lineage():
    navigation = FakeNavigationController()
    navigation.send_navigation_goal(
        "tb1",
        {"x": 1.0, "y": 0.0, "yaw": 0.0, "frame_id": "map"},
        30.0,
    )
    navigation.current["status"] = "ABORTED"
    client = TestClient(
        create_app(make_registry(), navigation_controller=navigation)
    )

    response = client.post("/api/robots/tb1/navigation/retry")

    assert response.status_code == 202
    assert response.json()["retry_count"] == 1
    assert response.json()["retried_from_goal_id"] == "goal-1"
    assert navigation.retry_calls == ["tb1"]


def test_navigation_retry_safety_conflict_returns_409():
    navigation = FakeNavigationController()
    navigation.retry_result = {
        "success": False,
        "robot_id": "tb1",
        "code": "estop_active",
        "message": "release emergency stop",
    }
    client = TestClient(
        create_app(make_registry(), navigation_controller=navigation)
    )

    response = client.post("/api/robots/tb1/navigation/retry")

    assert response.status_code == 409
    assert navigation.retry_calls == ["tb1"]


def test_navigation_goal_rejects_invalid_frame_and_non_finite_value():
    navigation = FakeNavigationController()
    client = TestClient(
        create_app(make_registry(), navigation_controller=navigation)
    )

    wrong_frame = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 1.0, "y": 0.0, "frame_id": "odom"},
    )
    non_finite = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": "NaN", "y": 0.0},
    )

    assert wrong_frame.status_code == 422
    assert non_finite.status_code == 422
    assert navigation.goal_calls == []


def test_navigation_goal_rejects_offline_robot():
    registry = StatusRegistry(online_timeout_sec=3.0, clock=lambda: 20.0)
    registry.update({"robot_id": "tb1", "level": 0}, now=10.0)
    navigation = FakeNavigationController()
    client = TestClient(
        create_app(registry, navigation_controller=navigation)
    )

    response = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 1.0, "y": 0.0},
    )

    assert response.status_code == 409
    assert navigation.goal_calls == []


def test_websocket_includes_navigation_state():
    navigation = FakeNavigationController()
    navigation.send_navigation_goal(
        "tb1",
        {"x": 1.0, "y": 0.0, "yaw": 0.0, "frame_id": "map"},
        30.0,
    )
    app = create_app(
        make_registry(),
        navigation_controller=navigation,
        websocket_interval_sec=0.01,
    )
    client = TestClient(app)

    with client.websocket_connect("/ws/robots") as websocket:
        message = websocket.receive_json()

    assert message["navigation"][0]["status"] == "RUNNING"


def test_dashboard_assets_work_with_symlink_install(tmp_path):
    source_dir = tmp_path / "source"
    static_dir = tmp_path / "install"
    source_dir.mkdir()
    static_dir.mkdir()
    (source_dir / "index.html").write_text("<h1>Fleet</h1>")
    (source_dir / "styles.css").write_text("body { color: white; }")
    (source_dir / "app.js").write_text("console.log('fleet');")
    for name in ("index.html", "styles.css", "app.js"):
        (static_dir / name).symlink_to(source_dir / name)

    client = TestClient(create_app(make_registry(), static_dir=static_dir))

    assert client.get("/").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/secret.txt").status_code == 404
