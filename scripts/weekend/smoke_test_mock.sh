#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

web_port="${WEB_PORT:-18000}"
smoke_dir="$(mktemp -d)"
mock_pid=""

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${mock_pid}" ]]; then
    kill -INT -- "-${mock_pid}" 2>/dev/null || true
    sleep 1
    kill -TERM -- "-${mock_pid}" 2>/dev/null || true
    wait "${mock_pid}" 2>/dev/null || true
  fi
  if (( exit_code != 0 )); then
    tail -n 250 "${smoke_dir}/mock.log" >&2 || true
  fi
  rm -rf -- "${smoke_dir}"
  return "${exit_code}"
}
trap cleanup EXIT

export FLEET_OPERATIONS_DB="${smoke_dir}/operations.sqlite3"
setsid env WEB_PORT="${web_port}" \
  bash scripts/weekend/start_mock_stack.sh \
  >"${smoke_dir}/mock.log" 2>&1 &
mock_pid="$!"

base_url="http://127.0.0.1:${web_port}"
for _ in {1..60}; do
  if curl --silent --fail "${base_url}/api/health" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl --silent --fail "${base_url}/api/health" >/dev/null

ROBOTLESS_BASE_URL="${base_url}" \
  python3 infra/navigation/robotless_operations_smoke_client.py

echo "WEEKEND_MOCK_SMOKE_OK tasks=faults=audit final_estop=true"
