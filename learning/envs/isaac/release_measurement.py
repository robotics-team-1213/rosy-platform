"""Turn a real-arm release measurement session into the simulation's noise ranges.

The release corrector trains and is evaluated with a 2-5 mm held-box estimate error that was assumed, not measured
(docs/validation/omx-release-corrector-2026-10-30). One supervised session on the real cell measures it. Each CSV row
is one observation in millimetres, measured minus reference:

    kind,trial,dx_mm,dy_mm,dz_mm
    estimate,1,1.8,-0.6,0.4     # top-camera box position vs the touched/known position
    drift,1,0.3,0.1,0.0         # settled box position after opening vs just before opening
    tcp,1,0.2,-0.1,0.1          # measured TCP after a move vs the commanded TCP

    python release_measurement.py session.csv
"""
import csv
import json
import math
import sys

import numpy as np


def summary(rows):
    """Per kind: count, horizontal error p50/p95/max (mm), and the noise range the fixture would take (metres)."""
    out = {}
    for kind in sorted({r['kind'] for r in rows}):
        planar = np.array([math.hypot(float(r['dx_mm']), float(r['dy_mm'])) for r in rows if r['kind'] == kind])
        p50, p95 = np.percentile(planar, [50, 95])
        out[kind] = dict(n=len(planar), p50_mm=round(float(p50), 3), p95_mm=round(float(p95), 3),
                         max_mm=round(float(planar.max()), 3))
    if 'estimate' in out:  # same [low, high] form as release_estimate_noise_m in mapped_stack_fixture
        out['release_estimate_noise_m'] = [out['estimate']['p50_mm']/1000, out['estimate']['p95_mm']/1000]
    return out


if __name__ == '__main__':
    with open(sys.argv[1], newline='', encoding='utf-8') as handle:
        print(json.dumps(summary(list(csv.DictReader(handle))), indent=2, sort_keys=True))
