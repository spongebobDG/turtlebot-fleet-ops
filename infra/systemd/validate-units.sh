#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
units_dir="${repo_root}/infra/systemd/user"

systemd-analyze verify "${units_dir}"/*.service

grep -Fq "Conflicts=tb1-navigation.service" \
  "${units_dir}/tb1-mapping.service"
grep -Fq "Conflicts=tb1-mapping.service" \
  "${units_dir}/tb1-navigation.service"
grep -Fq "ExecStartPre=/usr/bin/test -r %h/.local/share/" \
  "${units_dir}/tb1-navigation.service"
grep -Fq "After=fleet-control-zenoh.service" \
  "${units_dir}/fleet-gateway.service"
grep -Fq "ExecStart=/usr/bin/bash %h/turtlebot-fleet-ops/scripts/tb1/wait_network_ready.sh" \
  "${units_dir}/tb1-network-ready.service"
for unit in \
  tb1-bringup.service \
  tb1-safety-watchdog.service \
  tb1-robot-agent.service \
  tb1-zenoh-bridge.service \
  tb1-mapping.service \
  tb1-navigation.service; do
  grep -Eq '^After=.*tb1-network-ready\.service' "${units_dir}/${unit}"
  grep -Eq '^Wants=.*tb1-network-ready\.service' "${units_dir}/${unit}"
done
if grep -Eq '^After=default\.target$' "${units_dir}"/*.service; then
  echo "ERROR: a default.target wanted unit must not order itself after default.target." >&2
  exit 1
fi

for unit in \
  tb1-safety-watchdog.service \
  tb1-mapping.service \
  tb1-navigation.service \
  tb1-zenoh-bridge.service \
  fleet-control-zenoh.service \
  fleet-gateway.service; do
  grep -Eq '^Restart=(always|on-failure)$' "${units_dir}/${unit}"
  grep -Eq '^RestartSec=[1-9][0-9]*$' "${units_dir}/${unit}"
done

echo "SYSTEMD_UNIT_VALIDATION_OK restart_units=6 network_gate=1"
