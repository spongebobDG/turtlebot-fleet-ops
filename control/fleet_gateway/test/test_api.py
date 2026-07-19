from fastapi.testclient import TestClient
import pytest

from fleet_gateway.api import create_app
from fleet_gateway.map_registry import MapRegistry
from fleet_gateway.operations import OperationsStore
from fleet_gateway.registry import StatusRegistry
from fleet_gateway.scan_registry import ScanRegistry
from fleet_gateway.task_manager import NavigationTaskManager


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
        self.calls = []

    def set_initial_pose(self, robot_id, x, y, yaw):
        self.calls.append(("initial", robot_id, x, y, yaw))
        return {"success": True, "robot_id": robot_id, "message": "accepted"}

    def start_navigation(
        self,
        robot_id,
        x,
        y,
        yaw,
        confirm_warnings,
    ):
        self.calls.append(
            ("goal", robot_id, x, y, yaw, confirm_warnings)
        )
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": "goal-1",
            "message": "accepted",
        }

    def cancel_navigation(self, robot_id, command_id):
        self.calls.append(("cancel", robot_id, command_id))
        if command_id != "goal-1":
            return {
                "success": False,
                "robot_id": robot_id,
                "command_id": command_id,
                "status_code": 409,
                "message": "No matching active navigation goal",
            }
        return {
            "success": True,
            "robot_id": robot_id,
            "command_id": command_id,
            "message": "canceling",
        }


def make_registry():
    registry = StatusRegistry(clock=lambda: 10.0)
    registry.update(
        {"robot_id": "tb1", "hostname": "tb1", "level": 0},
        now=10.0,
    )
    return registry


def make_navigation_registry(level=0, active_command_id=""):
    registry = make_registry()
    registry.update(
        {
            "robot_id": "tb1",
            "hostname": "tb1",
            "level": level,
            "fault_codes": ["LOW_BATTERY"] if level == 1 else [],
        },
        now=10.0,
    )
    registry.update_navigation(
        {
            "robot_id": "tb1",
            "state": "ACTIVE" if active_command_id else "READY",
            "nav2_ready": True,
            "localization_ready": True,
            "safety_ready": True,
            "active_command_id": active_command_id,
            "current": {
                "frame_id": "map",
                "x": 0.25,
                "y": 0.25,
                "yaw": 0.0,
            },
        },
        now=10.0,
    )
    registry.update_safety(
        {
            "robot_id": "tb1",
            "estop_active": False,
            "motion_armed": True,
        },
        now=10.0,
    )
    return registry


def make_map_registry():
    registry = MapRegistry()
    registry.update(
        "tb1",
        {
            "frame_id": "map",
            "width": 2,
            "height": 2,
            "resolution": 1.0,
            "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "data": [0, 100, -1, 0],
        },
    )
    return registry


def make_scan_registry():
    registry = ScanRegistry()
    registry.update(
        "tb1",
        {
            "frame_id": "base_scan",
            "points": [[0.5, 0.0]],
            "valid_points": 1,
        },
    )
    return registry


