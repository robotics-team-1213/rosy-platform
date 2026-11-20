#!/usr/bin/env python3
"""Nav2 ActionClient + /clock pause probe through the CORE API (D-953 check 2). One Gazebo run, three cases:
a goal -> ARRIVED, b goal -> cancel -> CANCELED, c goal with gz pause/unpause. ROSY_CORE_EXECUTOR comes from the env.
--slam (D-953 check 3): slam_toolbox instead of Nav2; POST slam/start, slam/save (answer < 3 s), slam/stop, then one
pilot recorder start/stop through /api/v1/recordings (the recorder node is started here; the sim launch has none).
    python3 tools/sim/nav_events_probe.py --out DIR [--slam]
"""
import argparse, json, math, os, secrets, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_trips as ft
import route_drive as rd


class Probe:
    """Counts messages on <ns>/cmd_vel and /clock (sim time) on a spin thread."""
    def __init__(self, ns):
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from rosidl_runtime_py.utilities import get_message
        from rosgraph_msgs.msg import Clock
        rclpy.init(); self.rclpy = rclpy
        self.node = rclpy.create_node('nav_events_probe')
        typ = subprocess.run(['ros2', 'topic', 'type', f'/{ns}/cmd_vel'], capture_output=True, text=True).stdout.strip()
        self.cmd_type = typ
        self.cmd_n, self.clock, self.clock_n, self.lock = 0, 0.0, 0, threading.Lock()
        q = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.node.create_subscription(get_message(typ), f'/{ns}/cmd_vel', self._cmd, q)
        self.node.create_subscription(Clock, '/clock', self._clock, q)
        self.stop = threading.Event()
        threading.Thread(target=self._spin, daemon=True).start()

    def _cmd(self, msg):
        with self.lock: self.cmd_n += 1

    def _clock(self, msg):
        with self.lock: self.clock, self.clock_n = msg.clock.sec + msg.clock.nanosec * 1e-9, self.clock_n + 1

    def _spin(self):
        while not self.stop.is_set():
            self.rclpy.spin_once(self.node, timeout_sec=0.1)

    def snap(self):
        with self.lock: return self.cmd_n, self.clock, self.clock_n

    def window(self, s):
        a = self.snap(); t = time.monotonic(); time.sleep(s); b = self.snap(); dt = time.monotonic() - t
        return dict(wall_s=round(dt, 2), cmd_vel_hz=round((b[0] - a[0]) / dt, 2), clock_hz=round((b[2] - a[2]) / dt, 2), sim_advance_s=round(b[1] - a[1], 3))


def gz(env, *args):
    return subprocess.run(['gz', *args], env=env, capture_output=True, text=True, timeout=30)


def world_control(env):
    out = gz(env, 'service', '-l').stdout.split()
    return next((s for s in out if s.startswith('/world/') and s.endswith('/control')), None)


def set_pause(env, svc, on):
    r = gz(env, 'service', '-s', svc, '--reqtype', 'gz.msgs.WorldControl', '--reptype', 'gz.msgs.Boolean',
           '--timeout', '5000', '--req', 'pause: true' if on else 'pause: false')
    return (r.stdout + r.stderr).strip()


def core_env_report(run_id):
    rows = []
    for pid in ft.owned(run_id):
        try:
            env = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
            cmd = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode()[:120]
        except OSError:
            continue
        var = [e.decode() for e in env if e.startswith(b'ROSY_CORE_EXECUTOR')]
        if 'core' in cmd and var or 'core.main' in cmd:
            rows.append(dict(pid=pid, cmd=cmd, var=var))
    return rows


def goal(core, tok, pt, log):
    code, reply = ft.call(f'{core}/api/v1/navigation/goal', tok, 'POST', {'x': pt['x'], 'y': pt['y'], 'correlation_id': 'nep-' + secrets.token_hex(3)}, log)
    return code, reply


