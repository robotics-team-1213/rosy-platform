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

    def set_pose(self, x, y, yaw, forget=True):
        """forget: first end CORE's junction-stop memory. The entry heading of a junction stop
        survives OFF and a teleport (review N2) and ends only after lost_after_s in CAMERA_LINE
        without a sighting; a teleport back to the same junction would abort the next turn as
        'odom' (L2). So: park in the dark inner block (no junction in view), CAMERA_LINE 4 s, OFF."""
        self.mode('OFF')
        time.sleep(0.5)
        if forget:
            self._teleport(-0.95, 0.0, math.pi/2)
            self.mode('CAMERA_LINE')
            time.sleep(4.0)
            self.action('forget', state=self.last().get('state'), reason=self.last().get('reason'),
                        junction=self.last().get('junction'))
            self.mode('OFF')
            time.sleep(0.5)
        self._teleport(x, y, yaw)

    def _teleport(self, x, y, yaw):
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


def brief(r):
    return {k: r.get(k) for k in ('t', 'sim_t', 'gt', 'odom', 'state', 'reason', 'keep', 'body_gap_m')} | {
        'j': (r.get('junction') or {}).get('state'), 'jr': (r.get('junction') or {}).get('reason')}


def still(r):
    return bool(r.get('odom')) and abs(r['odom'][3]) < 0.005 and abs(r['odom'][4]) < 0.02


_LANES = None


def lane_heading(x, y, yaw):
    """(distance, direction) of the nearest lane_graph centre-line point, along the robot's way."""
    global _LANES
    if _LANES is None:
        import os
        import yaml
        from ament_index_python.packages import get_package_share_directory
        g = yaml.safe_load(open(os.path.join(get_package_share_directory('control'), 'map',
                                             'map_v2_fleet', 'lane_graph.yaml')))
        _LANES = []
        for seg in g['segments'].values():
            pts = seg['points']
            for a, b in zip(pts, pts[1:]):
                _LANES.append((a[0], a[1], math.atan2(b[1]-a[1], b[0]-a[0])))
    d, h = min((math.hypot(px-x, py-y), h) for px, py, h in _LANES)
    if abs(wrap(h-yaw)) > math.pi/2:
        h = wrap(h+math.pi)  # roads are two-way
    return d, h


def parse_item(item):
    """straight | stop[@stop_after_m] | left:deg[/advance_m] | right:-deg[/advance_m]"""
    kw = {}
    if item.startswith('stop@'):
        item, kw['stop_after_m'] = 'stop', float(item[5:])
    elif ':' in item:
        item, rest = item.split(':')
        deg, _, adv = rest.partition('/')
        kw['turn_deg'] = float(deg)
        if adv:
            kw['advance_m'] = float(adv)
    return item, kw


def run_trip(p, plan, prearm=True, late=0.5, duration=180.0, tag='P', stop_on_fail=True, hooks=None):
    """Drive a junction plan. prearm: each instruction goes out as soon as the previous junction
    is done (before the robot reaches the next one); else it goes out `late` s after
    junction_waiting. hooks(p, rec, row) may inject faults; a truthy return ends the trip."""
    recs, rec, idx, prev_js = [], None, 0, 'idle'

    def send(i, into=None):
        act, kw = parse_item(plan[i])
        code, resp = p.junction(act, f'{tag}{i}', **kw)
        if into is not None:
            into.setdefault('sent', []).append({'i': i, 'item': plan[i], 'code': code, 'resp': resp})
        return code

    first = None
    if prearm and plan:
        first = {'i': 0, 'item': plan[0], 'code': send(0)}
    end = time.monotonic()+duration
    while time.monotonic() < end:
        r = p.last()
        j = r.get('junction') or {}
        js, keep = j.get('state'), r.get('keep')
        if rec is None and (keep in JUNCTION_REASONS or js in ('waiting', 'turning')):
            rec = {'i': idx, 'item': plan[idx] if idx < len(plan) else None, 'sight': brief(r), 'seq': []}
            if first is not None:
                rec['sent'], first = [first], None
            recs.append(rec)
        if rec is not None:
            b = brief(r)
            key = [b['j'], b['jr'], b['state'], b['reason']]
            if not rec['seq'] or key != rec['seq'][-1]['key']:
                rec['seq'].append({'key': key, 'sim_t': b['sim_t'], 'gt': b['gt'], 'odom': b['odom']})
            if 'still' not in rec and still(r) and (r['sim_t'] or 0)-(rec['sight']['sim_t'] or 0) > 0.3:
                rec['still'] = b
            if js == 'turning' and 'turn_start' not in rec:
                rec['turn_start'] = b
            if prev_js == 'turning' and js != 'turning':
                rec['turn_end'] = b
            if hooks and hooks(p, rec, r):
                break
            if js == 'waiting' and not prearm and idx < len(plan) and 'sent' not in rec:
                time.sleep(late)
                send(idx, rec)
            if js == 'waiting' and idx >= len(plan) and 'still' in rec:
                rec['result'] = 'waiting_no_instruction'
                break
            if js == 'idle' and prev_js in ('executing', 'reacquiring'):
                rec['result'], rec['done'] = 'done', b
                idx += 1
                rec = None
                if prearm and idx < len(plan):
                    send(idx, recs[-1])
                    first = recs[-1]['sent'].pop()
            elif js in ('aborted', 'unresolved') and 'result' not in rec:
                rec['result'], rec['done'] = js, b
                if stop_on_fail:
                    break
            elif r.get('reason') == 'junction_stop' and still(r):
                rec['result'], rec['done'] = 'stopped', b
                break
            elif r.get('state') == 'LOST':
                rec['result'], rec['done'] = 'LOST', b
                break
        elif r.get('state') == 'LOST':
            recs.append({'i': idx, 'result': 'LOST_between_junctions', 'done': brief(r)})
            break
        elif r.get('reason') == 'junction_stop' and still(r):  # stop_after_m before any junction
            recs.append({'i': idx, 'item': plan[idx] if idx < len(plan) else None,
                         'result': 'stopped', 'done': brief(r), 'sent': [first] if first else []})
            break
        prev_js = js
        time.sleep(0.05)
    return recs


