#!/usr/bin/env bash
# Concurrency variant of the recipe per README "Can I get more concurrency?":
# 32K context ceiling, 8 sessions, MTP dialed back to k=1.
set -Eeuo pipefail
cd /home/user/mia-bench/nvfp4-5090
VENV=.venv
MODEL_DIR="$HOME/models/RadixArk/Qwen3.8-27B-NVFP4"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VLLM_USE_FLASHINFER_SAMPLER=0
PORT="${PORT:-8888}"
SPECK="${SPECK:-1}"
SEQS="${SEQS:-8}"
CTX="${CTX:-32768}"
TAG="${TAG:-conc}"
exec "$VENV/bin/vllm" serve "$MODEL_DIR" \
  --served-model-name "qwen38-nvfp4-$TAG" \
  --host 0.0.0.0 --port "$PORT" \
  --max-model-len "$CTX" \
  --kv-cache-dtype turboquant_4bit_nc \
  --kv-cache-memory-bytes 5905580032 \
  --max-num-seqs "$SEQS" \
  --max-num-batched-tokens 512 \
  --gpu-memory-utilization 0.96 \
  --attention-config.flash_attn_version=2 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 \
  --speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":$SPECK}"
