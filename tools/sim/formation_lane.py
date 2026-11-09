#!/usr/bin/env python3
"""D-1002 formation driving on the site lane map: a Nav2 leader and TRAIL followers in Gazebo, Gazebo truth scored.

    python tools/remote/remote_sim.py --host model --minutes 40 cmd -- \
        python3 tools/sim/formation_lane.py --out "$OUT/formation" [--robots 2|3|4] [--spacing 0.8] [--max-speed 0.2]

Runs on a sim host only (D-584). Launches gz_multi (map_v2_fleet_real world, Nav2 + AMCL + CORE per robot,
headless), arms the followers through the real Fleet path (fleet.bench FormationSession, Formation.TRAIL,
D-20 relay), and drives the leader with Nav2 goals along the east road of the lane graph, through its
north-east bend. Two injections while driving: the leader is stopped hard (navigation cancel, LEADER_STOP_S),
and later the last follower is lost (its own E-stop), which must put the session on HOLD and cancel the
leader (FOR-004). Truth from `gz topic -e /world/map_v2_fleet/dynamic_pose/info`.

Pass (result.json): while the leader moves, each follower's path gap behind the leader is within GAP_TOL_M
of spacing x rank at p95 and GAP_MAX_M at the worst sample; the closest two centres never come under
MIN_CENTRE_M (contact proxy for a 0.2 m body); after the lost follower every robot stops within HOLD_S.
No CORE is told anything but Nav2 goals, follow and E-stop: every stop is the robot's own.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / p) for p in ('tools/sim', 'tools/validation/fleet_gazebo', 'operations/fleet',
                                        'contracts/foundation')]
from fleet_trips import lane_pose, GRAPH, RENDER  # noqa: E402  the same lane graph the trip bench drives
from preflight import Reservations  # noqa: E402  D-426 run reservations: domain 20-29, API ports

WORLD = 'map_v2_fleet'
#: east road, driven in reverse like the trip bench: the convoy starts at S0 and the leader's goals climb
#: through the north-east bend (lap scenario `ne_corner` 0.3-1.3 m from east rev 0.92).
S0, GOAL_STEPS = 0.40, (0.9, 1.7, 2.6)
LEADER_STOP_S, LEADER_STOP_AT_S = 8.0, 4.0        # hard stop during goal 2, 4 s in
GAP_TOL_M, GAP_MAX_M, MIN_CENTRE_M, HOLD_S = 0.10, 0.15, 0.30, 1.5
MOVING_MPS, STOPPED_MPS = 0.02, 0.01
TERMINAL_NAV = ('IDLE', 'SUCCEEDED', 'FAILED', 'CANCELED', 'ARRIVED')


class Truth:
    """Gazebo poses of the named models, 50 Hz cap per model, to truth.jsonl and `latest`."""

    def __init__(self, names, path: Path) -> None:
        self.latest: dict[str, tuple] = {}
        self.rows: dict[str, list] = {n: [] for n in names}
        self._fh = path.open('w', encoding='utf-8')
        self._proc = subprocess.Popen(['gz', 'topic', '-e', '-t', f'/world/{WORLD}/dynamic_pose/info',
                                       '--json-output'], stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self._proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            stamp = msg.get('header', {}).get('stamp', {})
            sim_t = float(stamp.get('sec', 0)) + float(stamp.get('nsec', 0)) * 1e-9
            for p in msg.get('pose', []):
                name = p.get('name')
                if name not in self.rows or (self.rows[name] and sim_t - self.rows[name][-1][1] < 0.02):
                    continue
                pos, q = p.get('position', {}), p.get('orientation', {})
                yaw = math.atan2(2 * (q.get('w', 1.0) * q.get('z', 0.0) + q.get('x', 0.0) * q.get('y', 0.0)),
                                 1 - 2 * (q.get('y', 0.0) ** 2 + q.get('z', 0.0) ** 2))
                row = (time.monotonic(), sim_t, pos.get('x', 0.0), pos.get('y', 0.0), yaw)
                self.rows[name].append(row)
                self.latest[name] = row
                self._fh.write(json.dumps({'t': row[0], 'sim_t': sim_t, 'robot': name, 'x': row[2], 'y': row[3],
                                           'yaw': yaw}) + '\n')

    def speed(self, name: str, window_s: float = 0.5) -> float:
        rows = self.rows.get(name) or []
        if len(rows) < 2:
            return 0.0
        last = rows[-1]
        for row in reversed(rows):
            if last[1] - row[1] >= window_s:
                return math.dist(last[2:4], row[2:4]) / (last[1] - row[1])
        return 0.0

    def close(self) -> None:
        self._proc.terminate()
        self._fh.close()


def _project(points, x, y):
    """Arc length of the point on the polyline closest to (x, y), and the distance to it."""
    best, best_s, walked = float('inf'), 0.0, 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
        d = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if d < best:
            best, best_s = d, walked + t * math.sqrt(seg)
        walked += math.sqrt(seg)
    return best_s, best


def score(truth: Truth, leader: str, followers: list[str], spacing: float, marks: list[dict]) -> dict:
    """Gap error per follower from truth; the leader's own path is the reference (TRAIL replays it)."""
    lead = truth.rows[leader]
    path: list = []
    for r in lead:  # the leader's own track, thinned so zero-length segments do not break the projection
        if not path or math.dist((r[2], r[3]), path[-1]) > 0.005:
            path.append((r[2], r[3]))
    lead_s = [_project(path, r[2], r[3])[0] for r in lead]
    lost_at = next((m['t'] for m in marks if m['kind'] == 'inject' and m['value'] == 'follower_lost'), None)
    out = {}
    for rank, rid in enumerate(followers, start=1):
        errors, offpath = [], []
        for row in truth.rows[rid]:
            i = min(range(len(lead)), key=lambda k: abs(lead[k][1] - row[1]))
            if lost_at is not None and row[0] >= lost_at:
                break
            if i == 0 or lead[i][1] - lead[i - 1][1] <= 0:
                continue
            v = math.dist(lead[i][2:4], lead[i - 1][2:4]) / (lead[i][1] - lead[i - 1][1])
            if v < MOVING_MPS:
                continue  # a stopped leader: the follower stops too, its gap is judged by the hold check
            s, d = _project(path, row[2], row[3])
            if s < 0.02 or s > lead_s[-1] - 0.02:
                continue  # the follower is before the leader's first recorded point (spawned behind it) or past the end
            errors.append(lead_s[i] - s - spacing * rank)
            offpath.append(d)
        errors.sort()
        out[rid] = {'samples': len(errors), 'p95_abs_m': round(sorted(abs(e) for e in errors)[int(0.95 * (len(errors) - 1))], 3)
                    if errors else None, 'max_abs_m': round(max((abs(e) for e in errors), default=0.0), 3),
                    'mean_m': round(sum(errors) / len(errors), 3) if errors else None,
                    'offpath_max_m': round(max(offpath, default=0.0), 3)}
    names = [leader, *followers]
    min_centre, at = float('inf'), None
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            ra, rb = truth.rows[names[a]], truth.rows[names[b]]
            j = 0
            for row in ra:
                while j + 1 < len(rb) and rb[j + 1][1] <= row[1]:
                    j += 1
                if rb:
                    d = math.dist(row[2:4], rb[j][2:4])
                    if d < min_centre:
                        min_centre, at = d, (names[a], names[b], round(row[1], 2))
    return {'followers': out, 'min_centre_m': round(min_centre, 3), 'min_centre_at': at}


