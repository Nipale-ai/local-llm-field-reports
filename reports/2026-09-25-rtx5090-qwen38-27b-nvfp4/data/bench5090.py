#!/usr/bin/env python3
"""Standalone decode/TTFT sweep for an OpenAI-compatible server (vLLM/TabbyAPI).

Mirrors repo-single bench/sweep.py methodology without sparkDash:
  * streams 1/2/4/8, prose + code prompts, 600 completion tokens, 3 reps
  * per-request decode tok/s from streaming chunk timestamps + usage counts
  * /metrics deltas per level (spec-decode acceptance, tok/step) when present
  * TTFT mode: fixed long prompts (~8k / ~32k), small max_tokens

Usage:
  bench5090.py sweep --port 8888 --streams 1 2 4 8 --prompts prose code \
      --repeats 3 --max-tokens 600 --tag STOCK --out out.jsonl
  bench5090.py ttft  --port 8888 --lens 8192 32768 --gen 32 --tag STOCK --out ttft.jsonl
"""
import argparse, json, re, sys, threading, time, urllib.request

PROSE = ("Write a long, detailed essay about the history of computing, "
         "covering mechanical calculators, vacuum tubes, transistors, "
         "integrated circuits, microprocessors, and modern accelerators. "
         "Be thorough and technical.")
CODE = ("Write a complete Python implementation of a threaded HTTP server "
        "with connection pooling, request routing, middleware support, "
        "WebSocket upgrade handling, graceful shutdown, and unit tests. "
        "Include type hints and docstrings.")

LINE = re.compile(r'^(vllm:[a-z_]+|[a-z_:]+)(\{[^}]*\})?\s+([0-9.eE+-]+)$')
COUNTERS = [
    "vllm:inter_token_latency_seconds_sum",
    "vllm:inter_token_latency_seconds_count",
    "vllm:spec_decode_num_drafts_total",
    "vllm:spec_decode_num_accepted_tokens_total",
    "vllm:spec_decode_num_draft_tokens_total",
    "vllm:generation_tokens_total",
]


def metrics_snapshot(port):
    out = {}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as r:
            for raw in r.read().decode().splitlines():
                m = LINE.match(raw)
                if not m:
                    continue
                name, labels, val = m.groups()
                if name in COUNTERS:
                    out[name] = out.get(name, 0.0) + float(val)
                elif name == "vllm:spec_decode_num_accepted_tokens_per_pos_total":
                    mm = re.search(r'position="(\d+)"', labels or "")
                    if mm:
                        out[f"pos{mm.group(1)}"] = out.get(f"pos{mm.group(1)}", 0.0) + float(val)
    except Exception:
        pass
    return out


def meminfo():
    d = {}
    for raw in open("/proc/meminfo"):
        k, v = raw.split(":")
        if k in ("MemAvailable", "MemFree"):
            d[k] = int(v.split()[0]) / 2**20
    return d


class MemMin(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.ev = threading.Event()
        self.avail = self.free = 1e9

    def run(self):
        while not self.ev.is_set():
            m = meminfo()
            self.avail = min(self.avail, m["MemAvailable"])
            self.free = min(self.free, m["MemFree"])
            self.ev.wait(1)


def vram_used_mib():
    import subprocess
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).strip()
        return float(out)
    except Exception:
        return None


