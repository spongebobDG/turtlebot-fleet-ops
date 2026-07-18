#!/usr/bin/env bash
set -euo pipefail

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--dry-run]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
expected_repo="${HOME}/turtlebot-fleet-ops"

if [[ "${dry_run}" == "true" ]]; then
  cat <<'EOF'
TB1_ACCEPTANCE_DEPLOY_DRY_RUN
1. Refuse a non-Ubuntu-22.04 host or dirty repository.
2. Engage the local software e-stop when available.
3. Stop navigation/mapping, then all TB1 runtime services.
4. Install pinned ROS/Nav2/SLAM, sysstat, and Zenoh dependencies.
5. Build and test robot packages in isolated ROS domain 142.
6. Install all six TB1 user units.
7. Start bringup/watchdog/agent/Zenoh only; leave mapping/Nav2 inactive.
8. Run the connected acceptance preflight.
EOF
  exit 0
fi

if [[ "${repo_root}" != "${expected_repo}" ]]; then
  echo "ERROR: deploy from ${expected_repo}; found ${repo_root}." >&2
  exit 1
fi
if [[ -n "$(git -C "${repo_root}" status --porcelain)" ]]; then
  echo "ERROR: refusing to deploy a dirty TB1 repository." >&2
  git -C "${repo_root}" status --short >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  echo "ERROR: Ubuntu 22.04 is required." >&2
  exit 1
fi
if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  echo "ERROR: TB1 deployment requires aarch64." >&2
  exit 1
fi
if [[ ! -r /opt/ros/humble/setup.bash ]]; then
  echo "ERROR: ROS 2 Humble is missing." >&2
  exit 1
fi

set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
if [[ -r "${HOME}/turtlebot3_ws/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/turtlebot3_ws/install/setup.bash"
fi
if [[ -r "${repo_root}/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "${repo_root}/install/setup.bash"
fi
set -u
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

if systemctl --user is-active --quiet tb1-safety-watchdog.service; then
  timeout 8 ros2 service call \
    /safety_watchdog/set_estop \
    std_srvs/srv/SetBool \
    '{data: true}' >/dev/null 2>&1 || true
  sleep 1
fi

systemctl --user stop tb1-navigation.service tb1-mapping.service \
  2>/dev/null || true
systemctl --user stop \
  tb1-zenoh-bridge.service \
  tb1-robot-agent.service \
  tb1-safety-watchdog.service \
  tb1-bringup.service \
  2>/dev/null || true

deployment_failed() {
  echo "ERROR: deployment failed; TB1 motion services remain stopped for safety." >&2
  echo "Retry this script after correcting the reported error." >&2
}
trap deployment_failed ERR

sudo apt-get update
sudo apt-get install -y \
  dbus-user-session \
  curl \
  jq \
  netcat-openbsd \
  python3-colcon-common-extensions \
  python3-rosdep \
  ros-humble-nav2-bringup \
  ros-humble-rmw-cyclonedds-cpp \
  ros-humble-slam-toolbox \
  ros-humble-turtlebot3-navigation2 \
  sysstat

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init
fi
for attempt in 1 2 3; do
  if rosdep update --rosdistro humble; then
    break
  fi
  if [[ "${attempt}" == "3" ]]; then
    echo "ERROR: rosdep update failed after 3 attempts." >&2
    exit 1
  fi
  sleep $((attempt * 5))
done
rosdep install \
  --from-paths robot \
  --ignore-src \
  --rosdistro humble \
  --skip-keys ament_python \
  -r -y

bash infra/zenoh/install-standalone.sh

export ROS_DOMAIN_ID=142
colcon build \
  --base-paths robot \
  --packages-up-to \
    safety_watchdog_guard \
    safety_watchdog \
    robot_agent \
    navigation_agent \
  --symlink-install \
  --event-handlers console_direct+
set +u
# shellcheck disable=SC1091
source "${repo_root}/install/setup.bash"
set -u
colcon test \
  --packages-select \
    fleet_interfaces \
    safety_watchdog_guard \
    safety_watchdog \
    robot_agent \
    navigation_agent \
  --event-handlers console_direct+
colcon test-result --verbose
export ROS_DOMAIN_ID=42

mkdir -p "${HOME}/.config/systemd/user"
install -m 0644 infra/systemd/user/tb1-*.service \
  "${HOME}/.config/systemd/user/"
sudo loginctl enable-linger "${USER}"
systemctl --user daemon-reload
systemctl --user disable --now tb1-navigation.service tb1-mapping.service \
  2>/dev/null || true
systemctl --user enable --now \
  tb1-network-ready.service \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service

for attempt in $(seq 1 60); do
  if systemctl --user is-active --quiet \
    tb1-network-ready.service \
    tb1-bringup.service \
    tb1-safety-watchdog.service \
    tb1-robot-agent.service \
    tb1-zenoh-bridge.service; then
    break
  fi
  if [[ "${attempt}" == "60" ]]; then
    systemctl --user --no-pager --full status \
      tb1-network-ready.service \
      tb1-bringup.service \
      tb1-safety-watchdog.service \
      tb1-robot-agent.service \
      tb1-zenoh-bridge.service >&2 || true
    exit 1
  fi
  sleep 1
done

trap - ERR
bash scripts/tb1/preflight_acceptance.sh
echo "TB1_ACCEPTANCE_DEPLOY_OK commit=$(git rev-parse HEAD) profile=IDLE"
