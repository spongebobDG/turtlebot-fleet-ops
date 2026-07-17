#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

web_port="${WEB_PORT:-18000}"
log_file="${TMPDIR:-/tmp}/turtlebot-weekend-mock.log"
WEB_PORT="${web_port}" bash scripts/weekend/start_mock_stack.sh \
  >"${log_file}" 2>&1 &
mock_pid=$!

cleanup() {
  kill "${mock_pid}" 2>/dev/null || true
  wait "${mock_pid}" 2>/dev/null || true
}
trap cleanup EXIT

base_url="http://127.0.0.1:${web_port}"
for _ in $(seq 1 30); do
  if curl -fsS "${base_url}/api/health" \
    >/tmp/mock-health.json; then
    if grep -q '"online_robots":1' /tmp/mock-health.json; then
      break
    fi
  fi
  sleep 0.5
done

health="$(curl -fsS "${base_url}/api/health")"
robots="$(curl -fsS "${base_url}/api/robots")"
release="$(
  curl -fsS -X POST \
    -H 'Content-Type: application/json' \
    -d '{"engaged":false}' \
    "${base_url}/api/robots/tb1/estop"
)"
sleep 0.5
goal="$(
  curl -fsS -X POST \
    -H 'Content-Type: application/json' \
    -d '{"x":1.0,"y":0.0,"yaw":0.0,"timeout_sec":10}' \
    "${base_url}/api/robots/tb1/navigation/goals"
)"
sleep 3
result="$(
  curl -fsS "${base_url}/api/robots/tb1/navigation"
)"
estop="$(
  curl -fsS -X POST \
    -H 'Content-Type: application/json' \
    -d '{"engaged":true}' \
    "${base_url}/api/robots/tb1/estop"
)"

python3 - "${health}" "${robots}" "${release}" \
  "${goal}" "${result}" "${estop}" <<'PY'
import json
import sys

health, robots, release, goal, result, estop = map(json.loads, sys.argv[1:])
assert health["status"] == "ok"
assert health["online_robots"] == 1
assert robots["robots"][0]["robot_id"] == "tb1"
assert release["success"] is True
assert goal["success"] is True
assert result["status"] == "SUCCEEDED"
assert estop["success"] is True
print("WEEKEND_MOCK_SMOKE_OK status=SUCCEEDED final_estop=true")
PY
