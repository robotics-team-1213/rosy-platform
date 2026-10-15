#!/usr/bin/env python3
"""Two-robot Fleet + Gazebo lane trip bench on map_v2_fleet: each robot drives one lane trip.

    python tools/remote/remote_sim.py --host model --minutes 60 fleet_trips -- --render gpu
    python3 tools/sim/fleet_trips.py --out DIR [--render cpu|gpu] [--learned-lane-pointer DIR]

Runs on a sim host (never the laptop, D-584) with ROS Jazzy and a colcon install of gz_sim sourced
and CORE's pins plus the Fleet pins CORE lacks importable (remote_sim.py DEPS does all three).
The run owns its ROS domain (80-99), CORE/console ports and Gazebo partition (fleet_gazebo
Reservations, D-426) and a ~/rosy-jobs lock unless remote_sim already holds one. It launches
map_v2_fleet_multi_real (two camera robots, two COREs) with the regulated SIM CORE/Fleet settings
of the D-763 checks (line authority, trip lease), starts Fleet with the D-725 native Gazebo pose,
and sends each robot one lane trip TRIP_M along a straight lane-graph stretch to a stop place
seeded into site map version 1:
rosy_01 on the east road, rosy_02 on the west road. Pass = both trips `arrived` after moving.
result.json and the logs go to --out; tokens and configs stay in a temp run root.
`fleet` (internal) is the Fleet console with the native pose port bound to the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
GAZEBO = REPO / 'integrations/simulation/gazebo'
MAP = REPO / 'middleware/perception/map/map_v2_fleet'
WORLD = MAP / 'worlds/map_v2_fleet_real.world'
GRAPH = MAP / 'lane_graph.yaml'
URDF = REPO / 'middleware/devices/pinky/description/urdf/rosy_gz.urdf.xacro'
FLEET_PATHS = ('operations/fleet', 'contracts/foundation', 'contracts/learning/src', 'contracts/motion/src',
               'contracts/skill/src', 'operations/world/src', 'operations/execution/src',
               'operations/decision/src', 'tools/sim')
ROBOTS = ('rosy_01', 'rosy_02')
#: (segment, travel direction, start arc length m): straight stretches in the CCW travel direction,
#: clear of corners, crosswalks and the parking spur (lane_graph.yaml): the east road's south side
#: eastbound past its crosswalk to the corner, the west road's west side southbound to the spur.
TRIPS = {'rosy_01': ('east', 'rev', 0.92), 'rosy_02': ('west', 'rev', 1.00)}
#: Longer than Fleet's lane pass_window_m (0.3, trip_ports.py): within it Fleet sends the place's stop at
#: once and counts CORE holding it as arrived (run-2: `arrived` after 0.03 m of a 0.30 m trip).
TRIP_M = 0.42
SPEED_CAP = 0.08
TERMINAL = ('arrived', 'canceled', 'stopped', 'failed')
#: Marks this run's children so cleanup never touches a parent shell or another run.
MARK = 'FLEET_TRIPS_RUN'
RENDER = {'cpu': {'LIBGL_ALWAYS_SOFTWARE': '1', 'MESA_LOADER_DRIVER_OVERRIDE': 'llvmpipe'},
          'gpu': {'__EGL_VENDOR_LIBRARY_FILENAMES': '/usr/share/glvnd/egl_vendor.d/10_nvidia.json',
                  '__GLX_VENDOR_LIBRARY_NAME': 'nvidia'}}


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


def plan_trips(graph):
    """robot -> (spawn pose, trip end pose)."""
    return {ns: (lane_pose(graph, seg, way, s), lane_pose(graph, seg, way, s + TRIP_M))
            for ns, (seg, way, s) in TRIPS.items()}


def place_id(ns):
    return f'{ns}_end'


def seed_site_map(tasks_db):
    """Site map version 1 = the lane graph import plus each trip end as a stop place: a lane trip
    must end at a place (Fleet refuses LANE_END_NOT_A_PLACE). Fleet's own import then finds a map."""
    from fleet.server.site_map_store import SiteMapStore
    from fleet.site_map import SiteMap, from_lane_graph
    base = from_lane_graph(GRAPH, map_id=GRAPH.parent.name).model_dump(by_alias=True)
    ends = [dict(id=place_id(ns), name=place_id(ns), kind='stop', x=end[0], y=end[1], yaw=end[2])
            for ns, (_, end) in plan_trips(yaml.safe_load(GRAPH.read_text(encoding='utf-8'))).items()]
    SiteMapStore(Path(tasks_db)).import_if_empty(SiteMap.model_validate({**base, 'places': base['places'] + ends}),
                                                 source=GRAPH.name)


