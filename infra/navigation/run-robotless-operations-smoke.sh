#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
smoke_dir="$(mktemp -d)"
mock_pid=""
smoke_port="${ROBOTLESS_OPERATIONS_WEB_PORT:-18081}"
smoke_base_url="http://127.0.0.1:${smoke_port}"

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
export ROBOTLESS_BASE_URL="${smoke_base_url}"

setsid ros2 launch fleet_gateway weekend_mock.launch.py \
  web_port:="${smoke_port}" \
  >"${smoke_dir}/mock.log" 2>&1 &
mock_pid="$!"

for _ in {1..60}; do
  if curl --silent --fail "${smoke_base_url}/api/health" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl --silent --fail "${smoke_base_url}/api/health" >/dev/null

python3 "${repo_root}/infra/navigation/robotless_operations_smoke_client.py"

kill -0 "${mock_pid}"
test -s "${FLEET_OPERATIONS_DB}"
