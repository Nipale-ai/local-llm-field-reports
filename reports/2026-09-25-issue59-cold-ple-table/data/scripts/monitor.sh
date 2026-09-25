#!/usr/bin/env bash
# monitor.sh <out.csv> [interval_s] — loggt fortlaufend Residenz + Faults.
# CSV: ts,resident_pct,pgmajfault_cg,pgmajfault_host,refault_file_cg,memcurrent_gib,MemAvailable_gib
set -u
OUT="${1:?out.csv}"
IV="${2:-5}"
echo $$ > "$OUT.pid"
PLE_FILE="$HOME/.cache/vllm/ple_cache/Mia-AiLab--Qwen3.8-Flash-Next-NVFP4/language_model.model.layers.1.ple.ple_embedding.ngram_embedding.packed_u8"
RDIR="${RDIR:-$HOME/issue59-repro}"
echo "ts,resident_pct,pgmajfault_cg,pgmajfault_host,refault_file_cg,memcurrent_gib,memavail_gib" > "$OUT"
while true; do
  CID="$(docker inspect -f '{{.Id}}' vllm-fn-tp1 2>/dev/null)"
  if [ -n "$CID" ]; then
    CG="/sys/fs/cgroup/system.slice/docker-$CID.scope/memory.stat"
    maj_cg=$(awk '$1=="pgmajfault"{print $2}' "$CG" 2>/dev/null || echo -1)
    ref_cg=$(awk '$1=="workingset_refault_file"{print $2}' "$CG" 2>/dev/null || echo -1)
    cur=$(cat "/sys/fs/cgroup/system.slice/docker-$CID.scope/memory.current" 2>/dev/null || echo -1)
  else
    maj_cg=-1; ref_cg=-1; cur=-1
  fi
  maj_h=$(awk '$1=="pgmajfault"{print $2}' /proc/vmstat)
  avail=$(awk '$1=="MemAvailable:"{printf "%.1f", $2/2**20}' /proc/meminfo)
  res=$(python3 "$RDIR/dc_residency.py" "$PLE_FILE" 2>/dev/null | tail -1 | awk '{print $3}')
  echo "$(date +%s),${res:-na},${maj_cg},${maj_h},${ref_cg},$(awk "BEGIN{printf \"%.1f\", $cur/2**30}"),${avail}" >> "$OUT"
  sleep "$IV"
done
