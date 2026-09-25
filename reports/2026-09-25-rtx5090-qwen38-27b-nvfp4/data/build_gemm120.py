import os, sys, time, pathlib

# build gemm_sm120 JIT module in a scratch workspace
ws = pathlib.Path(os.path.expanduser("~/mia-bench/rtx5090/fi-workspace"))
ws.mkdir(parents=True, exist_ok=True)
os.environ["FLASHINFER_WORKSPACE"] = str(ws)

t0 = time.time()
from flashinfer.jit.gemm.core import gen_gemm_sm120_module
spec = gen_gemm_sm120_module()
print("build_dir:", spec.build_dir, flush=True)
sys.stdout.flush()
spec.build(verbose=True, need_lock=False)
print("BUILD_DONE seconds=%.1f" % (time.time() - t0), flush=True)
