#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mlops_root="${FLEET_LOG_MLOPS_ROOT:-${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs}"
window_sec=60
since_epoch=""
until_epoch=""
promote=false
scenario_labels=false

while (($# > 0)); do
  case "$1" in
    --promote)
      promote=true
      shift
      ;;
    --scenario-labels)
      scenario_labels=true
      shift
      ;;
    --window-sec)
      window_sec="$2"
      shift 2
      ;;
    --since-epoch)
      since_epoch="$2"
      shift 2
      ;;
    --until-epoch)
      until_epoch="$2"
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
range_arguments=()
if [[ -n "${since_epoch}" ]]; then
  range_arguments+=(--since-epoch "${since_epoch}")
fi
scenario_arguments=()
if [[ "${scenario_labels}" == "true" ]]; then
  scenario_arguments+=(--scenario-labels)
fi
annotation_arguments=()
if [[ "${scenario_labels}" == "true" ]]; then
  mapfile -t annotation_files < <(
    find "${mlops_root}/annotations" -maxdepth 1 -type f -name '*.json' \
      -print 2>/dev/null | sort
  )
  for annotation_file in "${annotation_files[@]}"; do
    annotation_arguments+=(--annotation "${annotation_file}")
  done
fi
if [[ -n "${until_epoch}" ]]; then
  range_arguments+=(--until-epoch "${until_epoch}")
fi

dataset_path="$(
  ros2 run fleet_gateway ros2_log_mlops --root "${mlops_root}" build-dataset \
    "${input_arguments[@]}" --window-sec "${window_sec}" \
    "${range_arguments[@]}" "${scenario_arguments[@]}" \
    "${annotation_arguments[@]}"
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
    f"excluded={model['quality'].get('excluded_outside_range_count', 0)} "
    f"gate_passed={str(quality['gate_passed']).lower()}"
)
validation = model.get("validation", {})
print(
    "SCENARIO_VALIDATION "
    f"clean_windows={quality.get('training_eligible_window_count', quality['sample_count'])} "
    f"clean_records={quality.get('training_record_count', quality['record_count'])} "
    f"excluded_fault_windows={quality.get('excluded_scenario_window_count', 0)} "
    f"fault_windows={validation.get('fault_window_count', 0)} "
    f"detection_rate={validation.get('overall_detection_rate', 0.0):.3f} "
    f"false_positive_rate={validation.get('baseline_false_positive_rate', 0.0):.3f}"
)
for label, metrics in validation.get("scenario_metrics", {}).items():
    print(
        "SCENARIO_METRIC "
        f"label={label} windows={metrics['window_count']} "
        f"detected={metrics['detected_count']} "
        f"rate={metrics['detection_rate']:.3f} "
        f"median_score={metrics['median_score']:.3f}"
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
