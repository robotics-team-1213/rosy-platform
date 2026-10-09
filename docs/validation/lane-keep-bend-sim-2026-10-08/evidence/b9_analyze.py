#!/usr/bin/env python3
"""B9 SIM summary (model PC or laptop, no ROS): keeper bundles vs ground truth at the SW bend.

  python3 b9_analyze.py <runs dir> [--json out.json]

Per run (<run>/rec/frames.npz stamps + gt, rec/keep.jsonl, summary.json from the D-495 probe):
approach  gt lateral offset from the south lane centre (y -0.511, + = left) over the frames with
          gt x in [-0.95, -0.78] and y < -0.30 (B8 result.md: the B9 acceptance window; the y bound
          drops the spawn pose before the teleport): median and max |.|
bend      keeper frames after the W->S corner exit (gt x > -1.0, y < -0.30): count of corner_*
          strategies, junction_fork / flipping / no_boundary / junction_transverse reasons, and
          the first HOLD reason with its gt pose
probe     first junction result, the keep reason at sighting and its gt, final state
"""
import argparse
import collections
import json
import math
import os

import numpy as np

CENTRE_Y = -0.511


def run_summary(run):
    rec = np.load(os.path.join(run, 'rec', 'frames.npz'))
    gt = {round(float(s), 3): g for s, g in zip(rec['stamp'], rec['gt'])}
    rows = []
    for line in open(os.path.join(run, 'rec', 'keep.jsonl')):
        b = json.loads(line)
        g = gt.get(round(float(b['stamp']), 3))
        if g is not None and np.all(np.isfinite(g)):
            rows.append((b, g))
    start = next((i for i, (_, g) in enumerate(rows) if g[0] < -1.0), 0)  # after this run's teleport
    rows = rows[start:]
    window = [g[1] - CENTRE_Y for _, g in rows if -0.95 <= g[0] <= -0.78 and g[1] < -0.30]
    bend = [(b, g) for b, g in rows if g[0] > -1.0 and g[1] < -0.30]
    count = collections.Counter()
    first_hold = None
    for b, g in bend:
        if b['strategy'].startswith('corner'):
            count[b['strategy']] += 1
        if b.get('reason'):
            count[b['reason']] += 1
            if first_hold is None:
                first_hold = [b['reason'], [round(float(v), 3) for v in g]]
    out = {'approach_frames': len(window),
           'approach_median_m': None if not window else round(float(np.median(window)), 4),
           'approach_max_abs_m': None if not window else round(float(np.max(np.abs(window))), 4),
           'bend_counts': dict(count), 'first_hold': first_hold}
    try:
        s = json.load(open(os.path.join(run, 'summary.json')))
        j = (s.get('junctions') or [{}])[0]
        out['probe'] = {'result': j.get('result'), 'keep_at_sight': j.get('keep_at_sight'),
                        'sight_gt': j.get('sight_gt'), 'final': s.get('final')}
    except (OSError, ValueError):
        out['probe'] = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs')
    ap.add_argument('--json')
    a = ap.parse_args()
    out = {}
    for name in sorted(os.listdir(a.runs)):
        run = os.path.join(a.runs, name)
        if os.path.exists(os.path.join(run, 'rec', 'frames.npz')):
            out[name] = run_summary(run)
            r = out[name]
            p = r['probe'] or {}
            print(f"{name:10s} approach median {r['approach_median_m']} max {r['approach_max_abs_m']} "
                  f"n={r['approach_frames']} | first hold {r['first_hold']} | {r['bend_counts']} | "
                  f"probe {p.get('result')} at {p.get('keep_at_sight')} {p.get('sight_gt')}")
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