def call(url, token, method='GET', body=None, log=None):
    request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=8) as reply:
            code, text = reply.status, reply.read()
    except urllib.error.HTTPError as error:
        code, text = error.code, error.read()
    except OSError as error:
        code, text = 0, json.dumps({'error': repr(error)[:200]}).encode()
    try:
        value = json.loads(text or b'{}')
    except ValueError:
        value = {'raw': text[:200].decode('utf-8', 'replace')}
    if log is not None:
        log.write(json.dumps(dict(t=round(time.time(), 2), method=method, url=url, body=body,
                                  status=code, response=value)) + '\n')
    return code, value if isinstance(value, dict) else {'value': value}


def until(deadline_s, check, every=1.0):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(every)
    return False


def owned(run_id):
    """Pids of this run's children (MARK in their environment), never a parent or another run."""
    mine = []
    for folder in Path('/proc').iterdir():
        try:
            if folder.name.isdigit() and f'{MARK}={run_id}'.encode() in (folder / 'environ').read_bytes().split(b'\0'):
                mine.append(int(folder.name))
        except OSError:
            pass
    return mine


def stop(run_id):
    for sig, wait in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 3.0)):
        for pid in owned(run_id):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        until(wait, lambda: not owned(run_id), every=0.2)
    return owned(run_id)