def slam_case(env, run_id, core, tok, ns, log, settle_s):
    """slam start -> save (timed) -> stop, then a recorder request; every reply is kept as evidence."""
    api = lambda path, body=None: ft.call(f'{core}/api/v1/{path}', tok, 'POST', {} if body is None else body, log)  # noqa: E731
    c = {}
    c['start_ok'] = ft.until(120, lambda: api('slam/start')[0] == 200, 3.0)  # slam_toolbox lifecycle may still be coming up
    c['start'] = api('slam/start') if not c['start_ok'] else None
    time.sleep(settle_s)  # scans must have built a map before save_map has something to write
    t = time.monotonic(); code, rep = api('slam/save', {'name': 'zz_events_probe'}); dt = time.monotonic() - t
    c['save'] = dict(post=code, reply=rep, answer_s=round(dt, 2))
    c['stop'] = api('slam/stop')[0]
    root = tempfile.mkdtemp(prefix='nep-rec-')
    subprocess.Popen(['ros2', 'run', 'control', 'pilot_recorder_node', '--ros-args', '-r', f'__ns:=/{ns}', '-p', f'recording_root:={root}'],
                     env=env, start_new_session=True)
    time.sleep(8.0)
    t = time.monotonic(); r_code, r_rep = api('recordings'); r_dt = time.monotonic() - t
    time.sleep(3.0); s_code, s_rep = api('recordings/active/stop')
    c['recorder'] = dict(start_post=r_code, start_answer_s=round(r_dt, 2), start_reply=r_rep, stop_post=s_code, stop_reply=s_rep)
    c['ok'] = c['start_ok'] and code == 200 and dt < 3.0 and bool(rep.get('map_id')) and c['stop'] == 200 and r_code == 201
    return c


def pause_ok(c):
    """Case c verdict: sim time stood still while paused, then /clock and cmd_vel came back and the goal went on."""
    return (c['goal_post'] == 200 and c['paused']['sim_advance_s'] < 0.05 and c['resumed']['clock_hz'] > 1
            and c['resumed']['cmd_vel_hz'] > 5 and c['final'] in ('ARRIVED', 'NAVIGATING'))


def run_pass(cases, slam):
    """The run passes only when every expected case ran (1 with --slam, else 3) and each passed."""
    return bool(cases) and len(cases) == (1 if slam else 3) and all(c['ok'] for c in cases.values())


