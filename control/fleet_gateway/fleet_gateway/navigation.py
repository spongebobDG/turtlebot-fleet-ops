"""Thread-safe navigation goal state shared by ROS and HTTP threads."""

from copy import deepcopy
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional
from uuid import uuid4


ACTIVE_NAVIGATION_STATUSES = frozenset(
    {"PENDING", "RUNNING", "CANCELING"}
)
TERMINAL_NAVIGATION_STATUSES = frozenset(
    {"SUCCEEDED", "ABORTED", "CANCELED", "REJECTED", "TIMEOUT"}
)
RETRYABLE_NAVIGATION_STATUSES = frozenset(
    {"ABORTED", "REJECTED", "TIMEOUT"}
)


class NavigationConflict(RuntimeError):
    """Raised when a robot already has an active navigation goal."""

    def __init__(self, robot_id: str, goal_id: str) -> None:
        super().__init__(f"{robot_id} already has active goal {goal_id}")
        self.robot_id = robot_id
        self.goal_id = goal_id


class NavigationRetryNotAllowed(RuntimeError):
    """Raised when the latest goal is not a retryable failure."""

    def __init__(self, robot_id: str, status: str) -> None:
        super().__init__(
            f"{robot_id} navigation status {status} cannot be retried"
        )
        self.robot_id = robot_id
        self.status = status


@dataclass
class _NavigationRecord:
    """Mutable internal state protected by the registry lock."""

    goal_id: str
    robot_id: str
    target: Dict[str, Any]
    status: str
    message: str
    feedback: Dict[str, Any]
    created_at: float
    updated_at: float
    deadline_monotonic: float
    timeout_sec: float
    timeout_requested: bool = False
    retry_count: int = 0
    retried_from_goal_id: Optional[str] = None


