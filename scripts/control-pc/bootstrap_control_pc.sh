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

mkdir -p \
  "${HOME}/.config/systemd/user" \
  "${HOME}/.config/turtlebot-fleet-ops"
install -m 0644 \
  infra/systemd/user/fleet-control-zenoh.service \
  infra/systemd/user/fleet-gateway.service \
  infra/systemd/user/fleet-log-mlops.service \
  "${HOME}/.config/systemd/user/"

cat >"${HOME}/.config/turtlebot-fleet-ops/control.env" <<EOF
ROBOT_ADDRESS=${robot_address}
ROS_DISTRO=humble
ROS_DOMAIN_ID=42
FLEET_LOG_MLOPS_ROOT=${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs
FLEET_LOG_MLOPS_STATUS=${HOME}/.local/share/turtlebot-fleet-ops/mlops/ros2-logs/status/latest.json
EOF
chmod 0600 "${HOME}/.config/turtlebot-fleet-ops/control.env"

# These are intentionally literal shell startup lines written to .bashrc.
# shellcheck disable=SC2016
for line in \
  'source /opt/ros/humble/setup.bash' \
  'source "$HOME/turtlebot-fleet-ops/install/setup.bash"' \
  'export ROS_DOMAIN_ID=42' \
  'export ROS_LOCALHOST_ONLY=0' \
  'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp'; do
  grep -qxF "${line}" "${HOME}/.bashrc" || printf '%s\n' "${line}" >>"${HOME}/.bashrc"
done

sudo loginctl enable-linger "${USER}"
systemctl --user daemon-reload
systemctl --user enable --now \
  fleet-control-zenoh.service \
  fleet-gateway.service \
  fleet-log-mlops.service

echo "CONTROL_PC_LINUX_BOOTSTRAP_OK robot=${robot_address}"
