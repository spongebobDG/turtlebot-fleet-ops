#!/usr/bin/env bash

set -eo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ros_distro="${ROS_DISTRO:-humble}"
map_file="${TB1_MAP_FILE:-${HOME}/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml}"

if [[ ! -r "${map_file}" ]]; then
  echo "TB1 map is not readable: ${map_file}" >&2
  exit 1
fi

set +u
source "/opt/ros/${ros_distro}/setup.bash"
source "${HOME}/turtlebot3_ws/install/setup.bash"
source "${repo_root}/install/setup.bash"
set -u

export ROS_DISTRO="${ros_distro}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export TURTLEBOT3_MODEL=burger

exec ros2 launch navigation_agent tb1_navigation.launch.py map:="${map_file}"