class NavigationRegistry:
    """Store the current navigation goal for every configured robot."""

    def __init__(
        self,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._records: Dict[str, _NavigationRecord] = {}
        self._lock = threading.RLock()

    def begin(
        self,
        robot_id: str,
        target: Mapping[str, Any],
        timeout_sec: float,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create one pending goal unless the robot is already busy."""
        timeout = float(timeout_sec)
        if timeout <= 0.0:
            raise ValueError("timeout_sec must be positive")
        identifier = goal_id or str(uuid4())
        now_monotonic = self._monotonic_clock()
        now_wall = self._wall_clock()
        with self._lock:
            current = self._records.get(robot_id)
            if current is not None and current.status in (
                ACTIVE_NAVIGATION_STATUSES
            ):
                raise NavigationConflict(robot_id, current.goal_id)
            record = _NavigationRecord(
                goal_id=identifier,
                robot_id=robot_id,
                target=deepcopy(dict(target)),
                status="PENDING",
                message="Waiting for Nav2 goal acceptance",
                feedback={},
                created_at=now_wall,
                updated_at=now_wall,
                deadline_monotonic=now_monotonic + timeout,
                timeout_sec=timeout,
            )
            self._records[robot_id] = record
            return self._snapshot(record)

    def begin_retry(
        self,
        robot_id: str,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically replace the latest failed goal with one retry."""
        now_monotonic = self._monotonic_clock()
        now_wall = self._wall_clock()
        with self._lock:
            current = self._records.get(robot_id)
            status = "IDLE" if current is None else current.status
            if current is None or status not in (
                RETRYABLE_NAVIGATION_STATUSES
            ):
                raise NavigationRetryNotAllowed(robot_id, status)

            identifier = goal_id or str(uuid4())
            record = _NavigationRecord(
                goal_id=identifier,
                robot_id=robot_id,
                target=deepcopy(current.target),
                status="PENDING",
                message="Waiting for retried Nav2 goal acceptance",
                feedback={},
                created_at=now_wall,
                updated_at=now_wall,
                deadline_monotonic=(
                    now_monotonic + current.timeout_sec
                ),
                timeout_sec=current.timeout_sec,
                retry_count=current.retry_count + 1,
                retried_from_goal_id=current.goal_id,
            )
            self._records[robot_id] = record
            return self._snapshot(record)

    def get(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Return the latest goal state for one robot."""
        with self._lock:
            record = self._records.get(robot_id)
            return None if record is None else self._snapshot(record)

    def snapshot(self) -> List[Dict[str, Any]]:
        """Return current goal states sorted by robot identifier."""
        with self._lock:
            return [
                self._snapshot(self._records[robot_id])
                for robot_id in sorted(self._records)
            ]

    def is_active(self, robot_id: str) -> bool:
        """Return whether a robot still owns an active goal."""
        with self._lock:
            record = self._records.get(robot_id)
            return bool(
                record is not None
                and record.status in ACTIVE_NAVIGATION_STATUSES
            )

    def mark_running(self, robot_id: str, goal_id: str) -> bool:
        """Mark an accepted Nav2 goal as running."""
        with self._lock:
            record = self._matching(robot_id, goal_id)
            if record is None or record.status != "PENDING":
                return False
            record.status = "RUNNING"
            record.message = "Nav2 goal accepted"
            record.updated_at = self._wall_clock()
            return True

    def update_feedback(
        self,
        robot_id: str,
        goal_id: str,
        feedback: Mapping[str, Any],
    ) -> bool:
        """Replace feedback for the matching active goal."""
        with self._lock:
            record = self._matching(robot_id, goal_id)
            if record is None or record.status not in (
                ACTIVE_NAVIGATION_STATUSES
            ):
                return False
            record.feedback = deepcopy(dict(feedback))
            record.updated_at = self._wall_clock()
            return True

    def request_cancel(
        self,
        robot_id: str,
        goal_id: str,
        message: str,
        timed_out: bool = False,
    ) -> bool:
        """Move a matching active goal to canceling state."""
        with self._lock:
            record = self._matching(robot_id, goal_id)
            if record is None or record.status not in (
                ACTIVE_NAVIGATION_STATUSES
            ):
                return False
            record.status = "CANCELING"
            record.message = message
            record.timeout_requested = bool(timed_out)
            record.updated_at = self._wall_clock()
            return True

    def finish(
        self,
        robot_id: str,
        goal_id: str,
        status: str,
        message: str,
    ) -> bool:
        """Store a terminal state for the matching goal."""
        if status not in TERMINAL_NAVIGATION_STATUSES:
            raise ValueError(f"unsupported terminal status: {status}")
        return self._update(
            robot_id,
            goal_id,
            status=status,
            message=message,
            terminal_only=True,
        )

    def claim_expired(self) -> List[Dict[str, Any]]:
        """Atomically mark elapsed goals for timeout cancellation."""
        now_monotonic = self._monotonic_clock()
        now_wall = self._wall_clock()
        expired: List[Dict[str, Any]] = []
        with self._lock:
            for robot_id in sorted(self._records):
                record = self._records[robot_id]
                if record.status not in {"PENDING", "RUNNING"}:
                    continue
                if record.deadline_monotonic > now_monotonic:
                    continue
                record.status = "CANCELING"
                record.message = "Navigation timeout; cancel requested"
                record.timeout_requested = True
                record.updated_at = now_wall
                expired.append(self._snapshot(record))
        return expired

    def _update(
        self,
        robot_id: str,
        goal_id: str,
        status: str,
        message: str,
        terminal_only: bool = False,
    ) -> bool:
        with self._lock:
            record = self._matching(robot_id, goal_id)
            if record is None:
                return False
            if terminal_only and record.status in (
                TERMINAL_NAVIGATION_STATUSES
            ):
                return False
            record.status = status
            record.message = message
            record.updated_at = self._wall_clock()
            return True

    def _matching(
        self,
        robot_id: str,
        goal_id: str,
    ) -> Optional[_NavigationRecord]:
        record = self._records.get(robot_id)
        if record is None or record.goal_id != goal_id:
            return None
        return record

    @staticmethod
    def _snapshot(record: _NavigationRecord) -> Dict[str, Any]:
        return {
            "goal_id": record.goal_id,
            "robot_id": record.robot_id,
            "target": deepcopy(record.target),
            "status": record.status,
            "message": record.message,
            "feedback": deepcopy(record.feedback),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "timeout_sec": record.timeout_sec,
            "timeout_requested": record.timeout_requested,
            "retry_count": record.retry_count,
            "retried_from_goal_id": record.retried_from_goal_id,
        }
