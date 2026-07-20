"""Reproducible MLOps pipeline for ROS 2 and systemd log anomalies."""

from argparse import ArgumentParser, Namespace
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


PIPELINE_VERSION = "1.0"
FEATURE_NAMES = (
    "line_count",
    "error_rate",
    "warning_rate",
    "timeout_rate",
    "disconnect_rate",
    "navigation_failure_rate",
    "restart_rate",
    "dropped_message_rate",
)
DEFAULT_UNITS = (
    "fleet-gateway.service",
    "fleet-control-zenoh.service",
)
ROS_LINE = re.compile(
    r"^\[(DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]\s+"
    r"\[([0-9]+(?:\.[0-9]+)?)\]\s+\[([^\]]+)\]:\s*(.*)$",
    re.IGNORECASE,
)
PATTERNS = {
    "timeout": re.compile(r"time(?:d)?\s*out|timeout|deadline", re.I),
    "disconnect": re.compile(
        r"disconnect|connection\s+(?:lost|closed|refused)|unreachable|offline",
        re.I,
    ),
    "navigation_failure": re.compile(
        r"nav(?:2|igation).*(?:fail|abort|reject)"
        r"|goal.*(?:fail|abort|reject)"
        r"|planning algorithm.*fail"
        r"|failed to make progress"
        r"|collision ahead"
        r"|(?:spin|backup|follow_path).*fail",
        re.I,
    ),
    "restart": re.compile(
        r"restart|process.*(?:died|exited)|lifecycle.*(?:error|finalized)",
        re.I,
    ),
    "dropped_message": re.compile(
        r"drop(?:ped)?|queue.*full|sample.*lost|message.*lost",
        re.I,
    ),
}

OPERATIONAL_SIGNAL_PATTERNS = (
    (
        "initial_pose_wait",
        "초기 위치 대기",
        re.compile(
            r"timed out waiting for transform.*(?:base_link|map)"
            r"|AMCL cannot publish.*set the initial pose",
            re.I,
        ),
    ),
    (
        "control_deadline_miss",
        "제어 주기 지연",
        re.compile(r"control loop missed|tick rate .* exceeded", re.I),
    ),
    (
        "planning_failure",
        "경로 생성 실패",
        re.compile(r"failed to create plan|failed to generate a valid path", re.I),
    ),
    (
        "collision_guard",
        "충돌 방지 개입",
        re.compile(r"collision ahead", re.I),
    ),
    (
        "progress_failure",
        "주행 진척 없음",
        re.compile(r"failed to make progress", re.I),
    ),
    (
        "message_drop",
        "센서 메시지 지연·유실",
        re.compile(r"dropping message|sample.*lost|message.*lost", re.I),
    ),
)

