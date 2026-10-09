#!/usr/bin/env python3
"""D-507 addendum bend pass SIM probe (model PC only; never on the Windows laptop).

Plays Fleet for the 260919 SW bend: the bend place is the site map's (lane_graph map_v2_fleet +
one `bend` place), the map pose is Gazebo ground truth (d495/gt), and the fields come from Fleet's
own trip_ports.bend_geometry, bend_in = s_start - s along west:rev, sent as Fleet sends them
(within arm_distance_m 0.6 of the arc start on a straight approach (trip_ports.straight_approach), bend_tol_m = the 0.12 floor, refreshed at half the
15 s expiry). Records through the D-495 probe (log/cmd/keep/actions/events.jsonl, summary.json).
  python3 bend_probe.py --out runs/<name> --base http://127.0.0.1:8113 [--x --y --yaw]
"""
import argparse
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path[:0] = [str(REPO/'docs/validation/d495-junction-sim-2026-10-07/evidence'), str(REPO/'operations/fleet')]
from d495_sim_probe import Probe, brief, path_len  # noqa: E402
from fleet.routing.graph import build_graph  # noqa: E402
from fleet.server.trip_ports import bend_geometry, straight_approach  # noqa: E402
from fleet.site_map import SiteMap, SitePlace, from_lane_graph  # noqa: E402

MAP_ID = 'map_v2_fleet'  # bend_run.sh: site_floor_map_id
#: Vertex and headings fitted to lane_graph `west`. radius_m is the arc the robot drives inside the
#: lane (--radius): the lane_graph centre-line rounding is 0.064 m; an arc of r cuts the corner by
#: 0.176 r at the bisector (63.6 deg), so the URDF half width 0.05655 m stays inside the inner
#: tape's inner edge (0.080 m from the centre line, 0.094 m at the bisector) up to r = 0.21 m.
SW_BEND = dict(id='B_SW', name='SW bend', kind='bend', x=-0.6924, y=-0.5091,
               yaw=math.radians(63.58-180), exit_yaw=math.pi, radius_m=0.064)
SW_NODE = (-0.5216, -0.1682)
ARM_M, TOL_M, EXPIRES_S = 0.6, 0.12, 15.0
#: The SW roundabout entry (lane_graph node SW, the D-507 junction place) counts as reached here.
REACHED_M = 0.10


def lane(radius):
    SW_BEND['radius_m'] = radius
    base = from_lane_graph(REPO/'middleware/perception/map/map_v2_fleet/lane_graph.yaml', map_id=MAP_ID)
    site = SiteMap(map_id=MAP_ID, places=[*base.places, SitePlace(**SW_BEND)], edges=base.edges)
    arc = build_graph(site).arcs['west:rev']
    return arc, bend_geometry(SitePlace(**SW_BEND), arc)


def run(p, a):
    arc, (s_start, s_end, turn, radius) = lane(a.radius)
    # One place id per run: CORE keeps the last done (place_id, action) across mode changes (D-495
    # R1), as a trip does between two passes of the same bend through other places.
    place_id = 'B_SW_'+Path(a.out).name
    p.set_pose(a.x, a.y, a.yaw)
    t0 = p.t()
    p.mode('CAMERA_LINE')
    sent_at, states, result, done_at, sighting, node_m = None, [], None, None, None, math.inf
    end = time.monotonic()+a.duration
    while time.monotonic() < end and result is None:
        r = p.last()
        gt, j = r.get('gt'), r.get('junction') or {}
        key = [j.get('state'), j.get('reason'), r.get('state'), r.get('reason')]
        if not states or states[-1]['key'] != key:
            states.append({'key': key, **brief(r)})
        if gt:
            s = arc.project(gt[0], gt[1])[1]
            bend_in = round(s_start-s, 3)
            if (not a.no_bend and straight_approach(arc, s, s_start) and j.get('state') in (None, 'idle', 'armed') and done_at is None
                    and 0 < bend_in <= ARM_M
                    and (sent_at is None or time.monotonic()-sent_at > EXPIRES_S/2)):
                code, _ = p.call('POST', '/api/v1/line-follow/junction', {
                    'action': 'bend', 'place_id': place_id, 'expires_s': EXPIRES_S, 'turn_deg': round(turn, 1),
                    'map_id': MAP_ID, 'bend_in_m': bend_in, 'bend_tol_m': TOL_M, 'bend_radius_m': radius})
                if code == 200:  # as Fleet: JUNCTION_ODOM_STALE is sent again on the next tick
                    sent_at = time.monotonic()
        if sent_at is not None and j.get('state') == 'idle' and done_at is None and any(
                st['key'][0] in ('bending', 'reacquiring') for st in states):
            done_at = brief(r)
        if done_at is not None and gt:
            node_m = min(node_m, math.dist(gt[:2], SW_NODE))
            if sighting is None and (r.get('keep') in ('junction_transverse', 'junction_fork')
                                     or j.get('state') == 'waiting'):
                sighting = {**brief(r), 'to_sw_node_m': round(math.dist(gt[:2], SW_NODE), 3)}
        if j.get('state') in ('aborted', 'unresolved') or r.get('state') == 'LOST':
            result = j.get('state') if j.get('state') in ('aborted', 'unresolved') else 'LOST'
        elif done_at is not None and (node_m <= REACHED_M or sighting is not None):
            result = 'reached_roundabout'  # at the SW entry point, or the keeper saw a junction
        time.sleep(0.05)
    time.sleep(1.0)
    with p.lock:
        rows = [x for x in p.rows if x['t'] >= t0]
    fin = rows[-1] if rows else {}
    gt = fin.get('gt')
    return {'scenario': 'bend', 'start': [a.x, a.y, a.yaw], 'result': result or 'timeout',
            'bend': {'s_start': round(s_start, 3), 's_end': round(s_end, 3), 'turn_deg': round(turn, 2),
                     'radius_m': radius},
            'done': done_at, 'first_sighting_after_bend': sighting,
            'min_to_sw_node_m': None if node_m == math.inf else round(node_m, 3),
            'final': brief(fin) if fin else None,
            'final_to_sw_node_m': round(math.dist(gt[:2], SW_NODE), 3) if gt else None,
            'final_lane_offset_m': round(arc.project(gt[0], gt[1])[0], 3) if gt else None,
            'gt_path_m': path_len(rows), 'states': states[:60]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--x', type=float, default=-1.26955)
    ap.add_argument('--y', type=float, default=0.24255)
    ap.add_argument('--yaw', type=float, default=-1.5708)
    ap.add_argument('--duration', type=float, default=150.0)
    ap.add_argument('--radius', type=float, default=0.15)
    ap.add_argument('--no-bend', action='store_true', help='baseline: never send the bend')
    ap.add_argument('--base', default='http://127.0.0.1:8113')
    ap.add_argument('--token', default='rosy-dev-operator')
    a = ap.parse_args()
    p = Probe(a)
    try:
        summary = run(p, a)
    except Exception as e:  # noqa: BLE001 - keep the evidence of a broken run
        summary = {'scenario': 'bend', 'error': repr(e)}
    p.close(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
