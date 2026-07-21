#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
robot_address="${ROBOT_ADDRESS:-tb1}"
failures=0

pass() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; failures=$((failures + 1)); }
warn() { printf 'WARN: %s\n' "$1"; }

source /etc/os-release
if [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "22.04" ]]; then
  pass "Ubuntu 22.04"
else
  fail "Ubuntu 22.04 required"
fi

if grep -Eq '^systemd=true$' /etc/wsl.conf; then
  pass "WSL systemd enabled"
else
  fail "WSL systemd is not enabled"
fi

for path in \
  /opt/ros/humble/setup.bash \
  "${repo_root}/install/setup.bash" \
  "${HOME}/.local/bin/zenoh-bridge-ros2dds" \
  "${HOME}/.config/turtlebot-fleet-ops/control.env"; do
  if [[ -e "${path}" ]]; then
    pass "${path}"
  else
    fail "missing ${path}"
  fi
done

if [[ -f /opt/ros/humble/setup.bash \
  && -f "${repo_root}/install/setup.bash" ]]; then
  set +u
  source /opt/ros/humble/setup.bash
  source "${repo_root}/install/setup.bash"
  set -u
fi

for command_name in ros2 colcon rosdep rviz2 shellcheck ssh curl nc jq; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    pass "command ${command_name}"
  else
    fail "missing command ${command_name}"
  fi
done

if command -v node >/dev/null 2>&1 \
  && node -e 'const value = null; process.exit((value ?? true) ? 0 : 1)' \
    >/dev/null 2>&1; then
  pass "WSL Node.js supports fleet web syntax"
else
  warn "WSL Node.js is optional; Windows Node.js performs the fleet web syntax check"
fi

if dpkg-query -W -f='${Status}' ros-humble-rmw-cyclonedds-cpp 2>/dev/null \
  | grep -q 'install ok installed'; then
  pass "CycloneDDS RMW installed"
else
  fail "CycloneDDS RMW missing"
fi

if grep -Fxq "ROBOT_ADDRESS=${robot_address}" \
  "${HOME}/.config/turtlebot-fleet-ops/control.env"; then
  pass "robot address ${robot_address}"
else
  fail "robot address mismatch"
fi
if grep -Fxq "ROS_DOMAIN_ID=42" \
  "${HOME}/.config/turtlebot-fleet-ops/control.env"; then
  pass "production ROS domain 42"
else
  fail "production ROS domain mismatch"
fi

ai_enabled="$(sed -n 's/^FLEET_LOG_AI_ENABLED=//p' \
  "${HOME}/.config/turtlebot-fleet-ops/control.env" | tail -n 1)"
ai_model="$(sed -n 's/^FLEET_LOG_AI_MODEL=//p' \
  "${HOME}/.config/turtlebot-fleet-ops/control.env" | tail -n 1)"
if [[ "${ai_enabled}" == "1" ]]; then
  ai_model="${ai_model:-qwen3:8b}"
  if command -v ollama >/dev/null 2>&1; then
    pass "command ollama"
  else
    warn "local log AI enabled but ollama is not installed"
  fi
  if systemctl is-active --quiet ollama.service 2>/dev/null; then
    pass "ollama.service active"
  else
    warn "local log AI enabled but ollama.service is not active"
  fi
  if curl --silent --fail --max-time 3 \
    http://127.0.0.1:11434/api/tags \
    | jq -e --arg model "${ai_model}" \
      '.models[]? | select((.name // .model) == $model)' >/dev/null; then
    pass "local log AI model ${ai_model}"
  else
    warn "local log AI model ${ai_model} is unavailable"
  fi
else
  warn "local log AI disabled; run setup_local_log_ai.sh to enable it"
fi

for unit in \
  fleet-control-zenoh.service \
  fleet-gateway.service \
  fleet-log-mlops.service; do
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

gateway_ready=false
for _attempt in $(seq 1 30); do
  if curl --silent --fail --max-time 2 \
    http://127.0.0.1:8000/api/health >/dev/null; then
    gateway_ready=true
    break
  fi
  sleep 1
done
if [[ "${gateway_ready}" == "true" ]]; then
  pass "Gateway health endpoint"
else
  fail "Gateway health endpoint unavailable"
fi

if nc -z -w 2 "${robot_address}" 22; then
  pass "TB1 SSH port reachable"
else
  warn "TB1 SSH port offline; expected while the robot is disconnected"
fi

if nc -z -w 2 "${robot_address}" 7447; then
  pass "TB1 Zenoh port reachable"
else
  warn "TB1 Zenoh port offline; expected while the robot is disconnected"
fi

if (( failures > 0 )); then
  echo "CONTROL_PC_PREFLIGHT_FAILED failures=${failures}" >&2
  exit 1
fi

echo "CONTROL_PC_PREFLIGHT_OK robot=${robot_address}"