ROOT_CAUSE_RULES = (
    (
        "localization_tf",
        "위치추정·TF 불일치",
        re.compile(
            r"AMCL cannot publish|set the initial pose|transform.*(?:fail|time)"
            r"|fail(?:ed)? to transform|frame ID.*(?:map|odom)|extrapolation",
            re.I,
        ),
        "초기 위치, map→odom TF 시각, AMCL 센서 정합을 확인하세요.",
    ),
    (
        "collision_clearance",
        "장애물·여유거리 차단",
        re.compile(
            r"collision ahead|obstacle|costmap.*(?:lethal|collision)"
            r"|no valid trajector|(?:lidar )?clearance.*(?:below|limit)",
            re.I,
        ),
        "실물 장애물과 LiDAR 사각지대, local costmap 표시를 함께 확인하세요.",
    ),
    (
        "navigation_progress",
        "경로 진행 정체",
        re.compile(
            r"failed to make progress|progress checker|controller.*fail"
            r"|failed to create plan|valid path",
            re.I,
        ),
        "목표 경로, 바퀴 미끄러짐, 장애물과 map-frame 진행량을 확인하세요.",
    ),
    (
        "network_lease",
        "Gateway·Zenoh·lease 단절",
        re.compile(
            r"lease.*(?:expired|stale)|disconnect|unreachable"
            r"|connection.*(?:lost|closed|refused)|zenoh.*(?:fail|error)",
            re.I,
        ),
        "Gateway와 Zenoh 서비스, Wi-Fi 신호와 2초 lease 만료 기록을 확인하세요.",
    ),
    (
        "sensor_data",
        "센서 지연·유실",
        re.compile(
            r"dropping message|message.*lost|sample.*lost|scan.*stale"
            r"|odom.*stale|queue.*full",
            re.I,
        ),
        "scan/odom 주기, QoS, CPU 부하와 센서 연결을 확인하세요.",
    ),
    (
        "process_restart",
        "프로세스 종료·재시작",
        re.compile(
            r"process.*(?:died|exited)|restart|lifecycle.*(?:error|finalized)"
            r"|bond.*(?:broken|timeout)",
            re.I,
        ),
        "해당 systemd unit의 직전 journal과 재시작 횟수를 확인하세요.",
    ),
    (
        "resource_pressure",
        "CPU·메모리·제어 주기 압박",
        re.compile(
            r"control loop missed|tick rate.*exceeded|deadline"
            r"|out of memory|cpu.*(?:high|warning)|memory.*(?:high|warning)",
            re.I,
        ),
        "10분 CPU·메모리 추세와 Nav2 제어 주기 지연을 비교하세요.",
    ),
    (
        "safety_stop",
        "안전 정지 개입",
        re.compile(r"emergency stop active|e-?stop|watchdog.*timeout", re.I),
        "정지 원인을 해소한 뒤 IDLE·0 입력에서만 수동으로 재무장하세요.",
    ),
)

# Some Nav2 components report caught, transient transform exceptions at INFO
# while successfully continuing, and the navigation agent announces its lease
# timeout configuration at startup.  Those records remain in the immutable raw
# log and anomaly features, but are not strong enough to become a root-cause
# incident without WARNING/ERROR severity.
ROOT_CAUSE_REQUIRES_WARNING = frozenset(
    {
        "collision_clearance",
        "localization_tf",
        "navigation_progress",
        "network_lease",
    }
)


@dataclass(frozen=True)
class LogRecord:
    """Normalized journal or ROS 2 console record."""

    timestamp: float
    severity: str
    logger: str
    message: str
    unit: str = ""


def utc_now(timestamp: Optional[float] = None) -> str:
    """Return a stable UTC timestamp for artifacts and status."""
    value = time.time() if timestamp is None else timestamp
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def parse_log_line(
    line: str,
    fallback_timestamp: Optional[float] = None,
) -> Optional[LogRecord]:
    """Parse journal JSON or the standard ROS 2 console format."""
    text = line.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping):
            return _record_from_journal(payload, fallback_timestamp)
    match = ROS_LINE.match(text)
    if match:
        return LogRecord(
            timestamp=float(match.group(2)),
            severity=_normalize_severity(match.group(1)),
            logger=match.group(3),
            message=match.group(4),
        )
    return LogRecord(
        timestamp=time.time()
        if fallback_timestamp is None
        else float(fallback_timestamp),
        severity="INFO",
        logger="unstructured",
        message=text,
    )


def _record_from_journal(
    payload: Mapping[str, Any],
    fallback_timestamp: Optional[float],
) -> LogRecord:
    raw_timestamp = payload.get(
        "__REALTIME_TIMESTAMP",
        payload.get("_SOURCE_REALTIME_TIMESTAMP"),
    )
    try:
        timestamp = float(raw_timestamp) / 1_000_000.0
    except (TypeError, ValueError):
        timestamp = (
            time.time()
            if fallback_timestamp is None
            else float(fallback_timestamp)
        )
    severity = payload.get("PRIORITY", "6")
    try:
        priority = int(severity)
    except (TypeError, ValueError):
        normalized = _normalize_severity(str(severity))
    else:
        if priority <= 3:
            normalized = "ERROR"
        elif priority == 4:
            normalized = "WARNING"
        elif priority >= 7:
            normalized = "DEBUG"
        else:
            normalized = "INFO"
    return LogRecord(
        timestamp=timestamp,
        severity=normalized,
        logger=str(
            payload.get("SYSLOG_IDENTIFIER")
            or payload.get("_COMM")
            or payload.get("_SYSTEMD_UNIT")
            or "journal"
        ),
        message=str(payload.get("MESSAGE", "")),
        unit=str(payload.get("_SYSTEMD_UNIT", "")),
    )