async def pose_frame(robot) -> str:
    """`frame` of one leader-stream sample (D-559 field): `map` once Nav2/AMCL localised this CORE."""
    import websockets
    url = robot.base_url.replace('http', 'ws', 1) + f'/ws/swarm/pose?token={robot.token}'
    async with websockets.connect(url) as ws:
        return json.loads(await asyncio.wait_for(ws.recv(), 5.0))['payload'].get('frame')


async def wait_ready(clients, robots, truth, mark, boot_s: float) -> bool:
    """Every CORE answers as itself, streams its pose in `map`, and Gazebo truth flows for it."""
    deadline = time.monotonic() + boot_s
    frames, polls = {}, 0
    while time.monotonic() < deadline:
        polls += 1
        if polls % 10 == 0:
            mark('waiting', {rid: frames.get(rid) for rid in clients})  # frames that are not yet `map`
        try:
            states = {rid: await c.state() for rid, c in clients.items()}
            frames = {r.robot_id: await pose_frame(r) for r in robots if r.robot_id in clients}
            if all(s.get('robot_id') == rid for rid, s in states.items()) and all(
                    f == 'map' for f in frames.values()) and all(rid in truth.latest for rid in clients):
                mark('ready', {rid: {'pose': s.get('pose'), 'frame': frames[rid]} for rid, s in states.items()})
                return True
        except Exception as exc:  # noqa: BLE001 - CORE or Nav2 still starting
            mark('wait', repr(exc)[:160], frames=frames)
        await asyncio.sleep(2.0)
    return False


async def goal(leader, pose, mark) -> str:
    x, y, yaw = pose
    try:
        await leader.navigation_goal(x, y, yaw)
    except Exception as exc:  # noqa: BLE001
        mark('goal_refused', repr(exc)[:200])
        return 'REFUSED'
    await asyncio.sleep(2.0)
    while True:
        state = (await leader.state()).get('navigation')
        if state in TERMINAL_NAV:
            return state
        await asyncio.sleep(0.5)


