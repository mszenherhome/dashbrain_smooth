#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-$HOME/models/Qwen3-0.6B-Q4_0.gguf}"
PORT="${LLAMA_PORT:-8080}"

exec "$HOME/llama.cpp/build/bin/llama-server" \
  -m "$MODEL" \
  -c 4096 \
  -t 2 \
  -tb 2 \
  --host 127.0.0.1 \
  --port "$PORT"
