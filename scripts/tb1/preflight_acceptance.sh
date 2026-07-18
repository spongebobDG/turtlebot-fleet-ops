#!/usr/bin/env bash
set -uo pipefail

require_map=false
if [[ "${1:-}" == "--require-map" ]]; then
  require_map=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--require-map]" >&2
  exit 2
fi

repo_root="${TB1_REPO:-${HOME}/turtlebot-fleet-ops}"
map_file="${TB1_MAP_FILE:-${HOME}/.local/share/turtlebot-fleet-ops/maps/tb1/map.yaml}"
failures=0
warnings=0

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; failures=$((failures + 1)); }
warn() { printf 'WARN: %s\n' "$1"; warnings=$((warnings + 1)); }

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
    pass "Ubuntu 22.04"
  else
    fail "Ubuntu 22.04 required"
  fi
else
  fail "missing /etc/os-release"
fi

case "$(uname -m)" in
  aarch64|arm64) pass "aarch64 robot architecture" ;;
  *) fail "TB1 requires aarch64, found $(uname -m)" ;;
esac

for path in \
  /opt/ros/humble/setup.bash \
  "${HOME}/turtlebot3_ws/install/setup.bash" \
  "${repo_root}/.git" \
  "${repo_root}/install/setup.bash" \
  "${HOME}/.local/bin/zenoh-bridge-ros2dds"; do
  if [[ -e "${path}" ]]; then
    pass "${path}"
  else
    fail "missing ${path}"
  fi
done

if [[ -r /opt/ros/humble/setup.bash ]]; then
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
fi

for command_name in \
  ros2 colcon rosdep git curl jq nc systemctl journalctl timeout pidstat; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "command ${command_name}"
  else
    fail "missing command ${command_name}"
  fi
done

for package_name in \
  ros-humble-rmw-cyclonedds-cpp \
  ros-humble-nav2-bringup \
  ros-humble-slam-toolbox \
  ros-humble-turtlebot3-navigation2 \
  sysstat; do
  if dpkg-query -W -f='${Status}' "${package_name}" 2>/dev/null \
    | grep -q 'install ok installed'; then
    pass "package ${package_name}"
  else
    fail "missing package ${package_name}"
  fi
done

if [[ -d "${repo_root}/.git" ]]; then
  commit="$(git -C "${repo_root}" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "${commit}" ]]; then
    pass "repository commit ${commit}"
  else
    fail "repository commit cannot be read"
  fi
  if [[ -z "$(git -C "${repo_root}" status --porcelain 2>/dev/null)" ]]; then
    pass "repository worktree clean"
  else
    fail "repository worktree has local changes; deployment will not overwrite them"
  fi
fi

if [[ -e /dev/serial0 ]]; then
  pass "LDS-02 UART /dev/serial0 exists"
else
  fail "LDS-02 UART /dev/serial0 is missing"
fi
if id -nG | tr ' ' '\n' | grep -qx dialout; then
  pass "user belongs to dialout"
else
  fail "user is not in dialout"
fi

if command -v loginctl >/dev/null 2>&1 \
  && [[ "$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null)" == "yes" ]]; then
  pass "systemd user linger enabled"
else
  fail "systemd user linger is not enabled"
fi

required_units=(
  tb1-bringup.service
  tb1-safety-watchdog.service
  tb1-robot-agent.service
  tb1-zenoh-bridge.service
)
for unit in "${required_units[@]}"; do
  if systemctl --user cat "${unit}" >/dev/null 2>&1; then
    pass "${unit} installed"
  else
    fail "${unit} not installed"
    continue
  fi
  if systemctl --user is-enabled --quiet "${unit}"; then
    pass "${unit} enabled"
  else
    fail "${unit} not enabled"
  fi
  if systemctl --user is-active --quiet "${unit}"; then
    pass "${unit} active"
  else
    fail "${unit} not active"
  fi
done

for unit in tb1-mapping.service tb1-navigation.service; do
  if systemctl --user cat "${unit}" >/dev/null 2>&1; then
    pass "${unit} installed"
  else
    fail "${unit} not installed"
  fi
  if systemctl --user is-active --quiet "${unit}"; then
    fail "${unit} must be inactive at acceptance handoff"
  else
    pass "${unit} inactive"
  fi
done

if [[ -r "${map_file}" ]]; then
  pass "saved map ${map_file}"
elif [[ "${require_map}" == "true" ]]; then
  fail "saved map required at ${map_file}"
else
  warn "saved map is absent; create it during the mapping acceptance step"
fi

available_kib="$(df -Pk "${HOME}" 2>/dev/null | awk 'NR == 2 {print $4}')"
if [[ "${available_kib}" =~ ^[0-9]+$ ]] && (( available_kib >= 2097152 )); then
  pass "at least 2 GiB free in ${HOME}"
else
  fail "less than 2 GiB free in ${HOME}"
fi

if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -qx yes; then
  pass "system clock synchronized"
else
  warn "system clock is not reported synchronized; Zenoh may reject stale timestamps"
fi

if (( failures > 0 )); then
  echo "TB1_ACCEPTANCE_PREFLIGHT_FAILED failures=${failures} warnings=${warnings}" >&2
  exit 1
fi

echo "TB1_ACCEPTANCE_PREFLIGHT_OK warnings=${warnings} require_map=${require_map}"
