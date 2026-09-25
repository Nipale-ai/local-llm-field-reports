import sys, json, time, threading, urllib.request
sys.path.insert(0, "/home/user/mia-bench/rtx5090")
from bench5090 import get_model, vram_used_mib

PORT = 8888
FILLER = ("The history of computation spans mechanical calculators, vacuum tubes, "
          "transistors, integrated circuits, microprocessors, and parallel accelerators. ")
ASK = "\n\nWrite a detailed technical essay about GPU memory hierarchies, cache levels, and bandwidth trade-offs. Be thorough."


def chat_request(port, model, prompt, max_tokens, result, idx):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0, "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    usage = {}
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
                    delta = ch.get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content"):
                        if ttft is None:
                            ttft = time.time() - t0
        tend = time.time()
        comp = usage.get("completion_tokens")
        decode_s = tend - t0 - (ttft or 0)
        result[idx] = {
            "ok": True, "ttft_s": ttft, "wall_s": tend - t0,
            "completion_tokens": comp,
            "prompt_tokens": usage.get("prompt_tokens"),
            "decode_tps": ((comp - 1) / decode_s) if comp and ttft is not None and decode_s > 0 else None,
        }
    except Exception as e:
        result[idx] = {"ok": False, "err": repr(e), "wall_s": time.time() - t0}


def run(port, model, prompt, streams, max_tokens):
    results = [None] * streams
    threads = [threading.Thread(target=chat_request,
                                args=(port, model, prompt, max_tokens, results, i))
             for i in range(streams)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    wall = time.time() - t0
    tot = sum(r["completion_tokens"] or 0 for r in results if r and r.get("ok"))
    return results, wall, tot


model = get_model(PORT)
print("model:", model, file=sys.stderr)
out = open("/home/user/mia-bench/rtx5090/sweep-exl3.jsonl", "a")
for depth, reps_fill in ((0, 0), (4096, 146), (8192, 291)):
    prompt = FILLER * reps_fill + ASK
    for c in (1, 2, 4):
        for rep in range(3):
            results, wall, tot = run(PORT, model, prompt, c, 128)
            ttfts = [r["ttft_s"] for r in results if r and r.get("ttft_s")]
            pers = [r["decode_tps"] for r in results if r and r.get("decode_tps")]
            fails = sum(1 for r in results if not (r and r.get("ok")))
            ptoks = [r.get("prompt_tokens") for r in results if r and r.get("ok")]
            row = {"engine": "exl3-4.0bpw", "depth": depth, "c": c, "rep": rep,
                   "agg_decode_tps": round(sum(pers), 1) if pers else 0,
                   "per_stream": [round(x, 1) for x in pers],
                   "ttft_s_max": max(ttfts) if ttfts else None,
                   "prompt_tokens": ptoks[:1],
                   "fails": fails, "vram": vram_used_mib()}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"depth={depth} c={c} rep={rep}: agg={row['agg_decode_tps']} "
                  f"per={row['per_stream']} ttft={round((row['ttft_s_max'] or 0)*1000)}ms "
                  f"ptok={ptoks[:1]} fails={fails}", flush=True)
out.close()
