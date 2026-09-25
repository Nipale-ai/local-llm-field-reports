#!/usr/bin/env bash
# issue11-test.sh -- verify the EXTRA_VLLM_ARGS fix for issue #11 of
# MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark. No docker, no GPU.
#
# start.sh moves EXTRA_VLLM_ARGS through two parse stages before vLLM sees it:
#   stage 1 (split):  the .env string becomes argv tokens
#   stage 2 (render): the tokens are written into .last_launch.sh and re-parsed
#                     by the shell when that script runs
# This test replays both stages. A `docker` stub on PATH prints the argv it
# receives -- i.e. exactly what vLLM would see.
#
# Three columns per case:
#   old = main:        read -ra + "${VLLM_ARGS[*]}" flatten,
#                      recipe JSONs carry literal '...' quotes
#   v1  = first fix:   read -ra + printf %q, recipe JSONs bare
#                      (regresses case 3 -- the documented workaround)
#   new = this patch:  shlex split (single-quote grouping) + printf %q,
#                      recipe JSONs bare
set -u
cd "$(dirname "$0")"

STUB=$(mktemp -d "${TMPDIR:-/tmp}/issue11.XXXXXX")
trap 'rm -rf "$STUB"' EXIT

cat > "$STUB/docker" <<'EOF'
#!/usr/bin/env bash
# Stub: print every argv element after __MODEL__ (the vLLM flags), one per line.
seen=0
for a in "$@"; do
    [[ $seen == 1 ]] && printf '%s\n' "$a"
    [[ $a == "__MODEL__" ]] && seen=1
done
EOF
chmod +x "$STUB/docker"

# ---- the two stages, verbatim semantics of each mode ------------------------

