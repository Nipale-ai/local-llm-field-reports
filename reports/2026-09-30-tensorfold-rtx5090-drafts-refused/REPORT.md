> **⚠️ AI-GENERATED, READ THIS FIRST.** The measurements in this report were run, and the report was written, by AI agents (Devin SWE-2 Max and Claude) working for Niklas Lenz, an independent creator. A human spot-checked the headline numbers against the raw files but did not review every line. Every finding carries a confidence label. One box per test, few repetitions, stock settings unless stated. Nothing here is an official TensorFold benchmark. If something looks wrong, the raw data is in `data/`; please open an issue.

# TensorFold on an RTX 5090: 27B + DFlash2 is refused at startup, although it fits

**Date:** 2026-09-29/30 · **Tool:** [TensorFold](https://github.com/ashhart/TensorFold) 0.3.7 (MIT, by Ash Hart) · **Upstream issue:** [ashhart/TensorFold#112](https://github.com/ashhart/TensorFold/issues/112)
**Hardware:** RTX 5090 (32 GB, one GPU, not integrated memory), 86 GiB host RAM available · container `nvcr.io/nvidia/pytorch:26.07-py3`, `TORCH_CUDA_ARCH_LIST=12.0`
**Model:** `Vontra/Qwen3.8-27B-MLX-4bit` + drafter `z-lab/Qwen3.8-27B-DFlash2` (speculative decoding: the small drafter proposes tokens, the 27B verifies them)

## Findings

| # | Finding | Confidence |
|---|---|---|
| 1 | With the drafter, `tensorfold serve` refuses to start: `estimated largest fitting prompt-plus-reply window: 0 tokens`. Same at default window, `--context 8192` and `--context 4096`. | **Confirmed** (verbatim logs in `data/`) |
| 2 | The startup budget check adds weights (model + drafter) **21.93 GiB** and a loading buffer ("staging") **7.27 GiB** = **29.20 GiB**, against a budget of **26.90 GiB**. So it refuses. Numbers come from wrapping `make_plan`; nothing was allocated. | **Confirmed** (inputs logged in issue #112) |
| 3 | The real GPU memory peak while loading with drafts is **16,967 MiB (16.6 GiB)**, far under the budget. | **Confirmed** (`data/version-peak.txt`, measured only with the local test patch in finding 5) |
| 4 | Without the drafter (`--no-drafts`) the same model starts and runs at **about 75 tok/s** with a 32,768-token window. | **Confirmed** (4 benchmark cells 74.3 / 74.2 / 75.3 / 75.3) |
| 5 | With a one-line **local test patch** (in the container only, reverted afterwards, nothing pushed) that skips this check, drafts work: **210 tok/s** vs **75 tok/s** serial on the same 187-token request, identical token hash `08bb548b35ae` (2.8x). Window only **4,096** tokens. | **Measured, small sample.** Two methods disagree, see below. |

## What we tried, in order (all outputs verbatim in `data/`)

| # | Command (all `tensorfold serve ...`) | Result | Runs? |
|---|---|---|---|
| 1 | 27B + DFlash2 | `... 0 tokens` | no |
| 2 | 27B `--no-drafts` | `startup estimate 26.40 GiB within 26.90 GiB; window 32768` | yes |
| 3 | 27B + DFlash2, `TENSORFOLD_MEMORY_LIMIT_GB=31` | same `0 tokens` (the variable only takes effect in the MLX path, per Devin's reading of `server/memory_budget.py`) | no |
| 4 | 27B + DFlash2, `--prompt-cache-gib 0 --context 2048` | `0 tokens` | no |
| 5 | 27B + DFlash2, `--parallel 1 --context 2048` | `0 tokens` | no |
| 6 | EXL3 3.00bpw + DFlash2 | `0 tokens` | no |
| 7 | EXL3 3.00bpw `--no-drafts` | `estimate 24.10 GiB within 26.90 GiB; window 32768` | yes |
| 8 | `nvidia/Qwen3.8-27B-NVFP4` (auto drafter) | `0 tokens` | no |
| 9 | NVFP4 `--no-drafts` | `estimate 26.45 GiB within 26.90 GiB; window 16384` | yes |
| 10 | 27B + DFlash2 with the local test patch | `estimate 29.21 GiB within 26.87 GiB; allocated window 4096; drafts on` | yes |

## Speed without drafts (official path, `tools/bench_openai.py` standard: 64-token replies, seeds 1234 to 1238, median)

| Checkpoint | Window | code sampled | chat sampled | code greedy | chat greedy |
|---|---:|---:|---:|---:|---:|
| `Vontra/Qwen3.8-27B-MLX-4bit` | 32,768 | 74.29 | 74.18 | 75.34 | 75.25 |
| `turboderp/Qwen3.8-27B-exl3` 3.00bpw | 32,768 | 43.60 | 43.49 | 44.37 | 44.06 |
| `nvidia/Qwen3.8-27B-NVFP4` | 16,384 | 63.56 | 63.42 | 64.37 | 64.34 |

GPU memory was recorded only for the patched drafted run (16,967 MiB, finding 3). The estimates in the attempts table are the tool's own numbers, not measurements.

## With the local test patch (NOT official, 4,096-token window)

- `bench_openai.py` 4 cells (stream-measured): 286.5 / 246.2 / 270.4 / 252.6 tok/s.
- Engine-internal `decode_s` on a 187-token request: **210.3 tok/s** drafted (second run 209.7) vs **75.0 tok/s** serial, same token hash.
- **The two methods disagree (about 210 vs 250 to 286).** The gap is not explained yet: different token counts and timing scope. Public posts use the lower, engine-internal number.
- The first drafted 64-token request measured only 36.2 tok/s (the agent's explanation is warm-up of the draft graphs; not verified separately). The 210 figure is after warm-up.
- Exactness: drafted and serial replies have identical token hashes in every pair we ran (`data/sysa-out.jsonl`).

## What is open

- Which part of the estimate is too high: the staging term (`3 x` the largest layer tensor), or the drafter counted at 4 bytes per value (reading of `capacity.py`)? Not isolated by us yet.
- How large a window the patched configuration can reach. Untested: `--ram-tier-gib` from PR #106.
- Re-check on TensorFold 0.4.0.

## Reproduce

```
docker run ... nvcr.io/nvidia/pytorch:26.07-py3   # RTX 5090, --gpus all
tensorfold serve Vontra/Qwen3.8-27B-MLX-4bit --drafter z-lab/Qwen3.8-27B-DFlash2 --no-update-check   # refused
tensorfold serve Vontra/Qwen3.8-27B-MLX-4bit --no-drafts --no-update-check                            # runs, ~75 tok/s
```

Raw data: [`data/`](data/) (serve logs per attempt, `sysa-out.jsonl` with every request and the engine block, `bench-sysa-*.json` with all seeds).