def make_dense_scan_registry():
    registry = ScanRegistry()
    registry.update(
        "tb1",
        {
            "frame_id": "base_scan",
            "points": [[0.5, index * 0.01] for index in range(40)],
            "valid_points": 40,
        },
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


def test_scan_route_is_separate_from_robot_snapshot():
    registry = make_registry()
    client = TestClient(
        create_app(registry, scan_registry=make_scan_registry())
    )

    response = client.get("/api/robots/tb1/scan")

    assert response.status_code == 200
    assert response.json()["frame_id"] == "base_scan"
    assert response.json()["points"] == [[0.5, 0.0]]
    assert "points" not in client.get("/api/robots/tb1").json().get(
        "scan", {}
    )


def test_lidar_auto_alignment_route_returns_verified_candidate(monkeypatch):
    result = {
        "pose": {"x": 0.25, "y": 0.25, "yaw": 0.1},
        "score": 0.8,
        "matched_ratio": 0.85,
        "inside_ratio": 1.0,
        "point_count": 40,
        "acceptable": True,
        "seed": {},
    }
    monkeypatch.setattr("fleet_gateway.api.align_pose", lambda *args: result)
    client = TestClient(
        create_app(
            make_registry(),
            map_registry=make_map_registry(),
            scan_registry=make_dense_scan_registry(),
        )
    )

    response = client.post(
        "/api/robots/tb1/localization/align-pose",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )

    assert response.status_code == 200
    assert response.json()["pose"]["yaw"] == 0.1


def test_initial_pose_rejects_weak_lidar_map_alignment(monkeypatch):
    weak = {
        "score": 0.0,
        "matched_ratio": 0.05,
        "inside_ratio": 0.5,
        "point_count": 40,
        "acceptable": False,
    }
    monkeypatch.setattr(
        "fleet_gateway.api.score_pose_alignment",
        lambda *args: weak,
    )
    controller = FakeNavigationController()
    client = TestClient(
        create_app(
            make_registry(),
            navigation_controller=controller,
            map_registry=make_map_registry(),
            scan_registry=make_dense_scan_registry(),
        )
    )

    response = client.put(
        "/api/robots/tb1/localization/initial-pose",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )

    assert response.status_code == 422
    assert "run LiDAR auto alignment" in response.json()["detail"]
    assert controller.calls == []


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
    (source_dir / "map_math.js").write_text("globalThis.FleetMapMath = {};")
    (source_dir / "map_viewport.js").write_text(
        "globalThis.FleetMapViewport = {};"
    )
    for name in (
        "index.html",
        "styles.css",
        "app.js",
        "map_math.js",
        "map_viewport.js",
    ):
        try:
            (static_dir / name).symlink_to(source_dir / name)
        except OSError:
            pytest.skip("symbolic links are not permitted on this platform")

    client = TestClient(create_app(make_registry(), static_dir=static_dir))

    assert client.get("/").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/map_math.js").status_code == 200
    assert client.get("/static/map_viewport.js").status_code == 200
    assert client.get("/static/secret.txt").status_code == 404


def test_dashboard_serves_map_math_from_regular_install(tmp_path):
    for name, content in {
        "index.html": "<h1>Fleet</h1>",
        "styles.css": "body {}",
        "app.js": "console.log('fleet');",
        "map_math.js": "globalThis.FleetMapMath = {};",
        "map_viewport.js": "globalThis.FleetMapViewport = {};",
    }.items():
        (tmp_path / name).write_text(content)
    client = TestClient(create_app(make_registry(), static_dir=tmp_path))

    assert client.get("/static/map_math.js").status_code == 200
    assert client.get("/static/map_viewport.js").status_code == 200
    assert client.get("/static/not-allowed.js").status_code == 404


def test_ros2_log_mlops_status_route_is_fail_visible(tmp_path):
    status_path = tmp_path / "latest.json"
    client = TestClient(
        create_app(make_registry(), log_mlops_status_path=status_path)
    )

    missing = client.get("/api/mlops/ros2-logs")
    status_path.write_text(
        '{"state":"NORMAL","model_id":"model-1","score":0.5,'
        '"observed_at":"2999-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    available = client.get("/api/mlops/ros2-logs")

    assert missing.status_code == 200
    assert missing.json()["state"] == "MODEL_NOT_READY"
    assert available.json()["state"] == "NORMAL"
    assert available.json()["model_id"] == "model-1"


def test_navigation_map_initial_pose_goal_and_cancel_routes():
    controller = FakeNavigationController()
    app = create_app(
        make_navigation_registry(),
        navigation_controller=controller,
        map_registry=make_map_registry(),
    )
    client = TestClient(app)

    map_response = client.get("/api/robots/tb1/map")
    initial = client.put(
        "/api/robots/tb1/localization/initial-pose",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )
    goal = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 1.0},
    )
    cancel = client.delete(
        "/api/robots/tb1/navigation/goals/goal-1"
    )

    assert map_response.status_code == 200
    assert initial.status_code == 202
    assert goal.status_code == 202
    assert goal.json()["command_id"] == "goal-1"
    assert cancel.status_code == 202
    assert [call[0] for call in controller.calls] == [
        "initial",
        "goal",
        "cancel",
    ]


