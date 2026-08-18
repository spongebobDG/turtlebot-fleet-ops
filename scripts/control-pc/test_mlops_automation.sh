#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u

python3 - "${test_root}" <<'PY'
from pathlib import Path
import sys
import time

from fleet_gateway.log_mlops import (
    LogRecord,
    create_scenario_annotation,
    write_json,
    write_jsonl,
)

root = Path(sys.argv[1])
epoch = (int(time.time()) // 60 - 23) * 60
records = []

def record(timestamp, severity="INFO", message="heartbeat ok"):
    return LogRecord(
        timestamp=float(timestamp),
        severity=severity,
        logger="fleet_gateway",
        message=message,
        unit="fleet-gateway.service",
    )

for minute in range(12):
    records.extend(
        record(epoch + minute * 60 + offset)
        for offset in range(10)
    )
fault_messages = [
    "watchdog input timeout triggered safety stop",
    "received NO reply; cannot reply to client",
    "Collision Ahead",
    "control loop missed its desired rate",
    "ODOM_STALE, BATTERY_STALE",
]
for index, message in enumerate(fault_messages * 2, start=12):
    records.extend(
        record(epoch + index * 60 + offset, "ERROR", message)
        for offset in range(5)
    )
write_jsonl(root / "raw" / "live-fixture.jsonl", records)

annotations = [
    create_scenario_annotation(
        "normal_navigation",
        epoch + minute * 60,
        epoch + (minute + 1) * 60,
        f"confirmed normal window {minute}",
    )
    for minute in range(2)
]
annotations.extend(
    create_scenario_annotation(
        label,
        epoch + minute * 60,
        epoch + (minute + 1) * 60,
        f"confirmed fault {label}",
    )
    for minute, label in (
        (12, "safety_stop"),
        (13, "connectivity_reply"),
        (14, "obstacle_clearance"),
    )
)
for annotation in annotations:
    write_json(
        root / "annotations" / f"{annotation['annotation_id']}.json",
        annotation,
    )
PY

bash "${repo_root}/scripts/control-pc/evaluate_ros2_log_candidate.sh" \
  --root "${test_root}" \
  --lookback-days 1

python3 - "${test_root}" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
report = json.loads(
    (root / "reports" / "latest-candidate.json").read_text(encoding="utf-8")
)
assert report["state"] == "READY_FOR_MANUAL_REVIEW"
assert report["promotion"]["ready"] is True
assert report["automatic_promotion"] is False
assert Path(report["candidate_path"]).is_file()
assert not (root / "registry" / "production.json").exists()
print(
    "MLOPS_AUTOMATION_E2E_OK "
    f"model={report['model_id']} automatic_promotion=false"
)
PY
