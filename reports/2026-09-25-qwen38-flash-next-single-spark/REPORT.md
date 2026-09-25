# Qwen3.8-Flash-Next on a single DGX Spark — baseline reproduced, best config +42 %

**Date:** 2026-09-25 · **Recipe:** [`MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark`](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark) @ `6b50864` (release #52) · **Raw data:** [`data/`](data/) (22 sweep JSONL + enum/prefill/greedy receipts)

## TL;DR

A fresh install of the recipe lands inside its published numbers
(single-stream prose 49.8, code 58.8 tok/s — *not* in the 13–28 tok/s band of
issue #59). From there, **MTP k=6 + BF16 KV cache + FP8 draft head** lifts
single-stream code from **58.8 → 83.7 tok/s (+42 %)**, confirmed on a second
independent node. All 21 measured variants are listed below, including the
ones that lost or crashed.

## Setup

| | |
|---|---|
| Node A | DGX Spark (GB10, 128 GB unified), fresh clone `main` @ `6b50864`, `.env` = `.env.sample` except `MAX_NUM_SEQS=8` |
| Node B | DGX Spark (GB10), same recipe; model weights mounted read-only over NFS, PLE table built locally |
| Checkpoint | `Mia-AiLab/Qwen3.8-Flash-Next-NVFP4` (sha256-verified snapshot `925d7be6`) |
| Stock config | MTP 3, 47k draft vocab (47,172 entries per log), FP8 KV, 262,144 ctx |
| Note | fresh installs need the issue-#53 workaround (empty file in `logs/archive/`) |

**Method:** `bench/sweep.py` driven through sparkDash 1.8.8 — OpenAI requests,
prose + code prompt sets, ~600 generated tokens, streams S = 1/2/4/8, n = 3
repeats per cell. Throughput = client-measured aggregate decode tok/s
(`dash_aggregate_tps`); `ms/step` is engine-side decode latency;
`tok/step` = MTP acceptance.

> **Comparability caveat:** sparkDash 1.8.7 (22.09) replaced the shared
> `clamp_00..49` code prompt with distinct tasks per stream — code numbers
> here are lower *by design* than pre-22.09 tables (e.g. PR #39).

## Baseline — published numbers reproduced

| cell | tok/s mean (min–max) | ms/step | tok/step |
|---|---|---|---|
| code 1 | 58.8 (58.0–60.0) | 59.7 | 3.51 |
| code 2 | 92.7 | 73.3 | 3.48 |
| code 4 | 140.9 | 96.7 | 3.57 |
| code 8 | 197.9 | 134.9 | 3.53 |
| prose 1 | 49.8 (49.1–50.9) | 59.4 | 2.91 |
| prose 2 | 75.0 | 71.0 | 2.76 |
| prose 4 | 114.4 | 93.3 | 2.81 |
| prose 8 | 169.9 | 126.8 | 2.82 |

0 stream failures, 0 `NV_ERR_NO_MEMORY`, MemAvailable min 14.3 GiB.
Receipts: `data/sweep-niklas-2026-09-25.jsonl`.

## The ladder — how the +42 % is built

All runs on node A unless noted; k > 4 requires
[PR #70](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/pull/70)'s
per-k legality guard (branch `pr70` @ `7757bf9`; stock `start.sh` only allows
k ∈ {0,2,3,4,9..12}).

| step | config delta | code 1 | code 8 | prose 1 | prose 8 |
|---|---|---:|---:|---:|---:|
| baseline | stock env | 58.8 | 197.9 | 49.8 | 169.9 |
| `mtp4` | MTP 4 only | 66.3 (+12.9 %) | 209.0 | 49.2 | 165.8 |
| `kvauto` | BF16 KV only (MTP 3) | 63.2 (+7.5 %) | 212.4 | 52.7 | 175.9 |
| `k6kv` | MTP 6 + BF16 KV | 75.1 (+27.9 %) | 247.3 | 49.5 | 165.8 |
| `k6kv-nocstate` | + CPU C-states off (runtime) | 79.4 (+35.1 %) | 255.2 | 54.5 | 162.8 |
| **`fp8head`** | + `MTP_DRAFT_HEAD_FP8=1` ([PR #31](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/pull/31), on merged pr70+pr31 branch) | **83.7 (+42.4 %)** | **257.7** | **54.5** | 165.7 |

- `kvauto` was the only single flag that won in **all 8 cells** (+2.4 … +7.5 %);
  cost: BF16 KV pool is larger (still 262k ctx).
- `nocstate`: ms/step −0.8 … −2.4 % in all cells → real effect ~1–2 %, not the
  5–6 % seen on the dual recipe. GPU 63 °C. (Prose cell means scatter due to
  acceptance noise.)
- `fp8head` cross-check on **node B**: code 80.7 / 118.5 / 175.8 / 249.3,
  prose 53.2 / 81.3 / 105.3 / 166.0 → **confirmed** (>3 % in code 1/4/8 vs
  that node's `k6kv`).

## All measured variants (mean tok/s; Δ% vs the node-A stock baseline)

| run | node | config delta vs comparison base | code 1 | code 8 | prose 1 | prose 8 | verdict |
|---|---|---|---:|---:|---:|---:|---|
| baseline | A | — | 58.8 | 197.9 | 49.8 | 169.9 | reference |
| mtp4 | A | MTP 4 | 66.3 | 209.0 | 49.2 | 165.8 | code +, prose flat→neg |
| kvauto | A | BF16 KV | 63.2 | 212.4 | 52.7 | 175.9 | win, all cells |
| k6kv | A | MTP 6 + BF16 KV | 75.1 | 247.3 | 49.5 | 165.8 | code win |
| k6kv-nocstate | A | + C-states off | 79.4 | 255.2 | 54.5 | 162.8 | small extra |
| fp8head | A | + FP8 draft head | **83.7** | **257.7** | **54.5** | 165.7 | **best** |
| fp8head | B | same, cross-check | 80.7 | 249.3 | 53.2 | 166.0 | confirmed |
| k6kv | B | control, NFS weights | 76.6 | 237.2 | 50.9 | 164.3 | ≈ node A (±4 %) |
| res28 | B | k6kv + `HOST_RESERVE_GIB=28` | 74.8 | 247.4 | 49.5 | 160.6 | noise, no win |
| bat8192 | B | k6kv + `MAX_NUM_BATCHED_TOKENS=8192` | 77.0 | 248.4 | 52.1 | 160.3 | mixed, no clear win |
| seqs16 | B | k6kv + `MAX_NUM_SEQS=16` | 79.0 | 242.7 | 51.6 | 160.0 | borderline |
| seqs16 | A | same | 76.6 | 251.1 | 51.3 | 166.3 | borderline |
| v65k | A | k6kv + 65k draft vocab | 73.5 | 249.4 | 51.4 | 163.6 | no win |
| mtp9 | A | MTP 9 + BF16 KV | 79.9 | 253.5 | **45.8** | **148.2** | prose collapses — loser |
| kombi | A | fp8head + seqs16 + res28 | 76.8 | 255.2 | 50.2 | 170.4 | dilutes fp8head |
| p01 | A | fp8head + async-meta patch (SCA+GDN nosync) | 79.5 | 250.4 | 53.6 | 167.3 | ms/step +1.3…3.4 % all cells — loser |
| p02 | B | fp8head + PLE-prefetch-v2 patch | 80.5 | 240.9 | 53.4 | 163.6 | neutral→slightly neg |
| b11-base | A | PR #31 rebased on `main` @ `796badd`, flags off | 58.3 | 199.5 | 50.7 | 175.9 | control ≈ baseline |
| b11-fp8 | A | rebase + `MTP_DRAFT_HEAD_FP8=1` only | 60.7 | 201.7 | 50.6 | 176.5 | small alone |
| b11-gdn | A | rebase + `GDN_PREFILL_BACKEND=flashinfer` | 60.4 | 197.2 | 48.5 | 172.7 | small alone |
| b11-both | A | both flags | 61.8 | 201.2 | 53.3 | 177.0 | small alone |
| d11-k6 | A | MTP 6 + BF16 KV on `main` @ `796badd` | 75.2 | 243.8 | 54.3 | 161.9 | reproduces k6kv on new main |
| noblock | A | k6kv + `MTP_DISABLE_BLOCK_DROP=1` | — | — | — | — | engine crash: `disable_eagle_block_drop` unknown in pinned image |

Notes:

- The `b11-*`/`d11-k6` runs were made for the maintainer's merge checks on
  PR #31 (rebased onto `main` @ `796badd`); in isolation the two flags are
  small — the +42 % needs the k=6+BF16-KV stack underneath.
- `p01`/`p02` were our own code patches (correctness-verified by 5× greedy
  runs — see `data/greedy-*.json`); neither won, both stay unmerged.
- `COMPILATION_MODE=3` was intentionally not re-measured — the recipe
  changelog already documents +0.3/+1.0 % (inside noise).
- `enum-*.jsonl` / `prefill-b11-*.jsonl` in `data/` back two posted answers:
  usmaneth's `MTP_K_SCHEDULE` question on PR #70 (schedule applies in the
  pinned image only for uniform k) and the PR #31 prefill checks.

## Reproduce

```bash
# on the node: fresh clone, .env from .env.sample, set MAX_NUM_SEQS=8
# (fresh installs need the #53 workaround: one empty file in logs/archive/)
# then from any machine that can ssh to the node:
HOST=node-a SSH_HOST=<your-node> ./tools/ab_lauf.sh k6kv \
  "MTP_NUM_SPECULATIVE_TOKENS=6 KV_CACHE_DTYPE=auto"
HOST=node-a SSH_HOST=<your-node> ./tools/ab_lauf.sh fp8head \
  "MTP_NUM_SPECULATIVE_TOKENS=6 KV_CACHE_DTYPE=auto MTP_DRAFT_HEAD_FP8=1"
SWEEP_PREFIX=sweep-<you>-<date> python3 tools/auswerten.py
```

`ab_lauf.sh` rebuilds `.env` from `.env.baseline` + your pairs, restarts the
recipe, runs `bench/sweep.py` (prose+code × S=1/2/4/8 × 3 reps), pulls the
JSONL back and updates the table.

## Receipts

`data/` — `sweep-niklas-2026-09-25*.jsonl` (22 runs incl. baseline),
`enum-off1-*.jsonl`, `enum-on-*.jsonl`, `prefill-b11-*.jsonl`,
`greedy-*.json`. File naming: `sweep-<user>-<date>-<host>-<run>`; files
without a host segment are historical node-A runs.

## Status

Posted: PR #70 measurement + k-schedule answer, issue #59 baseline, issue #53
fix tests, issue #19 sweep (links in the repo README). The +42 % config is
measured and cross-checked; posting waits on the maintainer's merge checks
for PR #31.
