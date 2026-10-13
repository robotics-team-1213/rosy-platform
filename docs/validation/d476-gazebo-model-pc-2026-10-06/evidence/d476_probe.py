#!/usr/bin/env python3
"""D-476 bridge probe against a running Gazebo + CORE (run_sim.sh), on the model PC.

run      move the robot (gz set_pose), start CAMERA_LINE hold-to-go (PUT mode, POST /hold
         10 Hz) and record at 10 Hz: CORE line-follow status, /odom, gz ground-truth pose,
         /cmd_vel, LiDAR minimum (all and forward +-30 deg), events. Stops at --duration or
         --after-lost s after LOST, then sets mode OFF. Writes log.jsonl + summary.json.
summary  recompute summary.json from a run's log.jsonl.

Ground-truth wall distance: closest body-footprint corner (URDF nominal front 0.042,
rear -0.076, half width 0.0566 about the model origin) to the inner faces of the perimeter
walls (x = +-1.400, y = +-0.625; map_v2_fleet_real.world).
"""
import argparse
import json
import math
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BODY = ((0.042, 0.0566), (0.042, -0.0566), (-0.076, 0.0566), (-0.076, -0.0566))
WALL_X, WALL_Y = 1.400, 0.625
LIDAR_FWD = math.pi  # pinky_pro core.yaml lidar_forward_deg 180


def wall_gap(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    gaps = []
    for bx, by in BODY:
        px, py = x + c*bx - s*by, y + s*bx + c*by
        gaps.append(min(WALL_X-abs(px), WALL_Y-abs(py)))
    return min(gaps)


class Core:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip('/'), token

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base+path, data=data, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=2.0) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError) as e:
            return 0, {'error': str(e)}


def set_pose(x, y, yaw):
    req = (f'name: "rosy", position: {{x: {x}, y: {y}, z: 0.01}}, '
           f'orientation: {{z: {math.sin(yaw/2)}, w: {math.cos(yaw/2)}}}')
    return subprocess.run(['gz', 'service', '-s', '/world/map_v2_fleet/set_pose', '--reqtype',
                           'gz.msgs.Pose', '--reptype', 'gz.msgs.Boolean', '--timeout', '3000',
                           '--req', req], capture_output=True, text=True).stdout.strip()


def yaw_of(q):
    return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))


