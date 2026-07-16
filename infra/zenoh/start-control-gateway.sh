#!/usr/bin/env bash

set -eo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ros_distro="${ROS_DISTRO:-humble}"

# ROS 2 Humble setup files reference optional variables that may be unset.
# Disable nounset only while loading the underlay and overlay environments.
set +u
source "/opt/ros/${ros_distro}/setup.bash"
source "${repo_root}/install/setup.bash"
set -u

export ROS_DISTRO="${ros_distro}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${repo_root}/infra/zenoh/cyclonedds-localhost.xml}"

exec ros2 launch fleet_gateway fleet_gateway.launch.py