def _normalize_severity(value: str) -> str:
    normalized = value.upper()
    if normalized in {"ERROR", "FATAL"}:
        return "ERROR"
    if normalized in {"WARN", "WARNING"}:
        return "WARNING"
    if normalized == "DEBUG":
        return "DEBUG"
    return "INFO"


def extract_features(records: Sequence[LogRecord]) -> Dict[str, float]:
    """Convert one time window into bounded operational log features."""
    count = len(records)
    if count == 0:
        return {name: 0.0 for name in FEATURE_NAMES}
    errors = sum(record.severity == "ERROR" for record in records)
    warnings = sum(record.severity == "WARNING" for record in records)
    messages = [record.message for record in records]

    def rate(pattern_name: str) -> float:
        pattern = PATTERNS[pattern_name]
        return sum(bool(pattern.search(message)) for message in messages) / count

    return {
        "line_count": float(count),
        "error_rate": errors / count,
        "warning_rate": warnings / count,
        "timeout_rate": rate("timeout"),
        "disconnect_rate": rate("disconnect"),
        "navigation_failure_rate": rate("navigation_failure"),
        "restart_rate": rate("restart"),
        "dropped_message_rate": rate("dropped_message"),
    }


def extract_operational_signals(
    records: Sequence[LogRecord],
) -> List[Dict[str, Any]]:
    """Summarize safety-relevant signatures while the model matures."""
    signals = []
    messages = [record.message for record in records]
    for name, label, pattern in OPERATIONAL_SIGNAL_PATTERNS:
        count = sum(bool(pattern.search(message)) for message in messages)
        if count:
            signals.append({"signal": name, "label": label, "count": count})
    signals.sort(key=lambda item: (-item["count"], item["signal"]))
    return signals