def run(a):
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import LaserScan

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    core = Core(a.base, a.token)
    core.call('PUT', '/api/v1/line-follow/mode', {'mode': 'OFF'})
    time.sleep(0.5)
    print('set_pose', set_pose(a.x, a.y, a.yaw), flush=True)
    time.sleep(1.5)

    rclpy.init()
    node = rclpy.create_node('d476_probe')
    latest = {}
    lock = threading.Lock()

    def put(k, v):
        with lock:
            latest[k] = v

    def on_scan(m):
        best, fwd = math.inf, math.inf
        for i, r in enumerate(m.ranges):
            if not (math.isfinite(r) and m.range_min <= r <= m.range_max):
                continue
            best = min(best, r)
            ang = m.angle_min + i*m.angle_increment - LIDAR_FWD
            if abs(math.atan2(math.sin(ang), math.cos(ang))) <= math.radians(30):
                fwd = min(fwd, r)
        put('scan', (best, fwd))

    node.create_subscription(LaserScan, 'scan', on_scan, qos_profile_sensor_data)
    node.create_subscription(Odometry, 'odom', lambda m: put('odom', (
        m.pose.pose.position.x, m.pose.pose.position.y, yaw_of(m.pose.pose.orientation))), 10)
    node.create_subscription(Twist, 'cmd_vel', lambda m: put('cmd', (m.linear.x, m.angular.z)), 10)
    def gt_reader():
        proc = subprocess.Popen(['gz', 'topic', '-e', '-t', '/world/map_v2_fleet/dynamic_pose/info',
                                 '--json-output'], stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            for p in msg.get('pose', []):
                if p.get('name') == 'rosy':
                    pos, q = p.get('position', {}), p.get('orientation', {})
                    w, z = q.get('w', 1.0), q.get('z', 0.0)
                    x_, y_ = q.get('x', 0.0), q.get('y', 0.0)
                    put('gt', (pos.get('x', 0.0), pos.get('y', 0.0),
                               math.atan2(2*(w*z+x_*y_), 1-2*(y_*y_+z*z))))
                    break

    threading.Thread(target=gt_reader, daemon=True).start()
    node.create_subscription(Clock, 'clock', lambda m: put(
        'sim_t', m.clock.sec + m.clock.nanosec*1e-9), 10)
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    time.sleep(1.0)

    _, ev0 = core.call('GET', '/api/v1/events?limit=1')
    since = ev0.get('last_seq')
    code, body = core.call('PUT', '/api/v1/line-follow/mode', {'mode': 'CAMERA_LINE', 'hold_s': 0.5})
    print('mode', code, body.get('state'), body.get('reason'), flush=True)
    stop = threading.Event()

    def holder():
        while not stop.is_set():
            core.call('POST', '/api/v1/line-follow/hold')
            stop.wait(0.1)

    threading.Thread(target=holder, daemon=True).start()
    t0 = time.monotonic()
    lost_at = None
    with open(out/'log.jsonl', 'w') as log, open(out/'events.jsonl', 'w') as evf:
        while time.monotonic()-t0 < a.duration:
            t = time.monotonic()-t0
            _, st = core.call('GET', '/api/v1/line-follow')
            q = '' if since is None else f'since_seq={since}&'
            _, ev = core.call('GET', f'/api/v1/events?{q}limit=200')
            for e in ev.get('events', []):
                if since is None or e.get('seq', 0) > since:
                    evf.write(json.dumps({'t': round(t, 3), **e})+'\n')
            if ev.get('last_seq') is not None:
                since = ev['last_seq']
            with lock:
                row = {'t': round(t, 3), **{k: latest.get(k) for k in
                       ('sim_t', 'odom', 'gt', 'cmd', 'scan')}}
            row.update({'state': st.get('state'), 'reason': st.get('reason'),
                        'linear': st.get('linear'), 'angular': st.get('angular')})
            if row['gt']:
                row['wall_gap'] = round(wall_gap(*row['gt']), 4)
            log.write(json.dumps(row)+'\n')
            log.flush()
            if st.get('state') == 'LOST' and lost_at is None:
                lost_at = t
            if lost_at is not None and t-lost_at > a.after_lost:
                break
            time.sleep(0.1)
    stop.set()
    core.call('PUT', '/api/v1/line-follow/mode', {'mode': 'OFF'})
    node.destroy_node()
    rclpy.shutdown()
    print(json.dumps(summarize(out), indent=1))


def summarize(out):
    rows = [json.loads(l) for l in open(Path(out)/'log.jsonl')]
    s = {'rows': len(rows)}
    tracked = False
    loss = None
    for i, r in enumerate(rows):
        if r['state'] == 'TRACKING':
            tracked = True
        elif tracked and loss is None:
            loss = i
    if loss is None:
        s['loss'] = None
        return _write(out, s)
    r0 = rows[loss]
    s['loss'] = {'t': r0['t'], 'sim_t': r0['sim_t'], 'state': r0['state'], 'reason': r0['reason'],
                 'gt': r0['gt'], 'odom': r0['odom']}
    seq, prev = [], None
    for r in rows[loss:]:
        key = (r['state'], r['reason'])
        if key != prev:
            seq.append({'t': r['t'], 'sim_t': r['sim_t'], 'state': r['state'], 'reason': r['reason']})
            prev = key
    s['sequence'] = seq
    br = [r for r in rows[loss:] if r['reason'] == 'lane_bridge']
    if br:
        first = rows.index(br[0])
        last = rows.index(br[-1])
        end = rows[min(last+1, len(rows)-1)]

        def dist(k, i, j):
            path = 0.0
            for p, q in zip(rows[i:j], rows[i+1:j+1]):
                if p[k] and q[k]:
                    path += math.hypot(q[k][0]-p[k][0], q[k][1]-p[k][1])
            return round(path, 4)
        # Travel from the loss tick until motion stops after the bridge (coasting incl.).
        stop_i = last+1
        while stop_i < len(rows)-1 and rows[stop_i]['cmd'] and abs(rows[stop_i]['cmd'][0]) > 1e-4:
            stop_i += 1
        s['bridge'] = {
            'enter_t': br[0]['t'], 'enter_sim_t': br[0]['sim_t'],
            'enter_after_loss_sim_s': _d(br[0]['sim_t'], r0['sim_t']),
            'last_bridge_sim_t': br[-1]['sim_t'],
            'end_after_loss_sim_s': _d(end['sim_t'], r0['sim_t']),
            'end_state': end['state'], 'end_reason': end['reason'],
            'odom_m_loss_to_end': dist('odom', loss, last+1),
            'gt_m_loss_to_end': dist('gt', loss, last+1),
            'gt_m_loss_to_stop': dist('gt', loss, stop_i),
            'max_linear': max(r['linear'] or 0 for r in br)}
    lost = [r for r in rows if r['state'] == 'LOST']
    if lost:
        s['lost_after_loss_sim_s'] = _d(lost[0]['sim_t'], r0['sim_t'])
    gaps = [r['wall_gap'] for r in rows[loss:] if 'wall_gap' in r]
    scans = [r['scan'][0] for r in rows[loss:] if r['scan']]
    s['min_wall_gap_after_loss_m'] = min(gaps) if gaps else None
    s['min_scan_after_loss_m'] = round(min(scans), 4) if scans else None
    s['gt_m_loss_to_end_of_run'] = round(sum(
        math.hypot(q['gt'][0]-p['gt'][0], q['gt'][1]-p['gt'][1])
        for p, q in zip(rows[loss:], rows[loss+1:]) if p['gt'] and q['gt']), 4)
    s['final'] = {'state': rows[-1]['state'], 'reason': rows[-1]['reason'], 'gt': rows[-1]['gt']}
    return _write(out, s)


def _d(a, b):
    return None if a is None or b is None else round(a-b, 3)


def _write(out, s):
    (Path(out)/'summary.json').write_text(json.dumps(s, indent=1))
    return s


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--x', type=float, required=True)
    r.add_argument('--y', type=float, required=True)
    r.add_argument('--yaw', type=float, required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--duration', type=float, default=60.0)
    r.add_argument('--after-lost', type=float, default=5.0)
    r.add_argument('--base', default='http://127.0.0.1:8095')
    r.add_argument('--token', default='rosy-dev-operator')
    sm = sub.add_parser('summary')
    sm.add_argument('out')
    a = p.parse_args()
    if a.cmd == 'run':
        run(a)
    else:
        print(json.dumps(summarize(a.out), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
