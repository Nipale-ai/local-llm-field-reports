# Issue #59: is a cold PLE table the cause? — tested, hypothesis refuted on our box

**Date:** 2026-09-25 · **Recipe:** [`MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark`](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark) · **Issue:** [#59](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/59) · **Raw data:** [`data/`](data/)

## The hypothesis

Issue #59 reporters see 13–28 tok/s single-stream where a healthy box gets
~50. Their py-spy shows the GPU worker blocked ~25–30 ms/step in
`ple_offload.wait_d2h`. Hypothesis under test: **the ~27 GiB PLE table falls
out of the page cache, decode faults rows in from NVMe, and the ~25 ms
`wait_d2h` window is storage latency.**

## Verdict

**On our box the issue is not reproducible via the PLE table: a verifiably
cold table delivers the same ~49–50 tok/s and the same step times as the
warm one — the page-cache hypothesis is refuted as the cause here.** The
remaining reporter delta sits in the MTP path (step time *and* acceptance),
not in table transport.

## What was done

The original `packed_u8` table (26.8 GiB / 28.8 GB, 320,001,536 × 90 B) was
moved aside and a byte-identical cold copy placed at the standard path, then
the server rebooted (`VLLM_PLE_PACKED_TABLE_DIR` only applies via `start.sh`;
vLLM itself does not know the var — warning `envs.py:2224` in the boot log,
ineffective).

After boot: `read_bytes` of the PLE worker ≈ 27.8 GB (whole table read,
drop-behind), `mincore` residency **0.00 %**, ≤ ~1.5 % during the decodes
(monitor `data/monitor.csv`, 5 s cadence). So: a guaranteed cold table — the
real issue-#59 condition.

## Results

### 1. Genuinely cold PLE table → same speed

| run | residency | ms/step | tok/step | tok/s |
|---|---|---|---|---|
| S=1 **cold** (`dc_coldboot_s1`, 2 reps) | ~0–1.4 % | 59.6 / 58.3 | 2.85 / 2.84 | **49.5 / 49.1** |
| S=1 **warm** (same-day baseline, 3 reps) | 100 % | 60.8 / 58.6 / 58.9 | 2.86–2.99 | 49.1–50.9 |
| S=8 **cold** (`dc_coldboot_s8`) | ~1 % | **125.8** | 2.86 | **172.5** |
| S=8 **warm** (baseline, 3 reps) | 100 % | 126.9 / 127.2 / 126.2 | 2.77–2.85 | 165.8–172.3 |

Cold = warm, within scatter in both directions. Second proof: py-spy on the
GPU worker during cold decodes (`data/pyspy-gpu-cold.json`):
**`wait_d2h` = 0.0 %** (warm: ~0.4 %), `_wait_done` 6.5 %, rest as usual
(`build_attn_metadata` 42 %, forward 34 %). The reporters' 25–30 ms block
does not exist even on a cold table.

### 2. I/O-throttling the table → no effect

`io.max` rbps on the container cgroup, 4 steps (decode reads only ~290 KB/s
new anyway): 16 M → 48.5 · 4 M → 52.1 · 2 M → 50.2 · **512 K** → 49.8 tok/s
(`data/dc_io_s1.jsonl`). No collapse — the fadvise-WILLNEED prefetch in the
PLE path fetches the ~64 rows/step (S=1, MTP3: 16 ids × 4 tokens, 1 PLE
layer) far enough ahead.

### 3. "Effectively cold" table (metadata cold, mincore=100 %) → no effect

Intermediate state: `randlat.py` measured 87.7 µs buffered read
(≈ NVMe instead of ~1.5 µs warm) while mincore still showed 100 % (cold
extent metadata): `dc_cold_s1` = 58.7 ms/step, **49.8 tok/s**.

### 4. Mechanism quantified (microbenchmark, `dc_gather_lat.py`)

On the guaranteed-cold copy, MADV_RANDOM mmap like the worker:
**512 serial pages = 25.75 ms ≈ exactly the reporters' `wait_d2h` window;
with fadvise batch prefetch = 2.06 ms.** Context: S=1 gathers only ~64
pages/step → even serial-cold ~3.4 ms; a 25 ms hit would need an S=8 gather
*and* serial faults. The prefetch is why our box does not collapse even when
cold.

### 5. Side finding: cache eviction is practically impossible on this box

Nothing moved the residency of the mapped file:
`posix_fadvise(DONTNEED)` (skips mapped pages), `drop_caches`,
`memory.reclaim` (EAGAIN after ~4 GiB), `process_madvise(MADV_PAGEOUT)`
(only the worker's ~2 GiB PTEs), a ~10 GiB memory balloon, io pressure.
Corollary: if the table really is being evicted on the reporters' machines,
a different kernel/cgroup path must be in play — which is why our repro used
the file swap instead.

## Fix attempt (kept as protection, not "the" fix)

Patch against `main` `6b50864`: env switch
`VLLM_PLE_TABLE_RESIDENT=auto|off|lock-required`; `auto`/`lock-required`
pins the table at worker start via `mlock` + sequential `pread` (instead of
fault-per-page), logs residency % and duration; prefetches get error logging;
plus a diagnostic tool (`mincore` residency, one command for reporters).

Measured on the patch itself: **mlock pinned the cold table to 100.0 %
resident in 131.5 s** (`data/start-fix-auto-cold.log`). Speed under the fix
was not measured (boot still running when the session ended) — but finding 1
makes the expectation certain: cold ≡ warm ⇒ the patch cannot add speed on
our box. It remains useful as protection + diagnosis — not as *the* #59 fix.

## What remains — the delta sits in the MTP path

Reporter (snowolf819) vs us, both from own measurements:

| quantity | reporter | us | Δ |
|---|---|---|---|
| MTP0 S=1, ms/step | ~43 (22.4–23.5 tok/s) | 37.9–40.1 (25.0–26.4 tok/s) | **only ~+4 ms** |
| MTP3 S=1, ms/step | ~109 (13.5–14.6 tok/s @ acc 1.52) | ~59–66 @ ~2.9–3.0 | **~+50 ms** |
| MTP3 acceptance (per-pos) | 0.338/0.099/0.085 → 1.52 (47k, ZH) | 0.81/0.61/0.44 → ~2.9 (EN) | language + ? |
| S=4 aggregate | 22.6 (no scaling, "globally serialized") | ~114–172 (scales) | ✗ |
| `wait_d2h` | ~25–30 ms/step | 0.0–0.4 % | symptom: their GPU work per step is slower |

- MTP0 differs by ~4 ms → their base forward/host path is almost our speed.
- The 2× collapse exists only with MTP on (verify+draft+acceptance path).
  `wait_d2h` waits on GPU work of the *previous* step → their GPU needs
  ~50 ms longer per MTP step; SM clock cap explains only ~4 %.
- Their `capture_sizes=[1,2,3,4]`: an S=4 verify batch is 4×(1+3)=16 > 4 →
  runs ungraphed → plausibly explains the missing S=4 scaling, **but not**
  S=1 (width 4 is captured → a different MTP cost block must sit there).
- Acceptance: ZH prose against a 47k en-code draft vocab naturally lowers
  acceptance (their zh-65k vocab gave only 1.74) — language alone explains
  neither 1.52 nor the step time.

## Next step (running, not yet posted)

Exact reporter config on a third node (fresh clone of `main`) + their two
extra conditions: `CUDAGRAPH_CAPTURE_SIZES=1,2,3,4` (FULL_DECODE_ONLY — the
reporter list had never been run) and a Chinese prose prompt. Measure S=1
and S=4: ms/step, tok/step, per-position acceptance. Discriminator: does it
reproduce the ~109 ms/step or the missing S=4 scaling — or does everything
stay in the normal band (→ their remaining delta is environment:
kernel/driver/DGX-OS, all unknown fields).

Reporter config (complete, from repcfg run + issue): `YARN=1`
(`YARN_MAX_MODEL_LEN=524288`), `KV_CACHE_DTYPE=auto`, `MAX_NUM_SEQS=4`,
`MAX_NUM_BATCHED_TOKENS=8192`, `MTP_NUM_SPECULATIVE_TOKENS=3`,
`HOST_RESERVE_GIB=26`, `PORT=8888`, `CUDAGRAPH_CAPTURE_SIZES=1,2,3,4` —
see `data/scripts/env-reporter.sh`.

## What would help (diagnostics asked of the reporters)

Boot-log lines `Capturing CUDA graphs (FULL): N/N` +
`cudagraph_capture_sizes`; /metrics deltas during decode
(`inter_token_latency_seconds`, `spec_decode_num_drafts/accepted_tokens`,
`spec_decode_num_accepted_tokens_per_pos`); the concrete prompt text
(language/length); py-spy speedscope of the GPU worker; `uname -r`, driver
version, DGX-OS build; pgmajfault/s + table residency (for completeness —
refuted here, unknown there).

## Receipts

`data/` — decode rows: `dc_coldboot_s1.jsonl`, `dc_coldboot_s8.jsonl`,
`dc_cold_s1.jsonl`, `dc_io_s1.jsonl`, `issue59-{s1,mtp0,repcfg}.jsonl`,
`base-resident.jsonl` (same-day warm baseline) · monitors:
`monitor.csv` (residency/majfault, 5 s), `dc_cold_memstat_{before,after}.txt`
· py-spy speedscopes: `pyspy-{gpu,ple}-{cold,resident,mtp0,repcfg,
worker-stock}.json` · boot logs (IPs redacted): `start-coldtable.log`,
`start-fix-auto-cold.log` (mlock 131.5 s → 100 %) · table metadata:
`cold_copy.packed_u8.json` (320,001,536 × 90 B, snapshot `925d7be6`) ·
scripts: `scripts/` (`dc_gather_lat.py`, `dc_residency.py`,
`residency{,-issue59}.py`, `randlat.py`, `waitd2h.py`, `analyze_pyspy.py`,
`memstat.sh`, `monitor.sh`, `run_stage.sh`, `env-reporter.sh`).

Verification note: every key figure above was re-checked against these raw
files on 2026-09-25 (cold S=1 49.48/49.1; cold S=8 125.76 ms/172.51 t/s vs
warm 126.90/127.20/126.23 ms → 171.49/172.31/165.82 t/s; residency 0.31 %
during the first cold decode, ≤1.51 % across the cold window; `wait_d2h`
0.00 %; io-throttle row 48.47/52.12/50.15/49.8). The only figure not backed
by a file is the gather microbenchmark (25.75/2.06 ms — stdout capture;
script + cold copy preserved, re-runnable any time).
