#!/usr/bin/env bash
set -euo pipefail

repo_root="${HOME}/turtlebot-fleet-ops"

set +u
source /opt/ros/humble/setup.bash
source "${repo_root}/install/setup.bash"
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${repo_root}/infra/zenoh/cyclonedds-localhost.xml}"

exec ros2 run fleet_gateway ros2_log_mlops_node
