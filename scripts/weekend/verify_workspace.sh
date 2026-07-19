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
    scripts/control-pc/*.sh \
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
  --executor sequential \
  --event-handlers console_direct+
set +u
source install/setup.bash
set -u
colcon test \
  --packages-select \
    fleet_interfaces \
    safety_watchdog_guard \
    safety_watchdog \
    robot_agent \
    navigation_agent \
    fleet_gateway \
  --event-handlers console_direct+
colcon test-result --verbose

shellcheck --exclude=SC1090,SC1091 \
  infra/navigation/*.sh infra/systemd/*.sh infra/zenoh/*.sh \
  scripts/control-pc/*.sh scripts/tb1/*.sh scripts/weekend/*.sh
bash scripts/tb1/deploy_acceptance.sh --dry-run >/dev/null
bash infra/systemd/validate-units.sh
python3 -m py_compile \
  infra/navigation/robotless_operations_smoke_client.py \
  infra/navigation/robotless_smoke_client.py \
  infra/navigation/robotless_web_preview.py
bash infra/navigation/run-robotless-operations-smoke.sh
bash infra/navigation/run-robotless-navigation-smoke.sh
bash infra/navigation/run-robotless-zenoh-action-smoke.sh

if command -v node >/dev/null 2>&1 \
  && node -e 'const value = null; process.exit((value ?? true) ? 0 : 1)' \
    >/dev/null 2>&1; then
  node --check control/fleet_gateway/web/app.js
elif command -v node >/dev/null 2>&1; then
  echo "INFO: installed Node.js is too old for app.js; use the Windows Node.js check."
else
  echo "INFO: Node.js missing; optional app.js syntax check skipped."
fi

echo "WEEKEND_WORKSPACE_VERIFY_OK ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
