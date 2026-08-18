#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mlops_root="${FLEET_LOG_MLOPS_ROOT:-${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs}"
lookback_days="${FLEET_LOG_MLOPS_EVALUATION_LOOKBACK_DAYS:-7}"

while (($# > 0)); do
  case "$1" in
    --root)
      mlops_root="$2"
      shift 2
      ;;
    --lookback-days)
      lookback_days="$2"
      shift 2
      ;;
    *)
      echo "ERROR: unsupported argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! [[ "${lookback_days}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: --lookback-days must be a positive integer" >&2
  exit 2
fi
if ! find "${mlops_root}/raw" -maxdepth 1 -type f -name '*.jsonl' \
  -print -quit 2>/dev/null | grep -q .; then
  echo "ROS2_LOG_AUTOMATED_EVALUATION_SKIPPED reason=no_raw_data"
  exit 0
fi

until_epoch="$(date -u +%s)"
since_epoch="$((until_epoch - lookback_days * 86400))"
evaluation_output="$(
  FLEET_LOG_MLOPS_ROOT="${mlops_root}" \
    bash "${repo_root}/scripts/control-pc/train_ros2_log_baseline.sh" \
      --scenario-labels \
      --since-epoch "${since_epoch}" \
      --until-epoch "${until_epoch}"
)"
printf '%s\n' "${evaluation_output}"

candidate_path="$(
  printf '%s\n' "${evaluation_output}" \
    | sed -n 's/^REVIEW_REQUIRED candidate=//p' \
    | tail -n 1
)"
if [[ -z "${candidate_path}" || ! -r "${candidate_path}" ]]; then
  echo "ERROR: automated evaluation did not produce a candidate" >&2
  exit 1
fi

python3 - "${candidate_path}" "${mlops_root}" \
  "${since_epoch}" "${until_epoch}" "${lookback_days}" <<'PY'
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

candidate_path = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
since_epoch = int(sys.argv[3])
until_epoch = int(sys.argv[4])
lookback_days = int(sys.argv[5])
model = json.loads(candidate_path.read_text(encoding="utf-8"))
generated_at = datetime.now(timezone.utc).isoformat()
report = {
    "report_version": "1.0",
    "generated_at": generated_at,
    "evaluation_since_epoch": since_epoch,
    "evaluation_until_epoch": until_epoch,
    "lookback_days": lookback_days,
    "candidate_path": str(candidate_path),
    "model_id": model["model_id"],
    "dataset_hash": model["dataset_hash"],
    "artifact_hash": model["artifact_hash"],
    "quality": model["quality"],
    "validation": model["validation"],
    "promotion": model["promotion"],
    "state": (
        "READY_FOR_MANUAL_REVIEW"
        if model["promotion"]["ready"]
        else "BLOCKED"
    ),
    "automatic_promotion": False,
}
reports = root / "reports"
reports.mkdir(parents=True, exist_ok=True)
stamp = generated_at.replace(":", "").replace("+00:00", "Z")
target = reports / f"candidate-evaluation-{stamp}.json"

def publish(path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)

publish(target)
publish(reports / "latest-candidate.json")
print(
    "ROS2_LOG_AUTOMATED_EVALUATION_OK "
    f"state={report['state']} model={report['model_id']} report={target}"
)
PY
