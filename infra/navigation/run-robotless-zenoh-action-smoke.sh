#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
smoke_dir="$(mktemp -d)"
bridge="${ZENOH_BRIDGE_BIN:-${HOME}/.local/bin/zenoh-bridge-ros2dds}"
robot_domain="${ZENOH_ROBOT_DOMAIN_ID:-160}"
control_domain="${ZENOH_CONTROL_DOMAIN_ID:-161}"
robot_endpoint="tcp/127.0.0.1:17447"
control_endpoint="tcp/127.0.0.1:17448"
declare -a smoke_pids=()

cleanup() {
  local exit_code=$?
  set +e
  for pid in "${smoke_pids[@]}"; do
    kill -INT "${pid}" 2>/dev/null || true
  done
  sleep 1
  for pid in "${smoke_pids[@]}"; do
    kill -TERM "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  if (( exit_code != 0 )); then
    for log_file in "${smoke_dir}"/*.log; do
      [[ -e "${log_file}" ]] || continue
      echo "===== ${log_file} =====" >&2
      tail -n 200 "${log_file}" >&2
    done
  fi
  rm -rf -- "${smoke_dir}"
  return "${exit_code}"
}
trap cleanup EXIT

if [[ ! -x "${bridge}" ]]; then
  echo "Zenoh bridge is not installed: ${bridge}" >&2
  exit 1
fi
if [[ "${robot_domain}" == "${control_domain}" ]]; then
  echo "Zenoh smoke requires different robot and control domains" >&2
  exit 1
fi

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u

common_env=(
  ROS_DISTRO=humble
  ROS_LOCALHOST_ONLY=1
  RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
)

env "${common_env[@]}" ROS_DOMAIN_ID="${robot_domain}" \
  "${bridge}" \
  -c "${repo_root}/infra/zenoh/robot-bridge.json5" \
  -l "${robot_endpoint}" \
  >"${smoke_dir}/robot-bridge.log" 2>&1 &
smoke_pids+=("$!")

env "${common_env[@]}" ROS_DOMAIN_ID="${control_domain}" \
  "${bridge}" \
  -c "${repo_root}/infra/zenoh/control-bridge.json5" \
  -l "${control_endpoint}" \
  -e "${robot_endpoint}" \
  >"${smoke_dir}/control-bridge.log" 2>&1 &
smoke_pids+=("$!")

env "${common_env[@]}" ROS_DOMAIN_ID="${robot_domain}" \
  python3 \
  "${repo_root}/infra/navigation/robotless_zenoh_action_fixture.py" \
  server >"${smoke_dir}/server.log" 2>&1 &
smoke_pids+=("$!")

sleep 1
for pid in "${smoke_pids[@]}"; do
  kill -0 "${pid}"
done

env "${common_env[@]}" ROS_DOMAIN_ID="${control_domain}" \
  timeout 60s python3 \
  "${repo_root}/infra/navigation/robotless_zenoh_action_fixture.py" \
  client

for pid in "${smoke_pids[@]}"; do
  kill -0 "${pid}"
done

echo "Robotless Zenoh navigation action smoke test passed"
