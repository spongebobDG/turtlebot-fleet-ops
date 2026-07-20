"""ROS 2 /rosout collector and live log-anomaly inference node."""

from collections import deque
from functools import partial
import json
import math
import os
from pathlib import Path
import re
import subprocess
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
    read_recent_jsonl,
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

SYSLOG_SEVERITIES = {
    0: "ERROR",
    1: "ERROR",
    2: "ERROR",
    3: "ERROR",
    4: "WARNING",
    5: "INFO",
    6: "INFO",
    7: "DEBUG",
}

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _journal_message(value: Any) -> str:
    """Decode journald text, including byte arrays used for ANSI output."""
    if isinstance(value, list):
        try:
            value = bytes(int(item) for item in value).decode(
                "utf-8",
                errors="replace",
            )
        except (TypeError, ValueError):
            return ""
    return ANSI_ESCAPE.sub("", str(value or "")).strip()


def rosout_message_to_record(
    message: Any,
    received_at: Optional[float] = None,
    unit: str = "rosout",
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
        unit=unit,
    )


def journal_payload_to_record(payload: Dict[str, Any]) -> Optional[LogRecord]:
    """Normalize one `journalctl --output=json` record."""
    message = _journal_message(payload.get("MESSAGE"))
    if not message:
        return None
    try:
        timestamp = int(payload["__REALTIME_TIMESTAMP"]) / 1_000_000.0
    except (KeyError, TypeError, ValueError):
        return None
    try:
        priority = int(payload.get("PRIORITY", 6))
    except (TypeError, ValueError):
        priority = 6
    severity = SYSLOG_SEVERITIES.get(priority, "INFO")
    embedded_level = re.search(r"\b(ERROR|WARN(?:ING)?)\b", message, re.I)
    if embedded_level is not None:
        severity = (
            "ERROR"
            if embedded_level.group(1).upper() == "ERROR"
            else "WARNING"
        )
    unit = str(
        payload.get("_SYSTEMD_USER_UNIT")
        or payload.get("_SYSTEMD_UNIT")
        or "journal"
    )
    logger = str(
        payload.get("SYSLOG_IDENTIFIER")
        or payload.get("_COMM")
        or unit
    )
    return LogRecord(
        timestamp=timestamp,
        severity=severity,
        logger=logger,
        message=message,
        unit=unit,
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
        self._journal_units = tuple(
            value.strip()
            for value in os.environ.get(
                "FLEET_LOG_MLOPS_JOURNAL_UNITS",
                "fleet-control-zenoh.service",
            ).split(",")
            if value.strip()
        )
        self._journal_since_usec = time.time_ns() // 1000 - 1_000_000
        self._journal_seen_order: Deque[str] = deque()
        self._journal_seen = set()
        self._model: Optional[Dict[str, Any]] = None
        self._model_mtime_ns: Optional[int] = None
        qos = QoSProfile(
            depth=500,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._log_subscriptions = [
            self.create_subscription(
                Log,
                topic,
                partial(self._on_log, source=source),
                qos,
            )
            for topic, source in (
                ("/fleet/rosout", "tb1_rosout"),
                ("/rosout", "control_rosout"),
            )
        ]
        self.create_timer(15.0, self._publish_inference)
        self.create_timer(2.0, self._poll_journal)
        self._restore_recent_records()
        self._publish_inference()

    def _restore_recent_records(self) -> None:
        """Keep the recent analysis window across monitor restarts."""
        candidates = sorted(self._paths["raw"].glob("live-*.jsonl"))[-2:]
        cutoff = time.time() - self._lookback_sec
        self._records.extend(read_recent_jsonl(candidates, cutoff))

    def _on_log(self, message: Log, source: str = "rosout") -> None:
        record = rosout_message_to_record(message, unit=source)
        self._store_record(record)

    def _store_record(self, record: LogRecord) -> None:
        """Persist one normalized record and retain it for live inference."""
        self._records.append(record)
        self._append_raw(record)
        self._trim_records(time.time())

    def _poll_journal(self) -> None:
        """Collect control-bridge warnings that are outside ROS `/rosout`."""
        if not self._journal_units:
            return
        poll_started_usec = time.time_ns() // 1000
        command = [
            "journalctl",
            "--user",
            "--no-pager",
            "--output=json",
            "--since",
            f"@{self._journal_since_usec / 1_000_000.0:.6f}",
        ]
        for unit in self._journal_units:
            command.extend(("--unit", unit))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if completed.returncode != 0:
            return
        for line in completed.stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            cursor = str(payload.get("__CURSOR") or "")
            if cursor and cursor in self._journal_seen:
                continue
            record = journal_payload_to_record(payload)
            if record is None or record.severity not in {"WARNING", "ERROR"}:
                continue
            self._store_record(record)
            if cursor:
                self._journal_seen.add(cursor)
                self._journal_seen_order.append(cursor)
                while len(self._journal_seen_order) > 2048:
                    self._journal_seen.discard(
                        self._journal_seen_order.popleft()
                    )
        # Keep one second of overlap so records committed while journalctl was
        # running are picked up on the next poll. Journal cursors deduplicate
        # that overlap without relying on message text.
        self._journal_since_usec = max(
            self._journal_since_usec,
            poll_started_usec - 1_000_000,
        )

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
