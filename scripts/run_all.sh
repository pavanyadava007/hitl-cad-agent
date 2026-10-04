#!/usr/bin/env bash
# Full evaluation on one GPU. Starts/stops the local Ollama containers it needs.
# Models are expected in the docker volumes isa_ollama (qwen2.5-coder:7b, qwen3-coder:30b)
# and mrs_ollama (llama3.1:8b); nothing is downloaded.
set -u
cd "$(dirname "$0")/.."
HCA=.venv/bin/hca
SEEDS=${SEEDS:-"0 1 2"}
A30_SEEDS=${A30_SEEDS:-"0"}

start() {  # name port volume
  docker start "$1" >/dev/null 2>&1 || docker run -d --name "$1" --gpus all -p "127.0.0.1:$2:11434" -v "$3:/root/.ollama" ollama/ollama >/dev/null
  for _ in $(seq 60); do curl -sf "127.0.0.1:$2/api/tags" >/dev/null && return 0; sleep 2; done
  echo "ollama $1 did not start"; return 1
}
unload() { curl -s "127.0.0.1:$2/api/generate" -d "{\"model\":\"$1\",\"keep_alive\":0}" >/dev/null; }

$HCA eval --approach R --seeds 0

start hca-ollama 11436 isa_ollama
for ap in B C A; do $HCA eval --model qwen2.5-coder:7b --approach $ap --seeds $SEEDS; done
unload qwen2.5-coder:7b 11436

start hca-ollama-llama 11437 mrs_ollama
for ap in B C A; do $HCA eval --model llama3.1:8b --approach $ap --seeds $SEEDS; done
unload llama3.1:8b 11437
docker stop hca-ollama-llama >/dev/null

for ap in B C; do $HCA eval --model qwen3-coder:30b --approach $ap --seeds $SEEDS; done
$HCA eval --model qwen3-coder:30b --approach A --seeds $A30_SEEDS
unload qwen3-coder:30b 11436
echo ALL_DONE
