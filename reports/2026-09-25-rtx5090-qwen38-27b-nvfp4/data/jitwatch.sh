#!/usr/bin/env bash
# log every second: total RSS (KB) of all JIT compiler processes + MemAvailable
OUT="$1"
echo "ts,avail_mb,jit_rss_mb,jit_n" > "$OUT"
while true; do
  avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
  rss=$(ps -eo rss=,comm= | awk '$2 ~ /^(nvcc|cicc|ptxas|cc1plus|as|ld|ninja|fatbinary)/ {s+=$1; n++} END{print s+0, n+0}' | awk '{print $1","$2}')
  echo "$(date +%H:%M:%S),$((avail/1024)),$rss" >> "$OUT"
  sleep 1
done
