#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
expected_repo="${HOME}/turtlebot-fleet-ops"
robot_address="${ROBOT_ADDRESS:-tb1}"

if [[ "${repo_root}" != "${expected_repo}" ]]; then
  echo "ERROR: control services require the repository at ${expected_repo}." >&2
  echo "Current repository: ${repo_root}" >&2
  exit 1
fi

cd "${repo_root}"

# A previous bootstrap may already have enabled the production stack. Stop it
# before isolated robotless smoke tests so port 8000 and ROS domain 142 belong
# only to the test fixture. The services are installed and started again below.
systemctl --user stop \
  fleet-log-mlops.service \
  fleet-gateway.service \
  fleet-control-zenoh.service \
  2>/dev/null || true

bash scripts/weekend/bootstrap_ubuntu22.sh
bash infra/zenoh/install-standalone.sh
bash scripts/weekend/verify_workspace.sh
ROBOT_ADDRESS="${robot_address}" bash scripts/control-pc/install_control_services.sh

echo "CONTROL_PC_LINUX_BOOTSTRAP_OK robot=${robot_address}"
