#!/usr/bin/env python3
"""Per-segment summary of lap SIM runs (no ROS): python lap_analyze.py <runs dir> [--json out.json]

Reads each run's log.jsonl (CORE line-follow at 10 Hz + ground truth), trip.jsonl (Fleet trip view),
events.jsonl, summary.json and the batch's sends.jsonl (Fleet's junction instructions).
  corner      ground truth reaches x > -1.15 and y < -0.45 (lane-ws-corner-sim definition)
  bend        CORE's B_SW instruction: 'pass' = it reached reacquiring and was never aborted/unresolved
  turn        CORE's SW instruction left 'armed' (approaching/turning) = started; reacquiring = turned
  reacquire   the SW instruction ended idle (or a newer seq) after reacquiring, not unresolved/aborted
  completed   the Fleet trip ended 'arrived'
"""
import argparse
import json
import math
from pathlib import Path

SW_NODE = (-0.5216, -0.1682)


def rows(path):
    return [json.loads(line) for line in open(path)] if path.exists() else []


def where(g):
    if not g:
        return None
    x, y = g[0], g[1]
    if x < -1.10:
        return 'west_road' if y > -0.30 else 'ws_corner'
    if y < -0.40 and x < -0.75:
        return 'south_road'
    if math.dist((x, y), SW_NODE) > 0.12 and y < -0.15 and x < -0.55:
        return 'sw_bend_spoke'
    return 'roundabout'


def pt(g):
    return [round(v, 3) for v in g[:2]] if g else None


