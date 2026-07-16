"""Linux host resource sampling for the Robot Agent."""

from dataclasses import dataclass
import math
import os
import time

import psutil

from robot_agent.model import UNKNOWN_VALUE


@dataclass(frozen=True)
class SystemMetrics:
    """One normalized Raspberry Pi resource snapshot."""

    cpu_percent: float
    memory_percent: float
    disk_percent: float
    load_average_1m: float
    uptime_sec: int


def sample_system_metrics() -> SystemMetrics:
    """Collect host metrics and replace unavailable values with sentinels."""
    try:
        cpu_percent = float(psutil.cpu_percent(interval=None))
    except (OSError, ValueError):
        cpu_percent = UNKNOWN_VALUE

    try:
        memory_percent = float(psutil.virtual_memory().percent)
    except (OSError, ValueError):
        memory_percent = UNKNOWN_VALUE

    try:
        disk_percent = float(psutil.disk_usage("/").percent)
    except (OSError, ValueError):
        disk_percent = UNKNOWN_VALUE

    try:
        load_average_1m = float(os.getloadavg()[0])
    except (AttributeError, OSError):
        load_average_1m = UNKNOWN_VALUE

    try:
        uptime_sec = max(0, int(time.time() - psutil.boot_time()))
    except (OSError, ValueError):
        uptime_sec = 0

    return SystemMetrics(
        cpu_percent=_finite_or_unknown(cpu_percent),
        memory_percent=_finite_or_unknown(memory_percent),
        disk_percent=_finite_or_unknown(disk_percent),
        load_average_1m=_finite_or_unknown(load_average_1m),
        uptime_sec=uptime_sec,
    )


def _finite_or_unknown(value: float) -> float:
    """Keep system snapshots JSON-safe even if a platform API misbehaves."""
    return value if math.isfinite(value) else UNKNOWN_VALUE
