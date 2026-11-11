#!/usr/bin/env bash
# Start the model containers ONE AT A TIME and put each to sleep once it is up.
#
# Why: every vLLM container grabs its GPU memory when it starts. If two start at once (or one
# starts while another is awake) they run out of memory. Starting them in sequence, sleeping
# each before the next, avoids that. Run it after a reboot, or before first starting the router.
#
# Usage:  scripts/bootstrap.sh gpt-oss-20b:8025 qwen3-vl-8b:8026
#         (container-name:host-port; the containers must already exist)
# Optional: VLLM_BACKEND_KEY=... if the containers set VLLM_API_KEY.
set -euo pipefail

auth=()
if [[ -n "${VLLM_BACKEND_KEY:-}" ]]; then auth=(-H "Authorization: Bearer ${VLLM_BACKEND_KEY}"); fi

for spec in "$@"; do
  name="${spec%%:*}"; port="${spec##*:}"
  echo ">> starting ${name}"
  docker start "${name}" >/dev/null
  until curl -sf "http://127.0.0.1:${port}/health" >/dev/null; do sleep 5; done
  curl -sf -X POST "http://127.0.0.1:${port}/sleep?level=1" "${auth[@]}" >/dev/null
  echo ">> ${name} is up and asleep"
done
