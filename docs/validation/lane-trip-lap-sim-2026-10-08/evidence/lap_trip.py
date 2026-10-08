#!/usr/bin/env python3
"""D-507 B13 lap SIM: one Fleet trip (POST /trip + /start) from the west road, recorded.

Model PC only. Records through the D-495 probe (log/cmd/keep/actions/events.jsonl) plus
trip.jsonl (GET /api/fleet/trips/{id} every 0.5 s with ground truth) and summary.json.
Before the run: CORE's junction memories are cleared (dark inner block, CAMERA_LINE 4 sim s,
one 'straight' for a throw-away place so the last done (place, action) is not one of the trip's),
then the robot is teleported to the start and CAMERA_LINE is selected, as an operator does.
  python3 lap_trip.py --out runs/<name> [--to NW] [--x -1.26955 --y 0.24255 --yaw -1.5708]
"""
import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path[:0] = [str(REPO/'docs/validation/d495-junction-sim-2026-10-07/evidence')]
from d495_sim_probe import Probe, brief, path_len  # noqa: E402

OPEN = ('started', 'running')


def fleet(a, method, path, body=None):
    req = urllib.request.Request(a.fleet+path, data=None if body is None else json.dumps(body).encode(),
                                 method=method, headers={'Authorization': f'Bearer {a.fleet_token}',
                                                         'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        return 0, {'error': str(e)}


def forget(p, tag):
    """D-495 probe set_pose(forget) + one throw-away instruction (CORE R1 done-place memory)."""
    p.mode('OFF')
    time.sleep(0.5)
    p._teleport(-0.95, 0.0, math.pi/2)
    p.mode('CAMERA_LINE')
    p.junction('straight', f'RESET_{tag}', expires_s=5)
    t_sim = p.get('sim_t') or 0.0
    while (p.get('sim_t') or 0.0)-t_sim < 4.0:
        time.sleep(0.2)
    p.action('forget', state=p.last().get('state'), reason=p.last().get('reason'), junction=p.last().get('junction'))
    p.mode('OFF')
    time.sleep(0.5)


def run(p, a):
    forget(p, Path(a.out).name)
    p._teleport(a.x, a.y, a.yaw)
    code, resp = p.mode('CAMERA_LINE')
    t0 = p.t()
    code, plan = fleet(a, 'POST', f'/api/fleet/robots/{a.robot}/trip', {'to': a.to})
    p.action('fleet', path='trip', code=code, resp=plan)
    if code != 200:
        return {'result': 'plan_refused', 'code': code, 'resp': plan}
    code, view = fleet(a, 'POST', f"/api/fleet/trips/{plan['plan_id']}/start")
    p.action('fleet', path='start', code=code, resp=view)
    if code != 200:
        return {'result': 'start_refused', 'code': code, 'resp': view}
    trip_id = view['trip_id']
    rows, hang = [], False
    end = time.monotonic()+a.timeout
    with open(p.out/'trip.jsonl', 'w') as f:
        while True:
            code, view = fleet(a, 'GET', f'/api/fleet/trips/{trip_id}')
            r = p.last()
            row = {'t': p.t(), 'sim_t': p.get('sim_t'), 'gt': r.get('gt'), 'code': code,
                   **{k: view.get(k) for k in ('state', 'reason', 'segment_index', 'current_edge', 'next_place',
                                               'next_action', 'hold', 'detail', 'traffic')}}
            f.write(json.dumps(row)+'\n')
            f.flush()
            rows.append(row)
            if code == 200 and view.get('state') not in OPEN:
                break
            if time.monotonic() > end:
                hang = True
                code, resp = fleet(a, 'POST', f'/api/fleet/trips/{trip_id}/cancel')
                p.action('fleet', path='cancel', code=code, resp=resp)
                break
            time.sleep(0.5)
    time.sleep(3.0)  # the halt and CORE's answer to it
    code, final = fleet(a, 'GET', f'/api/fleet/trips/{trip_id}')
    with p.lock:
        log = [x for x in p.rows if x['t'] >= t0]
    return {'result': 'hang' if hang else final.get('state'), 'reason': final.get('reason'),
            'trip_id': trip_id, 'plan': {k: plan.get(k) for k in ('segments', 'places', 'actions', 'length_m')},
            'final_view': final, 'trip_wall_s': round(rows[-1]['t']-t0, 1),
            'sim_s': round((log[-1].get('sim_t') or 0)-(log[0].get('sim_t') or 0), 1) if log else None,
            'gt_path_m': path_len(log), 'final': brief(log[-1]) if log else None,
            'core_after_halt': {k: p.last().get(k) for k in ('state', 'reason', 'junction', 'cmd', 'odom')}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--x', type=float, default=-1.26955)
    ap.add_argument('--y', type=float, default=0.24255)
    ap.add_argument('--yaw', type=float, default=-1.5708)
    ap.add_argument('--to', default='NW')
    ap.add_argument('--timeout', type=float, default=900.0)
    ap.add_argument('--robot', default='rosy_sim')
    ap.add_argument('--base', default='http://127.0.0.1:8188')
    ap.add_argument('--token', default='rosy-dev-operator')
    ap.add_argument('--fleet', default='http://127.0.0.1:8189')
    ap.add_argument('--fleet-token', default='lap-operator')
    a = ap.parse_args()
    p = Probe(a)
    try:
        summary = run(p, a)
    except Exception as e:  # noqa: BLE001 - keep the evidence of a broken run
        summary = {'result': 'error', 'error': repr(e)}
    p.close(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
