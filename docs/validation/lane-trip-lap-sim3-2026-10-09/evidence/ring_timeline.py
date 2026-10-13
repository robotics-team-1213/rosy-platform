#!/usr/bin/env python3
"""Lap SIM 3 timeline (ROS-free): per run, the CORE state/reason/junction and keeper changes after
the SW turn, with ground truth and ring offset (centre (-0.3357, 0.0011), r 0.2514).
  python3 ring_timeline.py <run_dir> [--from-place SW]"""
import json, math, sys
C, R = (-0.3357, 0.0011), 0.2514

def ring(gt):
    x, y, yaw = gt
    a = math.atan2(y - C[1], x - C[0])
    tangent = a + math.pi / 2
    d = math.atan2(math.sin(yaw - tangent), math.cos(yaw - tangent))
    return math.hypot(x - C[0], y - C[1]) - R, math.degrees(d)

run = sys.argv[1]
rows = [json.loads(l) for l in open(f'{run}/log.jsonl')]
last = None
for r in rows:
    if not r.get('gt'):
        continue
    j = r.get('junction') or {}
    key = (r.get('state'), r.get('reason'), r.get('keep'), j.get('state'), j.get('place_id'))
    if key != last:
        dr, dyaw = ring(r['gt'])
        print(f"{r['sim_t']:8.2f} gt=({r['gt'][0]:+.3f},{r['gt'][1]:+.3f},{math.degrees(r['gt'][2]):+6.1f}) "
              f"dr={dr:+.3f} dyaw={dyaw:+5.1f} cmd={r['cmd']} {r.get('state')}/{r.get('reason')} keep={r.get('keep')} "
              f"j={j.get('state')}:{j.get('place_id')}:{j.get('pending_action')}")
        last = key