def write_run(root, run_id, partition, reservations):
    """CORE overlays, Fleet manifest/site/users and the D-725 binding. Returns the operator token."""
    base = yaml.safe_load((GAZEBO / 'config/map_v2_fleet_core.yaml').read_text(encoding='utf-8'))
    sensors = yaml.safe_load((GAZEBO / 'config/sim_sensors_core.yaml').read_text(encoding='utf-8'))
    rows = []
    for ns, port in zip(ROBOTS, reservations.api_ports):
        rest, resolver = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        config = dict(base, **sensors)
        config.update(
            robot={'id': ns, 'name': f'SIM trips {ns}'},
            network={'api_host': '127.0.0.1', 'api_port': port},
            hardware_probe={'face_inputs_path': str(root / f'{ns}-face-inputs.json'),
                            'status_inputs_path': str(root / f'{ns}-status-inputs.json')},
            # The regulated lane drive of the D-763 checks: Fleet line authority, map entries,
            # route context, body path stop, calibrated IR guard (SIM_IR_CALIBRATION), site floor.
            line_follow={'bend_map_entry_enabled': True, 'turn_map_entry_enabled': True,
                         'authority_required': True, 'route_context_enabled': True, 'obstacle_mode': 'path',
                         'ir_guard_enabled': True, 'site_floor_map_id': 'map_v2_fleet',
                         'junction_signal_enabled': True},
            auth={'tokens': [{'token': rest, 'role': 'operator', 'label': f'{run_id} Fleet'},
                             {'token': resolver, 'role': 'stuck_resolver', 'label': f'{run_id} resolver'}]})
        (root / f'core_{ns}.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
        rows.append({'robot_id': ns, 'base_url': f'http://127.0.0.1:{port}', 'token': rest, 'resolver_token': resolver})
    (root / 'robots.yaml').write_text(yaml.safe_dump({'robots': rows}), encoding='utf-8')
    spec = {'run_id': run_id, 'core_config_dir': str(root), 'fleet_manifest': str(root / 'robots.yaml'),
            'hub_url': reservations.hub_url, 'gz_partition': partition,
            'ros_domain_id': reservations.ros_domain_id,
            'robots': [{'namespace': ns, 'api_port': port} for ns, port in zip(ROBOTS, reservations.api_ports)]}
    (root / 'run_spec.yaml').write_text(yaml.safe_dump(spec), encoding='utf-8')
    site = yaml.safe_load((GAZEBO / 'config/fleet_sim_camera_site.yaml').read_text(encoding='utf-8'))
    site['fleet']['traffic']['authority'] = True
    site['fleet']['trip_lease_required'] = True
    site['fleet']['trip_lease_ttl_s'] = 8.0  # D-760 1: longer than the 5 s line authority ttl
    (root / 'site.yaml').write_text(yaml.safe_dump(site), encoding='utf-8')
    operator = secrets.token_urlsafe(24)
    (root / 'users.yaml').write_text(yaml.safe_dump({'users': [{
        'principal_id': f'{run_id}-operator', 'role': 'operator',
        'token_sha256': hashlib.sha256(operator.encode()).hexdigest()}]}), encoding='utf-8')
    revision = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
    binding = dict(run_id=run_id, epoch=1, world='map_v2_fleet', map_id='map_v2_fleet', map_revision=1,
                   source_revision=revision, world_sha256=digest(WORLD), graph_sha256=digest(GRAPH),
                   urdf_sha256=digest(URDF), domain_id=reservations.ros_domain_id, partition=partition,
                   map_from_world=[0.0, 0.0, 0.0],
                   robots=[dict(robot_id=ns, model=ns, frame_id=ns + '/odom') for ns in ROBOTS])
    (root / 'binding.json').write_text(json.dumps(binding), encoding='utf-8')
    for name in ('robots.yaml', 'users.yaml'):
        (root / name).chmod(0o600)
    return operator


def drive(fleet, operator, trips, budget_s, log):
    """Plan and start one trip per robot, poll until both end. Returns the per-robot evidence."""
    rows = {}
    for ns in trips:
        code, plan = call(f'{fleet}/robots/{ns}/trip', operator, 'POST', {'to': place_id(ns), 'speed_cap': SPEED_CAP}, log)
        rows[ns] = {'plan_status': code, 'plan': plan, 'states': [], 'trip_id': None}
        if code == 200:
            code, started = call(f"{fleet}/trips/{plan['plan_id']}/start", operator, 'POST', {}, log)
            rows[ns].update(start_status=code, start=started, trip_id=plan['plan_id'] if code == 200 else None)
    open_rows = lambda: [r for r in rows.values() if r['trip_id'] and r['states'][-1:] not in [[s] for s in TERMINAL]]  # noqa: E731

    def poll():
        for row in open_rows():
            ns = next(n for n, r in rows.items() if r is row)
            _, view = call(f"{fleet}/trips/{row['trip_id']}", operator, log=log)
            _, pose = call(f'{fleet}/robots/{ns}/map-pose', operator, log=log)
            if view.get('state') not in row['states'][-1:]:
                row['states'].append(view.get('state'))
            row['last_view'] = view
            if isinstance(pose.get('x'), (int, float)) and isinstance(pose.get('y'), (int, float)):
                row['last_xy'] = (pose['x'], pose['y'])
        return not open_rows()

    until(budget_s, poll)
    for row in open_rows():
        row['cancel'] = call(f"{fleet}/trips/{row['trip_id']}/cancel", operator, 'POST', {}, log)
    for ns, row in rows.items():
        # From the spawn pose: polling starts after both starts, so its first sample can be late.
        moved = math.dist(trips[ns][0][:2], row['last_xy']) if 'last_xy' in row else 0.0
        row.update(moved_m=round(moved, 3), arrived=row['states'][-1:] == ['arrived'] and moved >= TRIP_M / 2)
    return rows


def run(args):
    sys.path.insert(0, str(REPO / 'tools/validation/fleet_gazebo'))
    from preflight import Reservations  # D-426 run reservations: domain 80-99, API/console ports
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    partition = os.environ.get('GZ_PARTITION') or f'trips-{secrets.token_hex(3)}'
    run_id = partition.lower()
    reservations = Reservations.derive(run_id, len(ROBOTS), started_at=time.time())
    for port in (*reservations.api_ports, reservations.console_port):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))  # an occupied port fails the run before anything starts
    jobs = Path.home() / 'rosy-jobs'
    lock = None if (jobs / f'{partition}.lock').exists() else jobs / f'fleet-trips-{os.getpid()}.lock'
    if lock is not None:  # standalone: tools/remote/AGENTS.md "<pid> sim <cores> <GB>"
        jobs.mkdir(exist_ok=True)
        lock.write_text(f'{os.getpid()} sim 6 8\n')
    root = Path(tempfile.mkdtemp(prefix='fleet-trips-'))
    operator = write_run(root, run_id, partition, reservations)
    manifest = yaml.safe_load((root / 'robots.yaml').read_text(encoding='utf-8'))['robots']
    rest = {row['robot_id']: row['token'] for row in manifest}
    cores = {row['robot_id']: row['base_url'] for row in manifest}
    fleet = f'http://127.0.0.1:{reservations.console_port}/api/fleet'
    trips = plan_trips(yaml.safe_load(GRAPH.read_text(encoding='utf-8')))
    env = dict(os.environ, GZ_PARTITION=partition, ROS_DOMAIN_ID=str(reservations.ros_domain_id), GZ_IP='127.0.0.1',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
               CYCLONEDDS_URI='file://' + str(REPO / 'middleware/devices/pinky/bringup/config/cyclonedds_localhost.xml'),
               **RENDER[args.render], **{MARK: run_id})
    launch = ['ros2', 'launch', 'gz_sim', 'map_v2_fleet_multi_real.launch.py', 'map_variant:=.',
              f'run_spec:={root / "run_spec.yaml"}',
              'spawn_poses:=' + ';'.join('%.5f,%.5f,%.6f' % trips[ns][0] for ns in ROBOTS)]
    if args.learned_lane_pointer:
        launch.append(f'learned_lane_pointer:={args.learned_lane_pointer}')
    fleet_cmd = [sys.executable, __file__, 'fleet', str(root / 'binding.json'), 'console',
                 '--robots', str(root / 'robots.yaml'), '--host', '127.0.0.1', '--port', str(reservations.console_port),
                 '--token-env', 'FLEET_TRIPS_TOKEN', '--tasks-db', str(root / 'tasks.sqlite'),
                 '--site-map-import', str(GRAPH), '--site-config', str(root / 'site.yaml'),
                 '--users-file', str(root / 'users.yaml')]
    result = dict(run_id=run_id, domain=reservations.ros_domain_id,
                  ports=[*reservations.api_ports, reservations.console_port],
                  learned_lane_pointer=args.learned_lane_pointer or None, render=args.render,
                  trips={ns: dict(zip(('segment', 'direction', 'start_s'), TRIPS[ns]), spawn=t[0], end=t[1])
                         for ns, t in trips.items()}, load_start=os.getloadavg())
    log = (out / 'api-log.jsonl').open('w', buffering=1)
    try:
        with (out / 'launch.log').open('w') as launch_log, (out / 'fleet.log').open('w') as fleet_log:
            subprocess.Popen(launch, env=env, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
            result['core_ready'] = until(args.boot_s, lambda: all(
                call(f'{cores[ns]}/api/v1/robot/state', rest[ns])[1].get('robot_id') == ns for ns in ROBOTS), 2.0)
            if result['core_ready']:
                subprocess.Popen(fleet_cmd, env=dict(env, FLEET_TRIPS_TOKEN=secrets.token_urlsafe(24)),
                                 stdout=fleet_log, stderr=subprocess.STDOUT, start_new_session=True)
                result['localized'] = until(180, lambda: all(
                    call(f'{fleet}/robots/{ns}/map-pose', operator)[1].get('state') == 'LOCALIZED'
                    for ns in ROBOTS), 2.0)
                result['camera'] = result['localized'] and until(120, lambda: all(
                    call(f'{cores[ns]}/api/v1/vision/front/status', rest[ns])[1].get('available') is True
                    for ns in ROBOTS), 2.0)
                if result['camera']:
                    time.sleep(args.settle_s)  # observers and lane keepers settle, as the lap probe does
                    result['robots'] = drive(fleet, operator, trips, args.budget_s, log)
    finally:
        log.close()
        result['load_end'] = os.getloadavg()
        result['left_running'] = stop(run_id)
        if lock is not None:
            lock.unlink(missing_ok=True)
    robots = result.get('robots') or {}
    result['pass'] = len(robots) == len(ROBOTS) and all(row['arrived'] for row in robots.values())
    (out / 'result.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k: result.get(k) for k in ('core_ready', 'localized', 'camera')}))
    print(json.dumps({ns: dict(states=row['states'], moved_m=row['moved_m']) for ns, row in robots.items()}))
    print('[fleet-trips]', 'PASS' if result['pass'] else 'FAIL', out / 'result.json', flush=True)
    return 0 if result['pass'] else 1


def fleet_console(binding_path, cli_args):
    """Fleet console with the D-725 native pose port: actual /clock and <ns>/odom, actual CORE reads."""
    import asyncio
    from contextlib import asynccontextmanager
    from dataclasses import asdict
    for rel in reversed(FLEET_PATHS):
        sys.path.insert(0, str(REPO / rel))
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from rosgraph_msgs.msg import Clock
    import fleet.server.app as app_module
    from fleet.cli import main as fleet_main
    from native_gazebo_map_pose import (NativeGazeboBinding, NativeGazeboMapPosePort, NativeGazeboSample,
                                        NativeRobotBinding)
    raw = json.loads(Path(binding_path).read_text(encoding='utf-8'))
    binding = NativeGazeboBinding(**dict(raw, map_from_world=tuple(raw['map_from_world']),
                                         robots=tuple(NativeRobotBinding(**r) for r in raw['robots'])))
    original = app_module.create_app

    def create_app(console, **kwargs):
        async def gather(robot_id):
            return await console._client(robot_id).state()
        port = NativeGazeboMapPosePort(binding, gather_core=gather)
        stopping, clock, pending = threading.Event(), [None], {}  # pending: robot -> (sample, wall, mono)
        rclpy.init()
        node = rclpy.create_node('fleet_trips_native_pose')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        stamp_ns = lambda stamp: stamp.sec * 1_000_000_000 + stamp.nanosec  # noqa: E731

        def join(robot_id):
            """A native frame is admitted against a /clock at or after its stamp, never refreshed (D-725 3)."""
            sample, wall, mono = pending[robot_id]
            if clock[0] is None or sample.stamp_ns > clock[0]:
                if max(time.time() - wall, time.monotonic() - mono) <= port.config.max_pair_s:
                    return
                port._fail(robot_id, 'native_join_timeout')
            else:
                port.observe(sample, clock_stamp_ns=clock[0], received_wall=wall, received_monotonic=mono)
            del pending[robot_id]

        def on_clock(msg):
            if port.observe_clock(stamp_ns(msg.clock)):
                clock[0] = stamp_ns(msg.clock)
                for robot_id in tuple(pending):
                    join(robot_id)

        def on_odom(robot, msg):
            wall, mono = time.time(), time.monotonic()
            if robot.robot_id in pending:  # an unjoined frame is never replaced
                port._fail(robot.robot_id, 'unjoined_native_replaced')
                return
            p, q = msg.pose.pose.position, msg.pose.pose.orientation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            pending[robot.robot_id] = (NativeGazeboSample(binding, robot.robot_id, robot.model, msg.header.frame_id,
                                                          stamp_ns(msg.header.stamp), (p.x, p.y, yaw)), wall, mono)
            join(robot.robot_id)

        node.create_subscription(Clock, '/clock', on_clock, qos)
        for robot in binding.robots:
            node.create_subscription(Odometry, f'/{robot.robot_id}/odom', lambda m, r=robot: on_odom(r, m), qos)

        def spin():
            while not stopping.is_set():
                rclpy.spin_once(node, timeout_sec=0.01)
                for robot_id in tuple(pending):
                    join(robot_id)

        kwargs.update(map_pose_port=port, simulation_pose_binding=asdict(binding), deployment_profile='simulation')
        app = original(console, **kwargs)
        lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def bound(app):
            async def refresh():  # actual CORE snapshots at 2 Hz (MapPose odom_stamp)
                while True:
                    await asyncio.gather(*(port.refresh(r.robot_id) for r in binding.robots), return_exceptions=True)
                    await asyncio.sleep(0.5)
            thread = threading.Thread(target=spin, name='native-pose', daemon=True)
            thread.start()
            async with lifespan(app):
                task = asyncio.create_task(refresh())
                try:
                    yield
                finally:
                    task.cancel()
                    stopping.set()
                    thread.join(timeout=3)
                    node.destroy_node()
                    rclpy.shutdown()
        app.router.lifespan_context = bound
        return app

    app_module.create_app = create_app
    seed_site_map(cli_args[cli_args.index('--tasks-db') + 1])
    return fleet_main(cli_args)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['fleet']:
        return fleet_console(argv[1], argv[2:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, help='new directory for result.json and logs')
    parser.add_argument('--render', choices=sorted(RENDER), default='cpu',
                        help='camera rendering: cpu (llvmpipe) or gpu (NVIDIA EGL; the model PC needs it)')
    parser.add_argument('--learned-lane-pointer', default='', help='model folder on this host; empty: denoise paint')
    parser.add_argument('--boot-s', type=float, default=300, help='wait for both COREs (includes Gazebo start)')
    parser.add_argument('--settle-s', type=float, default=30)
    parser.add_argument('--budget-s', type=float, default=240, help='wall time for both trips')
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
