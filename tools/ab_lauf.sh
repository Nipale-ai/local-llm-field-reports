#!/usr/bin/env bash
# ab_lauf.sh — run one full A/B measurement pass on a remote GPU node via ssh.
#
# Usage:  ./ab_lauf.sh <run-name> "<KEY=VALUE> [<KEY=VALUE> ...]"
#         HOST=node-b SSH_HOST=node-b ./ab_lauf.sh <run-name> "..."
# Example: ./ab_lauf.sh bf16kv "KV_CACHE_DTYPE=auto MTP_NUM_SPECULATIVE_TOKENS=3"
#
# HOST is only a label for the output file names (default "node-a").
# SSH_HOST is the ssh alias to connect to (default: same as HOST).
# RDIR is the recipe checkout directory under ~ on the remote (default:
# Qwen3.8-Flash-Next-Single-DGX-Spark — point it at a patch clone if needed).
#
# Flow: rebuild .env on the remote from .env.baseline + the given pairs ->
# stop.sh -> start.sh detached -> wait until :8888/v1/models answers ->
# run bench/sweep.py detached -> wait for 24 JSONL lines -> scp results back ->
# auswerten.py. Output: sweep-<user>-<date>-<host>-<run>.jsonl next to this script.
set -euo pipefail

HOST="${HOST:-node-a}"
[[ "$HOST" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || { echo "ERROR: bad HOST label '$HOST'" >&2; exit 1; }
SSH_HOST="${SSH_HOST:-$HOST}"
REMOTE_DIR="${RDIR:-Qwen3.8-Flash-Next-Single-DGX-Spark}"   # under ~ on $SSH_HOST
BOOT="${BOOT:-1}"            # BOOT=0: skip .env/stop/start/wait (server already up) — sweep only
CONTAINER="${CONTAINER:-vllm-fn-tp1}"
PORT="${PORT:-8888}"

READY_MAX_S=$((45*60))     # max wait for /v1/models
READY_POLL_S=30
START_STALL_S=300          # start log quiet + no container -> start.sh dead
SWEEP_LINES=24             # 2 prompts x 4 stream counts x 3 repeats
SWEEP_POLL_S=60
SWEEP_MAX_S=$((120*60))
SWEEP_STALL_S=$((15*60))   # no new JSONL line for this long -> sweep dead

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST")
SCP=(scp -o BatchMode=yes -o ConnectTimeout=15)

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$(date +%H:%M:%S)] $*"; }

remote_tail() {
  "${SSH[@]}" "tail -n 60 ~/'$REMOTE_DIR'/'$1' 2>/dev/null; echo '--- docker logs $CONTAINER ---'; docker logs --tail 40 '$CONTAINER' 2>&1 | tail -n 40" || true
}

# ---------- arguments ----------
LAUF="${1:-}"
[ -n "$LAUF" ] || die "usage: $0 <run-name> \"<KEY=VALUE> [<KEY=VALUE> ...]\""
shift
PAIRS="$*"
[[ "$LAUF" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || die "run-name '$LAUF': only [A-Za-z0-9_-] allowed"

# Validate KEY=VALUE pairs (whitelisted chars so values are safe to pass remotely).
# qstr stays a string, not an array: "${arr[@]}" on an empty array + set -u breaks on bash 3.2.
qstr=""
for kv in $PAIRS; do
  [[ "$kv" =~ ^[A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9._:/,=@%+-]*$ ]] \
    || die "invalid pair: '$kv' (expected KEY=VALUE, value without spaces/special chars)"
  qstr="$qstr $(printf '%q' "$kv")"
done

WHO="${WHO:-$(id -un 2>/dev/null || echo runner)}"
RJSON="logs/sweep-${WHO}-$(date +%F)-${HOST}-${LAUF}.jsonl"
RLOG="logs/sweep-${HOST}-${LAUF}.log"
RSTART="fn-start-${HOST}-${LAUF}.log"   # under ~ on $SSH_HOST
TAG="${WHO}-${HOST}-${LAUF}"
NOTE="${LAUF}${PAIRS:+: $PAIRS}"

log "run '$LAUF' | pairs: ${PAIRS:-<none, plain baseline>} | target: ${SSH_HOST}:~/$REMOTE_DIR"

# ---------- 1-3. .env + restart + wait (skipped with BOOT=0) ----------
if [ "$BOOT" = "0" ]; then
  log "BOOT=0: skipping .env build and restart — checking reachability only"
  "${SSH[@]}" "curl -sf -m 5 localhost:$PORT/v1/models >/dev/null 2>&1" \
    || die "BOOT=0 but no server on :$PORT"
  log "server on :$PORT responding"
else
# ---------- 1. rebuild .env on $SSH_HOST from .env.baseline + pairs ----------
log "building .env from .env.baseline (pairs: ${PAIRS:-none})"
"${SSH[@]}" "cd ~/'$REMOTE_DIR' && exec bash -s" -- $qstr <<'EOS'
set -euo pipefail
cp -f .env.baseline .env
for kv in "$@"; do
  key="${kv%%=*}"; val="${kv#*=}"
  esc="$(printf '%s' "$val" | sed 's/[&|\\]/\\&/g')"
  sed -i -E "s|^(${key}=)[^[:space:]#]*|\1${esc}|" .env
  line="$(grep -E "^${key}=" .env | head -n1 || true)"
  [ -n "$line" ] || { echo "ERROR: ${key}= not found in .env" >&2; exit 1; }
  actual="$(printf '%s' "$line" | sed -E 's/^[^=]+=//; s/[[:space:]#].*$//')"
  [ "$actual" = "$val" ] || { echo "ERROR: ${key} is '${actual}', expected '${val}'" >&2; exit 1; }
  echo "ok: $line"
done
EOS

# ---------- 2. stop.sh, then start.sh detached ----------
log "stopping server"
"${SSH[@]}" "cd ~/'$REMOTE_DIR' && ./stop.sh" || true
for _ in 1 2 3 4 5 6; do
  "${SSH[@]}" "curl -sf -m 5 localhost:$PORT/v1/models >/dev/null 2>&1" || break
  sleep 10
done
"${SSH[@]}" "curl -sf -m 5 localhost:$PORT/v1/models >/dev/null 2>&1" \
  && die "port $PORT still answering after stop.sh — old server alive"

log "starting server detached (log: ~/$RSTART)"
"${SSH[@]}" "cd ~/'$REMOTE_DIR' && (setsid nohup ./start.sh > ~/'$RSTART' 2>&1 < /dev/null &)"

# ---------- 3. wait for /v1/models ----------
log "waiting for localhost:$PORT/v1/models (every ${READY_POLL_S}s, max $((READY_MAX_S/60)) min)"
deadline=$((SECONDS + READY_MAX_S))
seen=0; prev_size=-1; quiet=0; ssh_fail=0; ready=0
while [ "$SECONDS" -lt "$deadline" ]; do
  if "${SSH[@]}" "curl -sf -m 5 localhost:$PORT/v1/models >/dev/null 2>&1"; then
    ready=1; break
  fi
  st="$("${SSH[@]}" "docker inspect -f '{{.State.Status}}' '$CONTAINER' 2>/dev/null || echo missing")" \
    || { ssh_fail=$((ssh_fail+1)); [ "$ssh_fail" -ge 5 ] && die "ssh $SSH_HOST unreachable"; sleep "$READY_POLL_S"; continue; }
  ssh_fail=0
  case "$st" in
    missing)
      if [ "$seen" = 1 ]; then
        remote_tail "$RSTART"; die "container $CONTAINER vanished"
      fi
      # Preflight without container: a stalled start log is the death signal
      sz="$("${SSH[@]}" "stat -c %s ~/'$RSTART' 2>/dev/null || echo 0")"
      sz="${sz//[!0-9]/}"; sz="${sz:-0}"
      if [ "$sz" = "$prev_size" ]; then quiet=$((quiet+READY_POLL_S)); else quiet=0; prev_size=$sz; fi
      if [ "$quiet" -ge "$START_STALL_S" ]; then
        remote_tail "$RSTART"
        die "container $CONTAINER never appeared and $RSTART quiet for $((START_STALL_S/60)) min"
      fi
      ;;
    exited|dead|removing)
      remote_tail "$RSTART"; die "container $CONTAINER status '$st'"
      ;;
    *) seen=1 ;;
  esac
  sleep "$READY_POLL_S"
