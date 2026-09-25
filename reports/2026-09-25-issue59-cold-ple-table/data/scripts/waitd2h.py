#!/usr/bin/env python3
"""Speedscope-JSON auswerten: Gewichts-Anteil der Samples, deren Stack einen
Frame mit gesuchtem Namen enthaelt.

Aufruf: waitd2h.py <speedscope.json> [name1 name2 ...]
Default-Ziele: wait_d2h _wait_done prepare_forward forward_impl
"""
import json
import sys

path = sys.argv[1]
targets = sys.argv[2:] or ["wait_d2h", "_wait_done", "prepare_forward",
                           "forward_impl", "_ple_prefetch_rows",
                           "index_select", "synchronize", "busy_loop",
                           "_handle_requests"]

d = json.load(open(path))
frames = d["shared"]["frames"]

def fname(i):
    f = frames[i]
    n = f.get("name", "")
    fl = f.get("file", "")
    ln = f.get("line", "")
    return f"{n} ({fl}:{ln})" if fl else n

tot = 0.0
hit = {t: 0.0 for t in targets}
hit_stacks = {}
for prof in d.get("profiles", []):
    if prof.get("type") != "sampled":
        continue
    weights = prof.get("weights") or [1.0] * len(prof["samples"])
    for stack, w in zip(prof["samples"], weights):
        tot += w
        names = [frames[i].get("name", "") for i in stack]
        full = [fname(i) for i in stack]
        for t in targets:
            if any(t in n for n in names):
                hit[t] += w
        # Top-Stacks mit wait_d2h
        if any("wait_d2h" in n for n in names):
            key = " <- ".join(full[-4:])
            hit_stacks[key] = hit_stacks.get(key, 0.0) + w

print(f"total weight: {tot:.1f}")
for t in targets:
    print(f"{t:24s} {100*hit[t]/max(tot,1e-9):6.2f}%  ({hit[t]:.0f})")
if hit_stacks:
    print("--- stacks mit wait_d2h (leaf-4) ---")
    for k, v in sorted(hit_stacks.items(), key=lambda kv: -kv[1])[:12]:
        print(f"{100*v/max(tot,1e-9):6.2f}%  {k}")
