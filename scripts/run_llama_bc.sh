#!/usr/bin/env bash
# Re-run llama3.1:8b B and C after the export-type crash fix (their first attempt aborted in the attack phase).
set -u
cd "$(dirname "$0")/.."
docker start hca-ollama-llama >/dev/null
for _ in $(seq 60); do curl -sf 127.0.0.1:11437/api/tags >/dev/null && break; sleep 2; done
for ap in B C; do .venv/bin/hca eval --model llama3.1:8b --approach $ap --seeds 0 1 2; done
curl -s 127.0.0.1:11437/api/generate -d '{"model":"llama3.1:8b","keep_alive":0}' >/dev/null
docker stop hca-ollama-llama >/dev/null
echo LLAMA_DONE
