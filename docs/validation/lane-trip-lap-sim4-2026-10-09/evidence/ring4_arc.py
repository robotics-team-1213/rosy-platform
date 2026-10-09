#!/usr/bin/env python3
"""Lap SIM 4: per ring arc (ring_s, ring_e, ring_n) the Gazebo ground-truth radial error dr = |p - c| - r
over the ticks CORE drives the arc (reason lane_arc / lane_arc_correcting), the arc's start heading error,
IR corrections and stop reasons. Ring of map_v2_fleet: centre (-0.3357, 0.0011), r 0.2514 m, CCW.
  python3 ring4_arc.py <runs dir> [--json out.json]"""
import json
import math
import sys
from pathlib import Path

C, R = (-0.3357, 0.0011), 0.2514
SECTORS = (('ring_s', -137.7, -52.5), ('ring_e', -52.5, 52.3), ('ring_n', 52.3, 137.1))


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def run(d):
    rows = [json.loads(line) for line in open(d/'log.jsonl')]
    summary = json.load(open(d/'summary.json'))
    arcs = {}
    for r in rows:
        if not str(r.get('reason') or '').startswith('lane_arc') or not r.get('gt'):
            continue
        x, y, yaw = r['gt']
        phi = math.degrees(math.atan2(y-C[1], x-C[0]))
        name = next((n for n, lo, hi in SECTORS if lo <= phi < hi), None)
        if name is None:
            continue
        dr = math.hypot(x-C[0], y-C[1]) - R
        a = arcs.setdefault(name, dict(start_dr=round(dr, 4), start_dyaw_deg=round(math.degrees(
            wrap(yaw-math.radians(phi+90))), 1), max_abs_dr=0., end_dr=None, correcting=False, ticks=0))
        a['max_abs_dr'] = round(max(a['max_abs_dr'], abs(dr)), 4)
        a['end_dr'], a['ticks'] = round(dr, 4), a['ticks']+1
        a['correcting'] |= r['reason'] == 'lane_arc_correcting'
    reasons = [r.get('reason') for r in rows]
    events = [json.loads(line).get('event') or json.loads(line).get('type') for line in open(d/'events.jsonl')]
    return dict(result=summary.get('result'), reason=summary.get('reason'), arcs=arcs,
                lane_arc_edge='lane_arc_edge' in reasons,
                near_stop=sum('near_stop' in str(r.get('reason')) or 'near_stop' in str(r.get('junction'))
                              for r in rows),
                unarmed=sum(e == 'nav.lane_arc_end_unarmed' for e in events),
                last_reason=next((x for x in reversed(reasons) if x), None))


def main():
    out = {}
    for d in sorted(p for p in Path(sys.argv[1]).iterdir() if (p/'summary.json').exists()):
        out[d.name] = run(d)
        o = out[d.name]
        print(d.name, o['result'], o['reason'], 'edge' if o['lane_arc_edge'] else '', 'unarmed', o['unarmed'],
              ' '.join(f"{n}:max{a['max_abs_dr']:+.3f}/start{a['start_dr']:+.3f}/dyaw{a['start_dyaw_deg']:+.1f}"
                       f"{'/IR' if a['correcting'] else ''}" for n, a in o['arcs'].items()))
    if '--json' in sys.argv:
        json.dump(out, open(sys.argv[sys.argv.index('--json')+1], 'w'), indent=1)


if __name__ == '__main__':
    main()
