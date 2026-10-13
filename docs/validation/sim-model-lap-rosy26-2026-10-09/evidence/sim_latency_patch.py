"""SIM-only: append a paint-worker latency floor to the scratch ws runner.py (never committed to product code).

ROSY_SIM_PAINT_LATENCY_MS > 0 makes LaneSegModel.infer_mask take at least that long (wall clock),
so the D-570 reuse/warp path sees Pi-like mask ages in Gazebo.
  python3 sim_latency_patch.py <ws>/src/rosy-platform/middleware/perception/control/sensing/perception/learned/runner.py
"""
import sys

PATCH = '''

# --- sim-model-lap 2026-10-09: SIM-only latency floor (scratch ws, not product code) ---
import os as _sim_os
_SIM_PAINT_LATENCY_S = float(_sim_os.environ.get("ROSY_SIM_PAINT_LATENCY_MS", "0") or 0) / 1000.0
if _SIM_PAINT_LATENCY_S > 0:
    _sim_infer_mask = LaneSegModel.infer_mask

    def _sim_slow_infer_mask(self, bgr):
        t0 = time.perf_counter()
        mask, _ = _sim_infer_mask(self, bgr)
        rest = _SIM_PAINT_LATENCY_S - (time.perf_counter() - t0)
        if rest > 0:
            time.sleep(rest)
        return mask, (time.perf_counter() - t0) * 1000.0

    LaneSegModel.infer_mask = _sim_slow_infer_mask
'''

path = sys.argv[1]
text = open(path).read()
if "sim-model-lap 2026-10-09" not in text:
    open(path, "a").write(PATCH)
print("patched", path)
