"""Process entry point that runs ROS and FastAPI together."""

from pathlib import Path
import multiprocessing
import os
from queue import Empty
import threading
from typing import List, Optional

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import MultiThreadedExecutor
import uvicorn

from fleet_gateway.api import create_app
from fleet_gateway.log_ai import LocalLogAIAnalyzer
from fleet_gateway.operations import OperationsStore
from fleet_gateway.patrol_manager import PatrolManager
from fleet_gateway.ros_node import (
    FleetGatewayNode,
    run_pose_process,
    run_scan_process,
)
from fleet_gateway.task_manager import NavigationTaskManager


def main(args: Optional[List[str]] = None) -> None:
    """Start the ROS executor and serve the dashboard until shutdown."""
    rclpy.init(args=args)
    node = FleetGatewayNode()
    process_context = multiprocessing.get_context("spawn")
    telemetry_queue = process_context.Queue(maxsize=32)
    telemetry_stop = process_context.Event()
    telemetry_processes = [
        process_context.Process(
            target=target,
            args=(
                node.telemetry_configuration,
                telemetry_queue,
                telemetry_stop,
            ),
            name=name,
            daemon=True,
        )
        for target, name in (
            (run_scan_process, "fleet-gateway-scan"),
            (run_pose_process, "fleet-gateway-pose"),
        )
    ]
    for telemetry_process in telemetry_processes:
        telemetry_process.start()

    def receive_telemetry() -> None:
        while not telemetry_stop.is_set():
            try:
                kind, robot_id, snapshot = telemetry_queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                if kind == "scan":
                    node.scan_registry.update(robot_id, snapshot)
                elif kind == "map_pose":
                    node.registry.update_map_pose(snapshot)
            except ValueError as error:
                node.get_logger().error(
                    f"Rejected {robot_id} {kind} telemetry: {error}"
                )

    telemetry_thread = threading.Thread(
        target=receive_telemetry,
        name="fleet-gateway-telemetry-receiver",
        daemon=True,
    )
    telemetry_thread.start()
    database_path = Path(
        os.environ.get(
            "FLEET_OPERATIONS_DB",
            "~/.local/share/turtlebot-fleet-ops/operations.sqlite3",
        )
    ).expanduser()
    operations_store = OperationsStore(database_path)
    log_mlops_root = Path(
        os.environ.get(
            "FLEET_LOG_MLOPS_ROOT",
            "~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs",
        )
    ).expanduser()
    log_mlops_status_path = Path(
        os.environ.get(
            "FLEET_LOG_MLOPS_STATUS",
            "~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/"
            "status/latest.json",
        )
    ).expanduser()
    log_ai_analyzer = LocalLogAIAnalyzer(
        status_path=log_mlops_status_path,
        root=log_mlops_root,
        robot_snapshot=node.registry.snapshot,
        enabled=os.environ.get("FLEET_LOG_AI_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        base_url=os.environ.get(
            "FLEET_LOG_AI_BASE_URL",
            "http://127.0.0.1:11434",
        ),
        model=os.environ.get("FLEET_LOG_AI_MODEL", "qwen3:8b"),
        timeout_sec=float(os.environ.get("FLEET_LOG_AI_TIMEOUT_SEC", "90")),
        retention_days=int(
            os.environ.get("FLEET_LOG_AI_RETENTION_DAYS", "30")
        ),
    )
    recovered_tasks = operations_store.reconcile_gateway_restart()
    recovered_patrols = operations_store.reconcile_patrol_restart()
    if recovered_tasks:
        node.get_logger().warning(
            f"Failed {recovered_tasks} nonterminal task(s) "
            "after Gateway restart"
        )
    if recovered_patrols:
        node.get_logger().warning(
            f"Failed {recovered_patrols} nonterminal patrol(s) "
            "after Gateway restart"
        )
    node.registry.add_listener(operations_store.observe)
    task_manager = NavigationTaskManager(operations_store, node)
    patrol_manager = PatrolManager(
        operations_store,
        node,
        current_pose_provider=lambda robot_id: (
            ((node.registry.get(robot_id) or {}).get("navigation") or {}).get(
                "current"
            )
        ),
    )
    node.registry.add_listener(patrol_manager.observe)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    ros_thread = threading.Thread(
        target=executor.spin,
        name="fleet-gateway-ros",
        daemon=True,
    )
    ros_thread.start()

    share_dir = Path(get_package_share_directory("fleet_gateway"))
    app = create_app(
        registry=node.registry,
        estop_controller=node,
        navigation_controller=node,
        manual_controller=node,
        profile_controller=node,
        map_registry=node.map_registry,
        scan_registry=node.scan_registry,
        operations_store=operations_store,
        task_manager=task_manager,
        patrol_manager=patrol_manager,
        log_mlops_status_path=log_mlops_status_path,
        log_ai_analyzer=log_ai_analyzer,
        static_dir=share_dir / "web",
    )
    try:
        uvicorn.run(app, host=node.web_host, port=node.web_port)
    finally:
        patrol_manager.close()
        telemetry_stop.set()
        for telemetry_process in telemetry_processes:
            telemetry_process.join(timeout=3.0)
            if telemetry_process.is_alive():
                telemetry_process.terminate()
                telemetry_process.join(timeout=2.0)
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        telemetry_thread.join(timeout=2.0)
        telemetry_queue.close()
        telemetry_queue.join_thread()
        ros_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
