#!/usr/bin/env python3
"""Wieviel % einer Datei steht im Page-Cache — mmap+mincore(2) via ctypes.

Zweite Zeile = Maschinenausgabe: resident_pages total_pages pct
"""
import sys, os, ctypes

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                      ctypes.c_int, ctypes.c_int, ctypes.c_long]
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_char)]
libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]

PROT_READ, MAP_PRIVATE = 1, 2
PAGE = os.sysconf("SC_PAGESIZE")

path = sys.argv[1]
size = os.path.getsize(path)
fd = os.open(path, os.O_RDONLY)
addr = libc.mmap(None, size, PROT_READ, MAP_PRIVATE, fd, 0)
os.close(fd)
if addr in (None, ctypes.c_void_p(-1).value):
    raise OSError(ctypes.get_errno(), "mmap failed")
npages = (size + PAGE - 1) // PAGE
vec = (ctypes.c_char * npages)()
if libc.mincore(addr, size, vec) != 0:
    raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
res = sum(1 for i in range(npages) if vec[i] != b"\x00")
libc.munmap(addr, size)
print(f"{path}")
print(f"{res} {npages} {100*res/npages:.2f}")
