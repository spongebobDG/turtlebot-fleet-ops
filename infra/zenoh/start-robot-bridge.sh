#!/usr/bin/env bash

set -euo pipefail

export ROS_DISTRO="${ROS_DISTRO:-humble}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

bridge="${ZENOH_BRIDGE_BIN:-${HOME}/.local/bin/zenoh-bridge-ros2dds}"

if [[ ! -x "${bridge}" ]]; then
  echo "Zenoh bridge is not installed: ${bridge}" >&2
  echo "Run: bash infra/zenoh/install-standalone.sh" >&2
  exit 1
fi

exec "${bridge}"
