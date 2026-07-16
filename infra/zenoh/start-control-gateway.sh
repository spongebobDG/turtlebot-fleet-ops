#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ros_distro="${ROS_DISTRO:-humble}"

source "/opt/ros/${ros_distro}/setup.bash"
source "${repo_root}/install/setup.bash"

export ROS_DISTRO="${ros_distro}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${repo_root}/infra/zenoh/cyclonedds-localhost.xml}"

exec ros2 launch fleet_gateway fleet_gateway.launch.py
