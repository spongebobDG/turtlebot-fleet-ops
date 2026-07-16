#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${ROBOT_ADDRESS:?Set ROBOT_ADDRESS to the robot hostname or LAN address}"

export ROS_DISTRO="${ROS_DISTRO:-humble}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-file://${repo_root}/infra/zenoh/cyclonedds-localhost.xml}"

bridge="${ZENOH_BRIDGE_BIN:-${HOME}/.local/bin/zenoh-bridge-ros2dds}"

if [[ ! -x "${bridge}" ]]; then
  echo "Zenoh bridge is not installed: ${bridge}" >&2
  echo "Run: bash infra/zenoh/install-standalone.sh" >&2
  exit 1
fi

exec "${bridge}" -e "tcp/${ROBOT_ADDRESS}:7447"
