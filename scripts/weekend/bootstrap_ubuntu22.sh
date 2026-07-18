#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  echo "ERROR: Ubuntu 22.04 is required for ROS 2 Humble." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install --no-install-recommends -y \
  ca-certificates \
  curl \
  dbus-user-session \
  git \
  iputils-ping \
  jq \
  libunwind-15-dev \
  locales \
  netcat-openbsd \
  openssh-client \
  shellcheck \
  software-properties-common
sudo add-apt-repository -y universe

if [[ ! -f /opt/ros/humble/setup.bash ]]; then
  ros_apt_version="$(
    curl -fsSL \
      https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
      | sed -n 's/.*"tag_name": "\([^"]*\)".*/\1/p'
  )"
  if [[ -z "${ros_apt_version}" ]]; then
    echo "ERROR: could not determine ros-apt-source release." >&2
    exit 1
  fi
  ros_apt_deb="/tmp/ros2-apt-source.deb"
  curl -fL -o "${ros_apt_deb}" \
    "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ros_apt_version}/ros2-apt-source_${ros_apt_version}.jammy_all.deb"
  sudo dpkg -i "${ros_apt_deb}"
  sudo apt-get update
  sudo apt-get install --no-install-recommends -y \
    ros-humble-desktop \
    ros-humble-rmw-cyclonedds-cpp \
    ros-dev-tools
fi

# The runtime is pinned to CycloneDDS even when ROS was already installed.
sudo apt-get install --no-install-recommends -y \
  ros-humble-rmw-cyclonedds-cpp

set +u
source /opt/ros/humble/setup.bash
set -u
if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init
fi
for attempt in 1 2 3; do
  if rosdep update --rosdistro humble; then
    break
  fi
  if (( attempt == 3 )); then
    echo "ERROR: rosdep update failed after 3 attempts." >&2
    exit 1
  fi
  sleep $((attempt * 5))
done
rosdep install \
  --from-paths "${repo_root}/robot" "${repo_root}/control" \
  --ignore-src \
  --rosdistro humble \
  --skip-keys ament_python \
  -y

setup_line='source /opt/ros/humble/setup.bash'
grep -qxF "${setup_line}" "${HOME}/.bashrc" \
  || printf '\n%s\n' "${setup_line}" >>"${HOME}/.bashrc"

echo "BOOTSTRAP_OK Ubuntu=${VERSION_ID} ROS_DISTRO=${ROS_DISTRO}"
echo "NEXT: bash scripts/weekend/verify_workspace.sh"
