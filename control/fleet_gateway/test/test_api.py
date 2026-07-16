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
