#!/usr/bin/env bash
OUT="$1"
echo "ts,mem_avail_mb,mem_free_mb,swap_used_mb,jit_procs,cc1plus,vllm_rss_mb" > "$OUT"
while true; do
  eval "$(awk '/^MemAvailable:/{a=$2} /^MemFree:/{f=$2} /^SwapTotal:/{t=$2} /^SwapFree:/{s=$2} END{printf "avail=%d free=%d swap=%d",a,f,t-s}' /proc/meminfo)"
  jit=$(pgrep -c -f "nvcc|cicc|ptxas|ninja" 2>/dev/null || true); jit=${jit:-0}
  c1=$(pgrep -c cc1plus 2>/dev/null || true); c1=${c1:-0}
  vrss=$(ps -C vllm -o rss= 2>/dev/null | awk '{s+=$1} END{print s+0}')
  echo "$(date +%H:%M:%S),$avail,$free,$swap,$jit,$c1,$vrss" >> "$OUT"
  sleep 1
done