def analyze(run, sends):
    log, trip, s = rows(run/'log.jsonl'), rows(run/'trip.jsonl'), json.loads((run/'summary.json').read_text())
    events = rows(run/'events.jsonl')
    view = s.get('final_view') or {}
    t0, t1 = view.get('created_at'), (view.get('updated_at') or 0)+5
    mine = [x for x in sends if t0 is not None and t0-1 <= x['wall'] <= t1]
    out = {'run': run.name, 'result': s.get('result'), 'reason': s.get('reason')}
    det = view.get('detail') or {}
    out['stop_detail'] = {k: det.get(k) for k in ('junction_place', 'junction_action', 'junction_fields',
                                                     'off_lane_m', 'junction_state', 'line_reason', 'stop_sent',
                                                     'stall_s', 'goal_reason') if k in det}
    last = trip[-1] if trip else {}
    out['stop_at'] = {'gt': pt(last.get('gt')), 'where': where(last.get('gt')),
                      'segment_index': last.get('segment_index')}
    out['max_segment_index'] = max((r.get('segment_index') or 0 for r in trip), default=None)
    out['corner_pass'] = any(r.get('gt') and r['gt'][0] > -1.15 and r['gt'][1] < -0.45 for r in log)
    holds, prev = [], None
    for r in log:
        key = (r.get('state'), r.get('reason'))
        if key != prev and key[1] in ('obstacle_ahead', 'junction_bend_blocked'):
            holds.append({'reason': key[1], 'gt': pt(r.get('gt')), 'where': where(r.get('gt')),
                          'body_gap_m': r.get('body_gap_m'), 'clearance_source': r.get('clearance_source')})
        prev = key
    out['d422_holds'] = {}
    for h in holds:
        k = f"{h['reason']}@{h['where']}"
        out['d422_holds'][k] = out['d422_holds'].get(k, 0)+1
    out['d422_hold_list'] = holds
    ret, prev = [], None
    for r in log:  # D-468 local lane return (recovery_local_enabled)
        k = r.get('reason') or ''
        if k != prev and k.startswith('lane_return_'):
            ret.append({'reason': k, 'gt': pt(r.get('gt')), 'where': where(r.get('gt')),
                        'containment': r.get('lane_return_containment'), 'keep': r.get('keep'),
                        'confidence': r.get('confidence')})
        prev = k
    out['lane_return'] = ret

    def place_states(place):
        seq = []
        for r in log:
            j = r.get('junction') or {}
            if j.get('place_id') == place and (not seq or seq[-1][0] != j.get('state')):
                seq.append((j.get('state'), j.get('reason'), pt(r.get('gt'))))
        return seq

    bend = place_states('B_SW')
    names = [b[0] for b in bend]
    bad = [b for b in bend if b[0] in ('aborted', 'unresolved')]
    out['bend'] = ('pass' if 'reacquiring' in names and not bad else
                   f'{bad[0][0]}:{bad[0][1]}@{bad[0][2]}' if bad else ('not_sent' if not bend else 'incomplete:'+names[-1]))
    out['bend_states'] = names
    sw = place_states('SW')
    sw_names = [b[0] for b in sw]
    sw_bad = [b for b in sw if b[0] in ('aborted', 'unresolved')]
    out['sw_states'] = sw
    out['turn_started'] = any(n in ('approaching', 'turning') for n in sw_names)
    out['turn_done'] = 'reacquiring' in sw_names
    out['reacquire'] = out['turn_done'] and not sw_bad and out['max_segment_index'] is not None and out['max_segment_index'] >= 1
    # keeper junction sightings and where (does the SW junction get sighted after the bend?)
    sight, prev = [], None
    for r in log:
        k = r.get('keep')
        j = r.get('junction') or {}
        if k != prev and k in ('junction_transverse', 'junction_fork'):
            sight.append({'keep': k, 'gt': pt(r.get('gt')), 'during': f"{j.get('place_id')}:{j.get('state')}"})
        prev = k
    out['junction_sightings'] = sight
    after = [r for r in log if r.get('gt') and (r.get('junction') or {}).get('place_id') == 'SW']
    out['sw_min_dist_while_armed_m'] = round(min((math.dist(r['gt'][:2], SW_NODE) for r in after), default=math.nan), 3)
    out['near_stop'] = sum('near_stop' in json.dumps(e) for e in events) + sum(
        1 for b in bend+sw if b[1] == 'near_stop')
    out['fleet_sends'] = [{k: x.get(k) for k in ('action', 'place_id', 'turn_deg', 'expect', 'error')} |
                          {'gt': pt(x.get('gt')), 'reply_state': (x.get('reply') or {}).get('state')} for x in mine]
    after_halt = s.get('core_after_halt') or {}
    out['clean_end'] = {'hang': s.get('result') == 'hang', 'stop_sent': det.get('stop_sent'),
                        'core_state_after': after_halt.get('state'), 'core_cmd_after': after_halt.get('cmd'),
                        'trip_wall_s': s.get('trip_wall_s')}
    out['completed'] = s.get('result') == 'arrived'
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs')
    ap.add_argument('--json')
    a = ap.parse_args()
    root = Path(a.runs)
    sends = rows(root/'sends.jsonl')
    res = [analyze(r, sends) for r in sorted(root.iterdir()) if (r/'summary.json').exists()]
    for r in res:
        print(r['run'], r['result'], r['reason'], 'corner', r['corner_pass'], 'bend', r['bend'],
              'turn', r['turn_started'], r['turn_done'], 'reacq', r['reacquire'], 'stop', r['stop_at'],
              'holds', r['d422_holds'], 'near_stop', r['near_stop'], 'lane_return', [x['reason'] for x in r['lane_return']])
    n = len(res)
    agg = {k: sum(1 for r in res if v(r)) for k, v in {
        'corner_pass': lambda r: r['corner_pass'], 'bend_pass': lambda r: r['bend'] == 'pass',
        'turn_started': lambda r: r['turn_started'], 'turn_done': lambda r: r['turn_done'],
        'reacquire': lambda r: r['reacquire'], 'completed': lambda r: r['completed'],
        'hang': lambda r: r['clean_end']['hang']}.items()}
    print('n', n, agg)
    if a.json:
        Path(a.json).write_text(json.dumps({'n': n, 'aggregate': agg, 'runs': res}, indent=1))


if __name__ == '__main__':
    main()
