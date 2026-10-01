# Qwen3.8-27B-NVFP4 on RTX 5090 — first independent measurements + issues #1 / #3 / #10

**Date:** 2026-09-25 · **Recipes:** [`MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090`](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090), [`…-16gb-NVIDIA-GPUs-one-click-install`](https://github.com/MiaAI-Lab/Qwen3.8-27B-16gb-NVIDIA-GPUs-one-click-install) · **Raw data:** [`data/`](data/)

**Host:** 1× RTX 5090 (32,607 MiB, driver 610.43.02, CUDA 13.3 UMD), Ryzen 9
9950X (16c/32t), 91 GiB RAM + 93 GiB swap, Debian 13 (kernel 6.12.95).
GPU idle before the runs, unrelated containers untouched.

## TL;DR

1. **Issue [#1](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/1)
   (JIT build OOM) quantitatively explained:** the `gemm_sm120` FlashInfer
   build (28 `.cu` objects) pulls **80.2 GiB compiler RSS** unbounded
   (`ninja -j34`) — a guaranteed exit-137 on the reporter's 59 GiB box.
   `MAX_JOBS=4` drops the peak to **30.6 GiB**. Bonus finding: the current
   recipe version only triggers this build when a CUDA toolkit ≥ 12.9 is on
   PATH — without `nvcc`, FlashInfer uses AOT kernels.
2. **README's "~160 tok/s" not reproduced:** stock recipe (262k ctx,
   TurboQuant-4bit KV 5.5 GiB, MTP-3, `max-num-seqs 1`) gives **104 t/s prose /
   118 t/s code** single-stream — clean, reproducible, MTP acceptance
   2.5–2.8 tok/step. The 24 GB simulation is even faster (117/124 t/s).
3. **Issue [#3](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/3)
   (5090D v2 / 24 GB): runs — but `gpu_memory_utilization` alone does
   nothing.** `--kv-cache-memory-bytes` overrides it. Fitting config:
   KV 2.0 GiB + ctx ≤ 80,896 → **24,372 MiB** (~200 MiB under 24 GiB), stable,
   117/124 t/s. Honesty note: simulated on a 32 GB card — the real D v2 has
   less memory bandwidth and must host the desktop in the same ~24 GiB.
4. **Issue [#10](https://github.com/MiaAI-Lab/Qwen3.8-27B-16gb-NVIDIA-GPUs-one-click-install/issues/10)
   (EXL3 "only 50–150 t/s"): not an engine limit.** Same recipe (4.0 bpw,
   262k, reporter methodology) gives **~130 t/s per stream, stable to c=4 →
   518–547 t/s aggregate**, no drop across context depths 0/4k/8k. The
   reporter's c4 collapse to ~35 t/s is a local problem, not the engine's
   ceiling.

## Issue #1 — JIT build peak RAM & MAX_JOBS

Build: `flashinfer` SM120 GEMM module, 28 `.cu` objects, ninja + nvcc.
Sampler at 1 Hz: summed RSS of all ninja/nvcc/cicc/ptxas processes +
`MemAvailable`. Duration = ninja `real` time for the compile phase (the
~7 MB `.so` was linked separately).

| parallelism | peak compiler RSS | min MemAvailable | peak procs | duration |
|---|---:|---:|---:|---:|
| unbounded (`-j34` = nproc+2 on 32 threads) | **80.2 GiB** | 8.4 GiB | 47 | 85.7 s |
| `MAX_JOBS=8` | **45.7 GiB** | 42.0 GiB | 13 | 122.4 s |
| `MAX_JOBS=4` | **30.6 GiB** | 57.6 GiB | 9 | 201.9 s |

~1.7–5.7 GiB per compile job (burst-dependent, cicc/ptxas children counted).

**Reporter explanation:** 16-core box, 59 GiB RAM — unbounded ninja takes
`-j18` (nproc+2), interpolated ~35–50 GiB compiler RSS → OOM kill 137.
Consistent with `MAX_JOBS=4` as the working workaround.

**Recommendation (posted to #1):**

- ≤ 64 GiB RAM: `MAX_JOBS=4` (measured 30.6 GiB peak, build ~3.4 min)
- ≥ 96 GiB: `MAX_JOBS=8` (45.7 GiB, ~2 min)
- rule of thumb: `MAX_JOBS ≈ RAM_GiB / 8`
- the current recipe only JIT-compiles when a CUDA toolkit ≥ 12.9 is on PATH
  — so the OOM hits only users who have one; a prophylactic `MAX_JOBS` note
  in the README would cover them.

Receipts: `data/jitwatch-j{4,8,34}.csv`, `data/ninja-j{4,8,34}.log`,
`data/build-j34.log`, `data/memmon-*.csv`, `data/build_gemm120.py`,
`data/jitwatch.sh`.

## Decode measurements

Methodology mirrors `bench/sweep.py`: OpenAI-compatible requests, prose +
code prompt sets, 600 generated tokens, n = 3, client-measured tok/s.

### Stock recipe (262,144 ctx, TQ-4bit KV 5.5 GiB, MTP-3, `max-num-seqs 1`)

| streams | prose agg | code agg | tok/step | VRAM |
|---:|---:|---:|---:|---:|
| 1 | 103.9–104.2 t/s | 118.1–118.3 t/s | 2.49 / 2.83 | 28,870 MiB |

TTFT: 7,892 prompt tokens **1.04–1.06 s** · 31,490 **5.57–5.58 s** ·
62,945 ~15.1 s · 125,882 ~46.2 s · small prompts ~35–44 ms.

**README ~160 t/s not reached** (factor ~0.7). Possible deltas: acceptance
rate, measurement basis, driver/toolkit revision, different build. No defect
detected — output is clean (garble spot-checks). Left as an open "measured
on" question in the posted report.

### Concurrency variant (32,768 ctx, MTP-1, `max-num-seqs 8`, KV unchanged)

The stock profile serializes at 1 seq (README flags MTP-3 + concurrency as
unstable), so the multi-stream cells were measured on this separate profile.

| streams | prose agg | code agg | per stream | fails |
|---:|---:|---:|---:|---:|
| 1 | 86.5–87.2 | 88.3–88.7 | ~87–89 | 0 |
| 2 | 163.0–169.7 | 174.4–175.5 | ~84–89 | 0 |
| 4 | 340.5–341.5 | 361.3–363.6 | ~85–92 | 0 |
| 8 | 649.2–654.5 | 682.4–689.7 | ~81–87 | 0 |

Near-linear scaling, MTP-1 acceptance ~1.73–1.85 tok/step even at batch 8 —
the engine holds up under batch; the 1-seq default is a stability guard, not
a hardware limit.

Receipts: `data/sweep-stock.jsonl`, `data/sweep-conc8-mtp1.jsonl`,
`data/ttft-stock.jsonl`, `data/ttft-stock-corrected.txt`,
`data/bench5090.py`, `data/ttft_probe.py`, `data/serve-conc.sh`,
`data/serve-conc8-mtp1.log`.

## Issue #3 — 24 GB simulation ("5090D v2")

- `GPU_UTIL=0.73` alone does **nothing**: `kv_cache_memory_bytes` takes
  precedence (vLLM log: *"does not respect the gpu_memory_utilization
  config"*) → still 28.2 GiB (28,870 MiB). Receipt: `data/vllm-24g-gpuutil073.log`.
- Minimal KV pool per context: vLLM computes exactly — 262,144 needs
  ≥ 5.02 GiB; 81,920 needs ≥ 2.02 GiB → chosen **2.0 GiB + 80,896 tokens**.
- Result profile: **24,372 MiB VRAM** (≈23.8 GiB, ~200 MiB headroom vs a
  24 GiB card), MTP-3, seqs 1. Receipts: `data/sweep-sim24g.jsonl`,
  `data/serve-24g.sh`, `data/serve-24g-kv2g.log`.
- Decode: prose 117.0–117.2 · code 123.2–124.7 t/s (**faster** than stock —
  smaller KV pool means less attention work). TTFT 8k 1.06–1.10 s,
  32k 5.53–5.58 s — identical to stock.
- Honesty label: simulation on a 32 GB card; the real 5090D v2 has less
  memory bandwidth → real decode presumably lower, and the desktop must
  live in the same ~24 GiB.

## Issue #10 — EXL3 engine (one-click) vs reporter

Setup: `linux/setup.sh` (via `bash` — it is not executable), profile identical
to the reporter's: `qwen3.8-27b-exl3-4.0bpw`, 262,144 ctx, int4 KV, budget
22.8 GB → VRAM 20,842 to 22,350 MiB (failed requests at 20,566 left out). Endpoint only `/v1/chat/completions`
(+streaming). Reporter methodology: depth 0 / 4,096 / 8,192 prompt tokens ×
concurrency 1/2/4 × 128 output tokens × 3 reps.

| depth | c=1 | c=2 agg | c=4 agg | per stream |
|---:|---:|---:|---:|---:|
| 0 | 128.9–135.5 | 259.4–262.6 | 518.0–523.7 | ~128–134 |
| 4,096 | 129.1–137.9 | ~263–266 | ~528–532 | ~128–138 |
| 8,192 | 126.8–138.0 | 270.5–273.3 | 518.4–546.6 | ~129–141 |

TTFT: warm ~0.15–0.25 s (c1), ~1.2 s (c2), ~3.4–3.5 s (c4); cold 3.6 s.
Zero failures, no drop with depth or concurrency — **the engine can do more
than "50–150 t/s".** The reporter's d0/c1 (~121 t/s) matches our ~130; their
c4 collapse does not reproduce here → local config/host problem.
Cross-check: NVFP4 stock 104–118 t/s single-stream vs EXL3 ~130. EXL3 is ahead
per stream and at 4 streams. I did not measure EXL3 at 8 streams.

Receipts: `data/sweep-exl3.jsonl` (first 27 rows = failed
`/v1/completions` attempt, valid from row 28), `data/exl3_bench.py`,
`data/simplex-start.log`.

## Install stumbling blocks (feedback for the recipe)

- `start.sh` works as documented; model ~20 GiB to
  `~/models/RadixArk/Qwen3.8-27B-NVFP4`.
- **No JIT build on start** with empty `~/.cache/vllm` + `~/.cache/flashinfer`:
  FlashInfer 0.6.16.post3 uses AOT kernels, vLLM 0.27.1 compiles via Inductor
  — cold ~50 s total, warm ~4 s, init engine 86 s, host RAM +~5.8 GiB,
  zero ninja/nvcc processes.
- The JIT path (`gen_gemm_sm120_module()`) aborts immediately with *"SM 12.x
  requires CUDA >= 12.9"* when no `nvcc` is on PATH. With the venv's cu13 nvcc
  exported, the build starts but fails on a CCCL version mismatch unless
  `CCCL_DISABLE_CTK_COMPATIBILITY_CHECK` is set; linking needs
  `LIBRARY_PATH` at `nvidia/cu13/lib`. The cleaner repro path would be
  `CUDA_HOME` at the pip `nvidia-cuda-nvcc-cu12` 12.9.86 — untested, noted
  as an alternative in the posted comment.
- No GNU `time` on this box — durations via shell `time`, RSS peaks via a
  1 Hz sampler.
- `pkill -f` patterns can match your own ssh command line (self-kill) —
  PID-based stopping needed.

## Limitations

- RAM peaks from 1 Hz sampling — sub-second spikes possible.
- j8/j4 builds stopped at the same link error after the compile phase;
  peaks/durations for the compile phase are valid, `.so` linked separately.
- The cold-start measurement covered the vLLM/Inductor pipeline, not the
  reporter's ninja path (which does not trigger in this recipe version
  without a CUDA toolkit).
- 24 GB figure = config simulation, not real 5090D-v2 silicon.
- EXL3 measured 128 output tokens vs NVFP4's 600 — decode rate is constant
  over length, but the TTFT share differs; stream-level comparison is fair.

## Status

Posted as issues/comments on 2026-09-25: RTX-5090 repo
[#1](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/1),
[#3](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/3),
[#4](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/4)
(this report, condensed) and 16 GB repo
[#10](https://github.com/MiaAI-Lab/Qwen3.8-27B-16gb-NVIDIA-GPUs-one-click-install/issues/10).
