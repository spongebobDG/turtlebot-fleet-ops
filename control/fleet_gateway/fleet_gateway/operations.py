"""Persistent TB1 task, fault and audit-event storage."""

from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Mapping, Optional
import uuid


TERMINAL_TASK_STATES = {"SUCCEEDED", "CANCELED", "FAILED"}


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp suitable for sorting."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class OperationsStore:
    """Store operational events, faults and navigation tasks in SQLite."""

    def __init__(self, database_path: Path) -> None:
        """Open or initialize one durable operations database."""
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connectivity_states: Dict[str, bool] = {}
        self._observed_navigation_commands: Dict[str, str] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    robot_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    task_id TEXT,
                    command_id TEXT,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_robot_time
                    ON events(robot_id, id DESC);

                CREATE TABLE IF NOT EXISTS faults (
                    robot_id TEXT NOT NULL,
                    fault_code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    cleared_at TEXT,
                    PRIMARY KEY (robot_id, fault_code)
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    robot_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    yaw REAL NOT NULL,
                    confirm_warnings INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    parent_task_id TEXT,
                    command_id TEXT,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_robot_time
                    ON tasks(robot_id, updated_at DESC);
                """
            )
            connection.commit()

    def record_event(
        self,
        robot_id: str,
        category: str,
        event_type: str,
        message: str,
        severity: str = "INFO",
        task_id: Optional[str] = None,
        command_id: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """Append an audit event and return its database identifier."""
        occurred_at = _utc_now()
        payload = json.dumps(dict(details or {}), sort_keys=True)
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO events (
                    occurred_at, robot_id, category, event_type, severity,
                    task_id, command_id, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurred_at,
                    robot_id,
                    category,
                    event_type,
                    severity,
                    task_id,
                    command_id,
                    message,
                    payload,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_events(
        self,
        robot_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return newest audit events, optionally restricted to one robot."""
        bounded_limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM events"
        values: List[Any] = []
        if robot_id:
            query += " WHERE robot_id = ?"
            values.append(robot_id)
        query += " ORDER BY id DESC LIMIT ?"
        values.append(bounded_limit)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._event_dict(row) for row in rows]

    def observe(self, kind: str, status: Mapping[str, Any]) -> None:
        """Consume a registry update without changing ROS callback behavior."""
        if kind == "robot":
            self.sync_faults(status)
        elif kind == "navigation":
            self.sync_navigation(status)

    def sync_connectivity(self, status: Mapping[str, Any]) -> None:
        """Record heartbeat-derived offline and recovery transitions once."""
        robot_id = str(status.get("robot_id", "")).strip()
        if not robot_id or "online" not in status:
            return
        online = bool(status["online"])
        with self._lock:
            previous = self._connectivity_states.get(robot_id)
            self._connectivity_states[robot_id] = online
        if previous is None or previous == online:
            return
        if online:
            self.record_event(
                robot_id,
                "CONNECTIVITY",
                "ROBOT_ONLINE",
                "로봇 heartbeat가 복구되었습니다",
                details={"heartbeat_age_sec": status.get("heartbeat_age_sec")},
            )
            return
        self.record_event(
            robot_id,
            "CONNECTIVITY",
            "ROBOT_OFFLINE",
            "로봇 heartbeat가 끊겼습니다 (전원·네트워크·Agent 중단 가능)",
            severity="ERROR",
            details={"heartbeat_age_sec": status.get("heartbeat_age_sec")},
        )

    def register_navigation_command(
        self,
        robot_id: str,
        command_id: str,
    ) -> None:
        """Correlate a newly accepted task before its next status update."""
        if not robot_id or not command_id:
            return
        with self._lock:
            self._observed_navigation_commands[robot_id] = command_id

    def sync_faults(self, status: Mapping[str, Any]) -> None:
        """Persist activation, severity change and clear transitions."""
        robot_id = str(status.get("robot_id", "")).strip()
        if not robot_id:
            return
        level = int(status.get("level", 0))
        severity = "ERROR" if level >= 2 else "WARN"
        current = {str(code) for code in status.get("fault_codes", []) if code}
        now = _utc_now()
        transitions = []
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM faults WHERE robot_id = ?",
                (robot_id,),
            ).fetchall()
            known = {str(row["fault_code"]): row for row in rows}
            for code in sorted(current):
                previous = known.get(code)
                if previous is None:
                    connection.execute(
                        """
                        INSERT INTO faults VALUES (?, ?, ?, 1, ?, ?, NULL)
                        """,
                        (robot_id, code, severity, now, now),
                    )
                    transitions.append(("FAULT_ACTIVATED", severity, code))
                else:
                    was_active = bool(previous["active"])
                    old_severity = str(previous["severity"])
                    connection.execute(
                        """
                        UPDATE faults SET severity = ?, active = 1,
                            last_seen = ?, cleared_at = NULL
                        WHERE robot_id = ? AND fault_code = ?
                        """,
                        (severity, now, robot_id, code),
                    )
                    if not was_active:
                        transitions.append(("FAULT_ACTIVATED", severity, code))
                    elif old_severity != severity:
                        transitions.append(
                            ("FAULT_SEVERITY_CHANGED", severity, code)
                        )
            for code, previous in known.items():
                if not bool(previous["active"]) or code in current:
                    continue
                connection.execute(
                    """
                    UPDATE faults SET active = 0, last_seen = ?, cleared_at = ?
                    WHERE robot_id = ? AND fault_code = ?
                    """,
                    (now, now, robot_id, code),
                )
                transitions.append(("FAULT_CLEARED", "INFO", code))
            for event_type, event_severity, code in transitions:
                connection.execute(
                    """
                    INSERT INTO events (
                        occurred_at, robot_id, category, event_type, severity,
                        task_id, command_id, message, details_json
                    ) VALUES (?, ?, 'FAULT', ?, ?, NULL, NULL, ?, '{}')
                    """,
                    (now, robot_id, event_type, event_severity, code),
                )
            connection.commit()

    def list_faults(
        self,
        robot_id: str,
        include_cleared: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return current faults and, when requested, cleared history."""
        query = "SELECT * FROM faults WHERE robot_id = ?"
        values: List[Any] = [robot_id]
        if not include_cleared:
            query += " AND active = 1"
        query += " ORDER BY active DESC, last_seen DESC, fault_code"
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._fault_dict(row) for row in rows]

    def create_task(
        self,
        robot_id: str,
        x: float,
        y: float,
        yaw: float,
        confirm_warnings: bool,
        attempt: int = 1,
        parent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a durable navigation task in CREATED state."""
        task_id = str(uuid.uuid4())
        now = _utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO tasks VALUES (
                    ?, ?, 'CREATED', ?, ?, ?, ?, ?, ?, NULL, '', ?, ?
                )
                """,
                (
                    task_id,
                    robot_id,
                    float(x),
                    float(y),
                    float(yaw),
                    int(bool(confirm_warnings)),
                    int(attempt),
                    parent_task_id,
                    now,
                    now,
                ),
            )
            connection.commit()
        self.record_event(
            robot_id,
            "TASK",
            "TASK_CREATED",
            "Navigation task created",
            task_id=task_id,
            details={"attempt": attempt, "parent_task_id": parent_task_id},
        )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return one task by identifier."""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return None if row is None else self._task_dict(row)

    def list_tasks(
        self,
        robot_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return newest updated tasks."""
        bounded_limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM tasks"
        values: List[Any] = []
        if robot_id:
            query += " WHERE robot_id = ?"
            values.append(robot_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        values.append(bounded_limit)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._task_dict(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        state: str,
        message: str,
        command_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Move a task to a new state and append an audit event."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        now = _utc_now()
        resolved_command = command_id or task.get("command_id")
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE tasks SET state = ?, command_id = ?, message = ?,
                    updated_at = ? WHERE task_id = ?
                """,
                (state, resolved_command, message, now, task_id),
            )
            connection.commit()
        if state != task["state"] or message != task["message"]:
            severity = "ERROR" if state == "FAILED" else "INFO"
            self.record_event(
                task["robot_id"],
                "TASK",
                f"TASK_{state}",
                message,
                severity=severity,
                task_id=task_id,
                command_id=resolved_command,
            )
        return self.get_task(task_id) or {}

    def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Create a new attempt from a terminal task without running it."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["state"] not in {"FAILED", "CANCELED"}:
            raise ValueError("Only failed or canceled tasks can be retried")
        return self.create_task(
            task["robot_id"],
            task["target"]["x"],
            task["target"]["y"],
            task["target"]["yaw"],
            task["confirm_warnings"],
            attempt=int(task["attempt"]) + 1,
            parent_task_id=task_id,
        )

    def reconcile_gateway_restart(self) -> int:
        """Fail tasks whose in-memory action ownership was lost on restart."""
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT task_id FROM tasks
                WHERE state IN ('STARTING', 'ACTIVE')
                ORDER BY updated_at, task_id
                """
            ).fetchall()
        for row in rows:
            self.update_task(
                str(row["task_id"]),
                "FAILED",
                "Fleet Gateway restarted; prior task will not resume",
            )
        return len(rows)

    def sync_navigation(self, status: Mapping[str, Any]) -> None:
        """Reconcile the current durable task with robot navigation status."""
        robot_id = str(status.get("robot_id", "")).strip()
        state = str(status.get("state", "")).upper()
        command_id = str(status.get("active_command_id", "")).strip()
        if robot_id and state == "UNAVAILABLE" and not command_id:
            with self._lock:
                self._observed_navigation_commands.pop(robot_id, None)
            self._fail_task_after_agent_restart(robot_id, status)
            return
        if not robot_id or state not in {
            "ACTIVE",
            "SUCCEEDED",
            "CANCELED",
            "FAILED",
            "LEASE_EXPIRED",
        }:
            return
        expected_command_id = command_id
        with self._lock, closing(self._connect()) as connection:
            if command_id:
                row = connection.execute(
                    """
                    SELECT task_id FROM tasks
                    WHERE robot_id = ? AND command_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (robot_id, command_id),
                ).fetchone()
                if row is not None:
                    self._observed_navigation_commands[robot_id] = command_id
            else:
                expected_command_id = self._observed_navigation_commands.get(
                    robot_id,
                    "",
                )
                if not expected_command_id:
                    return
                row = connection.execute(
                    """
                    SELECT task_id FROM tasks
                    WHERE robot_id = ? AND command_id = ?
                        AND state IN ('STARTING', 'ACTIVE')
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (robot_id, expected_command_id),
                ).fetchone()
        if row is None:
            return
        task = self.get_task(str(row["task_id"]))
        if task is None:
            return
        if not command_id and not self._status_target_matches_task(
            status,
            task,
        ):
            return
        mapped_state = "FAILED" if state == "LEASE_EXPIRED" else state
        message = str(status.get("message", "")) or (
            f"Navigation {state.lower()}"
        )
        self.update_task(
            str(row["task_id"]),
            mapped_state,
            message,
            command_id,
        )
        if state != "ACTIVE":
            with self._lock:
                if (
                    self._observed_navigation_commands.get(robot_id)
                    == expected_command_id
                ):
                    self._observed_navigation_commands.pop(robot_id, None)

    @staticmethod
    def _status_target_matches_task(
        status: Mapping[str, Any],
        task: Mapping[str, Any],
    ) -> bool:
        """Reject a late terminal status for a different target pose."""
        status_target = status.get("target")
        task_target = task.get("target")
        if not isinstance(status_target, Mapping) or not isinstance(
            task_target,
            Mapping,
        ):
            return True
        if status_target.get("frame_id") not in {None, "", "map"}:
            return False
        try:
            x_delta = abs(
                float(status_target["x"]) - float(task_target["x"])
            )
            y_delta = abs(
                float(status_target["y"]) - float(task_target["y"])
            )
            yaw_delta = float(status_target["yaw"]) - float(
                task_target["yaw"]
            )
        except (KeyError, TypeError, ValueError):
            return True
        wrapped_yaw_delta = abs(
            math.atan2(math.sin(yaw_delta), math.cos(yaw_delta))
        )
        return (
            x_delta <= 1.0e-4
            and y_delta <= 1.0e-4
            and wrapped_yaw_delta <= 1.0e-4
        )

    def _fail_task_after_agent_restart(
        self,
        robot_id: str,
        status: Mapping[str, Any],
    ) -> None:
        """Close an active task when the agent restarts fail-closed."""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT task_id FROM tasks
                WHERE robot_id = ? AND state = 'ACTIVE'
                    AND command_id IS NOT NULL AND command_id != ''
                ORDER BY updated_at DESC LIMIT 1
                """,
                (robot_id,),
            ).fetchone()
        if row is None:
            return
        detail = str(status.get("message", "")).strip()
        message = "Navigation agent restarted; prior task will not resume"
        if detail:
            message = f"{message}: {detail}"
        self.update_task(str(row["task_id"]), "FAILED", message)

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json"))
        return result

    @staticmethod
    def _fault_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["active"] = bool(result["active"])
        return result

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["confirm_warnings"] = bool(result["confirm_warnings"])
        result["target"] = {
            "frame_id": "map",
            "x": result.pop("x"),
            "y": result.pop("y"),
            "yaw": result.pop("yaw"),
        }
        return result
