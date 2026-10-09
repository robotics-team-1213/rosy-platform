#!/usr/bin/env python3
"""Lap SIM 3 (no ROS): the keeper's live bundles on the 260919 ring after the SW turn, against
ground truth. Ring centre (-0.3357, 0.0011), r 0.2514 (lane centre), half width 0.0925.

  python3 ring_keep.py <run> [--png outdir]   # --png: save the frames around each strategy change
Per frame: gt dr (+ = outside), heading minus CCW tangent (deg, - = outward), keeper strategy,
reason, error, and each boundary (heading_deg, length, nearest end)."""
import argparse, json, math, os
import numpy as np
C, R = (-0.3357, 0.0011), 0.2514


def ring(g):
    x, y, yaw = g
    a = math.atan2(y - C[1], x - C[0])
    d = yaw - (a + math.pi / 2)
    return math.hypot(x - C[0], y - C[1]) - R, math.degrees(math.atan2(math.sin(d), math.cos(d)))


ap = argparse.ArgumentParser()
ap.add_argument('run')
ap.add_argument('--png')
ap.add_argument('--all', action='store_true')
a = ap.parse_args()
rec = np.load(os.path.join(a.run, 'rec', 'frames.npz'))
gt = {round(float(s), 3): (i, g) for i, (s, g) in enumerate(zip(rec['stamp'], rec['gt']))}
on, last = False, None
for line in open(os.path.join(a.run, 'rec', 'keep.jsonl')):
    b = json.loads(line)
    hit = gt.get(round(float(b['stamp']), 3))
    if hit is None or not np.all(np.isfinite(hit[1])):
        continue
    i, g = hit
    dr, dyaw = ring(g)
    near = abs(dr) < 0.15 and g[1] < 0.05 and g[0] > -0.62
    if not near:
        on = False
        continue
    bnd = ' '.join(f"[{x.get('heading_deg')},{x.get('length_m')},{x.get('side', '')}]" for x in b.get('boundaries') or [])
    key = (b.get('strategy'), b.get('reason'))
    if a.all or key != last:
        print(f"{b['stamp']:8.3f} gt=({g[0]:+.3f},{g[1]:+.3f},{math.degrees(g[2]):+6.1f}) dr={dr:+.3f} dyaw={dyaw:+5.1f} "
              f"{b.get('strategy')}/{b.get('reason')} err={b.get('error')} tgt={b.get('target_m')} {bnd}")
        if a.png and key != last:
            import cv2
            os.makedirs(a.png, exist_ok=True)
            cv2.imwrite(os.path.join(a.png, f"{b['stamp']:.3f}_{b.get('strategy')}_{b.get('reason')}.png"), rec['frames'][i])
    last = key
