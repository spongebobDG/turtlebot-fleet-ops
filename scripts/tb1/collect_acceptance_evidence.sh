#!/usr/bin/env bash
set -uo pipefail

repo_root="${TB1_REPO:-${HOME}/turtlebot-fleet-ops}"
map_dir="${TB1_MAP_DIR:-${HOME}/.local/share/turtlebot-fleet-ops/maps/tb1}"

section() { printf '\n===== %s =====\n' "$1"; }
run() {
  printf '$'
  printf ' %q' "$@"
  printf '\n'
  "$@" 2>&1 || true
}

section "capture metadata"
printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"
printf 'hostname=%s\n' "$(hostname)"
printf 'user=%s\n' "${USER}"
printf 'capture_safety=read-only; no motion command is published\n'

section "operating system and resources"
run uname -a
run sed -n '1,12p' /etc/os-release
run uptime
run free -h
run df -h "${HOME}"
run timedatectl status
run id
run ls -l /dev/serial0
if command -v pidstat >/dev/null 2>&1; then
  run pidstat -r -u 1 3
fi

section "repository"
run git -C "${repo_root}" status --short --branch
run git -C "${repo_root}" log -1 --format=fuller
run git -C "${repo_root}" remote -v

section "systemd units"
for unit in \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service \
  tb1-mapping.service \
  tb1-navigation.service; do
  run systemctl --user show "${unit}" \
    --property=LoadState,UnitFileState,ActiveState,SubState,MainPID,NRestarts
done

section "recent journals"
for unit in \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service \
  tb1-mapping.service \
  tb1-navigation.service; do
  run journalctl --user -u "${unit}" --since '-20 min' -n 200 --no-pager
done

if [[ -r /opt/ros/humble/setup.bash ]]; then
  set +u
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
  if [[ -r "${HOME}/turtlebot3_ws/install/setup.bash" ]]; then
    # shellcheck disable=SC1091
    source "${HOME}/turtlebot3_ws/install/setup.bash"
  fi
  if [[ -r "${repo_root}/install/setup.bash" ]]; then
    # shellcheck disable=SC1091
    source "${repo_root}/install/setup.bash"
  fi
  set -u
  export ROS_DOMAIN_ID=42
  export ROS_LOCALHOST_ONLY=0
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

  section "ROS graph"
  run timeout 10 ros2 node list
  run timeout 10 ros2 topic list -t
  run timeout 10 ros2 topic info /cmd_vel --verbose
  run timeout 10 ros2 topic info /safety/cmd_vel_in --verbose
  run timeout 10 ros2 topic info /motion/navigation/cmd_vel --verbose
  run timeout 10 ros2 topic echo /fleet/safety_status --once
  run timeout 10 ros2 topic echo /fleet/navigation_status --once
  run timeout 10 ros2 topic echo /fleet/robot_status --once
else
  section "ROS graph"
  echo "ROS 2 Humble is missing; graph capture skipped."
fi

section "map artifacts"
run find "${map_dir}" -maxdepth 1 -type f -printf '%f %s bytes\n'
if [[ -d "${map_dir}" ]]; then
  while IFS= read -r -d '' map_path; do
    run sha256sum "${map_path}"
  done < <(find "${map_dir}" -maxdepth 1 -type f -print0 | sort -z)
fi

echo
echo "TB1_ACCEPTANCE_EVIDENCE_CAPTURE_OK"