def test_navigation_goal_requires_warning_confirmation():
    controller = FakeNavigationController()
    client = TestClient(
        create_app(
            make_navigation_registry(level=1),
            navigation_controller=controller,
            map_registry=make_map_registry(),
        )
    )

    blocked = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )
    accepted = client.post(
        "/api/robots/tb1/navigation/goals",
        json={
            "x": 0.25,
            "y": 0.25,
            "yaw": 0.0,
            "confirm_warnings": True,
        },
    )

    assert blocked.status_code == 409
    assert "LOW_BATTERY" in blocked.json()["detail"]
    assert accepted.status_code == 202


def test_navigation_rejects_active_goal_and_non_free_cells():
    controller = FakeNavigationController()
    active_client = TestClient(
        create_app(
            make_navigation_registry(active_command_id="existing"),
            navigation_controller=controller,
            map_registry=make_map_registry(),
        )
    )
    free_client = TestClient(
        create_app(
            make_navigation_registry(),
            navigation_controller=controller,
            map_registry=make_map_registry(),
        )
    )

    active = active_client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )
    occupied = free_client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 1.25, "y": 0.25, "yaw": 0.0},
    )
    unknown = free_client.put(
        "/api/robots/tb1/localization/initial-pose",
        json={"x": 0.25, "y": 1.25, "yaw": 0.0},
    )

    assert active.status_code == 409
    assert occupied.status_code == 422
    assert unknown.status_code == 422


def test_navigation_rejects_nonfinite_pose_and_wrong_command_id():
    controller = FakeNavigationController()
    client = TestClient(
        create_app(
            make_navigation_registry(),
            navigation_controller=controller,
            map_registry=make_map_registry(),
        )
    )

    nonfinite = client.post(
        "/api/robots/tb1/navigation/goals",
        data='{"x": NaN, "y": 0.25, "yaw": 0.0}',
        headers={"Content-Type": "application/json"},
    )
    wrong_cancel = client.delete(
        "/api/robots/tb1/navigation/goals/wrong-command"
    )

    assert nonfinite.status_code == 422
    assert wrong_cancel.status_code == 409


@pytest.mark.parametrize(
    ("blocker", "expected_detail"),
    [
        ("offline", "offline"),
        ("error", "active error"),
        ("nav2", "Nav2 is not ready"),
        ("localization", "Localization is not ready"),
        ("navigation_safety", "Motion safety is not ready"),
        ("estop", "Emergency stop is active"),
        ("unarmed", "Motion is not armed"),
    ],
)
def test_navigation_rejects_every_fail_closed_readiness_state(
    blocker,
    expected_detail,
):
    if blocker == "offline":
        registry = StatusRegistry(clock=lambda: 20.0)
        registry.update(
            {"robot_id": "tb1", "level": 0, "fault_codes": []},
            now=10.0,
        )
    else:
        registry = make_navigation_registry(
            level=2 if blocker == "error" else 0
        )
        navigation = {
            "robot_id": "tb1",
            "state": "READY",
            "nav2_ready": blocker != "nav2",
            "localization_ready": blocker != "localization",
            "safety_ready": blocker != "navigation_safety",
            "active_command_id": "",
        }
        safety = {
            "robot_id": "tb1",
            "estop_active": blocker == "estop",
            "motion_armed": blocker != "unarmed",
        }
        registry.update_navigation(navigation, now=10.0)
        registry.update_safety(safety, now=10.0)
    client = TestClient(
        create_app(
            registry,
            navigation_controller=FakeNavigationController(),
            map_registry=make_map_registry(),
        )
    )

    response = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )

    assert response.status_code == 409
    assert expected_detail in response.json()["detail"]


def test_invalid_map_pose_remains_422_when_robot_is_offline():
    registry = StatusRegistry(clock=lambda: 20.0)
    registry.update(
        {"robot_id": "tb1", "level": 0, "fault_codes": []},
        now=10.0,
    )
    client = TestClient(
        create_app(
            registry,
            navigation_controller=FakeNavigationController(),
            map_registry=make_map_registry(),
        )
    )

    response = client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 1.25, "y": 0.25, "yaw": 0.0},
    )

    assert response.status_code == 422