def score(p, recs):
    """Numbers per junction record (ground truth from d495/gt, CORE's own odom alongside)."""
    with p.lock:
        rows = list(p.rows)
    out = []
    for k, rec in enumerate(recs):
        m = {'i': rec.get('i'), 'item': rec.get('item'), 'result': rec.get('result')}
        sight = rec.get('sight')
        if sight and sight.get('gt'):
            m['sight_gt'] = [round(v, 3) for v in sight['gt']]
            m['keep_at_sight'] = sight.get('keep')
        st = rec.get('still')
        if sight and st:
            seg = [r for r in rows if sight['t'] <= r['t'] <= st['t']]
            m['stop'] = {'travel_after_sight_m': path_len(seg),
                         'sight_to_still_sim_s': round(st['sim_t']-sight['sim_t'], 3),
                         'paint_ahead_of_front_m': paint_ahead(st['gt']),
                         'state_at_still': st['j']}
        item = rec.get('item') or ''
        kw = parse_item(item)[1] if item else {}
        if 'turn_deg' in kw and rec.get('turn_end') and sight:
            target = wrap(sight['gt'][2]+math.radians(kw['turn_deg']))
            te, ts = rec['turn_end'], rec.get('turn_start')
            m['turn'] = {'entry_yaw_gt_deg': round(math.degrees(sight['gt'][2]), 2),
                         'final_yaw_gt_deg': round(math.degrees(te['gt'][2]), 2),
                         'error_vs_target_gt_deg': round(math.degrees(wrap(te['gt'][2]-target)), 2),
                         'turned_gt_deg': round(math.degrees(wrap(te['gt'][2]-sight['gt'][2])), 2),
                         'turned_odom_deg': round(math.degrees(wrap(te['odom'][2]-sight['odom'][2])), 2)
                         if te.get('odom') and sight.get('odom') else None,
                         'state_after': te['j'], 'reason_after': te['jr'],
                         'turn_s': round(te['sim_t']-ts['sim_t'], 2) if ts else None}
        done = rec.get('done')
        if done and done.get('gt'):
            d, h = lane_heading(*done['gt'])
            m['at_done'] = {'gt': [round(v, 3) for v in done['gt']], 'state': done['state'],
                            'reason': done['reason'], 'j': done['j'], 'jr': done['jr'],
                            'lane_offset_m': round(d, 3),
                            'heading_vs_lane_deg': round(math.degrees(wrap(done['gt'][2]-h)), 1)}
        if k > 0 and sight and recs[k-1].get('sight'):
            ps = recs[k-1]['sight']['gt']
            m['dist_from_prev_sight_m'] = round(math.hypot(sight['gt'][0]-ps[0], sight['gt'][1]-ps[1]), 3)
        m['seq'] = [{'j': e['key'][0], 'jr': e['key'][1], 'state': e['key'][2], 'reason': e['key'][3],
                     'sim_t': e['sim_t']} for e in rec.get('seq', [])][:40]
        m['sent'] = [{'i': s['i'], 'item': s['item'], 'code': s['code'], 'resp': s.get('resp')}
                     for s in rec.get('sent', [])]
        out.append(m)
    return out


# ----- scenarios -----
def trip(p, a):
    """--plan items in order (see parse_item); --reactive sends each `--late` s after waiting."""
    p.set_pose(a.x, a.y, a.yaw)
    p.action('capability', junction_turn=p.capabilities())
    t0 = p.t()
    p.mode('CAMERA_LINE')
    plan = [x for x in a.plan.split(',') if x]
    recs = run_trip(p, plan, prearm=not a.reactive, late=a.late, duration=a.duration, tag=a.tag)
    with p.lock:
        rows = [r for r in p.rows if r['t'] >= t0]
    return {'scenario': 'trip', 'plan': plan, 'prearm': not a.reactive, 'late_s': a.late,
            'junctions': score(p, recs), 'gt_path_m': path_len(rows),
            'final': brief(rows[-1]) if rows else None}


SCENARIOS = {'trip': trip}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario', choices=sorted(SCENARIOS))
    ap.add_argument('--out', required=True)
    ap.add_argument('--x', type=float, default=-1.26955)
    ap.add_argument('--y', type=float, default=0.24255)
    ap.add_argument('--yaw', type=float, default=-1.5708)
    ap.add_argument('--duration', type=float, default=120.0)
    ap.add_argument('--plan', default='')
    ap.add_argument('--reactive', action='store_true')
    ap.add_argument('--late', type=float, default=0.5)
    ap.add_argument('--tag', default='P')
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
