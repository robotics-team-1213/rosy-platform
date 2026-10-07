#!/usr/bin/env python3
"""D-495/D-498 junction SIM probe against a running run_sim.sh (model PC only).

Drives CORE through its HTTP API only (PUT /line-follow/mode CAMERA_LINE, POST /line-follow/junction),
moves the robot with gz set_pose and spawns/removes obstacle boxes with gz services, and records:
  log.jsonl     10 Hz: CORE line-follow status (state, reason, junction), /odom, ground truth
                (d495/gt from d495_sim_aux.py), last /cmd_vel, ir_sensor/range, keep_debug reason
  cmd.jsonl     every /cmd_vel with its sim time
  keep.jsonl    keep_debug HOLD-reason transitions (sim stamp, ground truth)
  actions.jsonl every API call / injection with the response
  events.jsonl  CORE events
  summary.json  scenario verdict + numbers
Usage: python3 d495_sim_probe.py <scenario> --out runs/<name> [--base http://127.0.0.1:8097]
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

WORLD = '/world/map_v2_fleet'
BODY_FRONT_X = 0.04205
JUNCTION_REASONS = ('junction_transverse', 'junction_fork')


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def gz(service, reqtype, req, reptype='gz.msgs.Boolean'):
    return subprocess.run(['gz', 'service', '-s', f'{WORLD}/{service}', '--reqtype', reqtype,
                           '--reptype', reptype, '--timeout', '3000', '--req', req],
                          capture_output=True, text=True).stdout.strip()


class Probe:
    def __init__(self, a):
        import rclpy
        from geometry_msgs.msg import Pose2D, Twist
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from rosgraph_msgs.msg import Clock
        from std_msgs.msg import String, UInt16MultiArray
        self.base, self.token = a.base.rstrip('/'), a.token
        self.out = Path(a.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.files = {k: open(self.out/f'{k}.jsonl', 'w') for k in
                      ('log', 'cmd', 'keep', 'actions', 'events')}
        self.lock = threading.Lock()
        self.latest = {}
        self.rows = []
        self.keep_reason = None
        rclpy.init()
        self.rclpy = rclpy
        n = self.node = rclpy.create_node('d495_probe')
        n.create_subscription(Clock, 'clock', lambda m: self._put(
            'sim_t', m.clock.sec+m.clock.nanosec*1e-9), 10)
        n.create_subscription(Odometry, 'odom', lambda m: self._put('odom', (
            m.pose.pose.position.x, m.pose.pose.position.y, self._yaw(m.pose.pose.orientation),
            m.twist.twist.linear.x, m.twist.twist.angular.z)), qos_profile_sensor_data)
        n.create_subscription(Pose2D, 'd495/gt', lambda m: self._put('gt', (m.x, m.y, m.theta)), 10)
        n.create_subscription(Twist, 'cmd_vel', self._on_cmd, 10)
        n.create_subscription(UInt16MultiArray, 'ir_sensor/range',
                              lambda m: self._put('ir', list(m.data)), qos_profile_sensor_data)
        n.create_subscription(String, 'line/keep_debug', self._on_keep, 1)
        self.pause_pub = n.create_publisher(String, 'd495/pause', 10)
        self._String = String
        threading.Thread(target=rclpy.spin, args=(n,), daemon=True).start()
        self.stop_rec = threading.Event()
        self.t0 = time.monotonic()
        _, ev = self.call('GET', '/api/v1/events?limit=1', log=False)
        self.since = ev.get('last_seq')
        time.sleep(1.0)
        threading.Thread(target=self._recorder, daemon=True).start()

    @staticmethod
    def _yaw(q):
        return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))

    def _put(self, k, v):
        with self.lock:
            self.latest[k] = v

    def get(self, k):
        with self.lock:
            return self.latest.get(k)

    def _on_cmd(self, m):
        row = {'sim_t': self.get('sim_t'), 'lin': round(m.linear.x, 4), 'ang': round(m.angular.z, 4)}
        self._put('cmd', (row['lin'], row['ang']))
        self.files['cmd'].write(json.dumps(row)+'\n')

    def _on_keep(self, m):
        try:
            d = json.loads(m.data)
        except ValueError:
            return
        r = d.get('reason')
        if r != self.keep_reason:
            self.keep_reason = r
            self.files['keep'].write(json.dumps({'stamp': d.get('stamp'), 'sim_t': self.get('sim_t'),
                                                 'reason': r, 'gt': self.get('gt')})+'\n')
            self.files['keep'].flush()

    def t(self):
        return round(time.monotonic()-self.t0, 3)

    def call(self, method, path, body=None, log=True):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base+path, data=data, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as r:
                code, resp = r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                code, resp = e.code, json.loads(e.read() or b'{}')
            except ValueError:
                code, resp = e.code, {}
        except (urllib.error.URLError, OSError) as e:
            code, resp = 0, {'error': str(e)}
        if log:
            self.action('api', method=method, path=path, body=body, code=code, resp=resp)
        return code, resp

    def action(self, kind, **kw):
        row = {'t': self.t(), 'sim_t': self.get('sim_t'), 'gt': self.get('gt'), 'kind': kind, **kw}
        self.files['actions'].write(json.dumps(row)+'\n')
        self.files['actions'].flush()
        print(json.dumps(row)[:300], flush=True)
        return row

    def _recorder(self):
        while not self.stop_rec.is_set():
            _, st = self.call('GET', '/api/v1/line-follow', log=False)
            q = '' if self.since is None else f'since_seq={self.since}&'
            _, ev = self.call('GET', f'/api/v1/events?{q}limit=200', log=False)
            for e in ev.get('events', []):
                if self.since is None or e.get('seq', 0) > self.since:
                    self.files['events'].write(json.dumps({'t': self.t(), **e})+'\n')
            if ev.get('last_seq') is not None:
                self.since = ev['last_seq']
            row = {'t': self.t(), **{k: self.get(k) for k in ('sim_t', 'gt', 'odom', 'cmd', 'ir')},
                   'keep': self.keep_reason, 'state': st.get('state'), 'reason': st.get('reason'),
                   'junction': st.get('junction'), 'body_gap_m': st.get('body_gap_m')}
            with self.lock:
                self.rows.append(row)
            self.files['log'].write(json.dumps(row)+'\n')
            self.files['log'].flush()
            time.sleep(0.1)

    def last(self):
        with self.lock:
            return self.rows[-1] if self.rows else {}

    def wait(self, pred, timeout, label=''):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            r = self.last()
            if r and pred(r):
                return r
            time.sleep(0.05)
        self.action('timeout', label=label)
        return None

    def jstate(self, r=None):
        return ((r or self.last()).get('junction') or {}).get('state')

    # ----- actions -----
    def mode(self, m):
        return self.call('PUT', '/api/v1/line-follow/mode', {'mode': m})

    def junction(self, action, place, **kw):
        body = {'action': action, 'place_id': place, 'expires_s': kw.pop('expires_s', 30), **kw}
        return self.call('POST', '/api/v1/line-follow/junction', body)

    def set_pose(self, x, y, yaw):
        self.mode('OFF')
        time.sleep(0.5)
        rep = gz('set_pose', 'gz.msgs.Pose', f'name: "rosy", position: {{x: {x}, y: {y}, z: 0.01}}, '
                 f'orientation: {{z: {math.sin(yaw/2)}, w: {math.cos(yaw/2)}}}')
        self.action('set_pose', x=x, y=y, yaw=yaw, rep=rep)
        time.sleep(2.0)

    def box(self, name, x, y, size=0.06):
        sdf = (f"<sdf version='1.9'><model name='{name}'><static>true</static><pose>{x} {y} {size/2} 0 0 0</pose>"
               f"<link name='l'><collision name='c'><geometry><box><size>{size} {size} {size}</size></box>"
               f"</geometry></collision><visual name='v'><geometry><box><size>{size} {size} {size}</size>"
               f"</box></geometry></visual></link></model></sdf>")
        rep = gz('create', 'gz.msgs.EntityFactory', 'sdf: ' + json.dumps(sdf))
        return self.action('box', name=name, x=x, y=y, size=size, rep=rep)

    def unbox(self, name):
        rep = gz('remove', 'gz.msgs.Entity', f'name: "{name}", type: MODEL')
        return self.action('unbox', name=name, rep=rep)

    def pause(self, what):
        self.pause_pub.publish(self._String(data=what))
        return self.action('pause', what=what)

    def capabilities(self):
        code, d = self.call('GET', '/api/v1/system/capabilities', log=False)
        items = (d.get('controls') or {}).get('items') or [{}]
        return items[0].get('junction_turn')

    def close(self, summary):
        self.pause('')
        self.mode('OFF')
        time.sleep(0.5)
        self.stop_rec.set()
        time.sleep(0.3)
        for f in self.files.values():
            f.close()
        summary['capability_at_end'] = self.capabilities()
        (self.out/'summary.json').write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))
        self.node.destroy_node()
        self.rclpy.shutdown()


# ----- measurement helpers (from recorded rows) -----
def paint_ahead(gt, max_m=0.5):
    """Distance from the body front along the heading to the first paint (PaintMap), or None."""
    import numpy as np
    from ament_index_python.packages import get_package_share_directory
    from control.sensing.perception.paint_localizer import PaintMap
    import os
    global _PAINT
    try:
        _PAINT
    except NameError:
        _PAINT = PaintMap.from_bundle(os.path.join(
            get_package_share_directory('control'), 'map', 'map_v2_fleet'))
    x, y, yaw = gt
    s = np.arange(0.0, max_m, 0.002)
    pts = np.stack([x+math.cos(yaw)*(BODY_FRONT_X+s), y+math.sin(yaw)*(BODY_FRONT_X+s)], axis=-1)
    hit = np.nonzero(_PAINT.distance_at(pts) <= 0.003)[0]
    return None if len(hit) == 0 else round(float(s[hit[0]]), 4)


def path_len(rows, k='gt'):
    return round(sum(math.hypot(b[k][0]-a[k][0], b[k][1]-a[k][1])
                     for a, b in zip(rows, rows[1:]) if a.get(k) and b.get(k)), 4)


def stop_record(p, sight_row, timeout=6.0):
    """After a junction sighting: wait for standstill and measure the stop."""
    still = p.wait(lambda r: r.get('odom') and abs(r['odom'][3]) < 0.005 and abs(r['odom'][4]) < 0.02
                   and r.get('sim_t') and sight_row.get('sim_t') and r['sim_t']-sight_row['sim_t'] > 0.3,
                   timeout, 'standstill')
    if still is None:
        return None
    with p.lock:
        seg = [r for r in p.rows if sight_row['t'] <= r['t'] <= still['t']]
    return {'sight_gt': sight_row['gt'], 'stop_gt': still['gt'],
            'travel_after_sight_m': path_len(seg), 'sight_to_still_sim_s': round(still['sim_t']-sight_row['sim_t'], 3),
            'paint_ahead_at_stop_m': paint_ahead(still['gt']) if still.get('gt') else None,
            'reason_at_stop': still.get('reason'), 'junction_state': p.jstate(still)}


# ----- scenarios -----
def explore(p, a):
    """Lap from the spawn: at every junction_waiting record the stop, then send the next action
    from --plan (default straight) for a new place id, until --duration."""
    p.set_pose(a.x, a.y, a.yaw)
    p.action('capability', junction_turn=p.capabilities())
    p.mode('CAMERA_LINE')
    plan = (a.plan or 'straight').split(',')
    stops, i = [], 0
    end = time.monotonic()+a.duration
    while time.monotonic() < end:
        sight = p.wait(lambda r: r.get('keep') in JUNCTION_REASONS or p.jstate(r) == 'waiting',
                       end-time.monotonic(), 'sighting')
        if sight is None:
            break
        rec = stop_record(p, sight) or {'standstill': False}
        rec.update(keep=sight.get('keep'), state=p.jstate(), status_reason=p.last().get('reason'))
        act = plan[min(i, len(plan)-1)]
        kw = {}
        if act.startswith(('left', 'right')):
            act, deg = act.split(':')
            kw['turn_deg'] = float(deg)
        code, resp = p.junction(act, f'X{i}', **kw)
        rec.update(sent=act, code=code, resp=resp)
        stops.append(rec)
        i += 1
        # leave the junction: wait until it is no longer seen and the instruction finished
        t_sent = p.t()
        p.wait(lambda r: p.jstate(r) in ('idle', 'aborted', 'unresolved', 'waiting')
               and r.get('keep') not in JUNCTION_REASONS and r['t'] > t_sent+0.5, 25, 'leave')
        time.sleep(1.0)
        if p.last().get('state') == 'LOST':
            p.action('lost', reason=p.last().get('reason'))
            break
    with p.lock:
        rows = list(p.rows)
    return {'scenario': 'explore', 'stops': stops, 'gt_path_m': path_len(rows),
            'final': {k: rows[-1].get(k) for k in ('state', 'reason', 'junction', 'gt')} if rows else None}


SCENARIOS = {'explore': explore}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario', choices=sorted(SCENARIOS))
    ap.add_argument('--out', required=True)
    ap.add_argument('--x', type=float, default=-1.26955)
    ap.add_argument('--y', type=float, default=0.24255)
    ap.add_argument('--yaw', type=float, default=-1.5708)
    ap.add_argument('--duration', type=float, default=120.0)
    ap.add_argument('--plan', default='')
    ap.add_argument('--base', default='http://127.0.0.1:8097')
    ap.add_argument('--token', default='rosy-dev-operator')
    a = ap.parse_args()
    p = Probe(a)
    try:
        summary = SCENARIOS[a.scenario](p, a)
    except Exception as e:  # noqa: BLE001 - keep the evidence of a broken run
        summary = {'scenario': a.scenario, 'error': repr(e)}
    p.close(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
