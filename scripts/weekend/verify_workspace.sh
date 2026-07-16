#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

if [[ ! -f /opt/ros/humble/setup.bash ]]; then
  echo "ERROR: ROS 2 Humble is missing." >&2
  echo "Run: bash scripts/weekend/bootstrap_ubuntu22.sh" >&2
  exit 1
fi

set +u
source /opt/ros/humble/setup.bash
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-142}"

bad_files="$(
  grep -Il $'\r' \
    infra/zenoh/*.sh \
    infra/systemd/user/*.service \
    scripts/weekend/*.sh \
    || true
)"
if [[ -n "${bad_files}" ]]; then
  printf 'ERROR: CRLF in Linux runtime files:\n%s\n' \
    "${bad_files}" >&2
  exit 1
fi

colcon build \
  --base-paths robot control \
  --symlink-install \
  --event-handlers console_direct+
set +u
source install/setup.bash
set -u
colcon test \
  --packages-select \
    fleet_interfaces \
    safety_watchdog \
    robot_agent \
    fleet_navigation \
    fleet_gateway \
  --event-handlers console_direct+
colcon test-result --verbose

if command -v node >/dev/null 2>&1; then
  node --check control/fleet_gateway/web/app.js
else
  echo "INFO: Node.js missing; optional app.js syntax check skipped."
fi

echo "WEEKEND_WORKSPACE_VERIFY_OK ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
