#!/usr/bin/env bash

# Linux entrypoint; repository attributes enforce LF endings.
set -euo pipefail

export ROS_DISTRO="${ROS_DISTRO:-humble}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bridge="${ZENOH_BRIDGE_BIN:-${HOME}/.local/bin/zenoh-bridge-ros2dds}"
config="${ZENOH_CONFIG:-${repo_root}/infra/zenoh/robot-bridge.json5}"

if [[ ! -x "${bridge}" ]]; then
  echo "Zenoh bridge is not installed: ${bridge}" >&2
  echo "Run: bash infra/zenoh/install-standalone.sh" >&2
  exit 1
fi

exec "${bridge}" -c "${config}"
