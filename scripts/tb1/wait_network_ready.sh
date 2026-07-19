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
  if [[ -n "${default_route}" && -n "${interface}" && -n "${address}" ]]; then
    echo "TB1_NETWORK_READY interface=${interface} address=${address}"
    exit 0
  fi

  now="${SECONDS}"
  if (( now >= reported_at )); then
    echo "Waiting for a default route and global IPv4 address..." >&2
    reported_at=$((now + 10))
  fi
  sleep 1
done