done
[ "$ready" = 1 ] || { remote_tail "$RSTART"; die "timeout: /v1/models not ready after $((READY_MAX_S/60)) min"; }
log "server ready"
fi

# ---------- 4. start sweep detached ----------
# Wait on line count, not on the process: pgrep -f on the sweep command would
# match itself (the waiting ssh command line contains the same string).
log "starting sweep detached -> $RJSON"
"${SSH[@]}" "cd ~/'$REMOTE_DIR' && mkdir -p logs && rm -f '$RJSON' && (setsid nohup python3 bench/sweep.py --tag '$TAG' --streams 1 2 4 8 --prompt prose code --repeats 3 --max-tokens 600 --out '$RJSON' --note '$NOTE' > '$RLOG' 2>&1 < /dev/null &)"

# ---------- 5. wait until JSONL has all lines ----------
deadline=$((SECONDS + SWEEP_MAX_S))
prev=-1; stall=0; n=0
while [ "$SECONDS" -lt "$deadline" ]; do
  n="$("${SSH[@]}" "wc -l < ~/'$REMOTE_DIR'/'$RJSON' 2>/dev/null || echo 0")"
  n="${n//[!0-9]/}"; n="${n:-0}"
  [ "$n" -ge "$SWEEP_LINES" ] && break
  if [ "$n" = "$prev" ]; then stall=$((stall+SWEEP_POLL_S)); else stall=0; prev=$n; fi
  log "  $n/$SWEEP_LINES lines"
  if [ "$stall" -ge "$SWEEP_STALL_S" ]; then
    "${SSH[@]}" "tail -n 40 ~/'$REMOTE_DIR'/'$RLOG'" || true
    die "sweep stalled: $n/$SWEEP_LINES lines for $((SWEEP_STALL_S/60)) min"
  fi
  sleep "$SWEEP_POLL_S"
done
[ "$n" -ge "$SWEEP_LINES" ] || die "sweep timeout after $((SWEEP_MAX_S/60)) min ($n/$SWEEP_LINES lines)"
log "sweep done ($n lines)"

# ---------- 6. fetch results + evaluate ----------
log "fetching JSONL + logs to $DIR"
"${SCP[@]}" "$SSH_HOST:~/$REMOTE_DIR/$RJSON" "$DIR/" || die "scp $RJSON failed"
"${SCP[@]}" "$SSH_HOST:~/$REMOTE_DIR/$RLOG"  "$DIR/" || echo "WARN: $RLOG not fetched" >&2
"${SCP[@]}" "$SSH_HOST:~/$RSTART"            "$DIR/" || echo "WARN: $RSTART not fetched" >&2

if table="$(cd "$DIR" && python3 auswerten.py)"; then
  printf '%s\n' "$table" > "$DIR/TABELLE-alle-laeufe.md"
  printf '%s\n' "$table"
  log "TABELLE-alle-laeufe.md updated"
else
  echo "WARN: auswerten.py failed" >&2
fi
log "run '$LAUF' complete"
