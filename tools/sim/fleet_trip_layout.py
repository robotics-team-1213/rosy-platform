"""Where the fleet_trips run puts its robots, trips and stops (lane geometry only; no process, no network)."""

from __future__ import annotations

import math

#: (segment, travel direction, start arc length m): straight stretches in the CCW travel direction,
#: clear of corners, crosswalks and the parking spur (lane_graph.yaml): the east road's south side
#: eastbound past its crosswalk to the corner, the west road's west side southbound to the spur.
TRIPS = {'rosy_01': ('east', 'rev', 0.92), 'rosy_02': ('west', 'rev', 1.00)}
#: Longer than Fleet's lane pass_window_m (0.3, trip_ports.py): within it Fleet sends the place's stop at
#: once and counts CORE holding it as arrived (run-2: `arrived` after 0.03 m of a 0.30 m trip).
TRIP_M = 0.42
SPEED_CAP = 0.08
#: --lap via place: the west road's west side, where the straight rosy_02 trip starts.
LAP_VIA = ('west', 'rev', 1.00)
#: --nav (D-1003): (tx, ty, yaw) of the site map from the world. The site map is the world turned and moved, so a
#: free goal sent in site coordinates lands metres off each robot's own Nav2 map (the world map); arriving proves
#: Fleet sent it in the robot's frame.
NAV_SITE_FROM_WORLD = (2.0, 3.0, math.pi / 2)


def lane_pose(graph, segment, direction, s):
    """(x, y, yaw) at arc length s along a lane-graph segment in its travel direction."""
    points = graph['segments'][segment]['points']
    points = points if direction == 'fwd' else points[::-1]
    walked = 0.0
    for a, b in zip(points, points[1:]):
        step = math.dist(a, b)
        if walked + step >= s:
            t = (s - walked) / step
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), math.atan2(b[1] - a[1], b[0] - a[0])
        walked += step
    raise ValueError(f'{segment} is shorter than {s} m')


def to_site(pose, nav=True):
    """A world (x, y[, yaw]) in the run's site frame; unchanged without --nav."""
    if not nav:
        return tuple(pose)
    tx, ty, turn = NAV_SITE_FROM_WORLD
    c, s = math.cos(turn), math.sin(turn)
    xy = (tx + c * pose[0] - s * pose[1], ty + s * pose[0] + c * pose[1])
    return xy + tuple(math.atan2(math.sin(a + turn), math.cos(a + turn)) for a in pose[2:3])


def nav_site_map(base):
    """--nav: the lane graph import in the site frame with every edge ``free`` (Fleet drives it with Nav2 goals).
    Crosswalks are lane-drive checks and are left out."""
    turn = lambda a: None if a is None else to_site((0.0, 0.0, a))[2]  # noqa: E731
    places = [dict(p, x=to_site((p['x'], p['y']))[0], y=to_site((p['x'], p['y']))[1], yaw=turn(p.get('yaw')),
                   exit_yaw=turn(p.get('exit_yaw'))) for p in base['places']]
    edges = [dict(e, drive_mode='free', polyline=[list(to_site(q)) for q in e['polyline']]) for e in base['edges']]
    return {**base, 'places': places, 'edges': edges, 'crosswalks': []}


def plan_trips(graph):
    """robot -> (spawn pose, trip end pose)."""
    return {ns: (lane_pose(graph, seg, way, s), lane_pose(graph, seg, way, s + TRIP_M))
            for ns, (seg, way, s) in TRIPS.items()}


def place_id(ns):
    return f'{ns}_end'


#: --depart: each onward stop is this far past the one before (longer than Fleet's lane pass_window_m 0.3)
HOP_M = 0.35


def onward_id(ns, k):
    return f'{ns}_stop{k}'


def layout(graph, lap=False, depart=0):
    """(spawn pose per robot, stop places {id: pose}, trip request per robot that drives).
    --lap: rosy_01 drives one D-517 finite lap (start_at) from its east start via the west road and
    back, so it passes both outer loops, the ring twice and every corner; rosy_02 waits off the
    loop on the parking spot."""
    trips = plan_trips(graph)
    if isinstance(lap, str) and lap not in ('', '1'):   # --scenario NAME: one short drive over one place
        from lap_scenarios import SCENARIOS, route_pose
        start, end = (route_pose(graph, d, lane_pose) for d in SCENARIOS[lap][:2])
        return ({'rosy_01': start, 'rosy_02': tuple(graph['parking']['spot'])}, {'scenario_end': end},
                {'rosy_01': {'to': 'scenario_end', 'speed_cap': SPEED_CAP}})
    if not lap:
        places = {place_id(ns): t[1] for ns, t in trips.items()}
        for k in range(1, int(depart) + 1):  # --depart N: N more stops onward along the same stretch, travel direction kept
            places.update({onward_id(ns, k): lane_pose(graph, seg, way, s + TRIP_M + HOP_M * k)
                           for ns, (seg, way, s) in TRIPS.items()})
        return ({ns: t[0] for ns, t in trips.items()}, places,
                {ns: {'to': place_id(ns), 'speed_cap': SPEED_CAP} for ns in trips})
    start = trips['rosy_01'][0]
    return ({'rosy_01': start, 'rosy_02': tuple(graph['parking']['spot'])},
            {'lap_start': start, 'lap_via': lane_pose(graph, *LAP_VIA)},
            {'rosy_01': {'to': 'lap_start', 'via': ['lap_via'], 'start_at': 'lap_start', 'speed_cap': SPEED_CAP}})
