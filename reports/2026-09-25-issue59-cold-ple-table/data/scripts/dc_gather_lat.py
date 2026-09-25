#!/usr/bin/env python3
# Measure PLE row-gather latency the way ple_layer does it:
#   MADV_RANDOM memmap -> optional fadvise(WILLNEED) page batch -> fancy-index.
# Usage: dc_gather_lat.py <packed_u8> <rows_per_step>...
# "cold" = munmap + posix_fadvise(DONTNEED) on the unmapped file + remap.
import os, sys, json, mmap, ctypes, time
import numpy as np

PAGE = 1 << 12
libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.posix_fadvise.argtypes = [ctypes.c_int, ctypes.c_int64, ctypes.c_int64, ctypes.c_int]
POSIX_FADV_WILLNEED = 3
POSIX_FADV_DONTNEED = 4

path = sys.argv[1]
sizes = [int(x) for x in sys.argv[2:]] or [64, 128, 320]
meta = json.load(open(path + ".json"))
rows, width = int(meta["total_rows"]), int(meta["row_width"])
assert os.path.getsize(path) == rows * width
fd = os.open(path, os.O_RDONLY)

def new_mm():
    m = np.memmap(path, dtype=np.uint8, mode="r", shape=(rows, width))
    m._mmap.madvise(mmap.MADV_RANDOM)
    return m

mm = new_mm()
out = np.empty((max(sizes), width), dtype=np.uint8)

def pages_of(ids):
    offs = ids.astype(np.int64) * width
    return np.unique(np.concatenate([offs // PAGE, (offs + width - 1) // PAGE]))

def prefetch(pg):
    for p in pg:
        libc.posix_fadvise(fd, int(p) * PAGE, PAGE, POSIX_FADV_WILLNEED)

def gather(mm, ids):
    return mm[ids]  # same serial row walk as torch.index_select

def recold():
    global mm
    mm._mmap.close()
    libc.posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED)
    mm = new_mm()

rng = np.random.default_rng(7)
print(f"file={path} rows={rows} width={width} page={PAGE}")
for n in sizes:
    ids = rng.integers(0, rows, n)
    pg = pages_of(ids)
    gather(mm, ids)
    t = []
    for _ in range(3):
        t0 = time.perf_counter_ns(); gather(mm, ids); t.append((time.perf_counter_ns() - t0) / 1e6)
    warm = min(t)
    recold()
    t0 = time.perf_counter_ns(); prefetch(pg); gather(mm, ids); coldpf = (time.perf_counter_ns() - t0) / 1e6
    recold()
    t0 = time.perf_counter_ns(); gather(mm, ids); coldnp = (time.perf_counter_ns() - t0) / 1e6
    print(f"n={n:4d} pages={len(pg):4d} warm={warm:7.2f}ms cold+prefetch={coldpf:8.2f}ms cold+noprefetch={coldnp:8.2f}ms", flush=True)
os.close(fd)
