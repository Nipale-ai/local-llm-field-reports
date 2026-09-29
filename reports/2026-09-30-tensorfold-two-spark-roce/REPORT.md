> **⚠️ AI-GENERATED, READ THIS FIRST.** The measurements in this report were run, and the report was written, by AI agents (Devin SWE-2 Max and Claude) working for Niklas Lenz, an independent creator. A human spot-checked the headline numbers against the raw files but did not review every line. Every finding carries a confidence label. One box per test, few repetitions, stock settings unless stated. Nothing here is an official TensorFold benchmark. If something looks wrong, the raw data is in `data/`; please open an issue.

# TensorFold on two DGX Sparks (TP=2): pin the RoCE device, about 2.2x over the Socket fallback

**Date:** 2026-09-29/30 · **Tool:** [TensorFold](https://github.com/ashhart/TensorFold) **0.3.5.1** (pinned, git 9db86058) · NCCL 2.30.7 · container `nvcr.io/nvidia/pytorch:26.07-py3`
**Hardware:** 2x DGX Spark (GB10) used as the TP=2 pair. Each Spark has two RoCE ports: one is cabled to the other Spark of the pair (192.168.100.x), the other goes to a third Spark that is not part of these runs (192.168.102.x on one box, 192.168.104.x on the other). Rank 1 started first, then rank 0 about 10 s later (as in the runbook).
**Not yet re-checked on 0.3.6.3 / 0.3.7 / 0.4.0** (related upstream issue: [#107](https://github.com/ashhart/TensorFold/issues/107), a hang on 0.3.6+ with Flash Next).

## Findings

| # | Finding | Confidence |
|---|---|---|
| 1 | With `--tp 2` and no device pin, NCCL picked `rocep1s0f0`, the port cabled to the third Spark (the two ranks' addresses on it are in different subnets, so the peer is unreachable), and the RoCE handshake failed: `Call to ibv_modify_qp failed with 110 Connection timed out, on dev rocep1s0f0:1, curr state INIT, next state RTR, local GID index 3, local GID ::ffff:192.168.102.1, remote GID ::ffff:192.168.104.1`. | **Confirmed** (`data/smoke-roce-fail-*`) |
| 2 | Pinning the device that carries the rank link fixes it: `NCCL_IB_HCA=rocep1s0f1 NCCL_SOCKET_IFNAME=enp1s0f1np1 NCCL_IB_GID_INDEX=3` (the link is 192.168.100.x). We did not test whether `NCCL_IB_GID_INDEX` is needed on its own. | **Confirmed** that this set works. Which variable matters: **untested** |
| 3 | Direct A/B on the same pair, same prompts, greedy, 128 tokens, three drafted and three serial requests per transport: **RoCE 61.2 tok/s drafted (24.6 serial) vs Socket 27.3 (12.3 serial)**, medians of three requests each, i.e. **2.2x drafted and 2.0x serial**. The first RoCE drafted request was slower (48.5), warm-up. Token hash identical in all twelve requests. | **Confirmed** (small sample, one pair) |
| 4 | Qwen3.8-27B + DFlash2, TP=2 over RoCE, the standard 4-cell benchmark (`tools/bench_openai.py`, 64-token replies, seeds 1234 to 1238, median): **81.9 / 69.9 / 79.8 / 71.4 tok/s** (code sampled / chat sampled / code greedy / chat greedy). | **Confirmed** as our measurement |
| 5 | Upstream's own table for two ranks (its docs label it *historical, not measurements of the merged 0.3.5 release*, not predictions for another runtime): 82.4 / 58.9 / 76.2 / 71.1. Ours is in the same range. This is **not** a reproduction claim, only a comparison. | Comparison only |
| 6 | GLM-5.3-Flash EXL3 (`Mia-AiLab/GLM-5.3-Flash-EXL3-TR3-4bpw`), TP=2, MTP only (the DFlash2 checkpoint is non-commercial): **32.1 / 28.4 / 37.8 / 31.4 tok/s**, about 107 GiB RAM used per Spark (`data/peak-glm-*.txt`). Different checkpoint and no DFlash2, so **do not compare with upstream's GLM numbers**. | **Own setup, no comparison** |

Memory (27B TP=2): startup estimate 56.61 GiB per rank, measured RAM used max 42.1 GiB (spark1) / 45.6 GiB (spark2), sampled every 2 s (`data/peak-qwen-*.txt`, values in MiB).

## Suggested documentation change

The runbook already says to set `NCCL_SOCKET_IFNAME` and `NCCL_IB_HCA` if automatic selection fails. What is missing is an example. The working line from finding 2 could be added to `RUNBOOK.md`.

## Reproduce (spark2 first, spark1 about 10 s later)

```
NCCL_IB_HCA=rocep1s0f1 NCCL_SOCKET_IFNAME=enp1s0f1np1 NCCL_IB_GID_INDEX=3 NCCL_IB_QPS_PER_CONNECTION=4
tensorfold serve Vontra/Qwen3.8-27B-MLX-4bit --drafter z-lab/Qwen3.8-27B-DFlash2 --tp 2 --rank 1 --master 192.168.100.1 --master-port 29551 --no-update-check   # spark2
tensorfold serve Vontra/Qwen3.8-27B-MLX-4bit --drafter z-lab/Qwen3.8-27B-DFlash2 --tp 2 --rank 0 --master 192.168.100.1 --master-port 29551 --no-update-check   # spark1
# Socket fallback for the A/B: NCCL_NET=Socket NCCL_IB_DISABLE=1
```

Raw data: [`data/`](data/) (serve logs per rank and transport, request rows with the engine block, `bench-tp2-*.json` with all seeds, `smoke-roce-fail-*` with the failing handshake).
