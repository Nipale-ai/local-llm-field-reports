import json, urllib.request, time
base = ("The history of computation spans mechanical calculators, vacuum tubes, "
        "transistors, integrated circuits, microprocessors, and parallel accelerators. ")
for name, reps in (("8k", 292), ("32k", 1166), ("64k", 2331), ("128k", 4662)):
    prompt = base * reps + "\n\nSummarize in one word:"
    for rep in range(2):
        body = json.dumps({"model": "qwen38-nvfp4-24g", "prompt": prompt,
                           "max_tokens": 1, "temperature": 0}).encode()
        t0 = time.time()
        r = json.loads(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8888/v1/completions", data=body,
            headers={"Content-Type": "application/json"}), timeout=300).read())
        dt = time.time() - t0
        pt = r["usage"]["prompt_tokens"]
        print("%s rep%d: prompt_tokens=%d ttft=%d ms" % (name, rep, pt, dt * 1000), flush=True)
