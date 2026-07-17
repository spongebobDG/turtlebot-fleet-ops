#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
smoke_dir="$(mktemp -d)"
mock_pid=""

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${mock_pid}" ]]; then
    kill -INT -- "-${mock_pid}" 2>/dev/null || true
    sleep 1
    kill -TERM -- "-${mock_pid}" 2>/dev/null || true
    wait "${mock_pid}" 2>/dev/null || true
  fi
  if (( exit_code != 0 )); then
    tail -n 250 "${smoke_dir}/mock.log" >&2 || true
  fi
  rm -rf -- "${smoke_dir}"
  return "${exit_code}"
}
trap cleanup EXIT

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-142}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export FLEET_OPERATIONS_DB="${smoke_dir}/operations.sqlite3"

setsid ros2 launch fleet_gateway weekend_mock.launch.py \
  >"${smoke_dir}/mock.log" 2>&1 &
mock_pid="$!"

for _ in {1..60}; do
  if curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null; then
    break
  fi
  sleep 0.25
done
curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null

python3 "${repo_root}/infra/navigation/robotless_operations_smoke_client.py"

kill -0 "${mock_pid}"
test -s "${FLEET_OPERATIONS_DB}"
