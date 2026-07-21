#!/usr/bin/env bash

set -euo pipefail

reported_at=0
while true; do
  default_route="$(ip -4 route show default 2>/dev/null | head -n 1 || true)"
  interface="$(awk '{for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}' <<<"${default_route}")"
  address=""
  if [[ -n "${interface}" ]]; then
    address="$(
      ip -4 -o address show dev "${interface}" scope global 2>/dev/null \
        | awk 'NR == 1 {print $4}'
    )"
  fi
  ntp_synchronized="$(
    timedatectl show --property=NTPSynchronized --value 2>/dev/null \
      || true
  )"
  if [[
    -n "${default_route}" &&
    -n "${interface}" &&
    -n "${address}" &&
    "${ntp_synchronized}" == "yes"
  ]]; then
    echo "TB1_NETWORK_TIME_READY interface=${interface} address=${address} ntp=yes"
    exit 0
  fi

  now="${SECONDS}"
  if (( now >= reported_at )); then
    echo "Waiting for IPv4 and NTP synchronization (ntp=${ntp_synchronized:-unknown})..." >&2
    reported_at=$((now + 10))
  fi
  sleep 1
done
