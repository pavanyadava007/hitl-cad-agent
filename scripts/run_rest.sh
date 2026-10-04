#!/usr/bin/env bash
# Resume script used after the first full run was interrupted during qwen2.5-coder:7b A seed 1.
# 7b A therefore has seed 0 only.
set -u
cd "$(dirname "$0")/.."
HCA=.venv/bin/hca
start() {
  docker start "$1" >/dev/null 2>&1 || docker run -d --name "$1" --gpus all -p "127.0.0.1:$2:11434" -v "$3:/root/.ollama" ollama/ollama >/dev/null
  for _ in $(seq 60); do curl -sf "127.0.0.1:$2/api/tags" >/dev/null && return 0; sleep 2; done
  echo "ollama $1 did not start"; return 1
}
unload() { curl -s "127.0.0.1:$2/api/generate" -d "{\"model\":\"$1\",\"keep_alive\":0}" >/dev/null; }

start hca-ollama-llama 11437 mrs_ollama
for ap in B C; do $HCA eval --model llama3.1:8b --approach $ap --seeds 0 1 2; done
$HCA eval --model llama3.1:8b --approach A --seeds 0
unload llama3.1:8b 11437
docker stop hca-ollama-llama >/dev/null

start hca-ollama 11436 isa_ollama
for ap in B C; do $HCA eval --model qwen3-coder:30b --approach $ap --seeds 0; done
$HCA eval --model qwen3-coder:30b --approach A --seeds 0
for ap in B C; do $HCA eval --model qwen3-coder:30b --approach $ap --seeds 1 2; done
unload qwen3-coder:30b 11436
echo ALL_DONE
