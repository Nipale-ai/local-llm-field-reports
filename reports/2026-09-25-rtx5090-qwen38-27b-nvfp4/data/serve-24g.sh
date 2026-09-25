#!/usr/bin/env bash
# 24 GB footprint test: same recipe, reduced KV pool, low gpu-util cap.
set -Eeuo pipefail
cd /home/user/mia-bench/nvfp4-5090
VENV=.venv
MODEL_DIR="$HOME/models/RadixArk/Qwen3.8-27B-NVFP4"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VLLM_USE_FLASHINFER_SAMPLER=0
PORT="${PORT:-8888}"
KVB="${KVB:-2147483648}"      # KV pool bytes (2 GiB default)
GUTIL="${GUTIL:-0.73}"        # ~23.8 GiB of 32.6
SPECK="${SPECK:-3}"
CTX="${CTX:-262144}"
EAGER="${EAGER:-0}"
EXTRA=()
[ "$EAGER" = "1" ] && EXTRA+=(--enforce-eager)
exec "$VENV/bin/vllm" serve "$MODEL_DIR" \
  --served-model-name qwen38-nvfp4-24g \
  --host 0.0.0.0 --port "$PORT" \
  --max-model-len "$CTX" \
  --kv-cache-dtype turboquant_4bit_nc \
  --kv-cache-memory-bytes "$KVB" \
  --max-num-seqs 1 \
  --max-num-batched-tokens 512 \
  --gpu-memory-utilization "$GUTIL" \
  --attention-config.flash_attn_version=2 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 \
  --speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":$SPECK}" \
  "${EXTRA[@]}"
