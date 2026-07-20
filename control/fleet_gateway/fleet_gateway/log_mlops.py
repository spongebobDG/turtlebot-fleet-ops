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


PIPELINE_VERSION = "1.3"
ACTIVE_INCIDENT_WINDOW_SEC = 120.0
INCIDENT_DEDUP_WINDOW_SEC = 5.0
FRESH_EVIDENCE_WINDOW_SEC = 120.0
FEATURE_NAMES = (
    "line_count",
    "error_rate",
    "warning_rate",
    "timeout_rate",
    "disconnect_rate",
    "navigation_failure_rate",
    "restart_rate",
    "dropped_message_rate",
    "tf_wait_rate",
    "safety_stop_rate",
    "resource_pressure_rate",
    "transport_reply_rate",
    "lease_failure_rate",
    "obstacle_clearance_rate",
    "sensor_health_rate",
    "qos_failure_rate",
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
    "tf_wait": re.compile(
        r"AMCL cannot publish|set the initial pose"
        r"|timed out waiting for transform.*(?:base_link|map)",
        re.I,
    ),
    "safety_stop": re.compile(
        r"emergency stop active|e-?stop|motion disarmed"
        r"|watchdog(?![^\n]*timeout\s*=)[^\n]*"
        r"(?:timeout|timed?\s*out|expired|stale|triggered)",
        re.I,
    ),
    "resource_pressure": re.compile(
        r"control loop missed|tick rate.*exceeded|status_transport_delay"
        r"|HIGH_CPU|out of memory|deadline",
        re.I,
    ),
    "transport_reply": re.compile(
        r"received NO reply|cannot reply to client|service.*timed out",
        re.I,
    ),
    "lease_failure": re.compile(
        r"lease.*(?:expired|stale)|navigation lease timer gap|lease publish gap",
        re.I,
    ),
    "obstacle_clearance": re.compile(
        r"OBSTACLE_CLEARANCE.*BLOCKED|collision ahead"
        r"|clearance.*(?:below|limit)|no valid trajectories",
        re.I,
    ),
    "sensor_health": re.compile(
        r"ODOM_(?:NOT_RECEIVED|STALE)|BATTERY_(?:NOT_RECEIVED|STALE)"
        r"|scan.*stale|sensor.*stale",
        re.I,
    ),
    "qos_failure": re.compile(
        r"incompatible QoS|offering incompatible QoS|QoS.*incompatible",
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
        "clock_sync",
        "관제 PC·TB1 시간 동기화 이상",
        re.compile(
            r"CLOCK_SKEW|clock skew|Local CMOS Clock|NTP.*(?:not synchronized|unsynchronized)"
            r"|incoming timestamp.*exceeding delta 500ms",
            re.I,
        ),
        "양쪽 시각을 외부 NTP와 비교하고 0.2초 이내로 맞춘 뒤 Zenoh 브리지를 재시작하세요.",
    ),
    (
        "lease_timer",
        "Gateway lease 발행 주기 지연",
        re.compile(r"navigation lease timer gap|lease publish gap", re.I),
        "Gateway lease timer 최대 간격과 executor 부하를 확인하고, 2초 안전 timeout은 유지하세요.",
    ),
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
        "transport_reply",
        "Zenoh 서비스/action 응답 손실",
        re.compile(
            r"received NO reply|cannot reply to client|service.*timed out",
            re.I,
        ),
        "명령 실행 상태와 응답 경로를 분리해 확인하고, 긴 서비스에는 작업 시간에 맞는 Zenoh query timeout을 적용하세요.",
    ),
    (
        "network_lease",
        "내비게이션 lease heartbeat 단절",
        re.compile(
            r"lease.*(?:expired|stale)|disconnect|unreachable"
            r"|connection.*(?:lost|closed|refused)|zenoh.*(?:fail|error)",
            re.I,
        ),
        "Gateway 발행과 TB1 수신 간격을 각각 확인해 끊긴 구간을 찾으세요. 2초 안전 timeout은 원인 확인 없이 늘리지 마세요.",
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
        "robot_telemetry",
        "로봇 상태 입력 stale·미수신",
        re.compile(
            r"ODOM_(?:NOT_RECEIVED|STALE)|BATTERY_(?:NOT_RECEIVED|STALE)",
            re.I,
        ),
        "odom·battery 발행 주기와 로봇 드라이버 상태, DDS 전달 경로를 순서대로 확인하세요.",
    ),
    (
        "sensor_qos",
        "센서 QoS 비호환",
        re.compile(
            r"incompatible QoS|offering incompatible QoS|QoS.*incompatible",
            re.I,
        ),
        "publisher와 subscriber의 reliability·durability QoS를 센서 데이터 계약에 맞추세요.",
    ),
    (
        "power_state",
        "배터리 전압·잔량 경고",
        re.compile(r"LOW_BATTERY|battery.*(?:low|critical)", re.I),
        "배터리 전압과 잔량 freshness를 확인하고 안전한 수준까지 충전한 뒤 시험하세요.",
    ),
    (
        "navigation_lifecycle",
        "Nav2 서버 중복·기동 실패",
        re.compile(
            r"more than one action server|unexpected goal response"
            r"|Failed to bring up all requested nodes|Aborting bringup",
            re.I,
        ),
        "중복 Nav2 프로세스와 lifecycle manager 실패 원인을 확인한 뒤 단일 서버만 기동하세요.",
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
            r"|status_transport_delay|out of memory"
            r"|HIGH_CPU|cpu.*(?:high|warning)|memory.*(?:high|warning)",
            re.I,
        ),
        "10분 CPU·메모리 추세와 Nav2 제어 주기 지연을 비교하세요.",
    ),
    (
        "safety_stop",
        "안전 정지 개입",
        re.compile(
            r"emergency stop active|e-?stop"
            r"|watchdog(?![^\n]*timeout\s*=)[^\n]*"
            r"(?:timeout|timed?\s*out|expired|stale|triggered)",
            re.I,
        ),
        "정지 원인을 해소한 뒤 IDLE·0 입력에서만 수동으로 재무장하세요.",
    ),
)

# Some Nav2 components report caught, transient transform exceptions or plugin
# initialization at INFO while successfully continuing, and the navigation
# agent announces its lease timeout configuration at startup.  Those records
# remain in the immutable raw log and anomaly features, but are not strong
# enough to become a root-cause incident without WARNING/ERROR severity.
ROOT_CAUSE_REQUIRES_WARNING = frozenset(
    {
        "collision_clearance",
        "localization_tf",
        "navigation_progress",
        "network_lease",
        "transport_reply",
        "robot_telemetry",
        "sensor_qos",
        "power_state",
        "navigation_lifecycle",
    }
)
INFO_ONLY_MIN_OCCURRENCES = {
    "sensor_data": 2,
}


