#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

set +u
source /opt/ros/humble/setup.bash
set -u
if [[ ! -f install/setup.bash ]]; then
  echo "ERROR: workspace is not built." >&2
  echo "Run: bash scripts/weekend/verify_workspace.sh" >&2
  exit 1
fi
set +u
source install/setup.bash
set -u

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-142}"
web_port="${WEB_PORT:-8000}"
unset CYCLONEDDS_URI

echo "MOCK_ONLY: no physical robot commands are produced."
echo "Dashboard: http://localhost:${web_port}"
echo "Stop: Ctrl+C"
exec ros2 launch fleet_gateway weekend_mock.launch.py \
  web_port:="${web_port}"
