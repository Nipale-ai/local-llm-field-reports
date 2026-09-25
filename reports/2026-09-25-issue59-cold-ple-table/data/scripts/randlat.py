#!/usr/bin/env python3
"""Random-4K-Leselatenz auf einer Datei: buffered (Cache) vs O_DIRECT (NVMe).
Simuliert den PLE-Gather: N zufaellige 4K-Reads ueber die ganze Datei.
"""
import sys, os, random, time, ctypes

path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
size = os.path.getsize(path)
PAGE = 4096
npages = size // PAGE
random.seed(42)
pages = [random.randrange(npages) for _ in range(n)]

def run(direct):
    flags = os.O_RDONLY | (os.O_DIRECT if direct else 0)
    fd = os.open(path, flags)
    try:
        if direct:
            buf = ctypes.create_string_buffer(PAGE)  # aligned genug fuer O_DIRECT
            t0 = time.perf_counter_ns()
            for p in pages:
                os.preadv(fd, [buf], p * PAGE)
            dt = time.perf_counter_ns() - t0
        else:
            t0 = time.perf_counter_ns()
            for p in pages:
                os.pread(fd, PAGE, p * PAGE)
            dt = time.perf_counter_ns() - t0
    finally:
        os.close(fd)
    return dt / n / 1000.0  # us pro Read

if __name__ == "__main__":
    which = sys.argv[3] if len(sys.argv) > 3 else "both"
    if which in ("both", "direct"):
        print(f"O_DIRECT  : {run(True):8.1f} us/read  (n={n})")
    if which in ("both", "buffered"):
        print(f"buffered  : {run(False):8.1f} us/read  (n={n})")