def diagnose_records(
    records: Sequence[LogRecord],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Rank explainable root-cause hypotheses with bounded evidence."""
    diagnoses = []
    for cause, label, pattern, recommendation in ROOT_CAUSE_RULES:
        matches = [
            record
            for record in records
            if pattern.search(record.message)
            and (
                cause not in ROOT_CAUSE_REQUIRES_WARNING
                or record.severity.upper() in {"WARNING", "WARN", "ERROR", "FATAL"}
            )
        ]
        if not matches:
            continue
        loggers = {record.logger for record in matches}
        confidence = min(
            0.98,
            0.5 + 0.08 * math.log2(len(matches) + 1) + 0.04 * len(loggers),
        )
        evidence = [
            {
                "timestamp": utc_now(record.timestamp),
                "severity": record.severity,
                "logger": record.logger,
                "message": record.message[:300],
            }
            for record in matches[-3:]
        ]
        diagnoses.append(
            {
                "cause": cause,
                "label": label,
                "count": len(matches),
                "confidence": round(confidence, 3),
                "last_seen": utc_now(matches[-1].timestamp),
                "evidence": evidence,
                "recommended_action": recommendation,
            }
        )
    diagnoses.sort(
        key=lambda item: (item["last_seen"], item["count"]),
        reverse=True,
    )
    return diagnoses[: max(1, min(int(limit), 20))]


def incidents_from_path(
    status_path: Optional[Path],
    max_records: int = 2000,
) -> Dict[str, Any]:
    """Read recent immutable raw logs and return explainable diagnoses."""
    status = status_from_path(status_path)
    records: List[LogRecord] = []
    if status_path is not None:
        raw_dir = Path(status_path).expanduser().parent.parent / "raw"
        try:
            files = sorted(raw_dir.glob("*.jsonl"), reverse=True)
        except OSError:
            files = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if len(records) >= max_records:
                    break
                try:
                    payload = json.loads(line)
                    records.append(
                        LogRecord(
                            timestamp=float(payload["timestamp"]),
                            severity=str(payload.get("severity", "INFO")),
                            logger=str(payload.get("logger", "unknown")),
                            message=str(payload.get("message", "")),
                            unit=str(payload.get("unit", "")),
                        )
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
            if len(records) >= max_records:
                break
    records.sort(key=lambda record: record.timestamp)
    return {
        "analysis_method": "rule_evidence_v1",
        "scope": "recent_ros2_raw_logs",
        "record_count": len(records),
        "model": {
            "model_id": status.get("model_id"),
            "state": status.get("state"),
            "score": status.get("score"),
            "threshold": status.get("threshold"),
            "observed_at": status.get("observed_at"),
        },
        "diagnoses": diagnose_records(records),
        "message": (
            "규칙 근거와 Production 모델 상태를 함께 표시합니다. "
            "원인 후보는 자동 제어에 사용되지 않습니다."
        ),
    }


def build_dataset(
    records: Sequence[LogRecord],
    window_sec: float = 60.0,
    created_at: Optional[str] = None,
    since_timestamp: Optional[float] = None,
    until_timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Build immutable time-window rows and a content-addressed manifest."""
    if not math.isfinite(window_sec) or window_sec <= 0:
        raise ValueError("window_sec must be positive and finite")
    for name, value in (
        ("since_timestamp", since_timestamp),
        ("until_timestamp", until_timestamp),
    ):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be positive and finite")
    if (
        since_timestamp is not None
        and until_timestamp is not None
        and since_timestamp >= until_timestamp
    ):
        raise ValueError("since_timestamp must be earlier than until_timestamp")
    valid_records = [
        record
        for record in records
        if math.isfinite(record.timestamp) and record.timestamp > 0
    ]
    selected_records = [
        record
        for record in valid_records
        if (since_timestamp is None or record.timestamp >= since_timestamp)
        and (until_timestamp is None or record.timestamp < until_timestamp)
    ]
    ordered = sorted(selected_records, key=lambda record: record.timestamp)
    buckets: Dict[int, List[LogRecord]] = {}
    for record in ordered:
        bucket = math.floor(record.timestamp / window_sec)
        buckets.setdefault(bucket, []).append(record)
    rows = []
    for bucket, window_records in sorted(buckets.items()):
        start = bucket * window_sec
        rows.append(
            {
                "window_start": utc_now(start),
                "window_end": utc_now(start + window_sec),
                "log_count": len(window_records),
                "features": extract_features(window_records),
            }
        )
    payload: Dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "created_at": created_at or utc_now(),
        "window_sec": float(window_sec),
        "feature_names": list(FEATURE_NAMES),
        "record_count": len(ordered),
        "discarded_record_count": len(records) - len(valid_records),
        "excluded_outside_range_count": len(valid_records) - len(ordered),
        "since_timestamp": since_timestamp,
        "until_timestamp": until_timestamp,
        "rows": rows,
    }
    payload["dataset_hash"] = content_hash(payload)
    return payload