DIAGNOSIS_GUIDANCE = {
    "clock_sync": {
        "confirmed_symptom": "관제 PC와 TB1 사이 시각 차이가 Zenoh의 500ms 허용 범위를 넘었습니다.",
        "root_cause_status": "CONFIRMED_ENVIRONMENT_FAULT",
        "hypotheses": [
            "Windows Time이 Local CMOS Clock을 사용하거나 동기화되지 않음",
            "WSL 또는 TB1이 부팅·절전 복귀 뒤 아직 NTP 보정 중임",
            "시각의 역방향 보정이 ROS timer를 일시 지연시킴",
        ],
        "checks": [
            "Windows에서 w32tm /query /status와 time.google.com stripchart를 확인",
            "WSL과 TB1에서 timedatectl timesync-status의 Offset을 확인",
            "양쪽 Zenoh journal에서 exceeding delta 500ms 발생 시각을 확인",
        ],
        "fixes": [
            "관리자 PowerShell에서 scripts/control-pc/configure_windows_time.ps1 실행",
            "WSL·TB1 시각 차이가 0.2초 이내인지 재확인",
            "시각 보정 뒤 control/TB1 Zenoh 브리지를 재시작하고 오류 0건 검증",
        ],
    },
    "lease_timer": {
        "confirmed_symptom": "Gateway의 lease timer 호출 간격이 정상 0.5초보다 크게 지연됐습니다.",
        "root_cause_status": "CONFIRMED_COMPONENT_FAULT",
        "hypotheses": [
            "시스템 시각 역방향 보정으로 ROS system-time timer가 지연됨",
            "Gateway executor가 장시간 callback 또는 높은 부하로 정체됨",
        ],
        "checks": [
            "lease timer gap과 같은 시각의 시계 보정·CPU·callback 로그를 비교",
            "Gateway lease TX와 TB1 lease RX 최대 간격을 비교",
        ],
        "fixes": [
            "lease timer를 wall clock과 분리된 steady clock으로 실행",
            "고부하 telemetry와 lease 발행 executor를 분리",
        ],
    },
    "network_lease": {
        "confirmed_symptom": "TB1이 2초 이상 유효한 navigation lease를 받지 못해 Nav2 목표를 fail-closed 취소했습니다.",
        "root_cause_status": "UNCONFIRMED_TRANSPORT_OR_PUBLISHER_CAUSE",
        "hypotheses": [
            "Gateway lease timer 또는 publisher가 2초 이상 멈춤",
            "control Zenoh→TB1 Zenoh→DDS 전달 경로가 끊김",
            "TB1 executor가 lease callback을 처리하지 못함",
            "Wi-Fi 지연·손실 또는 프로세스 재시작이 발생함",
        ],
        "checks": [
            "Gateway lease timer gap과 command_id lifecycle 로그를 확인",
            "TB1의 마지막 lease 수신 age와 Zenoh route 로그를 확인",
            "같은 시각의 Wi-Fi·CPU·재부팅 기록을 확인",
        ],
        "fixes": [
            "시계 동기화와 양쪽 브리지 상태를 먼저 복구",
            "lease TX는 정상인데 RX만 끊기면 Zenoh route/QoS와 Wi-Fi를 점검",
            "TX 자체가 끊기면 lease timer를 steady clock·독립 executor로 보호",
            "2초 timeout은 안전 deadman이므로 계측 없이 늘리지 않음",
        ],
    },
    "transport_reply": {
        "confirmed_symptom": "ROS service/action 요청에 Zenoh reply가 돌아오지 않아 클라이언트가 timeout을 기다렸습니다.",
        "root_cause_status": "CONFIRMED_TRANSPORT_RESPONSE_LOSS",
        "hypotheses": [
            "로봇 작업 시간이 Zenoh service query timeout보다 김",
            "서비스 처리 중 Zenoh 브리지가 재시작되거나 route가 사라짐",
            "중복 action 질의 중 일부가 응답 없이 종료됨",
        ],
        "checks": [
            "같은 command_id의 실제 로봇 상태가 변경됐는지 확인",
            "control bridge의 queries_timeout과 실제 작업 시간을 비교",
            "요청 시각에 양쪽 Zenoh PID·route 재생성 기록을 확인",
        ],
        "fixes": [
            "profile·map save처럼 긴 서비스에 개별 query timeout 적용",
            "서비스 응답 전에 해당 Zenoh 브리지를 재시작하지 않음",
            "응답 손실 시 mapping/navigation status로 결과를 멱등 확인",
        ],
    },
    "navigation_progress": {
        "confirmed_symptom": "Nav2가 유효한 local trajectory 또는 진행 조건을 유지하지 못했습니다.",
        "root_cause_status": "NAV2_LOCAL_PLANNER_OR_PROGRESS",
        "hypotheses": [
            "로봇 주변 여유 공간 부족 또는 local costmap 장애물",
            "controller 계산 지연이나 footprint·inflation 설정 불일치",
            "목표 방향·위치가 현재 자세에서 진입하기 어려움",
        ],
        "checks": [
            "local costmap과 footprint 위에 장애물·inflation 영역을 표시",
            "No valid trajectories, controller patience, control loop miss를 같은 command에서 확인",
            "전방·측면·후방 LiDAR 최소 거리와 센서 freshness를 확인",
        ],
        "fixes": [
            "로봇 주변 공간을 확보하고 가까운 중간 목표로 재시험",
            "footprint·inflation·controller 속도/샘플 설정을 실차 크기에 맞게 조정",
            "CPU 지연이 동반되면 costmap 크기·갱신률·controller 부하를 낮춤",
        ],
    },
    "localization_tf": {
        "confirmed_symptom": "map·odom·base TF 또는 초기 위치가 준비되지 않은 로그가 감지됐습니다.",
        "root_cause_status": "MAY_BE_EXPECTED_DURING_STARTUP",
        "hypotheses": [
            "초기 위치 설정 전 AMCL의 정상 대기 경고",
            "시각 오차 또는 오래된 TF 데이터",
            "초기 위치가 실제 위치와 크게 다름",
        ],
        "checks": [
            "경고가 초기 위치 설정 전인지, 목적지 이동 중인지 구분",
            "map→odom→base_footprint TF와 AMCL pose freshness 확인",
        ],
        "fixes": [
            "실제 위치와 방향에 초기 pose를 지정하고 LiDAR 정합 확인",
            "시계 동기화 뒤 TF_OLD_DATA가 계속되는지 재확인",
        ],
    },
    "safety_stop": {
        "confirmed_symptom": "e-stop 또는 watchdog 안전 정지가 속도 명령을 0으로 강제했습니다.",
        "root_cause_status": "CONFIRMED_SAFETY_INTERVENTION",
        "hypotheses": [
            "사용자 또는 Gateway가 e-stop을 활성화함",
            "watchdog 입력·authorization이 stale 상태가 됨",
            "안전 상태 heartbeat가 timeout을 넘김",
        ],
        "checks": [
            "Audit Events에서 e-stop 요청 주체와 시각을 확인",
            "safety status의 mode, motion_armed, freshness를 확인",
            "같은 시각의 arbiter·watchdog input gap을 확인",
        ],
        "fixes": [
            "정지 원인을 제거한 뒤 로봇 주변을 비우고 e-stop 해제",
            "IDLE·0 명령을 확인한 뒤에만 motion을 재무장",
            "watchdog 지연이면 callback·CPU·DDS 구간을 계측하고 timeout은 임의로 늘리지 않음",
        ],
    },
    "collision_clearance": {
        "confirmed_symptom": "LiDAR 또는 local planner가 안전 여유거리 부족을 감지했습니다.",
        "root_cause_status": "OBSTACLE_OR_COSTMAP_CONSTRAINT",
        "hypotheses": [
            "로봇 전방 또는 footprint 주변 실제 장애물",
            "측·후방 한 점이 360도 최소거리 검사에 포함된 과민 정지",
            "costmap obstacle·inflation 설정이 실차와 맞지 않음",
        ],
        "checks": [
            "LiDAR 점군과 local costmap을 같은 화면에서 확인",
            "장애물 방향이 전방·측면·후방 중 어디인지 구분",
            "scan freshness와 비정상 단일 최소값을 확인",
        ],
        "fixes": [
            "실제 장애물을 치우고 가까운 중간 목표로 재시험",
            "정지 검사를 진행 방향 sector 기반으로 분리",
            "footprint·inflation·obstacle range를 실차 측정값으로 조정",
        ],
    },
    "robot_telemetry": {
        "confirmed_symptom": "Gateway가 최신 odom 또는 battery 상태를 제한 시간 안에 받지 못했습니다.",
        "root_cause_status": "CONFIRMED_TELEMETRY_STALE_OR_MISSING",
        "hypotheses": [
            "OpenCR·로봇 드라이버가 센서 상태를 발행하지 못함",
            "TB1 ROS executor 또는 DDS·Zenoh 전달이 지연됨",
            "드라이버 재시작 직후 첫 상태를 기다리는 중임",
        ],
        "checks": [
            "TB1에서 odom·battery topic 주기와 publisher 수를 확인",
            "같은 시각 robot_agent CPU·restart·Zenoh 로그를 대조",
            "웹 상태의 각 센서 age가 회복되는지 확인",
        ],
        "fixes": [
            "발행 자체가 없으면 OpenCR·드라이버 연결과 서비스를 복구",
            "TB1에는 정상인데 관제에 없으면 DDS·Zenoh route와 QoS를 점검",
            "복구 뒤 freshness가 연속 30초 유지되는지 검증",
        ],
    },
    "sensor_qos": {
        "confirmed_symptom": "센서 publisher와 subscriber의 QoS가 호환되지 않아 데이터가 전달되지 않았습니다.",
        "root_cause_status": "CONFIRMED_QOS_CONTRACT_MISMATCH",
        "hypotheses": [
            "센서 publisher는 BEST_EFFORT인데 subscriber가 RELIABLE을 요구함",
            "새 publisher가 기존 topic과 다른 QoS로 시작됨",
        ],
        "checks": [
            "ros2 topic info -v로 양쪽 reliability·durability 확인",
            "동일 topic에 서로 다른 QoS publisher가 중복됐는지 확인",
        ],
        "fixes": [
            "LiDAR·고주기 센서 subscriber는 sensor-data QoS를 사용",
            "중복 publisher를 제거하고 수신 주기를 다시 측정",
        ],
    },
    "power_state": {
        "confirmed_symptom": "로봇이 낮은 배터리 상태를 보고했습니다.",
        "root_cause_status": "CONFIRMED_POWER_WARNING",
        "hypotheses": [
            "실제 배터리 전압·잔량이 운용 기준 아래임",
            "배터리 telemetry가 오래됐거나 순간적으로 잘못 읽힘",
        ],
        "checks": [
            "전압·잔량·freshness를 함께 확인",
            "충전 전후 값과 OpenCR 진단을 비교",
        ],
        "fixes": [
            "낮은 잔량이면 주행을 중단하고 충전",
            "값이 비정상이면 배터리 커넥터와 OpenCR telemetry를 점검",
        ],
    },
    "navigation_lifecycle": {
        "confirmed_symptom": "Nav2 lifecycle 기동이 실패했거나 action server가 중복 감지됐습니다.",
        "root_cause_status": "CONFIRMED_NAV2_PROCESS_TOPOLOGY_FAULT",
        "hypotheses": [
            "이전 Nav2 프로세스가 남은 상태에서 새 프로파일이 시작됨",
            "필수 lifecycle node 설정·TF·센서 준비가 실패함",
        ],
        "checks": [
            "Nav2 node와 action server가 각각 한 개만 존재하는지 확인",
            "lifecycle manager의 최초 실패 로그와 직전 profile 전환을 대조",
        ],
        "fixes": [
            "중복 프로세스를 정상 종료하고 단일 navigation profile로 재기동",
            "최초 configure·activate 실패 원인을 해결한 뒤 전체 lifecycle 상태 검증",
        ],
    },
}


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

    def rate(pattern_name: str, warning_only: bool = True) -> float:
        pattern = PATTERNS[pattern_name]
        eligible_records = [
            record
            for record in records
            if not warning_only
            or record.severity.upper()
            in {"WARNING", "WARN", "ERROR", "FATAL"}
        ]
        if not eligible_records:
            return 0.0
        return sum(
            bool(pattern.search(record.message))
            for record in eligible_records
        ) / len(eligible_records)

    return {
        "line_count": float(count),
        "error_rate": errors / count,
        "warning_rate": warnings / count,
        "timeout_rate": rate("timeout"),
        "disconnect_rate": rate("disconnect"),
        "navigation_failure_rate": rate("navigation_failure"),
        "restart_rate": rate("restart"),
        "dropped_message_rate": rate("dropped_message"),
        "tf_wait_rate": rate("tf_wait", warning_only=False),
        "safety_stop_rate": rate("safety_stop"),
        "resource_pressure_rate": rate("resource_pressure"),
        "transport_reply_rate": rate("transport_reply"),
        "lease_failure_rate": rate("lease_failure"),
        "obstacle_clearance_rate": rate("obstacle_clearance"),
        "sensor_health_rate": rate("sensor_health"),
        "qos_failure_rate": rate("qos_failure"),
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


def _incident_fingerprint(record: LogRecord) -> str:
    """Return a stable signature while removing per-request identifiers."""
    message = re.sub(
        r"\b(command|request|goal|task|patrol)(?:_id)?\s*[=:]\s*[0-9a-f-]{6,}\b",
        r"\1=<id>",
        record.message,
        flags=re.I,
    )
    message = re.sub(r"\([0-9a-f]{8,},\s*\d+\)", "(<request-id>)", message, flags=re.I)
    message = re.sub(r"\s+", " ", message).strip().lower()
    return f"{record.unit}|{record.logger}|{message}"


def _deduplicate_incident_records(
    records: Sequence[LogRecord],
    window_sec: float = INCIDENT_DEDUP_WINDOW_SEC,
) -> List[LogRecord]:
    """Collapse burst repeats into one occurrence, keeping the newest evidence."""
    clusters: List[Dict[str, Any]] = []
    last_cluster_by_key: Dict[str, int] = {}
    for record in sorted(records, key=lambda item: item.timestamp):
        key = _incident_fingerprint(record)
        cluster_index = last_cluster_by_key.get(key)
        if cluster_index is not None:
            cluster = clusters[cluster_index]
            if record.timestamp - cluster["last"].timestamp <= window_sec:
                cluster["last"] = record
                continue
        last_cluster_by_key[key] = len(clusters)
        clusters.append({"last": record})
    return sorted(
        (cluster["last"] for cluster in clusters),
        key=lambda item: item.timestamp,
    )


def _diagnoses_overlap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    margin_sec: float = 30.0,
) -> bool:
    return not (
        float(left["_first_ts"]) > float(right["_last_ts"]) + margin_sec
        or float(right["_first_ts"]) > float(left["_last_ts"]) + margin_sec
    )


