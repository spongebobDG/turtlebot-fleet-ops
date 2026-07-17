#!/usr/bin/env bash

set -eo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ros_distro="${ROS_DISTRO:-humble}"
map_dir="${TB1_MAP_DIR:-${HOME}/.local/share/turtlebot-fleet-ops/maps/tb1}"
map_base="${map_dir}/map"

mkdir -p "${map_dir}"

set +u
source "/opt/ros/${ros_distro}/setup.bash"
source "${repo_root}/install/setup.bash"
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 run nav2_map_server map_saver_cli \
  -f "${map_base}" \
  --free 0.196 \
  --occ 0.65
ros2 service call \
  /slam_toolbox/serialize_map \
  slam_toolbox/srv/SerializePoseGraph \
  "{filename: '${map_base}'}"

ros2 run navigation_agent validate_map \
  "${map_base}.yaml" \
  --min-known-cells 100 \
  --min-known-ratio 0.01 \
  --require-pose-graph

echo "Saved TB1 map and pose graph under ${map_dir}"