def test_navigation_rejects_stale_navigation_and_safety_status():
    stale_registry = StatusRegistry(clock=lambda: 14.0)
    stale_registry.update(
        {"robot_id": "tb1", "level": 0, "fault_codes": []},
        now=14.0,
    )
    stale_registry.update_navigation(
        {
            "robot_id": "tb1",
            "nav2_ready": True,
            "localization_ready": True,
            "safety_ready": True,
            "active_command_id": "",
        },
        now=10.0,
    )
    stale_registry.update_safety(
        {
            "robot_id": "tb1",
            "estop_active": False,
            "motion_armed": True,
        },
        now=14.0,
    )
    stale_client = TestClient(
        create_app(
            stale_registry,
            navigation_controller=FakeNavigationController(),
            map_registry=make_map_registry(),
        )
    )

    blocked = stale_client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )

    assert blocked.status_code == 409
    assert "stale" in blocked.json()["detail"]

    stale_registry.update_navigation(
        {
            "robot_id": "tb1",
            "nav2_ready": True,
            "localization_ready": True,
            "safety_ready": True,
            "active_command_id": "",
        },
        now=14.0,
    )
    stale_registry.update_safety(
        {
            "robot_id": "tb1",
            "estop_active": False,
            "motion_armed": True,
        },
        now=10.0,
    )

    blocked = stale_client.post(
        "/api/robots/tb1/navigation/goals",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    )

    assert blocked.status_code == 409
    assert "Safety status" in blocked.json()["detail"]


def test_task_fault_and_audit_routes(tmp_path):
    registry = make_navigation_registry()
    store = OperationsStore(tmp_path / "operations.sqlite3")
    registry.add_listener(store.observe)
    registry.update(
        {
            "robot_id": "tb1",
            "hostname": "tb1",
            "level": 1,
            "fault_codes": ["LOW_BATTERY"],
        },
        now=10.0,
    )
    controller = FakeNavigationController()
    manager = NavigationTaskManager(store, controller)
    client = TestClient(
        create_app(
            registry,
            navigation_controller=controller,
            map_registry=make_map_registry(),
            operations_store=store,
            task_manager=manager,
        )
    )

    created = client.post(
        "/api/robots/tb1/tasks",
        json={
            "x": 0.25,
            "y": 0.25,
            "yaw": 0.0,
            "confirm_warnings": True,
        },
    )
    task_id = created.json()["task_id"]
    started = client.post(f"/api/tasks/{task_id}/run")
    canceled = client.delete(f"/api/tasks/{task_id}")
    retried = client.post(f"/api/tasks/{task_id}/retry")

    assert created.status_code == 201
    assert started.status_code == 202
    assert started.json()["state"] == "ACTIVE"
    assert canceled.status_code == 202
    assert canceled.json()["state"] == "CANCELED"
    assert retried.status_code == 201
    assert retried.json()["attempt"] == 2
    assert client.get("/api/tasks").json()["tasks"]
    assert client.get(f"/api/tasks/{task_id}").status_code == 200
    assert client.get("/api/robots/tb1/faults").json()["faults"][0][
        "fault_code"
    ] == "LOW_BATTERY"
    assert client.get("/api/events?robot_id=tb1").json()["events"]


def test_task_routes_reject_invalid_transitions_and_unavailable_store(
    tmp_path,
):
    registry = make_navigation_registry()
    controller = FakeNavigationController()
    store = OperationsStore(tmp_path / "operations.sqlite3")
    manager = NavigationTaskManager(store, controller)
    client = TestClient(
        create_app(
            registry,
            navigation_controller=controller,
            map_registry=make_map_registry(),
            operations_store=store,
            task_manager=manager,
        )
    )
    created = client.post(
        "/api/robots/tb1/tasks",
        json={"x": 0.25, "y": 0.25, "yaw": 0.0},
    ).json()

    retry_response = client.post(
        f"/api/tasks/{created['task_id']}/retry"
    )
    assert retry_response.status_code == 409
    assert client.get("/api/tasks/missing").status_code == 404
    unavailable = TestClient(create_app(registry)).get("/api/events")
    assert unavailable.status_code == 503
