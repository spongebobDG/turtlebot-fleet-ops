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

echo "SYSTEMD_UNIT_VALIDATION_OK units=6"