def run(args):
    sys.path.insert(0, str(ft.REPO / 'tools/validation/fleet_gazebo'))
    from preflight import Reservations
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    partition = os.environ.get('GZ_PARTITION') or f'nep-{secrets.token_hex(3)}'
    run_id = partition.lower()
    res = Reservations.derive(run_id, len(ft.ROBOTS), started_at=time.time())
    root = Path(tempfile.mkdtemp(prefix='nep-'))
    ft.write_run(root, run_id, partition, res, None, nav=True)
    manifest = yaml.safe_load((root / 'robots.yaml').read_text(encoding='utf-8'))['robots']
    token = {r['robot_id']: r['token'] for r in manifest}; cores = {r['robot_id']: r['base_url'] for r in manifest}
    graph = yaml.safe_load(ft.GRAPH.read_text(encoding='utf-8'))
    spawns, _, _ = ft.layout(graph, False)
    env = dict(os.environ, GZ_PARTITION=partition, ROS_DOMAIN_ID=str(res.ros_domain_id), GZ_IP='127.0.0.1',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
               CYCLONEDDS_URI='file://' + str(ft.cyclone_profile(root, True)), **ft.RENDER[args.render], **{ft.MARK: run_id})
    poses = 'spawn_poses:=' + ';'.join('%.5f,%.5f,%.6f' % tuple(spawns[n]) for n in ft.ROBOTS)
    launch = ['ros2', 'launch', 'gz_sim', 'map_v2_fleet_multi_real.launch.py', 'map_variant:=.', f'run_spec:={root / "run_spec.yaml"}', poses, 'nav_mode:=nav', 'loc_assist:=false']
    if args.slam:  # the two-camera wrapper only knows none|nav; gz_multi takes mode:=slam directly
        launch = ['ros2', 'launch', 'gz_sim', 'gz_multi.launch.py', f'robots:={len(ft.ROBOTS)}', 'prefix:=rosy', 'world_name:=map_v2_fleet_real.world',
                  'mode:=slam', 'headless:=true', 'nominal_camera:=true', 'core:=true', f'run_spec:={root / "run_spec.yaml"}', poses]
    result = dict(run_id=run_id, executor=os.environ.get('ROSY_CORE_EXECUTOR', 'events'), cases={})
    log = (out / 'api-log.jsonl').open('w', buffering=1)
    ns, probe = ft.ROBOTS[0], None
    core, tok = None, None
    try:
        with (out / 'launch.log').open('w') as ll:
            subprocess.Popen(launch, env=env, stdout=ll, stderr=subprocess.STDOUT, start_new_session=True)
            os.environ.update(env)
            core, tok = cores[ns], token[ns]
            result['core_ready'] = ft.until(args.boot_s, lambda: all(ft.call(f'{cores[r]}/api/v1/robot/state', token[r])[1].get('robot_id') == r for r in ft.ROBOTS), 2.0)
            result['core_env'] = core_env_report(run_id)
            result['nav2_active'] = not args.slam and result['core_ready'] and ft.until(240, lambda: all(rd.nav2_active(r, env) for r in ft.ROBOTS), 3.0)
            if result['nav2_active']:
                for r in ft.ROBOTS:
                    ft.call(f'{cores[r]}/api/v1/localization/initialpose', token[r], 'POST', dict(zip(('x', 'y', 'yaw'), spawns[r])), log)
                time.sleep(8.0)
            if args.slam and result['core_ready']:
                time.sleep(args.settle_s)
                result['cases']['slam'] = slam_case(env, run_id, core, tok, ns, log, 20.0)
            result['nav_ready'] = result['nav2_active'] and ft.until(240, lambda: all((rd.nav_state(cores[r], token[r]).get('readiness') or {}).get('ready') is True for r in ft.ROBOTS), 3.0)
            if result['nav_ready']:
                time.sleep(args.settle_s)
                probe = Probe(ns); result['cmd_type'] = probe.cmd_type
                svc = world_control(env); result['world_control'] = svc
                ev0 = ft.call(f'{core}/api/v1/events?limit=1', tok)[1].get('last_seq')
                pts = {k: rd.build_points(graph, 's', s)[0][0] for k, s in (('a', 1.3), ('b', 2.8), ('c', 3.6))}
                # a: goal -> ARRIVED
                code, rep = goal(core, tok, pts['a'], log); seen = []
                st = rd.wait_end(core, tok, args.budget_s, log, seen)
                result['cases']['a_goal'] = dict(post=code, accepted=rep.get('accepted'), seen=seen, final=st.get('navigation'), ok=code == 200 and st.get('navigation') == 'ARRIVED')
                # b: goal -> cancel -> CANCELED
                code, rep = goal(core, tok, pts['b'], log); seen = []
                ft.until(60, lambda: rd.nav_state(core, tok).get('navigation') in ('NAVIGATING', 'PLANNING'), 1.0)
                time.sleep(3.0)
                moving = probe.window(2.0)
                c_code, c_rep = ft.call(f'{core}/api/v1/navigation/cancel', tok, 'POST', {}, log)
                st = rd.wait_end(core, tok, 60, log, seen)
                result['cases']['b_cancel'] = dict(goal_post=code, cancel_post=c_code, cancel_reply=c_rep, final=st.get('navigation'), before_cancel=moving, ok=code == 200 and c_code == 200 and st.get('navigation') == 'CANCELED')
                time.sleep(2.0)
                # c: goal + gz pause/unpause
                code, rep = goal(core, tok, pts['c'], log)
                ft.until(60, lambda: rd.nav_state(core, tok).get('navigation') == 'NAVIGATING', 1.0)
                time.sleep(3.0)
                c = dict(goal_post=code, before=probe.window(3.0), pause_reply=set_pause(env, svc, True) if svc else 'no world control service')
                time.sleep(1.0); c['paused'] = probe.window(5.0); c['nav_while_paused'] = rd.nav_state(core, tok).get('navigation')
                c['api_while_paused'] = ft.call(f'{core}/api/v1/robot/state', tok)[0]
                c['unpause_reply'] = set_pause(env, svc, False) if svc else ''
                time.sleep(2.0); c['resumed'] = probe.window(5.0)
                st = rd.wait_end(core, tok, args.budget_s, log, [])
                c['final'] = st.get('navigation')
                c['ok'] = pause_ok(c)
                result['cases']['c_pause'] = c
                rows = ft.call(f'{core}/api/v1/events?limit=500&since_seq={ev0}', tok)[1].get('events') or []
                result['events'] = [r.get('type') for r in rows if str(r.get('type', '')).startswith('nav')]
    except Exception as exc:
        import traceback; result['error'] = traceback.format_exc()
    finally:
        log.close()
        if probe: probe.stop.set()
        result['left_running'] = ft.stop(run_id)
    result['pass'] = run_pass(result['cases'], args.slam)
    (out / 'result.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps(result, indent=1, default=str)[:6000])
    print('[nav-events-probe]', result['executor'], 'PASS' if result['pass'] else 'FAIL', flush=True)
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', required=True); p.add_argument('--render', choices=sorted(ft.RENDER), default='gpu')  # cpu (Mesa EGL) crashed the gz server on the model PC, 2026-11-20
    p.add_argument('--slam', action='store_true'); p.add_argument('--boot-s', type=float, default=300); p.add_argument('--settle-s', type=float, default=10); p.add_argument('--budget-s', type=float, default=420)
    sys.exit(run(p.parse_args()))