split_stage() { # $1 = mode; reads $EXTRA_VLLM_ARGS, appends to VLLM_ARGS
    _ARR=()
    if [[ $1 == new ]]; then
        _PARSED=$(python3 - "$EXTRA_VLLM_ARGS" <<'PY'
import sys, shlex
lx = shlex.shlex(sys.argv[1], posix=True)
lx.whitespace_split = True
lx.quotes = "'"
lx.commenters = ""
print("\n".join(lx))
PY
        ) || return 1
        if [[ -n "$_PARSED" ]]; then
            while IFS= read -r _T; do _ARR+=("$_T"); done <<< "$_PARSED"
        fi
    else
        read -ra _ARR <<< "$EXTRA_VLLM_ARGS"
    fi
    if ((${#_ARR[@]})); then VLLM_ARGS+=("${_ARR[@]}"); fi
    return 0
}

render_stage() { # $1 = mode; sets VLLM_ARGS_STR from VLLM_ARGS
    if [[ $1 == old ]]; then
        VLLM_ARGS_STR="${VLLM_ARGS[*]}"
    else
        printf -v VLLM_ARGS_STR '%q ' ${VLLM_ARGS[@]+"${VLLM_ARGS[@]}"}
    fi
}

# ---- runner ----------------------------------------------------------------

FAIL=0
run() { # $1=mode $2=extra-args $3=RECIPE-or-empty $4=expected "a|b|c" ; prints one line
    local mode=$1
    EXTRA_VLLM_ARGS=$2
    VLLM_ARGS=()
    if [[ $3 == RECIPE ]]; then
        # Same array-build syntax as start.sh: old wraps the JSON in literal
        # '...' (main); v1/new emit it bare. 'quoted' format here keeps the
        # brace-expansion quirk of bash 3.2 inside $( ) from faking a
        # difference that bash >=4 (the launcher's target) does not have.
        if [[ $mode == old ]]; then
            VLLM_ARGS+=("--speculative-config" "$(printf "'{\"method\":\"mtp\",\"num_speculative_tokens\":%s}'" 3)")
        else
            VLLM_ARGS+=("--speculative-config" "$(printf '{"method":"mtp","num_speculative_tokens":%s}' 3)")
        fi
    fi
    split_stage "$mode" && render_stage "$mode" || { printf '  %-3s %s\n' "$mode" "<split failed>"; return; }
    cat > "$STUB/launch.sh" <<EOF
#!/usr/bin/env bash
docker run \\
    -d --name issue11-test \\
    __IMG__ \\
    __MODEL__ \\
    $VLLM_ARGS_STR \\
    --host 127.0.0.1 \\
    --port 8888
EOF
    local got
    got=$(PATH="$STUB:$PATH" bash "$STUB/launch.sh" | paste -s -d '|' -)
    if [[ $got == "$4" ]]; then
        printf '  %-3s %s\n' "$mode" "$got"
    else
        printf '  %-3s %s   <-- MISMATCH (expected %s)\n' "$mode" "$got" "$4"
        FAIL=1
    fi
}

TAIL='|--host|127.0.0.1|--port|8888'

echo "== case 1: plain flags =="
echo "EXTRA_VLLM_ARGS='--api-key sekrit --disable-log-requests'"
EXP="--api-key|sekrit|--disable-log-requests$TAIL"
run old '--api-key sekrit --disable-log-requests' '' "$EXP"
run v1  '--api-key sekrit --disable-log-requests' '' "$EXP"
run new '--api-key sekrit --disable-log-requests' '' "$EXP"

echo "== case 2: bare JSON flag (the #11 report) =="
echo "EXTRA_VLLM_ARGS='--default-chat-template-kwargs={\"enable_thinking\":false}'"
run old '--default-chat-template-kwargs={"enable_thinking":false}' '' \
    "--default-chat-template-kwargs={enable_thinking:false}$TAIL"   # the bug
run v1  '--default-chat-template-kwargs={"enable_thinking":false}' '' \
    "--default-chat-template-kwargs={\"enable_thinking\":false}$TAIL"
run new '--default-chat-template-kwargs={"enable_thinking":false}' '' \
    "--default-chat-template-kwargs={\"enable_thinking\":false}$TAIL"

echo "== case 3: documented workaround, single-quoted JSON =="
echo "EXTRA_VLLM_ARGS=\"--kernel-config '{\"moe_backend\":\"flashinfer_b12x\"}'\""
run old "--kernel-config '{\"moe_backend\":\"flashinfer_b12x\"}'" '' \
    "--kernel-config|{\"moe_backend\":\"flashinfer_b12x\"}$TAIL"
run v1  "--kernel-config '{\"moe_backend\":\"flashinfer_b12x\"}'" '' \
    "--kernel-config|'{\"moe_backend\":\"flashinfer_b12x\"}'$TAIL"  # v1 regression
run new "--kernel-config '{\"moe_backend\":\"flashinfer_b12x\"}'" '' \
    "--kernel-config|{\"moe_backend\":\"flashinfer_b12x\"}$TAIL"

echo "== case 4: recipe JSON, byte-identical across modes =="
echo "(VLLM_ARGS built with start.sh's --speculative-config printf for each mode)"
EXP="--speculative-config|{\"method\":\"mtp\",\"num_speculative_tokens\":3}$TAIL"
run old '' RECIPE "$EXP"
run v1  '' RECIPE "$EXP"
run new '' RECIPE "$EXP"

echo "== case 5: quoted value with a space =="
echo "EXTRA_VLLM_ARGS='--served-model-name '"'"'my model'"'"''"
EXP="--served-model-name|my model$TAIL"
run old "--served-model-name 'my model'" '' "$EXP"
run v1  "--served-model-name 'my model'" '' \
    "--served-model-name|'my|model'$TAIL"                          # v1 splits it
run new "--served-model-name 'my model'" '' "$EXP"

echo
if [[ $FAIL == 0 ]]; then echo "RESULT: all argv as expected"; else echo "RESULT: MISMATCHES above"; fi
exit $FAIL
