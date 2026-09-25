#!/usr/bin/env python3
"""Evaluate all <PREFIX>*.jsonl sweep files in this script's directory.

File naming convention: the baseline file is <PREFIX>.jsonl (no suffix).
Every other file <PREFIX>-<name>.jsonl is one measurement run; if <name>
starts with a known host label followed by '-', it is reported as <name>@<host>.

PREFIX defaults to "sweep"; override via the SWEEP_PREFIX env var or argv[1].
Host labels default to SWEEP_HOSTS env (comma-separated) or a built-in list.

Output: a Markdown table on stdout — cell (prompt x streams) | baseline mean |
per run: mean (min-max), delta % vs baseline, tok/step, ms/step, errors/nvrm.
Mean is taken over dash_aggregate_tps.
"""
import glob
import json
import os
import sys
from statistics import mean

DIR = os.path.dirname(os.path.abspath(__file__))
PREFIX = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SWEEP_PREFIX", "sweep")
BASE_FILE = os.path.join(DIR, PREFIX + ".jsonl")
PROMPT_ORDER = {"code": 0, "prose": 1}


KNOWN_HOSTS = tuple(
    h for h in os.environ.get("SWEEP_HOSTS", "node-a,node-b,spark1,spark2,dual").split(",") if h
)


def run_name(path):
    """-> (name, host). File names: <prefix>[-<host>]-<name>.jsonl;
    files without a host prefix are reported under their plain name."""
    stem = os.path.basename(path)[: -len(".jsonl")]
    suffix = stem[len(PREFIX):].lstrip("-")
    if not suffix:
        return "baseline", "-"
    for h in KNOWN_HOSTS:
        if suffix.startswith(h + "-"):
            return suffix[len(h) + 1:], h
    return suffix, "-"


def load(path):
    """{(prompt, S): {tps:[], tok:[], ms:[], fehler:int, nvrm:int}}"""
    cells = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (r.get("prompt"), r.get("S"))
            if key[0] is None or key[1] is None:
                continue
            c = cells.setdefault(key, {"tps": [], "tok": [], "ms": [], "fehler": 0, "nvrm": 0})
            tps = r.get("dash_aggregate_tps")
            if isinstance(tps, (int, float)):
                c["tps"].append(float(tps))
            for fld, src in (("tok", "tok_per_step"), ("ms", "ms_per_step")):
                v = r.get(src)
                if isinstance(v, (int, float)):
                    c[fld].append(float(v))
            c["fehler"] += int(r.get("streams_failed") or 0)
            if r.get("status") not in (None, "completed"):
                c["fehler"] += 1
            c["nvrm"] += int(r.get("nvrm") or 0)
    return cells


def fmt_mean_minmax(vals):
    if not vals:
        return "–"
    m = mean(vals)
    if len(vals) == 1:
        return f"{m:.1f}"
    return f"{m:.1f} ({min(vals):.1f}–{max(vals):.1f})"


def fmt_mean(vals, nd):
    return f"{mean(vals):.{nd}f}" if vals else "–"


def main():
    files = sorted(glob.glob(os.path.join(DIR, PREFIX + "*.jsonl")))
    if not files:
        sys.exit(f"no {PREFIX}*.jsonl in {DIR}")
    runs = []          # [(name, host, path, cells)]
    base_cells = None
    for p in files:
        name, host = run_name(p)
        cells = load(p)
        if p == BASE_FILE:
            name = "baseline"
            base_cells = cells
        runs.append((name, host, p, cells))
    runs.sort(key=lambda t: (t[0] != "baseline", t[1], t[0]))

    all_cells = sorted(
        {k for _, _, _, cells in runs for k in cells},
        key=lambda k: (PROMPT_ORDER.get(k[0], 9), k[1]),
    )

    def label(name, host):
        return name if name == "baseline" else (f"{name}@{host}" if host != "-" else name)

    out = []
    out.append(f"# TABLE — all runs (`{PREFIX}*.jsonl`)")
    out.append("")
    out.append("| run | host | file | rows | max reps/cell |")
    out.append("|---|---|---|---|---|")
    for name, host, p, cells in runs:
        reps = max((len(c["tps"]) for c in cells.values()), default=0)
        out.append(f"| **{label(name, host)}** | {host} | `{os.path.basename(p)}` | {sum(len(c['tps']) for c in cells.values())} | {reps} |")
    out.append("")
    if base_cells is None:
        out.append("_No baseline file (without suffix) found — delta % omitted._")
        out.append("")

    header = ["cell", "baseline tok/s"] if base_cells is not None else ["cell"]
    for name, host, _, _ in runs:
        if name == "baseline" and base_cells is not None:
            continue
        lbl = label(name, host)
        header += [f"{lbl} tok/s (min–max)", f"{lbl} Δ%", f"{lbl} tok/step", f"{lbl} ms/step", f"{lbl} err/nvrm"]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "---|" * len(header))

    for (prompt, s) in all_cells:
        row = [f"{prompt} {s}"]
        bmean = None
        if base_cells is not None:
            bc = base_cells.get((prompt, s))
            bmean = mean(bc["tps"]) if bc and bc["tps"] else None
            row.append(f"{bmean:.1f}" if bmean is not None else "–")
        for name, _, _, cells in runs:
            if name == "baseline" and base_cells is not None:
                continue
            c = cells.get((prompt, s))
            if not c:
                row += ["–", "–", "–", "–", "–"]
                continue
            m = mean(c["tps"]) if c["tps"] else None
            delta = f"{(m - bmean) / bmean * 100:+.1f} %" if (m is not None and bmean) else "–"
            row += [
                fmt_mean_minmax(c["tps"]),
                delta,
                fmt_mean(c["tok"], 2),
                fmt_mean(c["ms"], 1),
                f"{c['fehler']}/{c['nvrm']}",
            ]
        out.append("| " + " | ".join(row) + " |")

    print("\n".join(out))


if __name__ == "__main__":
    main()