def stream_request(port, model, prompt, max_tokens, result, idx):
    """One streaming /v1/completions request; fills result[idx]."""
    body = json.dumps({
        "model": model, "prompt": prompt, "max_tokens": max_tokens,
        "temperature": 0, "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    usage = {}
    n_chunks = 0
    finish = None
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            for raw in r:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices") or []:
                    txt = ch.get("text") or ""
                    if txt:
                        n_chunks += 1
                        if ttft is None:
                            ttft = time.time() - t0
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
        tend = time.time()
        comp = usage.get("completion_tokens")
        decode_s = tend - t0 - (ttft or 0)
        result[idx] = {
            "ok": True, "ttft_s": ttft, "wall_s": tend - t0,
            "completion_tokens": comp, "chunks": n_chunks,
            "finish": finish,
            "decode_tps": ((comp - 1) / decode_s) if comp and ttft is not None and decode_s > 0 else None,
        }
    except Exception as e:
        result[idx] = {"ok": False, "err": repr(e), "wall_s": time.time() - t0}


def get_model(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as r:
        return json.loads(r.read())["data"][0]["id"]


def run_level(port, model, streams, prompt, max_tokens):
    results = [None] * streams
    threads = []
    t0 = time.time()
    for i in range(streams):
        th = threading.Thread(target=stream_request,
                              args=(port, model, prompt, max_tokens, results, i))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    wall = time.time() - t0
    tot = sum(r["completion_tokens"] or 0 for r in results if r and r.get("ok"))
    return results, wall, tot


def cmd_sweep(a):
    model = get_model(a.port)
    print(f"model: {model}", file=sys.stderr)
    print(f"{'tag':<14}{'prompt':<7}{'S':>3}{'rep':>4}{'agg t/s':>9}{'per-stream':>26}"
          f"{'ttft ms':>9}{'tok/step':>9}{'wall s':>8}{'fail':>5}{'avail':>8}{'vram':>7}")
    order = list(a.streams)
    for rep in range(a.repeats):
        seq = order if rep % 2 == 0 else order[::-1]
        for s in seq:
            for pname in a.prompts:
                prompt = PROSE if pname == "prose" else CODE
                before = metrics_snapshot(a.port)
                mm = MemMin(); mm.start()
                vr0 = vram_used_mib()
                results, wall, tot = run_level(a.port, model, s, prompt, a.max_tokens)
                mm.ev.set()
                after = metrics_snapshot(a.port)
                d = {k: after.get(k, 0) - before.get(k, 0)
                     for k in set(before) | set(after)}
                drafts = d.get("vllm:spec_decode_num_drafts_total", 0)
                per = [round(r["decode_tps"], 1) for r in results if r and r.get("decode_tps")]
                fails = sum(1 for r in results if not (r and r.get("ok")))
                ttft = [r["ttft_s"] for r in results if r and r.get("ttft_s")]
                row = {
                    "tag": a.tag, "prompt": pname, "S": s, "rep": rep,
                    "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "agg_decode_tps": round(tot / max(wall - (min(ttft) if ttft else 0), 0.001), 2) if tot else None,
                    "per_stream_tps": per,
                    "ttft_ms": [round(x * 1000) for x in ttft],
                    "tok_per_step": 1 + d.get("vllm:spec_decode_num_accepted_tokens_total", 0) / drafts if drafts else None,
                    "per_pos_accept": [d.get(f"pos{i}", 0) / drafts if drafts else None for i in range(6)],
                    "gen_tokens_delta": d.get("vllm:generation_tokens_total"),
                    "itl_ms": d.get("vllm:inter_token_latency_seconds_sum", 0) / max(d.get("vllm:inter_token_latency_seconds_count", 1), 1) * 1000 if "vllm:inter_token_latency_seconds_sum" in d else None,
                    "wall_s": round(wall, 2), "streams_failed": fails,
                    "mem_avail_min_gib": round(mm.avail, 2),
                    "vram_mib": vr0,
                    "note": a.note,
                }
                with open(a.out, "a") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{a.tag:<14}{pname:<7}{s:>3}{rep:>4}{(row['agg_decode_tps'] or 0):>9.1f}"
                      f"{str(per):>26}{(max(ttft) * 1000 if ttft else 0):>9.0f}"
                      f"{(row['tok_per_step'] or 0):>9.2f}{wall:>8.1f}{fails:>5}"
                      f"{mm.avail:>8.1f}{(vr0 or 0):>7.0f}", flush=True)


def cmd_ttft(a):
    model = get_model(a.port)
    # build long prompts: repeat a sentence block to reach ~target tokens
    # rough heuristic: 1 token ~ 4 chars for english prose
    base = ("The history of computation spans mechanical calculators, vacuum tubes, "
            "transistors, integrated circuits, microprocessors, and parallel accelerators. ")
    for target in a.lens:
        prompt = base * int(target * 4 / len(base) + 1)
        for rep in range(a.repeats):
            res = [None]
            stream_request(a.port, model, prompt + "\n\nSummarize in one word:", a.gen, res, 0)
            r = res[0]
            row = {"tag": a.tag, "target_len": target, "rep": rep,
                   "ttft_s": r.get("ttft_s"), "wall_s": r.get("wall_s"),
                   "completion_tokens": r.get("completion_tokens"),
                   "ok": r.get("ok"), "err": r.get("err"),
                   "vram_mib": vram_used_mib()}
            with open(a.out, "a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"ttft tag={a.tag} len~{target} rep{rep}: "
                  f"ttft={((r.get('ttft_s') or 0) * 1000):.0f} ms "
                  f"wall={r.get('wall_s', 0):.1f} s ok={r.get('ok')}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sweep")
    p.add_argument("--port", type=int, default=8888)
    p.add_argument("--streams", type=int, nargs="+", default=[1, 2, 4, 8])
    p.add_argument("--prompts", nargs="+", default=["prose", "code"])
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=600)
    p.add_argument("--tag", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_sweep)
    t = sub.add_parser("ttft")
    t.add_argument("--port", type=int, default=8888)
    t.add_argument("--lens", type=int, nargs="+", default=[8192, 32768])
    t.add_argument("--gen", type=int, default=32)
    t.add_argument("--repeats", type=int, default=2)
    t.add_argument("--tag", required=True)
    t.add_argument("--out", required=True)
    t.set_defaults(fn=cmd_ttft)
    a = ap.parse_args()
    a.fn(a)
