#!/usr/bin/env bash
# run_stage.sh <label> [repeats] [streams...] — ein Messpunkt fuer die
# Residenz->tok/s-Kurve. Druck/Aufbau macht der Aufrufer vorher.
# Schreibt: ~/issue59-repro/<label>.jsonl (sweep) + <label>.memstat
set -u
LABEL="${1:?label}"
REPS="${2:-3}"
shift 2 || shift $#
STREAMS="${*:-1}"
RDIR="$HOME/issue59-repro"
REPO="$HOME/Qwen3.8-Flash-Next-Single-DGX-Spark"
PLE_FILE="$HOME/.cache/vllm/ple_cache/Mia-AiLab--Qwen3.8-Flash-Next-NVFP4/language_model.model.layers.1.ple.ple_embedding.ngram_embedding.packed_u8"

mkdir -p "$RDIR/out"
echo "== $LABEL ==" | tee -a "$RDIR/out/summary.txt"
echo "-- pre  $(date -u +%H:%M:%S)Z" | tee -a "$RDIR/out/summary.txt"
"$RDIR/memstat.sh" | tee "$RDIR/out/$LABEL.pre.memstat"
python3 "$RDIR/dc_residency.py" "$PLE_FILE" | tail -1 | tee -a "$RDIR/out/summary.txt"

( cd "$REPO" && python3 bench/sweep.py --tag "i59-$LABEL" \
    --streams $STREAMS --prompt prose --repeats "$REPS" \
    --max-tokens 600 --out "$RDIR/out/$LABEL.jsonl" \
    --note "$LABEL" 2>&1 | tee "$RDIR/out/$LABEL.sweep.log" )

echo "-- post $(date -u +%H:%M:%S)Z" | tee -a "$RDIR/out/summary.txt"
"$RDIR/memstat.sh" | tee "$RDIR/out/$LABEL.post.memstat"
python3 "$RDIR/dc_residency.py" "$PLE_FILE" | tail -1 | tee -a "$RDIR/out/summary.txt"