def _record_health(
    records: Sequence[LogRecord],
    reference_timestamp: float,
) -> Dict[str, Any]:
    """Summarize evidence freshness and provenance without claiming collector health."""
    if not records:
        return {
            "state": "NO_DATA",
            "latest_record_at": None,
            "latest_record_age_sec": None,
            "severity_counts": {},
            "sources": [],
        }
    latest = max(record.timestamp for record in records)
    age_sec = max(0.0, reference_timestamp - latest)
    severity_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    for record in records:
        severity = record.severity.upper()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        source = record.unit or record.logger or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
    sources = [
        {"source": source, "count": count}
        for source, count in sorted(
            source_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:10]
    ]
    return {
        "state": (
            "FRESH"
            if age_sec <= FRESH_EVIDENCE_WINDOW_SEC
            else "STALE_EVIDENCE"
        ),
        "latest_record_at": utc_now(latest),
        "latest_record_age_sec": round(age_sec, 3),
        "severity_counts": severity_counts,
        "sources": sources,
    }


def diagnose_records(
    records: Sequence[LogRecord],
    limit: int = 5,
    now_timestamp: Optional[float] = None,
    active_window_sec: float = ACTIVE_INCIDENT_WINDOW_SEC,
) -> List[Dict[str, Any]]:
    """Rank explainable root-cause hypotheses with bounded evidence."""
    diagnoses = []
    latest_timestamp = max(
        (record.timestamp for record in records),
        default=0.0,
    )
    reference_timestamp = (
        latest_timestamp if now_timestamp is None else float(now_timestamp)
    )
    cause_priority = {
        "network_lease": 100,
        "lease_timer": 95,
        "transport_reply": 92,
        "clock_sync": 90,
        "navigation_progress": 80,
        "collision_clearance": 75,
        "safety_stop": 70,
        "process_restart": 65,
        "navigation_lifecycle": 64,
        "resource_pressure": 55,
        "robot_telemetry": 54,
        "sensor_qos": 53,
        "sensor_data": 50,
        "power_state": 45,
        "localization_tf": 30,
    }
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
        matches.sort(key=lambda record: record.timestamp)
        occurrences = _deduplicate_incident_records(matches)
        if (
            all(record.severity.upper() in {"INFO", "DEBUG"} for record in matches)
            and len(occurrences) < INFO_ONLY_MIN_OCCURRENCES.get(cause, 1)
        ):
            continue
        loggers = {record.logger for record in matches}
        confidence = min(
            0.98,
            0.5
            + 0.08 * math.log2(len(occurrences) + 1)
            + 0.04 * len(loggers),
        )
        evidence = [
            {
                "timestamp": utc_now(record.timestamp),
                "severity": record.severity,
                "logger": record.logger,
                "message": record.message[:300],
            }
            for record in occurrences[-3:]
        ]
        guidance = DIAGNOSIS_GUIDANCE.get(cause, {})
        expected_startup = (
            cause == "localization_tf"
            and all(
                re.search(
                    r"AMCL cannot publish|set the initial pose",
                    item.message,
                    re.I,
                )
                for item in matches
            )
        )
        age_sec = max(0.0, reference_timestamp - matches[-1].timestamp)
        status = (
            "EXPECTED_STARTUP"
            if expected_startup
            else (
                "ACTION_REQUIRED"
                if age_sec <= active_window_sec
                else "HISTORICAL"
            )
        )
        sources = sorted(
            {
                record.unit or record.logger or "unknown"
                for record in matches
            }
        )
        diagnoses.append(
            {
                "cause": cause,
                "label": label,
                "count": len(matches),
                "raw_count": len(matches),
                "occurrence_count": len(occurrences),
                "confidence": round(confidence, 3),
                "evidence_strength": round(confidence, 3),
                "first_seen": utc_now(matches[0].timestamp),
                "last_seen": utc_now(matches[-1].timestamp),
                "duration_sec": round(
                    max(0.0, matches[-1].timestamp - matches[0].timestamp),
                    3,
                ),
                "status": status,
                "active": status == "ACTION_REQUIRED",
                "age_sec": round(age_sec, 3),
                "source_count": len(sources),
                "sources": sources,
                "evidence": evidence,
                "recommended_action": recommendation,
                "confirmed_symptom": guidance.get(
                    "confirmed_symptom",
                    f"{label} 관련 경고 또는 오류가 확인됐습니다.",
                ),
                "root_cause_status": guidance.get(
                    "root_cause_status",
                    "HYPOTHESIS",
                ),
                "hypotheses": list(guidance.get("hypotheses", [])),
                "checks": list(guidance.get("checks", [recommendation])),
                "fixes": list(guidance.get("fixes", [recommendation])),
                "missing_evidence": [],
                "correlated_causes": [],
                "_first_ts": matches[0].timestamp,
                "_last_ts": matches[-1].timestamp,
                "_sort_score": (
                    cause_priority.get(cause, 0)
                    - (60 if expected_startup else 0)
                    - (200 if status == "HISTORICAL" else 0)
                    - min(age_sec / 60.0, 20.0)
                ),
            }
        )
    by_cause = {item["cause"]: item for item in diagnoses}
    correlation_candidates = {
        "network_lease": (
            "lease_timer",
            "clock_sync",
            "transport_reply",
            "process_restart",
            "resource_pressure",
        ),
        "navigation_progress": (
            "collision_clearance",
            "localization_tf",
            "sensor_data",
            "resource_pressure",
        ),
        "transport_reply": ("network_lease", "process_restart", "clock_sync"),
        "sensor_data": ("resource_pressure", "process_restart"),
        "robot_telemetry": (
            "resource_pressure",
            "sensor_qos",
            "process_restart",
            "network_lease",
        ),
        "navigation_lifecycle": (
            "process_restart",
            "localization_tf",
            "sensor_qos",
        ),
    }
    for cause, candidates in correlation_candidates.items():
        diagnosis = by_cause.get(cause)
        if diagnosis is None:
            continue
        diagnosis["correlated_causes"] = [
            candidate
            for candidate in candidates
            if candidate in by_cause
            and _diagnoses_overlap(diagnosis, by_cause[candidate])
        ]
    lease = by_cause.get("network_lease")
    if lease is not None:
        lease["missing_evidence"] = [
            "과거 로그에는 Gateway lease TX sequence와 TB1 RX sequence가 없어 단절 지점을 확정할 수 없습니다.",
        ]
        correlated = lease["correlated_causes"]
        if correlated:
            lease["root_cause_status"] = "CORRELATED_EVIDENCE"
            lease["_sort_score"] += 25
    safety = by_cause.get("safety_stop")
    if safety is not None:
        safety_messages = [record.message for record in records if re.search(
            r"emergency stop active|e-?stop|watchdog.*timeout",
            record.message,
            re.I,
        )]
        expected_estop_state = bool(safety_messages) and all(
            re.search(r"emergency stop active|e-?stop active|estop active", message, re.I)
            and not re.search(r"watchdog", message, re.I)
            for message in safety_messages
        )
        related_failures = [
            cause
            for cause in (
                "network_lease",
                "lease_timer",
                "navigation_progress",
                "collision_clearance",
                "sensor_data",
                "robot_telemetry",
                "sensor_qos",
                "navigation_lifecycle",
                "resource_pressure",
                "process_restart",
            )
            if cause in by_cause
            and _diagnoses_overlap(safety, by_cause[cause], margin_sec=15.0)
        ]
        safety["correlated_causes"] = related_failures
        if expected_estop_state and not related_failures:
            safety["status"] = "EXPECTED_SAFETY_STATE"
            safety["active"] = False
            safety["root_cause_status"] = "EXPECTED_OPERATOR_OR_IDLE_STATE"
            safety["_sort_score"] -= 160
    diagnoses.sort(
        key=lambda item: (
            item["_sort_score"],
            item["last_seen"],
            item["count"],
        ),
        reverse=True,
    )
    selected = diagnoses[: max(1, min(int(limit), 20))]
    for item in selected:
        for internal_key in ("_sort_score", "_first_ts", "_last_ts"):
            item.pop(internal_key, None)
    return selected