def train_model(
    dataset: Mapping[str, Any],
    trained_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Fit a robust median/MAD model and evaluate its promotion gate."""
    rows = list(dataset.get("rows", []))
    if not rows:
        raise ValueError("dataset must contain at least one feature window")
    centers: Dict[str, float] = {}
    scales: Dict[str, float] = {}
    for feature in FEATURE_NAMES:
        values = [float(row["features"][feature]) for row in rows]
        center = statistics.median(values)
        deviations = [abs(value - center) for value in values]
        mad_scale = statistics.median(deviations) * 1.4826
        floor = max(1.0, abs(center) * 0.10) if feature == "line_count" else 0.01
        centers[feature] = center
        scales[feature] = max(mad_scale, floor)
    base_model: Dict[str, Any] = {
        "centers": centers,
        "scales": scales,
        "feature_names": list(FEATURE_NAMES),
    }
    scores = [score_features(row["features"], base_model)["score"] for row in rows]
    calibration = _percentile(scores, 0.99)
    threshold = max(4.0, calibration * 1.25)
    sample_count = len(rows)
    record_count = int(dataset.get("record_count", 0))
    discarded_record_count = int(dataset.get("discarded_record_count", 0))
    excluded_outside_range_count = int(
        dataset.get("excluded_outside_range_count", 0)
    )
    gate_passed = sample_count >= 5 and record_count >= 20
    warnings = []
    if discarded_record_count:
        warnings.append(
            f"{discarded_record_count} records with invalid timestamps "
            "were excluded"
        )
    timestamp = trained_at or utc_now()
    dataset_hash = str(dataset.get("dataset_hash") or content_hash(dataset))
    model_id = (
        "ros2-log-mad-"
        f"{timestamp.replace(':', '').replace('+00:00', 'Z')}-"
        f"{dataset_hash[:8]}"
    )
    return {
        "pipeline_version": PIPELINE_VERSION,
        "model_type": "robust_median_mad",
        "model_id": model_id,
        "stage": "candidate",
        "trained_at": timestamp,
        "dataset_hash": dataset_hash,
        "feature_names": list(FEATURE_NAMES),
        "centers": centers,
        "scales": scales,
        "threshold": threshold,
        "quality": {
            "gate_passed": gate_passed,
            "sample_count": sample_count,
            "record_count": record_count,
            "discarded_record_count": discarded_record_count,
            "excluded_outside_range_count": excluded_outside_range_count,
            "minimum_sample_count": 5,
            "minimum_record_count": 20,
            "calibration_p99_score": calibration,
            "warnings": warnings,
            "reason": "quality gate passed"
            if gate_passed
            else "at least 5 windows and 20 log records are required",
        },
    }


def score_features(
    features: Mapping[str, Any],
    model: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the maximum robust deviation and explainable contributors."""
    contributors = []
    for feature in FEATURE_NAMES:
        value = float(features.get(feature, 0.0))
        center = float(model["centers"][feature])
        scale = float(model["scales"][feature])
        deviation = abs(value - center) / max(scale, 1.0e-12)
        contributors.append(
            {
                "feature": feature,
                "value": value,
                "baseline": center,
                "deviation": deviation,
            }
        )
    contributors.sort(key=lambda item: item["deviation"], reverse=True)
    return {
        "score": contributors[0]["deviation"] if contributors else 0.0,
        "top_features": contributors[:3],
    }


def analyze_records(
    records: Sequence[LogRecord],
    model: Optional[Mapping[str, Any]],
    observed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the API status payload for one live log window."""
    timestamp = observed_at or utc_now()
    operational_signals = extract_operational_signals(records)
    if model is None:
        status = model_not_ready_status(timestamp)
        status["log_count"] = len(records)
        status["feature_values"] = extract_features(records)
        status["operational_signals"] = operational_signals
        signal_summary = ", ".join(
            f"{item['label']} {item['count']}회"
            for item in operational_signals[:3]
        )
        status["message"] = (
            f"최근 로그 {len(records)}건을 수집했습니다. "
            "검토·승격된 Production 모델이 없습니다."
            + (f" 현재 운영 신호: {signal_summary}." if signal_summary else "")
        )
        return status
    features = extract_features(records)
    score = score_features(features, model)
    threshold = float(model["threshold"])
    state = "ANOMALY" if score["score"] > threshold else "NORMAL"
    return {
        "pipeline_version": PIPELINE_VERSION,
        "state": state,
        "observed_at": timestamp,
        "model_id": model.get("model_id", "unknown"),
        "model_stage": model.get("stage", "production"),
        "score": score["score"],
        "threshold": threshold,
        "log_count": len(records),
        "feature_values": features,
        "top_features": score["top_features"],
        "operational_signals": operational_signals,
        "message": "운영 로그 패턴 이상이 감지되었습니다."
        if state == "ANOMALY"
        else "최근 ROS 2 운영 로그 패턴이 기준 범위입니다.",
    }


def model_not_ready_status(observed_at: Optional[str] = None) -> Dict[str, Any]:
    """Return a fail-visible status before a production model exists."""
    return {
        "pipeline_version": PIPELINE_VERSION,
        "state": "MODEL_NOT_READY",
        "observed_at": observed_at or utc_now(),
        "model_id": None,
        "model_stage": None,
        "score": None,
        "threshold": None,
        "log_count": 0,
        "feature_values": {},
        "top_features": [],
        "operational_signals": [],
        "message": "검토·승격된 Production 로그 모델이 없습니다.",
    }


def content_hash(payload: Mapping[str, Any]) -> str:
    """Hash canonical JSON for dataset and model lineage."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish JSON so the Gateway never reads partial state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> Dict[str, Any]:
    """Read one JSON artifact."""
    return json.loads(path.read_text(encoding="utf-8"))


def status_from_path(
    path: Optional[Path],
    stale_after_sec: float = 60.0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Read the latest inference status, falling back visibly."""
    if path is None or not path.is_file():
        return model_not_ready_status()
    try:
        status = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            **model_not_ready_status(),
            "state": "ERROR",
            "message": "로그 분석 상태 파일을 읽을 수 없습니다.",
        }
    observed_at = status.get("observed_at")
    try:
        observed = datetime.fromisoformat(
            str(observed_at).replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError):
        return {
            **status,
            "source_state": status.get("state"),
            "state": "STALE",
            "message": "로그 분석 상태의 관측 시각이 없습니다.",
        }
    current = time.time() if now is None else float(now)
    if current - observed > stale_after_sec:
        return {
            **status,
            "source_state": status.get("state"),
            "state": "STALE",
            "message": "ROS 2 로그 분석 상태가 갱신되지 않고 있습니다.",
        }
    return status


def collect_journal(
    since: str,
    units: Sequence[str] = DEFAULT_UNITS,
) -> List[LogRecord]:
    """Read normalized records from the current user's journal."""
    command = ["journalctl", "--user", "--no-pager", "-o", "json"]
    command.extend(["--since", since])
    for unit in units:
        command.extend(["--unit", unit])
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        record
        for line in completed.stdout.splitlines()
        if (record := parse_log_line(line)) is not None
    ]


def read_jsonl(path: Path) -> List[LogRecord]:
    """Load normalized records from a collected JSON Lines artifact."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        records.append(LogRecord(**payload))
    return records


def replay_jsonl_range(
    raw_inputs: Sequence[Path],
    model: Mapping[str, Any],
    since_timestamp: float,
    until_timestamp: float,
) -> Dict[str, Any]:
    """Evaluate one immutable JSONL time range without changing live status."""
    since = float(since_timestamp)
    until = float(until_timestamp)
    if not math.isfinite(since) or not math.isfinite(until) or since > until:
        raise ValueError("replay time range must be finite and ordered")

    selected = []
    excluded_outside_range = 0
    excluded_invalid_timestamp = 0
    for raw_input in raw_inputs:
        for record in read_jsonl(raw_input):
            timestamp = float(record.timestamp)
            if not math.isfinite(timestamp) or timestamp <= 0.0:
                excluded_invalid_timestamp += 1
                continue
            if timestamp < since or timestamp > until:
                excluded_outside_range += 1
                continue
            selected.append(record)
    selected.sort(key=lambda item: item.timestamp)

    status = analyze_records(selected, model)
    status["replay"] = {
        "since_timestamp": since,
        "until_timestamp": until,
        "record_count": len(selected),
        "excluded_outside_range_count": excluded_outside_range,
        "excluded_invalid_timestamp_count": excluded_invalid_timestamp,
    }
    return status


def read_recent_jsonl(
    paths: Iterable[Path],
    cutoff_timestamp: float,
) -> List[LogRecord]:
    """Restore a recent inference window, skipping torn JSONL records."""
    records = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = LogRecord(**payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if record.timestamp >= cutoff_timestamp:
                records.append(record)
    records.sort(key=lambda record: record.timestamp)
    return records


def write_jsonl(path: Path, records: Iterable[LogRecord]) -> None:
    """Write one immutable normalized raw-log artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(record), ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def pipeline_paths(root: Path) -> Dict[str, Path]:
    """Return repository-independent local artifact paths."""
    return {
        "raw": root / "raw",
        "datasets": root / "datasets",
        "models": root / "models",
        "production": root / "registry" / "production.json",
        "status": root / "status" / "latest.json",
    }


def promote_model(root: Path, candidate_path: Path) -> Dict[str, Any]:
    """Promote only a candidate that passed the recorded quality gate."""
    model = read_json(candidate_path)
    if not model.get("quality", {}).get("gate_passed", False):
        raise ValueError("candidate model did not pass the quality gate")
    production = dict(model)
    production["stage"] = "production"
    production["promoted_at"] = utc_now()
    write_json(pipeline_paths(root)["production"], production)
    return production


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _root_from_args(arguments: Namespace) -> Path:
    return Path(arguments.root).expanduser()


def _artifact_name(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def run_command(arguments: Namespace) -> int:
    """Execute one CLI stage and print its machine-readable artifact path."""
    root = _root_from_args(arguments)
    paths = pipeline_paths(root)
    units = tuple(getattr(arguments, "unit", None) or DEFAULT_UNITS)
    if arguments.command == "collect":
        records = collect_journal(arguments.since, units)
        target = paths["raw"] / f"{_artifact_name('ros2-logs')}.jsonl"
        write_jsonl(target, records)
        print(target)
        return 0
    if arguments.command == "build-dataset":
        records = []
        for raw_input in arguments.input:
            records.extend(read_jsonl(Path(raw_input).expanduser()))
        dataset = build_dataset(
            records,
            arguments.window_sec,
            since_timestamp=arguments.since_epoch,
            until_timestamp=arguments.until_epoch,
        )
        target = paths["datasets"] / f"{_artifact_name('dataset')}.json"
        write_json(target, dataset)
        print(target)
        return 0
    if arguments.command == "train":
        dataset = read_json(Path(arguments.input).expanduser())
        model = train_model(dataset)
        target = paths["models"] / f"{model['model_id']}.json"
        write_json(target, model)
        print(target)
        return 0
    if arguments.command == "promote":
        model = promote_model(root, Path(arguments.input).expanduser())
        print(f"{paths['production']} {model['model_id']}")
        return 0
    if arguments.command == "replay":
        model_path = (
            Path(arguments.model).expanduser()
            if arguments.model
            else paths["production"]
        )
        if not model_path.is_file():
            raise ValueError("Production model is unavailable for replay")
        status = replay_jsonl_range(
            [Path(item).expanduser() for item in arguments.input],
            read_json(model_path),
            arguments.since_epoch,
            arguments.until_epoch,
        )
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0
    if arguments.command in {"analyze", "monitor"}:
        interval = arguments.interval if arguments.command == "monitor" else None
        while True:
            production = (
                read_json(paths["production"])
                if paths["production"].is_file()
                else None
            )
            try:
                records = collect_journal(arguments.since, units)
                status = analyze_records(records, production)
            except (OSError, subprocess.SubprocessError) as error:
                status = {
                    **model_not_ready_status(),
                    "state": "ERROR",
                    "message": f"journal 수집 실패: {error}",
                }
            write_json(paths["status"], status)
            if interval is None:
                print(paths["status"])
                return 0
            time.sleep(max(5.0, float(interval)))
    raise ValueError(f"unknown command: {arguments.command}")


def build_parser() -> ArgumentParser:
    """Build the standalone pipeline CLI."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=os.environ.get(
            "FLEET_LOG_MLOPS_ROOT",
            "~/.local/share/turtlebot-fleet-ops/mlops/ros2-logs",
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--since", default="24 hours ago")
    collect.add_argument("--unit", action="append")
    dataset = subparsers.add_parser("build-dataset")
    dataset.add_argument("--input", required=True, action="append")
    dataset.add_argument("--window-sec", type=float, default=60.0)
    dataset.add_argument("--since-epoch", type=float)
    dataset.add_argument("--until-epoch", type=float)
    train = subparsers.add_parser("train")
    train.add_argument("--input", required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--input", required=True)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--input", required=True, action="append")
    replay.add_argument("--since-epoch", required=True, type=float)
    replay.add_argument("--until-epoch", required=True, type=float)
    replay.add_argument("--model")
    for name in ("analyze", "monitor"):
        command = subparsers.add_parser(name)
        command.add_argument("--since", default="5 minutes ago")
        command.add_argument("--unit", action="append")
        if name == "monitor":
            command.add_argument("--interval", type=float, default=15.0)
    return parser


def main() -> None:
    """Run the ROS 2 log MLOps command-line interface."""
    raise SystemExit(run_command(build_parser().parse_args()))


if __name__ == "__main__":
    main()
