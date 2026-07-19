#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mlops_root="${FLEET_LOG_MLOPS_ROOT:-${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs}"
window_sec=60
promote=false

while (($# > 0)); do
  case "$1" in
    --promote)
      promote=true
      shift
      ;;
    --window-sec)
      window_sec="$2"
      shift 2
      ;;
    *)
      echo "ERROR: unsupported argument: $1" >&2
      exit 2
      ;;
  esac
done

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u

mapfile -t raw_files < <(
  find "${mlops_root}/raw" -maxdepth 1 -type f -name '*.jsonl' -print \
    | sort
)
if ((${#raw_files[@]} == 0)); then
  echo "ERROR: no collected /rosout JSONL files in ${mlops_root}/raw" >&2
  exit 1
fi

input_arguments=()
for raw_file in "${raw_files[@]}"; do
  input_arguments+=(--input "${raw_file}")
done

dataset_path="$(
  ros2 run fleet_gateway ros2_log_mlops --root "${mlops_root}" build-dataset \
    "${input_arguments[@]}" --window-sec "${window_sec}"
)"
candidate_path="$(
  ros2 run fleet_gateway ros2_log_mlops --root "${mlops_root}" train \
    --input "${dataset_path}"
)"

python3 - "${candidate_path}" <<'PY'
import json
from pathlib import Path
import sys

model = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
quality = model["quality"]
print(
    "ROS2_LOG_MODEL_CANDIDATE "
    f"model={model['model_id']} "
    f"windows={quality['sample_count']} "
    f"records={quality['record_count']} "
    f"gate_passed={str(quality['gate_passed']).lower()}"
)
print(f"QUALITY_REASON={quality['reason']}")
for warning in quality.get("warnings", []):
    print(f"QUALITY_WARNING={warning}")
PY

if [[ "${promote}" == "true" ]]; then
  ros2 run fleet_gateway ros2_log_mlops --root "${mlops_root}" promote \
    --input "${candidate_path}"
  systemctl --user restart fleet-log-mlops.service
  echo "ROS2_LOG_MODEL_PROMOTED candidate=${candidate_path}"
else
  echo "REVIEW_REQUIRED candidate=${candidate_path}"
  echo "NEXT: bash scripts/control-pc/train_ros2_log_baseline.sh --promote"
fi
