#!/usr/bin/env python3
"""D-573 (g) crosswalk baseline: one lane run across the west-road crosswalk, with or without a pedestrian.

Model PC only (Gazebo). Runs against a running xwalk_sim.sh (the D-495 launch on map_v2_fleet_real)
and xwalk_batch.sh's lap_fleet.py. The robot starts on the west road heading south, CAMERA_LINE is
selected and a Fleet trip to NW is started, exactly as lap_trip.py does; the trip crosses the D-491
crosswalk 1 (lane_graph.yaml crosswalks[0]) after about 0.3 m. One pedestrian model from
integrations/simulation/gazebo/models is spawned on the lane centre in the middle of the crosswalk.
The run ends when the body front is 0.15 m past the crosswalk far edge, when the robot has stood
still for HOLD_END_S sim seconds, or after MAX_SIM_S sim seconds; then the trip is cancelled.

  python3 xwalk_run.py --out runs/<name> --ped legs|fig150|fig100|none
  python3 xwalk_run.py --self-check      # scoring on synthetic rows, no ROS/Gazebo

Scoring (score()): body front = gt + body_front_x_m along the heading. 'stop' = |odom v| < STOP_V
for at least STOP_MIN_S sim s after the robot first moved. A stop before the near edge is recorded
with CORE's line-follow state/reason, so an obstacle stop (D-344 §11 / D-422) is told apart from a
D-573 crosswalk gate stop (no such reason exists in CORE yet). Collision = front gap to the
pedestrian's near surface <= COLLIDE_M (static models: the robot cannot pass through).
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
MODELS = REPO/'integrations/simulation/gazebo/models'

# lane_graph.yaml crosswalks[0]: x -1.343..-1.197, y -0.206..-0.086 (west road, lane centre x -1.2696).
LANE_X = -1.2696
NEAR_Y, FAR_Y = -0.086, -0.206          # heading south: near edge first
PED_Y = (NEAR_Y+FAR_Y)/2
BODY_FRONT_X = 0.04205                  # pinky profile core.yaml body_front_x_m
START = (-1.26955, 0.24255, -1.5708)    # lap_trip.py default start
PEDS = {  # name -> (model dir, half depth along the road = radius)
    'legs': ('crosswalk_pedestrian_legs', 0.02),
    'fig150': ('crosswalk_figurine_150', 0.02),
    'fig100': ('crosswalk_figurine_100', 0.02),
    'none': (None, 0.0),
}
STOP_V, STOP_MIN_S, COLLIDE_M = 0.005, 1.0, 0.003
PASS_M, HOLD_END_S, MAX_SIM_S = 0.15, 12.0, 60.0


def front(gt):
    x, y, yaw = gt
    return x+math.cos(yaw)*BODY_FRONT_X, y+math.sin(yaw)*BODY_FRONT_X


def score(rows, ped):
    """rows: recorded log rows (sim_t, gt, odom, state, reason). Returns the verdict dict."""
    rows = [r for r in rows if r.get('gt') and r.get('odom') and r.get('sim_t') is not None]
    if not rows:
        return {'verdict': 'no_data'}
    half = PEDS[ped][1]
    moved, stops, cur = False, [], None
    min_gap, max_v, max_v_zone = None, 0.0, 0.0
    for r in rows:
        fy = front(r['gt'])[1]
        v = abs(r['odom'][3])
        max_v = max(max_v, v)
        if FAR_Y <= fy <= NEAR_Y:
            max_v_zone = max(max_v_zone, v)
        if ped != 'none':
            gap = fy-(PED_Y+half)
            min_gap = gap if min_gap is None else min(min_gap, gap)
        if v > 0.03:
            moved = True
        if moved and v < STOP_V:
            if cur is None:
                cur = {'t0': r['sim_t'], 'edge_m': round(fy-NEAR_Y, 3), 'state': r.get('state'),
                       'reason': r.get('reason'), 'keep': r.get('keep'), 'body_gap_m': r.get('body_gap_m'),
                       'clearance_source': r.get('clearance_source')}
            cur['t1'] = r['sim_t']
        elif cur is not None:
            stops.append(cur)
            cur = None
    if cur is not None:
        stops.append(cur)
    stops = [dict(s, dur_s=round(s['t1']-s['t0'], 1)) for s in stops if s['t1']-s['t0'] >= STOP_MIN_S]
    before = [s for s in stops if s['edge_m'] > 0]
    last_fy = front(rows[-1]['gt'])[1]
    collided = min_gap is not None and min_gap <= COLLIDE_M
    return {
        'verdict': ('collision' if collided else 'passed' if last_fy < FAR_Y
                    else 'stopped_before' if before else 'other'),
        'stopped_before_crosswalk': bool(before),
        'first_stop': before[0] if before else (stops[0] if stops else None),
        'stops': stops,
        'entered_crosswalk': any(front(r['gt'])[1] <= NEAR_Y for r in rows),
        'passed_crosswalk': last_fy < FAR_Y,
        'min_gap_to_ped_m': None if min_gap is None else round(min_gap, 3),
        'collision': collided,
        'max_speed_mps': round(max_v, 3),
        'max_speed_in_zone_mps': round(max_v_zone, 3),
        'end_front_to_near_edge_m': round(last_fy-NEAR_Y, 3),
        'sim_s': round(rows[-1]['sim_t']-rows[0]['sim_t'], 1),
    }


def spawn(p, ped):
    from d495_sim_probe import gz
    model = PEDS[ped][0]
    sdf = (MODELS/model/'model.sdf').read_text()
    req = (f'sdf: {json.dumps(sdf)}, name: "xwalk_ped", allow_renaming: false, '
           f'pose: {{position: {{x: {LANE_X}, y: {PED_Y}, z: 0}}}}')
    return p.action('spawn', ped=ped, model=model, x=LANE_X, y=PED_Y, rep=gz('create', 'gz.msgs.EntityFactory', req))


def unspawn(p):
    from d495_sim_probe import gz
    return p.action('unspawn', rep=gz('remove', 'gz.msgs.Entity', 'name: "xwalk_ped", type: MODEL'))


def run(p, a):
    from lap_trip import fleet, forget
    unspawn(p)  # a model left by a broken earlier run
    forget(p, Path(a.out).name)
    if a.ped != 'none':
        spawn(p, a.ped)
    p._teleport(*START)
    p.mode('CAMERA_LINE')
    t0 = p.t()
    code, plan = fleet(a, 'POST', f'/api/fleet/robots/{a.robot}/trip', {'to': 'NW'})
    p.action('fleet', path='trip', code=code, resp=plan)
    if code != 200:
        return {'result': 'plan_refused', 'code': code, 'resp': plan}
    code, view = fleet(a, 'POST', f"/api/fleet/trips/{plan['plan_id']}/start")
    p.action('fleet', path='start', code=code, resp=view)
    if code != 200:
        return {'result': 'start_refused', 'code': code, 'resp': view}
    sim0, still, end = p.get('sim_t') or 0.0, None, 'max_sim'
    while (p.get('sim_t') or 0.0)-sim0 < MAX_SIM_S:
        r = p.last()
        if r.get('gt') and front(r['gt'])[1] < FAR_Y-PASS_M:
            end = 'passed'
            break
        odom, st = r.get('odom'), r.get('sim_t') or 0.0
        if odom and abs(odom[3]) < STOP_V and st-sim0 > 5.0:
            still = st if still is None else still
            if st-still >= HOLD_END_S:
                end = 'held'
                break
        else:
            still = None
        time.sleep(0.2)
    _, trip = fleet(a, 'GET', f"/api/fleet/trips/{view['trip_id']}")
    p.action('fleet', path='trip_view', resp=trip)
    code, resp = fleet(a, 'POST', f"/api/fleet/trips/{view['trip_id']}/cancel")
    p.action('fleet', path='cancel', code=code, resp=resp)
    p.mode('OFF')
    time.sleep(1.0)
    with p.lock:
        rows = [x for x in p.rows if x['t'] >= t0]
    if a.ped != 'none':
        unspawn(p)
    return {'result': end, 'ped': a.ped, 'trip_id': view['trip_id'],
            'trip_at_end': {k: trip.get(k) for k in ('state', 'reason', 'hold', 'detail')}, **score(rows, a.ped)}


def self_check():
    """Synthetic rows: a run that stops 0.05 m before the edge, one that hits, one that passes."""
    def rows(stop_y=None, v=0.08, dt=0.1, n=200):
        out, y, t = [], START[1], 0.0
        for _ in range(n):
            fy = y-BODY_FRONT_X
            moving = stop_y is None or fy > stop_y
            out.append({'sim_t': t, 'gt': (LANE_X, y, -math.pi/2), 'odom': (0, 0, 0, v if moving else 0.0, 0),
                        'state': 'running' if moving else 'holding', 'reason': None if moving else 'obstacle_ahead'})
            y -= v*dt if moving else 0.0
            t += dt
        return out
    s = score(rows(stop_y=NEAR_Y+0.05), 'legs')
    assert s['verdict'] == 'stopped_before' and s['first_stop']['reason'] == 'obstacle_ahead', s
    assert abs(s['first_stop']['edge_m']-0.05) < 0.01 and not s['collision'], s
    s = score(rows(stop_y=PED_Y+0.02), 'fig100')
    assert s['verdict'] == 'collision' and s['entered_crosswalk'], s
    s = score(rows(), 'none')
    assert s['verdict'] == 'passed' and not s['stops'] and s['min_gap_to_ped_m'] is None, s
    pause = rows(stop_y=0.10)[:60] + [dict(r, sim_t=r['sim_t']+6.0) for r in rows()[25:]]
    s = score(pause, 'none')
    assert s['verdict'] == 'passed' and s['stopped_before_crosswalk'], s
    assert set(PEDS) - {'none'} == {k for k, (m, _) in PEDS.items() if m and (MODELS/m/'model.sdf').is_file()}
    print('self-check OK')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-check', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('--ped', choices=sorted(PEDS), default='none')
    ap.add_argument('--robot', default='rosy_sim')
    ap.add_argument('--base', default='http://127.0.0.1:8661')
    ap.add_argument('--token', default='rosy-dev-operator')
    ap.add_argument('--fleet', default='http://127.0.0.1:8662')
    ap.add_argument('--fleet-token', default='lap-operator')
    a = ap.parse_args()
    if a.self_check:
        return self_check()
    sys.path[:0] = [str(REPO/'docs/validation/d495-junction-sim-2026-10-07/evidence'),
                    str(REPO/'docs/validation/lane-trip-lap-sim-2026-10-08/evidence')]
    from lap_trip import LapProbe
    p = LapProbe(a)
    try:
        summary = run(p, a)
    except Exception as e:  # noqa: BLE001 - keep the evidence of a broken run
        summary = {'result': 'error', 'error': repr(e)}
    p.close(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
