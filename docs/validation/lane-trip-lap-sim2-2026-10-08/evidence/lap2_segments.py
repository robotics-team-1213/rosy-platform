#!/usr/bin/env python3
"""Per-segment table of lap SIM 2 runs (no ROS): python lap2_segments.py <runs dir> [--json out.json]

Plan: west:rev -> B_SW bend -> SW right -> ring_s -> SE straight -> ring_e -> NE straight -> ring_n -> NW stop.
  corner   ground truth reaches x > -1.15 and y < -0.45 (lap SIM definition)
  bend     CORE's B_SW instruction was never aborted/unresolved and SW got an instruction after it
  sw_turn  CORE's SW instruction turned and ended without aborted/unresolved, then reacquired the lane
           (lap 'reacquire') or, with D-520 arc_enabled, opened the ring_s arc (CORE reason lane_arc*)
  ring     the trip reached its last segment (ring_n): SE and NE were passed
  nw_stop  CORE's NW stop instruction held (executing, held) or the trip arrived
  done     the Fleet trip ended 'arrived'
Uses lap_analyze.analyze (same folder as the lap SIM harness) for the per-run record."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lane-trip-lap-sim-2026-10-08' / 'evidence'))
from lap_analyze import analyze, rows, pt, where  # noqa: E402

RING_C, RING_R = (-0.3357, 0.0011), 0.2514  # D-520 Context 1 / d520-arc-stage1-sim


def seg(run, sends):
    a = analyze(run, sends)
    log, trip = rows(run/'log.jsonl'), rows(run/'trip.jsonl')
    places = {}
    for r in log:
        j = r.get('junction') or {}
        p = j.get('place_id')
        if p and (p not in places or places[p][-1] != j.get('state')):
            places.setdefault(p, []).append(j.get('state'))
    last_index = max((r.get('segment_index') or 0 for r in trip), default=0)
    edges = [r.get('current_edge') for r in trip if r.get('current_edge')]
    bend_bad = any(s in ('aborted', 'unresolved') for s in places.get('B_SW', []))
    nw = places.get('NW', [])
    sw = places.get('SW', [])
    # D-520: ring centre-line circle (lane_graph map_v2_fleet), radial error dr of the ground truth
    arc_dr = [math.dist(r['gt'][:2], RING_C) - RING_R for r in log
              if r.get('gt') and (r.get('reason') or '').startswith('lane_arc')]
    reasons, prev = [], None
    for r in log:
        k = r.get('reason')
        if k != prev and k and (k.startswith('junction_') or k.startswith('lane_') or k in (
                'obstacle_ahead', 'camera_line_not_visible', 'stuck_back_off')):
            reasons.append((k, pt(r.get('gt')), where(r.get('gt'))))
        prev = k
    opened_arc = any(k.startswith('lane_arc') for k, _, _ in reasons)
    out = dict(run=run.name.strip(), result=a['result'], reason=a['reason'], stop_at=a['stop_at'],
               stop_detail=a['stop_detail'], corner=a['corner_pass'],
               bend=bool(places.get('B_SW')) and not bend_bad and 'SW' in places,
               sw_turn=a['reacquire'] or ('turning' in sw and not any(s in ('aborted', 'unresolved') for s in sw)
                                          and opened_arc),
               arc_max_abs_dr_m=round(max(map(abs, arc_dr)), 3) if arc_dr else None,
               arc_end_dr_m=round(arc_dr[-1], 3) if arc_dr else None, ring='ring_n' in edges, nw_stop=('executing' in nw) or a['completed'],
               done=a['completed'], places=places, edges=sorted(set(edges)), last_index=last_index,
               core_reasons=reasons, fleet_sends=a['fleet_sends'], clean_end=a['clean_end'],
               d422_holds=a['d422_holds'], lane_return=[x['reason'] for x in a['lane_return']])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs')
    ap.add_argument('--json')
    a = ap.parse_args()
    root = Path(a.runs)
    sends = rows(root/'sends.jsonl')
    res = [seg(r, sends) for r in sorted(root.iterdir()) if (r/'summary.json').exists()]
    keys = ('corner', 'bend', 'sw_turn', 'ring', 'nw_stop', 'done')
    for r in res:
        print(r['run'], *(f"{k}={int(r[k])}" for k in keys), r['result'], r['reason'], r['arc_max_abs_dr_m'],
              r['stop_at']['where'], r['stop_at']['gt'], r['edges'])
    agg = {k: sum(1 for r in res if r[k]) for k in keys}
    print('n', len(res), agg)
    if a.json:
        Path(a.json).write_text(json.dumps({'n': len(res), 'aggregate': agg, 'runs': res}, indent=1))


if __name__ == '__main__':
    main()
