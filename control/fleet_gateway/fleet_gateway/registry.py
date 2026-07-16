"""Thread-safe storage and heartbeat health for robot status snapshots."""

from copy import deepcopy
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class _RobotRecord:
    """A last-known status and the local monotonic receipt time."""

    status: Dict[str, Any]
    received_monotonic: float


class StatusRegistry:
    """Keep the latest status for each robot and infer online state."""

    def __init__(
        self,
        online_timeout_sec: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if online_timeout_sec <= 0.0:
            raise ValueError("online_timeout_sec must be positive")
        self._online_timeout_sec = float(online_timeout_sec)
        self._clock = clock
        self._records: Dict[str, _RobotRecord] = {}
        self._lock = threading.RLock()

    @property
    def online_timeout_sec(self) -> float:
        """Return the configured heartbeat timeout."""
        return self._online_timeout_sec

    def update(
        self,
        status: Mapping[str, Any],
        now: Optional[float] = None,
    ) -> None:
        """Store one robot snapshot using local receipt time."""
        robot_id = str(status.get("robot_id", "")).strip()
        if not robot_id:
            raise ValueError("status must contain a non-empty robot_id")
        received = self._clock() if now is None else float(now)
        record = _RobotRecord(deepcopy(dict(status)), received)
        with self._lock:
            self._records[robot_id] = record

    def get(
        self,
        robot_id: str,
        now: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return one enriched robot snapshot, if it exists."""
        current = self._clock() if now is None else float(now)
        with self._lock:
            record = self._records.get(robot_id)
            if record is None:
                return None
            return self._enrich(record, current)

    def snapshot(
        self,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Return all enriched snapshots sorted by robot identifier."""
        current = self._clock() if now is None else float(now)
        with self._lock:
            return [
                self._enrich(self._records[robot_id], current)
                for robot_id in sorted(self._records)
            ]

    def _enrich(
        self,
        record: _RobotRecord,
        now: float,
    ) -> Dict[str, Any]:
        age = max(0.0, now - record.received_monotonic)
        result = deepcopy(record.status)
        result["online"] = age <= self._online_timeout_sec
        result["heartbeat_age_sec"] = round(age, 3)
        return result
