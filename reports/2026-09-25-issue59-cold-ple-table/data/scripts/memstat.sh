#!/usr/bin/env bash
# Einmalig: kumulative Zaehler des vllm-fn-tp1-cgroups + Host-vmstat + Residenz.
# Ausgabe: ts pgmajfault_cg refault_file_cg memcurrent_gib pgmajfault_host resident_pct
set -u
PLE_FILE="$HOME/.cache/vllm/ple_cache/Mia-AiLab--Qwen3.8-Flash-Next-NVFP4/language_model.model.layers.1.ple.ple_embedding.ngram_embedding.packed_u8"
RDIR="${RDIR:-$HOME/issue59-repro}"
CID="$(docker inspect -f '{{.Id}}' vllm-fn-tp1 2>/dev/null)"
if [ -z "$CID" ]; then echo "no-container"; exit 0; fi
CG="/sys/fs/cgroup/system.slice/docker-$CID.scope/memory.stat"
maj_cg=$(awk '$1=="pgmajfault"{print $2}' "$CG" 2>/dev/null || echo -1)
ref_cg=$(awk '$1=="workingset_refault_file"{print $2}' "$CG" 2>/dev/null || echo -1)
cur=$(cat "/sys/fs/cgroup/system.slice/docker-$CID.scope/memory.current" 2>/dev/null || echo -1)
maj_h=$(awk '$1=="pgmajfault"{print $2}' /proc/vmstat)
res=$(python3 "$RDIR/dc_residency.py" "$PLE_FILE" 2>/dev/null | tail -1 | awk '{print $3}')
echo "$(date +%s) $maj_cg $ref_cg $(awk "BEGIN{printf \"%.1f\", $cur/2**30}") $maj_h ${res:-na}"
