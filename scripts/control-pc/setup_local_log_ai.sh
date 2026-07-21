#!/usr/bin/env bash
set -euo pipefail

model="${FLEET_LOG_AI_MODEL:-qwen3:8b}"
base_url="${FLEET_LOG_AI_BASE_URL:-http://127.0.0.1:11434}"
timeout_sec="${FLEET_LOG_AI_TIMEOUT_SEC:-90}"
retention_days="${FLEET_LOG_AI_RETENTION_DAYS:-30}"
control_dir="${HOME}/.config/turtlebot-fleet-ops"
control_env="${control_dir}/control.env"
restart_gateway=false

if [[ "${1:-}" == "--restart-gateway" ]]; then
  restart_gateway=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--restart-gateway]" >&2
  exit 2
fi

if [[ "${base_url}" != "http://127.0.0.1:11434" \
  && "${base_url}" != "http://localhost:11434" ]]; then
  echo "ERROR: local log AI only permits the localhost Ollama API." >&2
  exit 1
fi
if ! grep -Eq '^systemd=true$' /etc/wsl.conf; then
  echo "ERROR: WSL systemd must be enabled before installing Ollama." >&2
  exit 1
fi
for required_command in curl jq; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "ERROR: ${required_command} is required." >&2
    exit 1
  fi
done

if ! command -v zstd >/dev/null 2>&1; then
  echo "Installing required zstd package..."
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y zstd
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama from the official Linux installer..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

sudo systemctl enable --now ollama.service

ollama_ready=false
for _attempt in $(seq 1 30); do
  ollama_pid="$(systemctl show ollama.service --property MainPID --value)"
  if systemctl is-active --quiet ollama.service \
    && [[ "${ollama_pid}" =~ ^[1-9][0-9]*$ ]] \
    && curl --silent --fail --max-time 2 \
    "${base_url}/api/tags" >/dev/null; then
    ollama_ready=true
    break
  fi
  sleep 1
done
if [[ "${ollama_ready}" != "true" ]]; then
  sudo systemctl --no-pager --full status ollama.service || true
  echo "ERROR: Ollama API did not become ready." >&2
  exit 1
fi

echo "Downloading local log AI model ${model}..."
ollama pull "${model}"

model_payload="$({
  jq -nc --arg model "${model}" '{
    model: $model,
    messages: [{role: "user", content: "Return a JSON object with ok=true."}],
    stream: false,
    think: false,
    format: {
      type: "object",
      properties: {ok: {type: "boolean"}},
      required: ["ok"],
      additionalProperties: false
    },
    options: {temperature: 0, num_ctx: 2048, num_predict: 32},
    keep_alive: "5m"
  }'
})"
model_response="$(curl --silent --show-error --fail \
  --max-time "${timeout_sec}" \
  -H 'Content-Type: application/json' \
  -d "${model_payload}" \
  "${base_url}/api/chat")"
if ! jq -e '.message.content | fromjson | .ok == true' \
  <<<"${model_response}" >/dev/null; then
  echo "ERROR: ${model} did not return the expected structured response." >&2
  exit 1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version \
    --format=csv,noheader
else
  echo "WARN: nvidia-smi is unavailable; inference may use CPU." >&2
fi
ollama ps
if ! ollama ps | grep -q 'GPU'; then
  echo "WARN: Ollama did not report GPU residency; review ollama.service logs." >&2
fi

mkdir -p "${control_dir}"
touch "${control_env}"
chmod 0600 "${control_env}"

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${control_env}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${control_env}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${control_env}"
  fi
}

upsert_env FLEET_LOG_AI_ENABLED 1
upsert_env FLEET_LOG_AI_BASE_URL "${base_url}"
upsert_env FLEET_LOG_AI_MODEL "${model}"
upsert_env FLEET_LOG_AI_TIMEOUT_SEC "${timeout_sec}"
upsert_env FLEET_LOG_AI_RETENTION_DAYS "${retention_days}"

if [[ "${restart_gateway}" == "true" ]] \
  && systemctl --user is-active --quiet fleet-gateway.service; then
  systemctl --user restart fleet-gateway.service
fi

echo "LOCAL_LOG_AI_READY model=${model} api=${base_url}"
echo "Dashboard status: http://127.0.0.1:8000/api/mlops/ros2-logs/ai"
if [[ "${restart_gateway}" != "true" ]]; then
  echo "Gateway was not restarted. Restart it during a safe maintenance window."
fi
