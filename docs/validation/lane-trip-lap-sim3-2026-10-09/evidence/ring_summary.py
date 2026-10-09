#!/usr/bin/env python3
"""Lap SIM 3 (no ROS): per run, the SW turn end and what happened on ring_s.
  python3 ring_summary.py <runs dir> [--json out.json]
turn_end   heading minus ring CCW tangent (deg, - = outward) when the SW turn becomes 'advancing'
reacq      gt dr (+ = outside the lane centre circle r 0.2514) and heading error when CORE is TRACKING again
max_dr     largest dr on ring_s before the first lane loss (lane half width 0.0925)
first_loss first CORE camera_line_not_visible / no_boundary row: gt pose, dr
ends       last CORE reason before mode_off, Fleet result/reason (summary.json)"""
import json, math, os, sys
C, R = (-0.3357, 0.0011), 0.2514


def ring(g):
    x, y, yaw = g
    a = math.atan2(y - C[1], x - C[0])
    d = yaw - (a + math.pi / 2)
    return round(math.hypot(x - C[0], y - C[1]) - R, 3), round(math.degrees(math.atan2(math.sin(d), math.cos(d))), 1)


out = {}
root = sys.argv[1]
for name in sorted(os.listdir(root)):
    p = os.path.join(root, name, 'log.jsonl')
    if not os.path.exists(p):
        continue
    rows = [r for r in map(json.loads, open(p)) if r.get('gt')]
    s = json.load(open(os.path.join(root, name, 'summary.json')))
    turn_end = reacq = loss = None
    max_dr, last_reason, after_turn = -1, None, False
    for r in rows:
        j = r.get('junction') or {}
        if j.get('place_id') == 'SW' and j.get('state') == 'advancing' and turn_end is None:
            turn_end = ring(r['gt'])[1]
            after_turn = True
        if after_turn and reacq is None and r.get('state') == 'TRACKING':
            reacq = ring(r['gt'])
        if after_turn and loss is None:
            dr = ring(r['gt'])[0]
            if r.get('reason') in ('camera_line_not_visible',) or r.get('keep') == 'no_boundary':
                loss = {'gt': [round(v, 3) for v in r['gt'][:2]], 'dr': dr, 'reason': r.get('reason')}
            else:
                max_dr = max(max_dr, dr)
        if r.get('reason') not in (None, 'mode_off'):
            last_reason = r.get('reason')
    out[name] = {'turn_end_dyaw_deg': turn_end, 'reacquire_dr_dyaw': reacq, 'max_dr_before_loss': max_dr,
                 'first_loss': loss, 'last_core_reason': last_reason,
                 'fleet': [s.get('result'), s.get('reason')]}
    print(name, out[name])
if '--json' in sys.argv:
    json.dump(out, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)
