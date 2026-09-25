#!/bin/bash
# env-reporter.sh — baut .env im frischen Klon zur exakten Reporter-Konfig
# (Issue #59) um. Aufruf auf spark3:  bash env-reporter.sh ~/test-issue59
# Reporter-Werte (Issue-Text + repcfg-Lauf): YARN=1/512k, KV auto (BF16),
# SEQS=4, BATCHED=8192, MTP3, HOST_RESERVE=26, capture [1,2,3,4]
# FULL_DECODE_ONLY, en-code-47k Draft-Vokab, V2-Runner, PORT=8888.
# MTP_DISABLE_BLOCK_DROP=0: Reporter-Commit 6b50864 kannte den Backport
# nicht (Image ignoriert den Key) -> 0 = identisches Engine-Verhalten.
set -e
d=${1:-~/test-issue59}
cd "$d"
cp .env.sample .env
sed -i \
  -e 's/^YARN=0 /YARN=1 /' \
  -e 's/^KV_CACHE_DTYPE=fp8 /KV_CACHE_DTYPE=auto /' \
  -e 's/^MAX_NUM_BATCHED_TOKENS=2048 /MAX_NUM_BATCHED_TOKENS=8192 /' \
  -e 's/^CUDAGRAPH_CAPTURE_SIZES=auto /CUDAGRAPH_CAPTURE_SIZES=1,2,3,4 /' \
  -e 's/^MTP_DISABLE_BLOCK_DROP=1 /MTP_DISABLE_BLOCK_DROP=0 /' \
  .env
grep -n "^YARN=\|^KV_CACHE_DTYPE=\|^MAX_NUM_SEQS=\|^MAX_NUM_BATCHED_TOKENS=\|^MTP_NUM\|^HOST_RESERVE\|^CUDAGRAPH\|^MTP_DISABLE\|^MTP_DRAFT_VOCAB=\|^PORT=\|^ABLIT=" .env
