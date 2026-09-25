# local-llm-field-reports

Independent, reproducible measurements of public local-LLM recipes, run on my
own hardware. Each report contains the full numbers — including every variant
that did **not** work — plus the raw JSONL/log receipts the numbers were taken
from, so every figure can be re-checked against the data.

**Hardware lab:** 3× NVIDIA DGX Spark (GB10, 128 GB unified memory) ·
1× RTX 5090 (32 GB) workstation.

## Why this exists

Recipes for running large models locally spread fast, and published numbers
are hard to compare — different prompts, different client vs. engine-side
timing, different machines. AI agents working for me re-measure public recipes under one consistent
methodology, and the results go back to the upstream projects
([MiaAI-Lab](https://github.com/MiaAI-Lab) recipes mostly, so far). This repo
is the durable home for the full data behind those comments.

## Methodology

- Decode throughput is measured **client-side** over the OpenAI-compatible
  endpoint: aggregate tok/s across S = 1/2/4/8 concurrent streams, prose and
  code prompt sets, ~600 generated tokens per request, n = 3 repeats per cell
  (mean with min–max reported).
- Engine-side per-step latency (`ms/step`) and MTP acceptance (`tok/step`)
  are recorded alongside; both appear in the raw rows.
- Every claimed number is backed by a `data/` folder in the same report
  directory — JSONL sweep rows, py-spy profiles, monitors, boot logs.
- Fresh clones, stock `.env` unless stated; every deviation from the recipe
  default is listed explicitly.
- Tools used are in [`tools/`](tools/) — the same scripts that produced these
  tables.

## Reports

| Report | Recipe under test | Result in one sentence |
|---|---|---|
| [2026-09-25 Qwen3.8-Flash-Next, single DGX Spark](reports/2026-09-25-qwen38-flash-next-single-spark/REPORT.md) | `MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark` | Stock recipe reproduces the published numbers; best config (MTP k=6 + BF16 KV + FP8 draft head) reaches **83.7 tok/s code single-stream, +42 % over stock** — verified on two nodes, 21 variant runs incl. all losers documented. |
| [2026-09-25 Qwen3.8-27B-NVFP4 on RTX 5090](reports/2026-09-25-rtx5090-qwen38-27b-nvfp4/REPORT.md) | `MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090` + `…-16gb-NVIDIA-GPUs-one-click-install` | First external data point: 104/118 t/s stock single-stream (README's ~160 not reproduced), ~650–690 t/s aggregate at 8 streams, working 24 GB config found, and the issue #1 build-OOM quantitatively explained (80.2 GiB compiler RSS unbounded → 30.6 GiB at `MAX_JOBS=4`). |
| [2026-09-25 Issue #59: cold PLE table test](reports/2026-09-25-issue59-cold-ple-table/REPORT.md) | same single-Spark recipe | The "PLE table falls out of page cache → 13–23 tok/s" hypothesis is **refuted on our box**: a verifiably cold (0 % resident) 26.8 GiB table decodes at the same ~49–50 tok/s as warm; the remaining reporter delta sits in the MTP path. |

## Where the results were posted

| Where | What | Link |
|---|---|---|
| PR #70 (usmaneth): k=6 MTP guard | Independent measurement: k=6 + BF16 KV → +20–28 % code; later answered the author's k-schedule test request | [link](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/pull/70) — **merged to main via #72** |
| Issue #59: slow single-stream decode | Fresh-install baseline: 49.8 prose / 58.8 code tok/s — not in the reporters' 13–28 band | [link](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/59) |
| Issue #53: fresh-install start crash | Tested all three fix PRs (#55, #56, #65) — all work; #65 landed via #72 | [link](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/53) |
| Issue #19: throughput ceiling | S-sweep data: aggregate does not flatline at 4 streams; `MAX_NUM_SEQS` is not a throughput lever below the cap | [link](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/19) |
| RTX-5090 recipe: issues #1, #3, #4 | JIT build RAM peaks quantified; 24 GB config found; full measurement report | [#1](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/1) · [#3](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/3) · [#4](https://github.com/MiaAI-Lab/Qwen3.8-27B-NVFP4-RTX-5090/issues/4) |
| 16 GB one-click repo: issue #10 | EXL3 engine is not the limit: ~130 t/s/stream stable to c=4 → reporter's c4 drop is local | [link](https://github.com/MiaAI-Lab/Qwen3.8-27B-16gb-NVIDIA-GPUs-one-click-install/issues/10) |
| sparkDash PR #113: CRLF SSE parsing | Bug reproduced on `main` (0 tokens), fix verified incl. split-delimiter case; harness in [`tools/`](tools/) | [link](https://github.com/MiaAI-Lab/sparkDash/pull/113) |
| Raw-data gist | All sweep JSONL for the posted PR #70 / #19 numbers | [gist](https://gist.github.com/Nipale-ai/e492c7d1e4830183c84e314c83e4d5e3) |

### In progress (measured or measuring, not yet posted)

- [PR #31](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/pull/31)
  (rwl4): FP8 draft head — the +42 % config above; maintainer-requested merge
  checks running.
- [Issue #48](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/48):
  model aborts agent tasks mid-run — first reproduction succeeded, frequency
  and trigger under measurement.
- [Issue #59](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/59)
  follow-up: exact reporter config (YaRN 512k, capture `[1,2,3,4]`, zh prompt)
  on a third node.
- [Dual-spark recipe](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks/pull/67):
  first real end-to-end boot of PR #67 plus measurement.
- [Issue #11](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark/issues/11):
  own fix for `EXTRA_VLLM_ARGS` quoting — all 5 test cases green
  ([issue11-test.sh](tools/issue11-test.sh)); PR drafted, needs a fork.

## Tools

- [`tools/ab_lauf.sh`](tools/ab_lauf.sh) — drive one full A/B run on a remote
  node: rebuild `.env`, restart the recipe, wait, sweep, fetch results.
- [`tools/auswerten.py`](tools/auswerten.py) — turn `sweep-*.jsonl` files into
  the Markdown comparison table used in these reports.
- [`tools/fake_sse_server.py`](tools/fake_sse_server.py) +
  [`tools/bench_crlf.mjs`](tools/bench_crlf.mjs) — loopback OpenAI-SSE server
  with LF/CRLF/mixed/split framing + driver for sparkDash's real
  `DecodeBenchManager` (built to verify sparkDash PR #113).
- [`tools/issue11-test.sh`](tools/issue11-test.sh) — docker-free argv test for
  the `EXTRA_VLLM_ARGS` quoting fix (issue #11): replays both parse stages of
  `start.sh` with a stubbed `docker`.

## Credits

The recipes, issues and PRs being measured belong to
[Mia / MiaAI-Lab](https://github.com/MiaAI-Lab). Thanks to
[@usmaneth](https://github.com/usmaneth) (PR #70, k=6 guard),
[@rwl4](https://github.com/rwl4) (PR #31, FP8 draft head + GDN backend) and
[@jvr0x](https://github.com/jvr0x) (MiaAI-Lab team) — and to the issue
reporters whose measurements motivated these runs.

## Transparency

All measurements were run by AI agents working for me — Claude Code as
orchestrator and [Devin](https://devin.ai) (SWE-2 Max) as the executing
agent — on my own hardware. They ran the benches, parsed the logs and drafted
the reports and comments; **every published number was checked against the
raw receipts in `data/` before it went out.** The same note was added under
all earlier GitHub posts.

## License

- **Code** (everything under `tools/` and all scripts): MIT.
- **Reports, data and text** (everything else): CC BY 4.0 — share and adapt
  with attribution.

See [LICENSE](LICENSE).
