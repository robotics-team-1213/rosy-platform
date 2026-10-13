#!/usr/bin/env python3
"""B8 offline analysis (laptop, no ROS): keeper bundles vs ground truth on the 260919 track.

  python b8_analyze.py <runs dir> [--json out.json]

Per run (<runs>/<name>/rec/frames.npz + keep.jsonl, <name>/log.jsonl): joins each keeper
bundle to its frame by image stamp and the frame's d495/gt pose, then

south   frames on the straight south lane (gt x in [-1.15, -0.80], |yaw| < 0.35 rad, y within
        0.06 m of the lane centre): gt lateral offset of base_link from the lane centre (+ =
        left = +y), strategy mix, and per detected boundary the error of its y_at_side_x_m
        against the true paint line (lines measured from the PaintMap raster of the world STL:
        inner/left line y -0.4185, outer/right -0.6035, centre -0.511, half-width 0.0925).
bend    the first non-'both' keeper events from x > -0.85 on (the SW bend at about
        (-0.74, -0.51)): sequence of strategy/reason, first flipping/junction frame.
"""
import argparse
import collections
import json
import math
import os

import numpy as np

LEFT_Y, RIGHT_Y = -0.4185, -0.6035
CENTRE_Y = (LEFT_Y + RIGHT_Y) / 2.0
SIDE_X_M = 0.22


def lateral(y_line, gy, yaw, x=SIDE_X_M):
    """base_link y of the world line y = y_line at x ahead (straight lane along +x)."""
    return (y_line - gy - x * math.sin(yaw)) / math.cos(yaw)


def load(run):
    rec = np.load(os.path.join(run, 'rec', 'frames.npz'))
    gt = {round(float(s), 3): g for s, g in zip(rec['stamp'], rec['gt'])}
    out = []
    for line in open(os.path.join(run, 'rec', 'keep.jsonl')):
        b = json.loads(line)
        g = gt.get(round(float(b['stamp']), 3))
        if g is not None and np.all(np.isfinite(g)):
            out.append((b, g))
    return out


def south(rows):
    s = [(b, g) for b, g in rows
         if -1.15 <= g[0] <= -0.80 and abs(g[2]) < 0.35 and abs(g[1] - CENTRE_Y) < 0.06]
    if not s:
        return None
    off = np.array([g[1] - CENTRE_Y for _, g in s])
    strat = collections.Counter(b['strategy'] for b, _ in s)
    errs = {'left': [], 'right': []}
    tgt = []
    for b, g in s:
        for r in b.get('boundaries', []):
            truth = lateral(LEFT_Y if r['side'] == 'left' else RIGHT_Y, g[1], g[2])
            errs[r['side']].append(r['y_at_side_x_m'] - truth)
        if b.get('target_m') and b['strategy'] in ('both', 'left_only', 'right_only'):
            tx, ty = b['target_m']
            # target vs the true centre line at the same ahead distance (+ = target left of centre)
            tgt.append((b['strategy'], ty - lateral(CENTRE_Y, g[1], g[2], tx)))
    q = lambda a: None if not len(a) else [round(float(v), 4) for v in np.percentile(a, [10, 50, 90])]
    return {'frames': len(s), 'gt_offset_m_p10_50_90': q(off), 'gt_offset_mean_m': round(float(off.mean()), 4),
            'strategy': dict(strat),
            'boundary_err_m_p10_50_90': {k: q(v) for k, v in errs.items()},
            'boundary_n': {k: len(v) for k, v in errs.items()},
            'target_vs_centre_m': {st: q([d for s_, d in tgt if s_ == st])
                                   for st in ('both', 'left_only', 'right_only')}}


def bend(rows):
    seq, first = [], {}
    for b, g in rows:
        if g[0] < -0.86 or g[1] > -0.30:
            continue
        key = b['strategy'] if b['strategy'] != 'none' else b.get('reason')
        if not seq or seq[-1][0] != key:
            seq.append([key, round(float(b['stamp']), 2), [round(float(v), 3) for v in g]])
        for k in ('flipping', 'junction_fork', 'junction_transverse', 'no_boundary'):
            if b.get('reason') == k and k not in first:
                first[k] = [round(float(b['stamp']), 2), [round(float(v), 3) for v in g]]
    return {'seq': seq[:40], 'first': first}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs')
    ap.add_argument('--json')
    a = ap.parse_args()
    out = {}
    for name in sorted(os.listdir(a.runs)):
        run = os.path.join(a.runs, name)
        if not os.path.exists(os.path.join(run, 'rec', 'frames.npz')):
            continue
        rows = load(run)
        out[name] = {'bundles': len(rows), 'south': south(rows), 'bend': bend(rows)}
        print(name, json.dumps(out[name]['south']))
        print('   bend', ' > '.join(f"{k}@{p[0]:.2f},{p[1]:.2f}" for k, _, p in out[name]['bend']['seq'][:14]))
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
