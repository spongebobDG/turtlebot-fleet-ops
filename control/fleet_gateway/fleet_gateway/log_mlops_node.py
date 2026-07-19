"""ROS 2 /rosout collector and live log-anomaly inference node."""

from collections import deque
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Deque, Dict, Optional

import rclpy
from rcl_interfaces.msg import Log
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from fleet_gateway.log_mlops import (
    LogRecord,
    analyze_records,
    model_not_ready_status,
    pipeline_paths,
    read_json,
    write_json,
)


SEVERITIES = {
    10: "DEBUG",
    20: "INFO",
    30: "WARNING",
    40: "ERROR",
    50: "ERROR",
}


def rosout_message_to_record(
    message: Any,
    received_at: Optional[float] = None,
) -> LogRecord:
    """Normalize an rcl_interfaces/Log-like message without ROS coupling."""
    timestamp = float(message.stamp.sec) + float(message.stamp.nanosec) / 1e9
    if not math.isfinite(timestamp) or timestamp <= 0:
        timestamp = time.time() if received_at is None else float(received_at)
    return LogRecord(
        timestamp=timestamp,
        severity=SEVERITIES.get(int(message.level), "INFO"),
        logger=str(message.name),
        message=str(message.msg),
        unit="rosout",
    )


class RosoutMlopsNode(Node):
    """Persist /rosout records and publish explainable inference state."""

    def __init__(self) -> None:
        super().__init__("ros2_log_mlops")
        self._root = Path(
            os.environ.get(
                "FLEET_LOG_MLOPS_ROOT",
                "~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs",
            )
        ).expanduser()
        self._paths = pipeline_paths(self._root)
        self._lookback_sec = max(
            60.0,
            float(os.environ.get("FLEET_LOG_MLOPS_LOOKBACK_SEC", "300")),
        )
        self._records: Deque[LogRecord] = deque()
        self._model: Optional[Dict[str, Any]] = None
        self._model_mtime_ns: Optional[int] = None
        qos = QoSProfile(
            depth=500,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(Log, "/fleet/rosout", self._on_log, qos)
        self.create_timer(15.0, self._publish_inference)
        write_json(self._paths["status"], model_not_ready_status())

    def _on_log(self, message: Log) -> None:
        record = rosout_message_to_record(message)
        self._records.append(record)
        self._append_raw(record)
        self._trim_records(time.time())

    def _append_raw(self, record: LogRecord) -> None:
        day = time.strftime("%Y%m%d", time.gmtime(record.timestamp))
        path = self._paths["raw"] / f"live-{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": record.timestamp,
            "severity": record.severity,
            "logger": record.logger,
            "message": record.message,
            "unit": record.unit,
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _trim_records(self, now: float) -> None:
        cutoff = now - self._lookback_sec
        while self._records and self._records[0].timestamp < cutoff:
            self._records.popleft()

    def _reload_model(self) -> None:
        path = self._paths["production"]
        if not path.is_file():
            self._model = None
            self._model_mtime_ns = None
            return
        mtime_ns = path.stat().st_mtime_ns
        if mtime_ns != self._model_mtime_ns:
            self._model = read_json(path)
            self._model_mtime_ns = mtime_ns

    def _publish_inference(self) -> None:
        try:
            self._trim_records(time.time())
            self._reload_model()
            status = analyze_records(list(self._records), self._model)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            status = {
                **model_not_ready_status(),
                "state": "ERROR",
                "message": f"ROS 2 로그 추론 실패: {error}",
            }
        write_json(self._paths["status"], status)


def main() -> None:
    """Run the /rosout collection and inference node."""
    rclpy.init()
    node = RosoutMlopsNode()
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    finally:
        try:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except (ExternalShutdownException, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