async def main_async(args) -> int:
    from fleet.bench import Formation, FormationSession, FormationSpec, HttpRobotClient, SessionState, load_robots
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    names = [f'rosy_{i:02d}' for i in range(1, args.robots + 1)]
    leader_id, follower_ids = names[0], names[1:]
    graph = yaml.safe_load(GRAPH.read_text(encoding='utf-8'))
    s_leader = S0 + args.spacing * len(follower_ids)
    spawns = {rid: lane_pose(graph, 'east', 'rev', s_leader - args.spacing * k) for k, rid in enumerate(names)}
    goals = [lane_pose(graph, 'east', 'rev', s_leader + d) for d in GOAL_STEPS]
    partition = os.environ.get('GZ_PARTITION') or f'formation-{secrets.token_hex(3)}'
    reservations = Reservations.derive(partition.lower(), args.robots, started_at=time.time())
    env = dict(os.environ, GZ_PARTITION=partition, ROS_DOMAIN_ID=str(reservations.ros_domain_id), GZ_IP='127.0.0.1',
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', TMPDIR=str(out / 'tmp'), **RENDER[args.render],
               # run 3 (2026-11-09): without the loopback CycloneDDS config, rosy_02's Nav2 nodes died with
               # `rmw_create_node: failed to create domain` (two robots' participants on one domain); same as fleet_trips
               RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
               CYCLONEDDS_URI='file://' + str(out / 'cyclonedds_formation.xml'))
    (out / 'tmp').mkdir()
    # run 5 (2026-11-09): two Nav2 stacks exceed Cyclone's default 9 auto participant indexes on unicast loopback
    # (amcl, controller, map_server died "no free participant index"); same widening as fleet_trips --nav (D-1003)
    xml = (REPO / 'middleware/devices/pinky/bringup/config/cyclonedds_localhost.xml').read_text(encoding='utf-8')
    xml = xml.replace('    </General>\n', '    </General>\n    <Discovery>\n      <ParticipantIndex>auto</ParticipantIndex>\n'
                      '      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>\n    </Discovery>\n', 1)
    assert '<MaxAutoParticipantIndex>' in xml
    (out / 'cyclonedds_formation.xml').write_text(xml, encoding='utf-8')
    launch = ['ros2', 'launch', 'gz_sim', 'gz_multi.launch.py', f'robots:={args.robots}', 'mode:=nav', 'core:=true',
              'headless:=true', 'world_name:=map_v2_fleet_real.world', 'nav_composition:=false', 'loc_assist:=false',
              f'api_port_base:={reservations.api_ports[0]}',
              'spawn_poses:=' + ';'.join('%.5f,%.5f,%.6f' % spawns[rid] for rid in names)]
    events = (out / 'events.jsonl').open('w', encoding='utf-8')
    marks: list[dict] = []

    def mark(kind, value, **extra):
        row = {'t': time.monotonic(), 'kind': kind, 'value': value, **extra}
        marks.append(row)
        events.write(json.dumps(row, default=str) + '\n')
        events.flush()
        print(f"[{time.strftime('%H:%M:%S')}] {kind} {value} {extra or ''}", flush=True)

    result = {'robots': names, 'spacing': args.spacing, 'max_speed': args.max_speed, 'spawns': spawns, 'goals': goals,
              'domain': reservations.ros_domain_id, 'ports': list(reservations.api_ports), 'render': args.render}
    sim = subprocess.Popen(launch, env=env, stdout=(out / 'launch.log').open('w'), stderr=subprocess.STDOUT)
    truth = Truth(names, out / 'truth.jsonl')
    clients, session = {}, None
    try:
        manifest = None
        for _ in range(int(args.boot_s)):
            found = list((out / 'tmp').glob('rosy_gz_multi_*/robots.yaml'))
            if found:
                manifest = found[0]
                break
            await asyncio.sleep(1.0)
        if manifest is None:
            mark('fail', 'no robots.yaml from gz_multi')
            return 1
        robots = load_robots(manifest)
        clients = {r.robot_id: HttpRobotClient(r) for r in robots if r.robot_id in names}
        result['ready'] = await wait_ready(clients, robots, truth, mark, args.boot_s)
        if not result['ready']:
            mark('fail', 'robots not ready')
            return 1
        await asyncio.sleep(args.settle_s)
        leader, followers = clients[leader_id], [clients[rid] for rid in follower_ids]
        session = FormationSession(leader, followers, FormationSpec(Formation.TRAIL, spacing=args.spacing,
                                                                     max_speed=args.max_speed),
                                   member_order=names)
        await session.start()
        mark('armed', {k: vars(v) for k, v in (session.assignment or {}).items()}, state=session.state.value)
        nav = []
        nav.append(await goal(leader, goals[0], mark))
        mark('goal', 1, nav=nav[-1], speeds={rid: round(truth.speed(rid), 3) for rid in names})
        # Injection 1: hard stop of the leader 4 s into goal 2; followers must stop on their own trail gap.
        task = asyncio.create_task(goal(leader, goals[1], mark))
        await asyncio.sleep(LEADER_STOP_AT_S)
        await leader.navigation_cancel()
        mark('inject', 'leader_stop')
        await asyncio.sleep(LEADER_STOP_S)
        result['leader_stop'] = {'speeds_after_8s': {rid: round(truth.speed(rid), 3) for rid in names},
                                 'session': session.state.value}
        mark('leader_stop', result['leader_stop'])
        nav.append(await task)
        nav.append(await goal(leader, goals[1], mark))
        mark('goal', 2, nav=nav[-1])
        # Injection 2: the last follower is lost (its own E-stop) during goal 3 -> HOLD, leader cancelled.
        task = asyncio.create_task(goal(leader, goals[2], mark))
        await asyncio.sleep(LEADER_STOP_AT_S)
        t_lost = time.monotonic()
        await followers[-1].estop()
        mark('inject', 'follower_lost', robot=follower_ids[-1])
        hold_at = stopped_at = None
        while time.monotonic() - t_lost < 15.0:
            if hold_at is None and session.state is not SessionState.RUNNING:
                hold_at = time.monotonic() - t_lost
            if stopped_at is None and all(truth.speed(rid) < STOPPED_MPS for rid in names):
                stopped_at = time.monotonic() - t_lost
            if hold_at is not None and stopped_at is not None:
                break
            await asyncio.sleep(0.1)
        nav.append(await task)
        result['follower_lost'] = {'session_left_running_s': hold_at, 'all_stopped_s': stopped_at,
                                   'session': session.state.value, 'reason': session.reason_text(),
                                   'leader_nav': nav[-1], 'speeds': {rid: round(truth.speed(rid), 3) for rid in names}}
        mark('follower_lost', result['follower_lost'])
        result['nav'] = nav
    finally:
        try:
            if session is not None:
                await session.stop()
        except Exception as exc:  # noqa: BLE001
            mark('stop_failed', repr(exc)[:200])
        await asyncio.sleep(1.0)
        truth.close()
        for c in clients.values():
            await c.aclose()
        sim.terminate()
        try:
            sim.wait(20)
        except subprocess.TimeoutExpired:
            sim.kill()
        events.close()
    result['score'] = score(truth, leader_id, follower_ids, args.spacing, marks)
    gaps = result['score']['followers'].values()
    lost = result.get('follower_lost') or {}
    result['checks'] = {
        'spacing': all(g['samples'] > 50 and g['p95_abs_m'] <= GAP_TOL_M and g['max_abs_m'] <= GAP_MAX_M for g in gaps),
        'no_contact': result['score']['min_centre_m'] >= MIN_CENTRE_M,
        'leader_stop_followers_stop': all(v < STOPPED_MPS for v in result.get('leader_stop', {}).get(
            'speeds_after_8s', {}).values()) if 'leader_stop' in result else False,
        'lost_follower_degrades_safely': (lost.get('all_stopped_s') is not None and lost['all_stopped_s'] <= HOLD_S
                                          and lost.get('session') in ('HOLDING', 'STOPPED')),
    }
    result['pass'] = all(result['checks'].values())
    (out / 'result.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print('[formation-lane]', 'PASS' if result['pass'] else 'FAIL', json.dumps(result['checks']), out / 'result.json',
          flush=True)
    return 0 if result['pass'] else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out', required=True, help='new directory for result.json, truth.jsonl, events.jsonl, launch.log')
    p.add_argument('--robots', type=int, default=2, choices=(2, 3, 4))
    p.add_argument('--spacing', type=float, default=0.8, help='path gap per rank (m); >= Fleet lane floor at --max-speed')
    p.add_argument("--max-speed", type=float, default=0.2, help="follower cap (m/s), at most the CORE SAF-004 ceiling 0.2; the Nav2 leader is not capped")
    p.add_argument('--render', choices=sorted(RENDER), default='cpu', help='gpu on the model PC: llvmpipe EGL segfaults there (run 1, 2026-11-09)')
    p.add_argument('--boot-s', type=float, default=300)
    p.add_argument('--settle-s', type=float, default=10)
    return asyncio.run(main_async(p.parse_args(argv)))


if __name__ == '__main__':
    sys.exit(main())
