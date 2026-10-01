> **⚠️ AI-GENERATED, READ THIS FIRST.** The measurements in this report were run, and the report was written, by AI agents (Devin SWE-2 Max and Claude) working for Niklas Lenz, an independent creator. A human spot-checked the headline numbers against the raw files but did not review every line. Every finding carries a confidence label. One box per test, few repetitions, stock settings unless stated. Nothing here is an official TensorFold benchmark. If something looks wrong, the raw data is in `data/`; please open an issue.

# TensorFold issue #98: an identical resend is re-prefilled on Flash Next, resumed on the 27B

**Date:** 2026-09-30 · **Tool:** [TensorFold](https://github.com/ashhart/TensorFold) 0.3.7 and 0.4.0 · **Upstream issue:** [ashhart/TensorFold#98](https://github.com/ashhart/TensorFold/issues/98)
**Hardware:** one DGX Spark (GB10), container `nvcr.io/nvidia/pytorch:26.07-py3` · default `tensorfold serve` (no cache flags) · temperature 0, 32 output tokens, one request at a time.

The same **11,053-token** prompt was sent three times in a row.

| Model | run 1 prefill | run 2 prefill | run 3 prefill | tokens served from cache (run 2 / 3) |
|---|---:|---:|---:|---|
| `Vontra/Qwen3.8-Flash-Next-MLX-4bit-MTP` | 4.74 s | 4.57 s | 4.56 s | **0 / 0** |
| `Vontra/Qwen3.8-27B-MLX-4bit` + DFlash2 | 7.32 s | 0.11 s | 0.11 s | **11,048 / 11,052** |

Token hashes are identical across the three runs on both models.

### Same test on TensorFold 0.4.0 (pip release)

| Model | prefill run 1 / 2 / 3 | `cached` run 2 / 3 |
|---|---|---|
| `Vontra/Qwen3.8-Flash-Next-MLX-4bit-MTP` | 4.89 / 5.96 / 5.86 s | 0 / 0 |
| `Vontra/Qwen3.8-27B-MLX-4bit` + DFlash2 | 6.96 / 0.11 / 0.11 s | 11,048 / 11,052 |

Same behavior as 0.3.7. Raw rows: `data/results-v040.jsonl`. `main` is 0.5.0 now and was not run.

**Confidence: confirmed** for these two models on this box with default settings (raw rows in `data/`). Not tested: GLM-5.3-Flash and Qwen3.6. Correction: the Qwen3.6 MoE engine also keeps prefixes at message boundaries, so my earlier note on it was incomplete. I have not measured either family.

## Why (my reading of the code on `main`, commit 9cd52ab = 0.5.0; not tested as a fix)

- The 0.3.6.3 changelog says: "the 27B keeps its prompt cache entry one token before the prompt's end, so the next chat turn resumes from it (#65)". In `families/qwen3_5/cuda/engine.py` that is `entry_end`, so a resend is a strict prefix of a cached entry and resumes.
- On Flash Next, `_decode` remembers the **full** prompt (`families/qwen4_exp/cuda/engine.py`, `self._remember(list(prompt), ...)`) and `_resume` requires `len(ids) < len(prompt)`, so an identical prompt can never hit.
- A possible fix, **not tested by me:** keep the Flash Next entry at `len(prompt) - 1`, like the 27B.

## Raw data

[`data/`](data/): `results-fn98.jsonl` (Flash Next, three requests with the engine block, `cached` is 0 each time), `results-prefill-27b.jsonl` (27B), `serve-*.log`.
