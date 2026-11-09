#!/usr/bin/env python3
"""Route drive bench (D-1009): CORE `POST /navigation/route` on a Gazebo robot with Nav2, counting its stops.

    python tools/remote/remote_sim.py --host model --durable --minutes 60 route_drive -- --render gpu

Runs on a sim host (never the laptop, D-584), launching what fleet_trips.py --nav launches (two robots, one
COREs each, Nav2 + AMCL on the world map) and reusing its helpers. No Fleet. rosy_01 gets routes along the
east road of map_v2_fleet, each from the previous route's end. For each route the bench records /odom (sim
time) and counts the stops it made: stretches of |v| < 0.01 m/s lasting 0.8 s after the robot first moved.

    A  pppS    3 pass points then a stop        -> 1 stop
    B  ppSpS   two stops, passes between        -> 2 stops
    C  SSS     every point a stop               -> 3 stops
    D  qpS     q is 60 m off the costmap, so CORE skips it; p, S as usual -> 1 stop, skipped [0]
    E  the points of B sent as five single goals (the old way, 409 until each ends) -> 5 stops

Pass = every route ends ARRIVED with route.result succeeded, one POST and no 409 for A-D, observed stops equal
the stop points of the route (A-D), and E shows the stop-per-point behavior the route replaces.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_trips as ft  # noqa: E402

STEP_M = 0.2
START_S = 0.92 + ft.TRIP_M     # east road, past the straight trip's end
STOP_V, STOP_MIN_S, MOVING_V = 0.01, 0.8, 0.03
OFF_MAP = (60.0, 60.0)
ROUTES = {'A': 'pppS', 'B': 'ppSpS', 'C': 'SSS', 'D': 'qpS'}


class OdomTrace:
    """(sim seconds, |linear v|) from <ns>/odom on a spin thread."""

    def __init__(self, ns):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        rclpy.init()
        self.rclpy, self.samples, self.lock = rclpy, [], threading.Lock()
        self.node = rclpy.create_node('route_drive_trace')
        self.node.create_subscription(Odometry, f'/{ns}/odom', self._on, QoSProfile(
            depth=5, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.stopping = threading.Event()
        threading.Thread(target=self._spin, daemon=True).start()

    def _on(self, msg):
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        v = msg.twist.twist.linear
        with self.lock:
            self.samples.append((t, math.hypot(v.x, v.y)))

    def _spin(self):
        while not self.stopping.is_set():
            self.rclpy.spin_once(self.node, timeout_sec=0.05)

    def mark(self):
        with self.lock:
            return len(self.samples)

    def since(self, mark):
        with self.lock:
            return list(self.samples[mark:])

    def close(self):
        self.stopping.set()
        self.node.destroy_node()
        self.rclpy.shutdown()


def count_stops(samples):
    """Stops after the first motion: runs of |v| < STOP_V of at least STOP_MIN_S sim seconds. -> [(start, seconds)]"""
    stops, run_start, last, moved = [], None, None, False
    for t, v in samples:
        moved = moved or v > MOVING_V
        if not moved:
            continue
        if v < STOP_V:
            run_start = t if run_start is None else run_start
        elif run_start is not None:
            if t - run_start >= STOP_MIN_S:
                stops.append((round(run_start, 2), round(t - run_start, 2)))
            run_start = None
        last = t
    if run_start is not None and last is not None and last - run_start >= STOP_MIN_S:
        stops.append((round(run_start, 2), round(last - run_start, 2)))
    return stops


def build_points(graph, kinds, s_start):
    """Route body for `kinds` (p pass, S stop, q a pass point off the costmap) and the s after it."""
    points, s = [], s_start
    for kind in kinds:
        if kind == 'q':
            points.append({'x': OFF_MAP[0], 'y': OFF_MAP[1], 'kind': 'pass'})
            continue
        s += STEP_M
        x, y, _ = ft.lane_pose(graph, 'east', 'rev', s)
        points.append({'x': round(x, 3), 'y': round(y, 3), 'kind': 'pass' if kind == 'p' else 'stop'})
    return points, s


def nav_state(core, token):
    return ft.call(f'{core}/api/v1/navigation/state', token)[1]


def wait_end(core, token, budget_s, log):
    """Poll until navigation leaves PLANNING/NAVIGATING; returns the last state body."""
    end, state = time.monotonic() + budget_s, {}
    while time.monotonic() < end:
        state = nav_state(core, token)
        if state.get('navigation') in ('ARRIVED', 'FAILED', 'CANCELED', 'IDLE'):
            break
        time.sleep(1.0)
    log.write(json.dumps(dict(t=round(time.time(), 2), state=state)) + '\n')
    return state


def drive_route(core, token, trace, points, expected_stops, budget_s, log):
    mark = trace.mark()
    code, reply = ft.call(f'{core}/api/v1/navigation/route', token, 'POST',
                          {'points': points, 'correlation_id': 'route-' + secrets.token_hex(3)}, log)
    row = {'post': code, 'points': len(points), 'expected_stops': expected_stops}
    if code != 200:
        return dict(row, reply=reply, ok=False)
    state = wait_end(core, token, budget_s, log)
    time.sleep(3.0)
    stops = count_stops(trace.since(mark))
    route = state.get('route') or {}
    row.update(navigation=state.get('navigation'), route_result=route.get('result'), stops_made=route.get('stops_made'),
               actions=route.get('actions'), skipped=route.get('skipped'), observed_stops=stops)
    row['ok'] = (row['navigation'] == 'ARRIVED' and route.get('result') == 'succeeded'
                 and route.get('stops_made') == expected_stops and len(stops) == expected_stops)
    return row


def drive_goals(core, token, trace, points, budget_s, log):
    """The old way: one single goal per point, the next only after the last ended (409 until then)."""
    mark, conflicts, deadline = trace.mark(), 0, time.monotonic() + budget_s
    for point in points:
        while time.monotonic() < deadline:
            code, _ = ft.call(f'{core}/api/v1/navigation/goal', token, 'POST', {'x': point['x'], 'y': point['y']}, log)
            if code == 200:
                break
            conflicts += code == 409
            time.sleep(1.0)
        wait_end(core, token, deadline - time.monotonic(), log)
    time.sleep(3.0)
    stops = count_stops(trace.since(mark))
    return {'points': len(points), 'conflicts': conflicts, 'observed_stops': stops, 'ok': len(stops) >= len(points) - 1}


def run(args):
    sys.path.insert(0, str(ft.REPO / 'tools/validation/fleet_gazebo'))
    from preflight import Reservations
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    partition = os.environ.get('GZ_PARTITION') or f'route-{secrets.token_hex(3)}'
    run_id = partition.lower()
    reservations = Reservations.derive(run_id, len(ft.ROBOTS), started_at=time.time())
    for port in reservations.api_ports:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    jobs = Path.home() / 'rosy-jobs'
    lock = None if (jobs / f'{partition}.lock').exists() else jobs / f'route-drive-{os.getpid()}.lock'
    if lock is not None:
        jobs.mkdir(exist_ok=True)
        lock.write_text(f'{os.getpid()} sim 6 8\n')
    root = Path(tempfile.mkdtemp(prefix='route-drive-'))
    ft.write_run(root, run_id, partition, reservations, None, nav=True)
    manifest = yaml.safe_load((root / 'robots.yaml').read_text(encoding='utf-8'))['robots']
    token = {row['robot_id']: row['token'] for row in manifest}
    cores = {row['robot_id']: row['base_url'] for row in manifest}
    graph = yaml.safe_load(ft.GRAPH.read_text(encoding='utf-8'))
    spawns, _, _ = ft.layout(graph, False)
    env = dict(os.environ, GZ_PARTITION=partition, ROS_DOMAIN_ID=str(reservations.ros_domain_id), GZ_IP='127.0.0.1',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
               CYCLONEDDS_URI='file://' + str(ft.cyclone_profile(root, True)), **ft.RENDER[args.render], **{ft.MARK: run_id})
    launch = ['ros2', 'launch', 'gz_sim', 'map_v2_fleet_multi_real.launch.py', 'map_variant:=.',
              f'run_spec:={root / "run_spec.yaml"}',
              'spawn_poses:=' + ';'.join('%.5f,%.5f,%.6f' % tuple(spawns[ns]) for ns in ft.ROBOTS), 'nav_mode:=nav']
    result = dict(run_id=run_id, render=args.render, load_start=os.getloadavg(), routes={})
    log = (out / 'api-log.jsonl').open('w', buffering=1)
    ns, trace = ft.ROBOTS[0], None
    try:
        with (out / 'launch.log').open('w') as launch_log:
            subprocess.Popen(launch, env=env, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
            os.environ.update(env)
            result['core_ready'] = ft.until(args.boot_s, lambda: all(
                ft.call(f'{cores[r]}/api/v1/robot/state', token[r])[1].get('robot_id') == r for r in ft.ROBOTS), 2.0)
            result['localized'] = result['core_ready'] and ft.until(180, lambda: all(
                ft.localize(cores[r], token[r], spawns[r], log) for r in ft.ROBOTS), 3.0)
            if result['localized']:
                time.sleep(args.settle_s)
                trace = OdomTrace(ns)
                s = START_S
                for name, kinds in ROUTES.items():
                    points, s = build_points(graph, kinds, s)
                    result['routes'][name] = dict(kinds=kinds, **drive_route(
                        cores[ns], token[ns], trace, points, kinds.count('S'), args.budget_s, log))
                    result['routes'][name]['points_body'] = points
                if args.baseline:
                    points, _ = build_points(graph, ROUTES['B'], s)
                    result['routes']['E'] = dict(kinds='goals:' + ROUTES['B'],
                                                 **drive_goals(cores[ns], token[ns], trace, points, args.budget_s, log))
    finally:
        log.close()
        if trace is not None:
            trace.close()
        result['load_end'] = os.getloadavg()
        result['left_running'] = ft.stop(run_id)
        if lock is not None:
            lock.unlink(missing_ok=True)
    rows = result['routes']
    result['pass'] = bool(rows) and all(row.get('ok') for row in rows.values()) and len(rows) == len(ROUTES) + args.baseline
    (out / 'result.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    for name, row in rows.items():
        print(name, json.dumps({k: row.get(k) for k in ('kinds', 'post', 'navigation', 'stops_made', 'skipped', 'actions',
                                                         'conflicts', 'ok')}), 'observed stops:', len(row.get('observed_stops', [])))
    print('[route-drive]', 'PASS' if result['pass'] else 'FAIL', out / 'result.json', flush=True)
    return 0 if result['pass'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, help='new directory for result.json and logs')
    parser.add_argument('--render', choices=sorted(ft.RENDER), default='cpu')
    parser.add_argument('--boot-s', type=float, default=300)
    parser.add_argument('--settle-s', type=float, default=10)
    parser.add_argument('--budget-s', type=float, default=420, help='wall time per route')
    parser.add_argument('--no-baseline', dest='baseline', action='store_false', help='skip route E (the old single goals)')
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