def incidents_from_path(
    status_path: Optional[Path],
    max_records: int = 2000,
    lookback_sec: float = 3600.0,
    now_timestamp: Optional[float] = None,
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
    all_records = list(records)
    total_record_count = len(all_records)
    reference_timestamp = (
        time.time() if now_timestamp is None else float(now_timestamp)
    )
    if records and math.isfinite(lookback_sec) and lookback_sec > 0.0:
        cutoff = reference_timestamp - float(lookback_sec)
        records = [record for record in records if record.timestamp >= cutoff]
    model_state = status.get("state")
    diagnoses = diagnose_records(
        records,
        limit=20,
        now_timestamp=reference_timestamp,
    )
    incident_summary = {
        "active": sum(item["status"] == "ACTION_REQUIRED" for item in diagnoses),
        "historical": sum(item["status"] == "HISTORICAL" for item in diagnoses),
        "expected": sum(item["status"].startswith("EXPECTED_") for item in diagnoses),
        "total": len(diagnoses),
    }
    return {
        "analysis_method": "rule_evidence_v3",
        "analysis_mode": (
            "MODEL_AND_RULES"
            if model_state not in {None, "MODEL_NOT_READY", "ERROR"}
            else "RULE_ONLY"
        ),
        "scope": "bounded_recent_ros2_raw_logs",
        "record_count": len(records),
        "total_record_count": total_record_count,
        "lookback_sec": float(lookback_sec),
        "summary": incident_summary,
        "data_health": _record_health(all_records, reference_timestamp),
        "model": {
            "model_id": status.get("model_id"),
            "state": status.get("state"),
            "score": status.get("score"),
            "threshold": status.get("threshold"),
            "observed_at": status.get("observed_at"),
        },
        "diagnoses": diagnoses,
        "message": (
            "Production 모델이 없으면 규칙·상태 기반 분석만 사용합니다. "
            "확정 증상과 근본원인 가설을 구분하며 자동 제어에는 사용하지 않습니다."
        ),
    }


SCENARIO_CAUSE_LABELS = {
    "clock_sync": "connectivity_time",
    "lease_timer": "connectivity_lease",
    "network_lease": "connectivity_lease",
    "transport_reply": "connectivity_reply",
    "localization_tf": "localization_wait",
    "collision_clearance": "obstacle_clearance",
    "navigation_progress": "navigation_failure",
    "sensor_data": "sensor_degradation",
    "robot_telemetry": "sensor_degradation",
    "sensor_qos": "sensor_qos",
    "process_restart": "process_lifecycle",
    "navigation_lifecycle": "process_lifecycle",
    "resource_pressure": "resource_pressure",
    "power_state": "power_warning",
    "safety_stop": "safety_stop",
}
SCENARIO_SIGNAL_LABELS = {
    "initial_pose_wait": "localization_wait",
    "control_deadline_miss": "resource_pressure",
    "planning_failure": "navigation_failure",
    "collision_guard": "obstacle_clearance",
    "progress_failure": "navigation_failure",
    "message_drop": "sensor_degradation",
}
SCENARIO_LABEL_ORDER = (
    "safety_stop",
    "connectivity_time",
    "connectivity_lease",
    "connectivity_reply",
    "process_lifecycle",
    "sensor_qos",
    "sensor_degradation",
    "power_warning",
    "resource_pressure",
    "obstacle_clearance",
    "navigation_failure",
    "localization_wait",
    "unclassified_warning",
    "expected_safety_state",
    "expected_manual_stop",
    "normal_navigation",
    "normal_mapping",
    "normal_idle",
)


def classify_scenario_window(
    records: Sequence[LogRecord],
) -> Dict[str, Any]:
    """Label one time window for baseline training and fault validation."""
    if not records:
        return {
            "primary_label": "normal_idle",
            "labels": ["normal_idle"],
            "baseline_eligible": True,
            "label_source": "auto_rule",
            "annotation_ids": [],
            "diagnostic_causes": [],
            "operational_signals": [],
            "warning_error_count": 0,
        }
    diagnoses = diagnose_records(records, limit=20)
    diagnostic_causes = [item["cause"] for item in diagnoses]
    fault_diagnostic_causes = [
        item["cause"]
        for item in diagnoses
        if not str(item.get("status", "")).startswith("EXPECTED_")
    ]
    operational_signals = [
        item["signal"]
        for item in extract_operational_signals(records)
        if item["signal"] != "message_drop"
        or int(item["count"]) >= INFO_ONLY_MIN_OCCURRENCES["sensor_data"]
        or any(
            record.severity.upper()
            in {"WARNING", "WARN", "ERROR", "FATAL"}
            and re.search(
                r"dropping message|sample.*lost|message.*lost",
                record.message,
                re.I,
            )
            for record in records
        )
    ]
    labels = {
        SCENARIO_CAUSE_LABELS[cause]
        for cause in fault_diagnostic_causes
        if cause in SCENARIO_CAUSE_LABELS
    }
    if any(
        item["cause"] == "safety_stop"
        and str(item.get("status", "")).startswith("EXPECTED_")
        for item in diagnoses
    ):
        labels.add("expected_safety_state")
    labels.update(
        SCENARIO_SIGNAL_LABELS[signal]
        for signal in operational_signals
        if signal in SCENARIO_SIGNAL_LABELS
    )
    warning_error_count = sum(
        record.severity.upper() in {"WARNING", "WARN", "ERROR", "FATAL"}
        for record in records
    )
    if not labels and warning_error_count:
        warning_messages = [
            record.message
            for record in records
            if record.severity.upper()
            in {"WARNING", "WARN", "ERROR", "FATAL"}
        ]
        if warning_messages and all(
            re.search(
                r"Manual session stopped|Motion disarmed; waiting for neutral command",
                message,
                re.I,
            )
            for message in warning_messages
        ):
            labels.add("expected_manual_stop")
        else:
            labels.add("unclassified_warning")
    if not labels:
        if any(
            record.logger == "slam_toolbox"
            or re.search(r"slam_toolbox|serializePoseGraph", record.message, re.I)
            for record in records
        ):
            labels.add("normal_mapping")
        elif any(
            re.search(
                r"Passing new path to controller|navigate(?:_to_pose)?"
                r"|goal (?:accepted|reached|succeeded)",
                record.message,
                re.I,
            )
            for record in records
        ):
            labels.add("normal_navigation")
        else:
            labels.add("normal_idle")
    ordered_labels = sorted(
        labels,
        key=lambda label: (
            SCENARIO_LABEL_ORDER.index(label)
            if label in SCENARIO_LABEL_ORDER
            else len(SCENARIO_LABEL_ORDER),
            label,
        ),
    )
    baseline_eligible = all(
        label.startswith("normal_") for label in ordered_labels
    )
    return {
        "primary_label": ordered_labels[0],
        "labels": ordered_labels,
        "baseline_eligible": baseline_eligible,
        "label_source": "auto_rule",
        "annotation_ids": [],
        "diagnostic_causes": diagnostic_causes,
        "operational_signals": operational_signals,
        "warning_error_count": warning_error_count,
    }


def create_scenario_annotation(
    label: str,
    since_timestamp: float,
    until_timestamp: float,
    note: str,
    confirmed_by: str = "operator",
    robot_id: str = "tb1",
    created_at: Optional[str] = None,
    supersedes_annotation_ids: Sequence[str] = (),
) -> Dict[str, Any]:
    """Create an immutable operator-confirmed scenario interval."""
    normalized_label = str(label).strip()
    if normalized_label not in SCENARIO_LABEL_ORDER:
        raise ValueError(f"unsupported scenario label: {normalized_label}")
    since = float(since_timestamp)
    until = float(until_timestamp)
    if (
        not math.isfinite(since)
        or not math.isfinite(until)
        or since <= 0
        or until <= since
    ):
        raise ValueError("scenario timestamps must be positive, finite and ordered")
    if not str(note).strip():
        raise ValueError("scenario annotation note is required")
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "label": normalized_label,
        "since_timestamp": since,
        "until_timestamp": until,
        "note": str(note).strip(),
        "confirmed_by": str(confirmed_by).strip() or "operator",
        "robot_id": str(robot_id).strip() or "tb1",
        "label_source": "operator_confirmed",
        "created_at": created_at or utc_now(),
    }
    supersedes = sorted(
        {
            str(annotation_id).strip()
            for annotation_id in supersedes_annotation_ids
            if str(annotation_id).strip()
        }
    )
    if supersedes:
        payload["supersedes_annotation_ids"] = supersedes
    payload["annotation_id"] = f"scenario-{content_hash(payload)[:12]}"
    return payload


