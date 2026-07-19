#!/usr/bin/env bash
set -euo pipefail

mlops_root="${FLEET_LOG_MLOPS_ROOT:-${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs}"
raw_days=30
apply=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      mlops_root="$2"
      shift 2
      ;;
    --raw-days)
      raw_days="$2"
      shift 2
      ;;
    --apply)
      apply=true
      shift
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if ! [[ "${raw_days}" =~ ^[0-9]+$ ]] || [[ "${raw_days}" -lt 1 ]]; then
  echo "ERROR: --raw-days must be a positive integer" >&2
  exit 2
fi

raw_dir="${mlops_root}/raw"
if [[ ! -d "${raw_dir}" ]]; then
  echo "ROS2_LOG_RAW_PRUNE_OK mode=dry-run candidates=0 raw_dir=${raw_dir}"
  exit 0
fi

mapfile -d '' candidates < <(
  find "${raw_dir}" \
    -maxdepth 1 \
    -type f \
    -name 'live-*.jsonl' \
    -mtime "+${raw_days}" \
    -print0
)

for path in "${candidates[@]}"; do
  resolved="$(realpath -- "${path}")"
  case "${resolved}" in
    "$(realpath -- "${raw_dir}")"/live-*.jsonl)
      ;;
    *)
      echo "ERROR: refusing path outside raw directory: ${resolved}" >&2
      exit 1
      ;;
  esac
  if [[ "${apply}" == "true" ]]; then
    rm -- "${resolved}"
    echo "REMOVED ${resolved}"
  else
    echo "WOULD_REMOVE ${resolved}"
  fi
done

mode="dry-run"
if [[ "${apply}" == "true" ]]; then
  mode="apply"
fi
echo "ROS2_LOG_RAW_PRUNE_OK mode=${mode} candidates=${#candidates[@]} raw_days=${raw_days}"
