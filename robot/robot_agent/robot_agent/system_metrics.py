"""Linux host resource sampling for the Robot Agent."""

from dataclasses import dataclass
import math
import os
from pathlib import Path
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
    wifi_valid: bool
    wifi_interface: str
    wifi_signal_dbm: float
    wifi_quality_percent: float


@dataclass(frozen=True)
class WifiMetrics:
    """Normalized Linux wireless link information."""

    valid: bool
    interface: str
    signal_dbm: float
    quality_percent: float


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

    wifi = read_wifi_metrics()

    return SystemMetrics(
        cpu_percent=_finite_or_unknown(cpu_percent),
        memory_percent=_finite_or_unknown(memory_percent),
        disk_percent=_finite_or_unknown(disk_percent),
        load_average_1m=_finite_or_unknown(load_average_1m),
        uptime_sec=uptime_sec,
        wifi_valid=wifi.valid,
        wifi_interface=wifi.interface,
        wifi_signal_dbm=wifi.signal_dbm,
        wifi_quality_percent=wifi.quality_percent,
    )


def read_wifi_metrics(
    path: str = "/proc/net/wireless",
) -> WifiMetrics:
    """Read the kernel wireless status without spawning a shell command."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _unknown_wifi()
    return parse_wireless_status(content)


def parse_wireless_status(content: str) -> WifiMetrics:
    """Parse the first valid interface row from `/proc/net/wireless`."""
    for line in content.splitlines():
        if ":" not in line:
            continue
        interface, raw_values = line.split(":", 1)
        fields = raw_values.split()
        if len(fields) < 3:
            continue
        try:
            link_quality = float(fields[1].rstrip("."))
            signal_dbm = float(fields[2].rstrip("."))
        except ValueError:
            continue
        if not math.isfinite(link_quality) or not math.isfinite(signal_dbm):
            continue

        quality_percent = max(0.0, min(100.0, link_quality / 70.0 * 100.0))
        return WifiMetrics(
            valid=True,
            interface=interface.strip(),
            signal_dbm=signal_dbm,
            quality_percent=quality_percent,
        )
    return _unknown_wifi()


def _unknown_wifi() -> WifiMetrics:
    """Return a JSON-safe unknown wireless snapshot."""
    return WifiMetrics(False, "", UNKNOWN_VALUE, UNKNOWN_VALUE)


def _finite_or_unknown(value: float) -> float:
    """Keep system snapshots JSON-safe even if a platform API misbehaves."""
    return value if math.isfinite(value) else UNKNOWN_VALUE
