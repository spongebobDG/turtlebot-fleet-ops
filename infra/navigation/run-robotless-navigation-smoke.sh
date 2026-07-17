#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
smoke_dir="$(mktemp -d)"
telemetry_file="${smoke_dir}/telemetry.json"
declare -a smoke_pids=()

cleanup() {
  local exit_code=$?
  set +e
  for pid in "${smoke_pids[@]}"; do
    kill -INT "${pid}" 2>/dev/null || true
  done
  sleep 2
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

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-142}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export TURTLEBOT3_MODEL=burger
export ROBOTLESS_TELEMETRY_FILE="${telemetry_file}"

map_image="${smoke_dir}/map.pgm"
map_yaml="${smoke_dir}/map.yaml"
{
  echo "P2"
  echo "80 80"
  echo "255"
  for ((pixel = 0; pixel < 6400; pixel++)); do
    printf "254 "
  done
  printf "\n"
} >"${map_image}"
cat >"${map_yaml}" <<EOF
image: ${map_image}
mode: trinary
resolution: 0.05
origin: [-2.0, -2.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
EOF

python3 "${repo_root}/infra/navigation/robotless_fixture.py" \
  >"${smoke_dir}/fixture.log" 2>&1 &
smoke_pids+=("$!")
ros2 launch safety_watchdog safety_watchdog.launch.py \
  >"${smoke_dir}/watchdog.log" 2>&1 &
smoke_pids+=("$!")
ros2 launch navigation_agent tb1_navigation.launch.py map:="${map_yaml}" \
  >"${smoke_dir}/navigation.log" 2>&1 &
smoke_pids+=("$!")
ros2 launch fleet_gateway fleet_gateway.launch.py \
  >"${smoke_dir}/gateway.log" 2>&1 &
smoke_pids+=("$!")

for _ in {1..120}; do
  if curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null; then
    break
  fi
  sleep 0.5
done
curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null

python3 "${repo_root}/infra/navigation/robotless_smoke_client.py"

for pid in "${smoke_pids[@]}"; do
  kill -0 "${pid}"
done

node_list="$(ros2 node list)"
echo "${node_list}"
grep -Fxq "/safety_watchdog" <<<"${node_list}"
grep -Fxq "/motion_arbiter" <<<"${node_list}"
grep -Fxq "/navigation_agent" <<<"${node_list}"
grep -Fxq "/fleet_gateway" <<<"${node_list}"

action_list="$(ros2 action list -t)"
echo "${action_list}"
grep -Fq "/navigate_to_pose [nav2_msgs/action/NavigateToPose]" \
  <<<"${action_list}"
grep -Fq "/tb1/navigation/navigate [fleet_interfaces/action/NavigateRobot]" \
  <<<"${action_list}"

cmd_info="$(ros2 topic info /cmd_vel --verbose)"
echo "${cmd_info}"
grep -Fq "Publisher count: 1" <<<"${cmd_info}"
grep -Fq "Node name: safety_watchdog" <<<"${cmd_info}"

navigation_cmd_info="$(
  ros2 topic info /motion/navigation/cmd_vel --verbose
)"
echo "${navigation_cmd_info}"
grep -Fq "Node name: velocity_smoother" <<<"${navigation_cmd_info}"

python3 - "${telemetry_file}" <<'PY'
import json
from pathlib import Path
import sys

telemetry = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert telemetry["nonzero_commands"] > 0, telemetry
assert telemetry["max_abs_linear"] <= 0.050001, telemetry
assert telemetry["max_abs_angular"] <= 0.300001, telemetry
assert abs(telemetry["current_linear"]) <= 0.000001, telemetry
assert abs(telemetry["current_angular"]) <= 0.000001, telemetry
print("PASS: watchdog velocity limits and final zero command", telemetry)
PY

echo "Robotless TB1 navigation smoke test passed"
