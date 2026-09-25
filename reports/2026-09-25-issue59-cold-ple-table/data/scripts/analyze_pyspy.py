#!/usr/bin/env python3
"""analyze_pyspy.py <speedscope.json> — Frame-Anteile (%) der Samples.

Gruppiert nach Regex-Mustern, die fuer den PLE-Handshake relevant sind.
Ausgabe: name | samples | pct — absteigend.
"""
import json
import re
import sys

PATTERNS = [
    ("wait_d2h (conn:380)", r"wait_d2h|_d2h_done_event\.synchronize"),
    ("_wait_done (conn)", r"_wait_done"),
    ("prepare_forward total", r"prepare_forward"),
    ("_launch", r"_launch"),
    ("_process_request", r"_process_request"),
    ("build_attn_metadata", r"build_attn_metadata|prepare_attn"),
    ("forward/model", r"forward|model\.py"),
    ("sample", r"sampl"),
    ("index_select/gather", r"index_select|forward_impl|_ple_prefetch"),
    ("_handle_requests (ple)", r"_handle_requests"),
]


def walk(node, acc, total_key="samples"):
    """speedscope: profile.frames[] + tree via profile.events? Format:
    speedscope 'sampled' profile: profiles[i].samples = [[frameIdx,...]..]"""
    pass


def main(path):
    doc = json.load(open(path))
    # speedscope schema: {shared:{frames:[{name,file,line}]}, profiles:[{type:'sampled'|'evented', samples:[[...]], weights:[..]}]}
    frames = doc["shared"]["frames"]
    names = [f.get("name", "?") for f in frames]
    tot = {label: 0 for label, _ in PATTERNS}
    total = 0
    for prof in doc["profiles"]:
        samples = prof.get("samples", [])
        weights = prof.get("weights") or [1] * len(samples)
        for stack, w in zip(samples, weights):
            total += w
            seen = set()
            for idx in stack:
                n = names[idx] if isinstance(idx, int) else str(idx)
                for label, pat in PATTERNS:
                    if label not in seen and re.search(pat, n):
                        tot[label] += w
                        seen.add(label)
    print(f"total samples: {total}")
    for label, _ in PATTERNS:
        v = tot[label]
        print(f"{label:28s} {v:6.0f}  {100*v/max(total,1):5.1f}%")


if __name__ == "__main__":
    main(sys.argv[1])
