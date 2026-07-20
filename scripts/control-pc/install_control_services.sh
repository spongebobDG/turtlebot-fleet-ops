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
if [[ ! -r "${repo_root}/install/setup.bash" ]]; then
  echo "ERROR: verified ROS workspace build is missing." >&2
  echo "Run: bash scripts/weekend/verify_workspace.sh" >&2
  exit 1
fi
if [[ ! -x "${HOME}/.local/bin/zenoh-bridge-ros2dds" ]]; then
  echo "ERROR: the Zenoh ROS 2 bridge is not installed." >&2
  exit 1
fi

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

echo "CONTROL_PC_SERVICES_INSTALLED robot=${robot_address}"