def _validated_annotations(
    annotations: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    validated = []
    for annotation in annotations:
        validated.append(
            create_scenario_annotation(
                str(annotation.get("label", "")),
                float(annotation.get("since_timestamp", 0.0)),
                float(annotation.get("until_timestamp", 0.0)),
                str(annotation.get("note", "")),
                confirmed_by=str(annotation.get("confirmed_by", "operator")),
                robot_id=str(annotation.get("robot_id", "tb1")),
                created_at=str(annotation.get("created_at") or utc_now()),
                supersedes_annotation_ids=annotation.get(
                    "supersedes_annotation_ids", ()
                ),
            )
        )
        supplied_id = str(annotation.get("annotation_id") or "")
        if supplied_id:
            validated[-1]["annotation_id"] = supplied_id
    known_ids = {
        str(annotation["annotation_id"]) for annotation in validated
    }
    superseded_ids = {
        str(annotation_id)
        for annotation in validated
        for annotation_id in annotation.get(
            "supersedes_annotation_ids", []
        )
    }
    unknown_ids = sorted(superseded_ids - known_ids)
    if unknown_ids:
        raise ValueError(
            "superseded scenario annotations are unavailable: "
            + ", ".join(unknown_ids)
        )
    for annotation in validated:
        if annotation["annotation_id"] in annotation.get(
            "supersedes_annotation_ids", []
        ):
            raise ValueError("scenario annotation cannot supersede itself")
    return [
        annotation
        for annotation in validated
        if annotation["annotation_id"] not in superseded_ids
    ]


def _apply_window_annotations(
    scenario: Mapping[str, Any],
    annotations: Sequence[Mapping[str, Any]],
    window_start: float,
    window_end: float,
) -> Dict[str, Any]:
    matches = [
        annotation
        for annotation in annotations
        if float(annotation["since_timestamp"]) < window_end
        and float(annotation["until_timestamp"]) > window_start
    ]
    if not matches:
        return dict(scenario)
    labels = sorted(
        {str(annotation["label"]) for annotation in matches},
        key=lambda label: SCENARIO_LABEL_ORDER.index(label),
    )
    confirmed = dict(scenario)
    confirmed.update(
        {
            "primary_label": labels[0],
            "labels": labels,
            "baseline_eligible": all(
                label.startswith("normal_") for label in labels
            ),
            "label_source": "operator_confirmed",
            "annotation_ids": [
                str(annotation["annotation_id"]) for annotation in matches
            ],
            "auto_labels": list(scenario.get("labels", [])),
        }
    )
    return confirmed


def build_dataset(
    records: Sequence[LogRecord],
    window_sec: float = 60.0,
    created_at: Optional[str] = None,
    since_timestamp: Optional[float] = None,
    until_timestamp: Optional[float] = None,
    include_scenarios: bool = False,
    annotations: Sequence[Mapping[str, Any]] = (),
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
    validated_annotations = _validated_annotations(annotations)
    include_scenarios = include_scenarios or bool(validated_annotations)
    rows = []
    scenario_counts: Dict[str, int] = {}
    label_source_counts: Dict[str, int] = {}
    for bucket, window_records in sorted(buckets.items()):
        start = bucket * window_sec
        row = {
            "window_start": utc_now(start),
            "window_end": utc_now(start + window_sec),
            "log_count": len(window_records),
            "features": extract_features(window_records),
        }
        if include_scenarios:
            scenario = classify_scenario_window(window_records)
            scenario = _apply_window_annotations(
                scenario,
                validated_annotations,
                start,
                start + window_sec,
            )
            row["scenario"] = scenario
            label_source = str(scenario["label_source"])
            label_source_counts[label_source] = (
                label_source_counts.get(label_source, 0) + 1
            )
            for label in scenario["labels"]:
                scenario_counts[label] = scenario_counts.get(label, 0) + 1
        rows.append(row)
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
    if include_scenarios:
        eligible_rows = [
            row for row in rows if row["scenario"]["baseline_eligible"]
        ]
        payload.update(
            {
                "dataset_kind": "scenario_labeled_windows",
                "scenario_counts": scenario_counts,
                "label_source_counts": label_source_counts,
                "annotation_ids": sorted(
                    str(annotation["annotation_id"])
                    for annotation in validated_annotations
                ),
                "superseded_annotation_ids": sorted(
                    {
                        str(annotation_id)
                        for annotation in validated_annotations
                        for annotation_id in annotation.get(
                            "supersedes_annotation_ids", []
                        )
                    }
                ),
                "training_eligible_window_count": len(eligible_rows),
                "training_eligible_record_count": sum(
                    int(row["log_count"]) for row in eligible_rows
                ),
                "excluded_scenario_window_count": (
                    len(rows) - len(eligible_rows)
                ),
            }
        )
    payload["dataset_hash"] = content_hash(payload)
    return payload


def train_model(
    dataset: Mapping[str, Any],
    trained_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Fit a robust baseline and validate labeled fault scenarios."""
    rows = list(dataset.get("rows", []))
    if not rows:
        raise ValueError("dataset must contain at least one feature window")
    scenario_labeled = dataset.get("dataset_kind") == "scenario_labeled_windows"
    eligible_rows = [
        row
        for row in rows
        if not scenario_labeled
        or bool(row.get("scenario", {}).get("baseline_eligible", False))
    ]
    if not eligible_rows:
        raise ValueError("dataset has no baseline-eligible feature windows")
    validation_rows: List[Mapping[str, Any]] = []
    training_rows = list(eligible_rows)
    validation_strategy = "in_sample_robust_calibration"
    if scenario_labeled and len(eligible_rows) >= 10:
        validation_count = max(2, int(math.ceil(len(eligible_rows) * 0.20)))
        training_rows = eligible_rows[:-validation_count]
        validation_rows = eligible_rows[-validation_count:]
        validation_strategy = "temporal_last_20_percent_holdout"
    centers: Dict[str, float] = {}
    scales: Dict[str, float] = {}
    for feature in FEATURE_NAMES:
        values = [
            float(row["features"].get(feature, 0.0))
            for row in training_rows
        ]
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
    feature_thresholds: Dict[str, float] = {}
    for feature in FEATURE_NAMES:
        deviations = [
            abs(float(row["features"].get(feature, 0.0)) - centers[feature])
            / max(scales[feature], 1.0e-12)
            for row in training_rows
        ]
        feature_thresholds[feature] = max(
            4.0,
            _percentile(deviations, 0.99) * 1.25,
        )
    base_model["feature_thresholds"] = feature_thresholds
    scores = [
        score_features(row["features"], base_model)["score"]
        for row in training_rows
    ]
    calibration = _percentile(scores, 0.99)
    threshold = max(1.0, calibration * 1.25)
    sample_count = len(training_rows)
    record_count = int(dataset.get("record_count", 0))
    training_record_count = sum(
        int(row.get("log_count", 0)) for row in training_rows
    )
    discarded_record_count = int(dataset.get("discarded_record_count", 0))
    excluded_outside_range_count = int(
        dataset.get("excluded_outside_range_count", 0)
    )
    basic_gate_passed = sample_count >= 5 and training_record_count >= 20
    baseline_evaluation_rows = validation_rows or training_rows
    baseline_evaluation_scores = [
        score_features(row["features"], base_model)["score"]
        for row in baseline_evaluation_rows
    ]
    baseline_false_positives = sum(
        score > threshold for score in baseline_evaluation_scores
    )
    baseline_false_positive_rate = (
        baseline_false_positives / len(baseline_evaluation_scores)
        if baseline_evaluation_scores
        else 0.0
    )
    fault_rows = [
        row
        for row in rows
        if scenario_labeled
        and not bool(row.get("scenario", {}).get("baseline_eligible", False))
        and any(
            not str(label).startswith("expected_")
            for label in row.get("scenario", {}).get("labels", [])
        )
    ]
    fault_labels = sorted(
        {
            str(label)
            for row in fault_rows
            for label in row.get("scenario", {}).get("labels", [])
            if not str(label).startswith("normal_")
            and not str(label).startswith("expected_")
        }
    )
    operator_confirmed_rows = [
        row
        for row in rows
        if row.get("scenario", {}).get("label_source")
        == "operator_confirmed"
    ]
    operator_confirmed_normal_rows = [
        row
        for row in operator_confirmed_rows
        if bool(row.get("scenario", {}).get("baseline_eligible", False))
    ]
    operator_confirmed_fault_labels = sorted(
        {
            str(label)
            for row in operator_confirmed_rows
            if not bool(
                row.get("scenario", {}).get("baseline_eligible", False)
            )
            for label in row.get("scenario", {}).get("labels", [])
            if not str(label).startswith("expected_")
        }
    )
    scenario_metrics: Dict[str, Any] = {}
    for label in fault_labels:
        label_rows = [
            row
            for row in fault_rows
            if label in row.get("scenario", {}).get("labels", [])
        ]
        label_scores = [
            score_features(row["features"], base_model)["score"]
            for row in label_rows
        ]
        detected_count = sum(score > threshold for score in label_scores)
        scenario_metrics[label] = {
            "window_count": len(label_rows),
            "detected_count": detected_count,
            "detection_rate": (
                detected_count / len(label_rows) if label_rows else 0.0
            ),
            "median_score": statistics.median(label_scores)
            if label_scores
            else 0.0,
            "max_score": max(label_scores, default=0.0),
        }
    fault_scores = [
        score_features(row["features"], base_model)["score"]
        for row in fault_rows
    ]
    detected_fault_windows = sum(score > threshold for score in fault_scores)
    overall_detection_rate = (
        detected_fault_windows / len(fault_scores) if fault_scores else 0.0
    )
    qualified_fault_labels = [
        label
        for label in fault_labels
        if label != "unclassified_warning"
        and scenario_metrics[label]["window_count"] >= 2
    ]
    validated_fault_labels = [
        label
        for label in qualified_fault_labels
        if scenario_metrics[label]["detection_rate"] >= 0.50
    ]
    macro_detection_rate = (
        statistics.mean(
            scenario_metrics[label]["detection_rate"]
            for label in qualified_fault_labels
        )
        if qualified_fault_labels
        else 0.0
    )
    scenario_gate_passed = (
        not scenario_labeled
        or (
            len(validation_rows) >= 2
            and len(qualified_fault_labels) >= 3
            and len(validated_fault_labels) >= 3
            and len(fault_rows) >= 5
            and overall_detection_rate >= 0.60
            and macro_detection_rate >= 0.60
            and baseline_false_positive_rate <= 0.10
        )
    )
    validation_strength = (
        "operator_confirmed"
        if len(operator_confirmed_normal_rows) >= 2
        and len(operator_confirmed_fault_labels) >= 3
        else "auto_rule_weak_supervision"
    )
    gate_passed = basic_gate_passed and scenario_gate_passed
    warnings = []
    if discarded_record_count:
        warnings.append(
            f"{discarded_record_count} records with invalid timestamps "
            "were excluded"
        )
    if scenario_labeled and not validation_rows:
        warnings.append(
            "at least 10 clean windows are required for temporal holdout"
        )
    unclassified_count = int(
        dataset.get("scenario_counts", {}).get("unclassified_warning", 0)
    )
    if unclassified_count:
        warnings.append(
            f"{unclassified_count} warning windows need manual labels"
        )
    for label in fault_labels:
        if (
            label != "unclassified_warning"
            and scenario_metrics[label]["window_count"] < 2
        ):
            warnings.append(
                f"scenario {label} has only one labeled window"
            )
    if scenario_labeled and validation_strength != "operator_confirmed":
        warnings.append(
            "operator-confirmed normal and fault scenario coverage is pending"
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
        "model_type": (
            "robust_median_mad_scenario_validated"
            if scenario_labeled
            else "robust_median_mad"
        ),
        "model_id": model_id,
        "stage": "candidate",
        "trained_at": timestamp,
        "dataset_hash": dataset_hash,
        "feature_names": list(FEATURE_NAMES),
        "centers": centers,
        "scales": scales,
        "feature_thresholds": feature_thresholds,
        "threshold": threshold,
        "validation": {
            "strategy": validation_strategy,
            "validation_strength": validation_strength,
            "label_source_counts": dict(
                dataset.get("label_source_counts", {})
            ),
            "operator_confirmed_normal_window_count": len(
                operator_confirmed_normal_rows
            ),
            "operator_confirmed_fault_scenarios": (
                operator_confirmed_fault_labels
            ),
            "baseline_window_count": len(baseline_evaluation_rows),
            "baseline_false_positive_count": baseline_false_positives,
            "baseline_false_positive_rate": baseline_false_positive_rate,
            "fault_window_count": len(fault_rows),
            "detected_fault_window_count": detected_fault_windows,
            "overall_detection_rate": overall_detection_rate,
            "macro_detection_rate": macro_detection_rate,
            "qualified_fault_scenarios": qualified_fault_labels,
            "covered_fault_scenarios": validated_fault_labels,
            "scenario_metrics": scenario_metrics,
        },
        "quality": {
            "gate_passed": gate_passed,
            "sample_count": sample_count,
            "record_count": record_count,
            "training_eligible_window_count": len(eligible_rows),
            "training_record_count": training_record_count,
            "excluded_scenario_window_count": len(rows) - len(eligible_rows),
            "discarded_record_count": discarded_record_count,
            "excluded_outside_range_count": excluded_outside_range_count,
            "minimum_sample_count": 5,
            "minimum_record_count": 20,
            "calibration_p99_score": calibration,
            "basic_gate_passed": basic_gate_passed,
            "scenario_gate_passed": scenario_gate_passed,
            "warnings": warnings,
            "reason": "quality gate passed"
            if gate_passed
            else (
                "at least 5 clean windows and 20 clean log records are required"
                if not basic_gate_passed
                else "scenario validation gate failed"
            ),
        },
    }


def score_features(
    features: Mapping[str, Any],
    model: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the maximum robust deviation and explainable contributors."""
    contributors = []
    feature_thresholds = model.get("feature_thresholds", {})
    model_features = model.get("feature_names", FEATURE_NAMES)
    for feature in model_features:
        value = float(features.get(feature, 0.0))
        center = float(model["centers"][feature])
        scale = float(model["scales"][feature])
        deviation = abs(value - center) / max(scale, 1.0e-12)
        feature_threshold = float(feature_thresholds.get(feature, 1.0))
        normalized_score = deviation / max(feature_threshold, 1.0e-12)
        contributors.append(
            {
                "feature": feature,
                "value": value,
                "baseline": center,
                "deviation": deviation,
                "feature_threshold": feature_threshold,
                "normalized_score": normalized_score,
            }
        )
    contributors.sort(
        key=lambda item: item["normalized_score"],
        reverse=True,
    )
    return {
        "score": (
            contributors[0]["normalized_score"] if contributors else 0.0
        ),
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
    validation = model.get("validation", {})
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
        "model_validation": {
            "strategy": validation.get("strategy"),
            "validation_strength": validation.get(
                "validation_strength",
                "auto_rule_weak_supervision",
            ),
            "label_source_counts": dict(
                validation.get("label_source_counts", {})
            ),
            "operator_confirmed_normal_window_count": validation.get(
                "operator_confirmed_normal_window_count",
                0,
            ),
            "operator_confirmed_fault_scenarios": list(
                validation.get("operator_confirmed_fault_scenarios", [])
            ),
            "baseline_false_positive_rate": validation.get(
                "baseline_false_positive_rate"
            ),
            "overall_detection_rate": validation.get(
                "overall_detection_rate"
            ),
            "macro_detection_rate": validation.get("macro_detection_rate"),
            "fault_window_count": validation.get("fault_window_count"),
            "covered_fault_scenarios": list(
                validation.get("covered_fault_scenarios", [])
            ),
        },
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
        "annotations": root / "annotations",
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
    if arguments.command == "annotate-scenario":
        annotation = create_scenario_annotation(
            arguments.label,
            arguments.since_epoch,
            arguments.until_epoch,
            arguments.note,
            confirmed_by=arguments.confirmed_by,
            robot_id=arguments.robot_id,
            supersedes_annotation_ids=(
                arguments.supersedes_annotation_id
            ),
        )
        target = (
            paths["annotations"]
            / f"{annotation['annotation_id']}.json"
        )
        write_json(target, annotation)
        print(target)
        return 0
    if arguments.command == "build-dataset":
        records = []
        for raw_input in arguments.input:
            records.extend(read_jsonl(Path(raw_input).expanduser()))
        annotations = [
            read_json(Path(path).expanduser())
            for path in arguments.annotation
        ]
        dataset = build_dataset(
            records,
            arguments.window_sec,
            since_timestamp=arguments.since_epoch,
            until_timestamp=arguments.until_epoch,
            include_scenarios=arguments.scenario_labels,
            annotations=annotations,
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
    annotation = subparsers.add_parser("annotate-scenario")
    annotation.add_argument("--label", required=True, choices=SCENARIO_LABEL_ORDER)
    annotation.add_argument("--since-epoch", required=True, type=float)
    annotation.add_argument("--until-epoch", required=True, type=float)
    annotation.add_argument("--note", required=True)
    annotation.add_argument("--confirmed-by", default="operator")
    annotation.add_argument("--robot-id", default="tb1")
    annotation.add_argument(
        "--supersedes-annotation-id",
        action="append",
        default=[],
    )
    dataset = subparsers.add_parser("build-dataset")
    dataset.add_argument("--input", required=True, action="append")
    dataset.add_argument("--window-sec", type=float, default=60.0)
    dataset.add_argument("--since-epoch", type=float)
    dataset.add_argument("--until-epoch", type=float)
    dataset.add_argument("--scenario-labels", action="store_true")
    dataset.add_argument("--annotation", action="append", default=[])
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
