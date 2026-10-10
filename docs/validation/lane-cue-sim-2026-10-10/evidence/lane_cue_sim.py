#!/usr/bin/env python3
"""D-511 CORE Fleet lane cue SIM safety scenarios (model PC only; against a running run_sim.sh).

A fake Fleet poster sends ``POST /api/v1/line-follow/lane-cue`` with the Fleet site seat (a
pair-physical operator token labelled ``site:``, made by run_sim.sh) at 2 Hz from the Gazebo
ground-truth pose (d495/gt) as Fleet's MapPose: each cue is judged from the pose sampled
``latency`` (uniform lat_min..lat_max s) ago and carries that sample's CORE ``odom_pose.stamp``
(GET /robot/state), as Fleet's pose_stamp does. The recorder is the D-495 probe's (10 Hz CORE
line-follow status incl. ``stuck``, /odom, ground truth, every /cmd_vel, events). GET /line-follow
does not carry ``lane_cue`` (LineFollowStatus has no such field), so a pivot is read from the status
reason (fleet_*_turn), a latch from the HOLD reason, and starts/latches from ``nav.lane_cue`` events.

  python3 lane_cue_sim.py s1|s2|s3|s4 --out runs/<name> --site-token <ws>/lcsim/site_token
        [--lat-min 0.4 --lat-max 0.8] [--noise 3] [--exact180] [--box]

s1  Fleet NO_POSE >= 3 s, then OFF_MAP with the last (stale) stamp: latch fleet_off_map; stays held
    through OFF_LANE, another epoch and an old seq; a fresh same-epoch ON_LANE releases; a second
    latch is released by a mode change.
s2  WRONG_WAY pivot (turn ~120 deg), cues stop mid-turn: latch fleet_cue_lost/fleet_turn_unconfirmed
    within ttl + one cue period, turned <= |angle| + 30 deg, no rotation after.
s3  Robot faces against west:f (+y); WRONG_WAY turn_deg near +-180 with sign noise: one pivot, one
    sign, ends within 10 deg of the lane (odom and ground truth), not instantly. --box: a box beside
    the body inside the rotation circle (outside the straight corridor): pivot held obstacle_ahead.
s4  s3 --box held until a D-407 stuck opens: the pivot is dropped without a latch, and ON_LINE side
    cues sent while the stuck is open steer nothing.
Outputs (per run dir): log/cmd/keep/actions/events/cues .jsonl, summary.json, plot.png.
"""
import argparse
import collections
import json
import math
import random
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'd495-junction-sim-2026-10-07' / 'evidence'))
from d495_sim_probe import Probe, gz, wrap  # noqa: E402  (rclpy recorder, CORE API, gz services)

# Inner road of map_v2_fleet: east segment straight x=0.327, y 0.20..0.38, lane order runs -y; the
# nearest wall return there is 0.26-0.29 m. On the perimeter roads (s3 --pose -1.2696,0.243,-90
# --lane 90) the wall is ~0.12 m from base_link: D-422 measured a 0.04 m rotation gap with the C1
# sigma (run_sim.sh SIGMA), but the shipped SIM sigma 0.02 m / 0.03 m resolution puts it inside.
INNER = '0.327,0.20,90'                # facing +y against the lane; the curve starts at y 0.38
PERIOD_S, TTL_S = 0.5, 1.0            # Fleet lane_compliance_service PERIOD_S, CUE_TTL_S
ROT_R, MARGIN = 0.08257, 0.02         # pinky body_rotation_radius_m, obstacle_body_margin_m
LATCHES = ('fleet_off_map', 'fleet_cue_lost', 'fleet_turn_unconfirmed', 'fleet_turn_interrupted')


class CueProbe(Probe):
    def __init__(self, a):
        self.site = 'Bearer ' + Path(a.site_token).read_text().strip()
        self.samples = collections.deque(maxlen=300)   # (wall, sim_t, gt, odom_stamp)
        self.cue_fn, self.seq, self.epoch = None, 0, f'sim-{a.scenario}-{int(time.time())}'
        self.lat, self.rng = (a.lat_min, a.lat_max), random.Random(a.seed)
        self.last_stamp = self.last_post = None
        super().__init__(a)
        self.files['cues'] = open(self.out / 'cues.jsonl', 'w')
        threading.Thread(target=self._poster, daemon=True).start()

    def _recorder(self):
        while not self.stop_rec.is_set():
            _, st = self.call('GET', '/api/v1/line-follow', log=False)
            _, rs = self.call('GET', '/api/v1/robot/state', log=False)
            q = '' if self.since is None else f'since_seq={self.since}&'
            _, ev = self.call('GET', f'/api/v1/events?{q}limit=200', log=False)
            for e in ev.get('events', []):
                if self.since is None or e.get('seq', 0) > self.since:
                    self.files['events'].write(json.dumps({'t': self.t(), **e}) + '\n')
            if ev.get('last_seq') is not None:
                self.since = ev['last_seq']
            stamp = (rs.get('odom_pose') or {}).get('stamp')
            gt = self.get('gt')
            if stamp and gt:
                self.samples.append((time.time(), self.get('sim_t'), gt, stamp))
            row = {'t': self.t(), 'wall': time.time(), **{k: self.get(k) for k in ('sim_t', 'gt', 'odom', 'cmd', 'ir')},
                   'state': st.get('state'), 'reason': st.get('reason'), 'lane_cue': st.get('lane_cue'),
                   'stuck': st.get('stuck'), 'body_gap_m': st.get('body_gap_m'), 'odom_stamp': stamp}
            with self.lock:
                self.rows.append(row)
            self.files['log'].write(json.dumps(row) + '\n')
            self.files['log'].flush()
            time.sleep(0.1)

    def sample(self, age):
        """Newest (wall, sim_t, gt, odom_stamp) at least ``age`` s old (Fleet's MapPose then)."""
        cut = time.time() - age
        return next((s for s in reversed(self.samples) if s[0] <= cut), None)

    def post_cue(self, state, pose_stamp, epoch=None, seq=None, lat=None, **fields):
        if seq is None:
            self.seq += 1
            seq = self.seq
        body = {'cue_id': f'{epoch or self.epoch}-{seq}', 'fleet_epoch': epoch or self.epoch, 'seq': seq,
                'ttl_s': TTL_S, 'pose_stamp': pose_stamp, 'state': state,
                **{k: v for k, v in fields.items() if v is not None}}
        code, resp = self.call('POST', '/api/v1/line-follow/lane-cue', body, log=False, auth=self.site)
        row = {'wall': time.time(), 't': self.t(), 'sim_t': self.get('sim_t'), 'gt': self.get('gt'),
               'latency_s': lat, 'stamp_age_s': round(time.time() - pose_stamp, 3), 'body': body,
               'code': code, 'resp': resp}
        self.files['cues'].write(json.dumps(row) + '\n')
        self.files['cues'].flush()
        if code == 200 and resp.get('accepted'):
            self.last_post = row['wall']
            if state != 'OFF_MAP':
                self.last_stamp = pose_stamp
        return code, resp

    def call(self, method, path, body=None, log=True, auth=None):
        if auth is None:
            return super().call(method, path, body, log)
        tok, self.token = self.token, auth[len('Bearer '):]
        try:
            return super().call(method, path, body, log)
        finally:
            self.token = tok

    def _poster(self):
        nxt = time.monotonic()
        while not self.stop_rec.is_set():
            fn = self.cue_fn
            if fn is not None:
                lat = self.rng.uniform(*self.lat)
                s = self.sample(lat)
                cue = None if s is None else fn(s)
                if cue is not None:
                    self.post_cue(lat=round(lat, 3), **cue)
            nxt += PERIOD_S
            time.sleep(max(0.0, nxt - time.monotonic()))

    def fresh(self):
        s = self.sample(self.rng.uniform(*self.lat))
        return s[3]

    def box(self, name, x, y, sx, sy, yaw=0.0, height=0.25):
        geo = f"<geometry><box><size>{sx} {sy} {height}</size></box></geometry>"
        sdf = (f"<sdf version='1.9'><model name='{name}'><static>true</static><pose>{x} {y} {height/2} 0 0 {yaw}</pose>"
               f"<link name='l'><collision name='c'>{geo}</collision><visual name='v'>{geo}</visual></link>"
               f"</model></sdf>")
        return self.action('box', name=name, x=x, y=y, sx=sx, sy=sy,
                           rep=gz('create', 'gz.msgs.EntityFactory', 'sdf: ' + json.dumps(sdf)))

    def sleep(self, s):
        time.sleep(s)
        return self.last()


# ---------- helpers ----------
def deg(r):
    return math.degrees(r)


def le(v, limit):
    return v is not None and v <= limit


def prep(p, pose, box=False):
    p.unbox('lcbox')
    p.mode('OFF')
    time.sleep(0.5)
    p._teleport(*pose)
    if box:
        # A 0.24 m wall along the heading, left of the body, its face 0.092 m from base_link: inside
        # the rotation circle + margin (0.1026) and outside the straight body corridor (0.0766).
        x, y, yaw = pose
        lx, ly, fx, fy = -math.sin(yaw), math.cos(yaw), math.cos(yaw), math.sin(yaw)
        p.box('lcbox', x + 0.097 * lx + 0.04 * fx, y + 0.097 * ly + 0.04 * fy, 0.24, 0.01, yaw)
        time.sleep(1.0)
    p.mode('CAMERA_LINE')
    r = p.wait(lambda r: r.get('state') == 'TRACKING', 8 if box else 20, 'tracking')
    p.action('ready', state=p.last().get('state'), reason=p.last().get('reason'))
    return r


def reasons(rows, t0=None, t1=None):
    """Reason timeline: [(sim_t, state, reason)] at each change."""
    out, last = [], None
    for r in rows:
        if (t0 is not None and r['wall'] < t0) or (t1 is not None and r['wall'] > t1):
            continue
        k = (r.get('state'), r.get('reason'))
        if k != last:
            out.append((r.get('sim_t'), *k))
            last = k
    return out


def disp(rows, t0, t1):
    seg = [r['gt'] for r in rows if t0 <= r['wall'] <= t1 and r.get('gt')]
    if len(seg) < 2:
        return None, None
    return (round(max(math.hypot(g[0] - seg[0][0], g[1] - seg[0][1]) for g in seg), 4),
            round(max(abs(deg(wrap(g[2] - seg[0][2]))) for g in seg), 2))


def cmds(p, sim0, sim1):
    out = []
    with open(p.out / 'cmd.jsonl') as f:
        for line in f:
            c = json.loads(line)
            if c.get('sim_t') is not None and sim0 <= c['sim_t'] <= sim1:
                out.append(c)
    return out


def sim_at(rows, wall):
    return next((r['sim_t'] for r in rows if r['wall'] >= wall and r.get('sim_t') is not None), None)


def first(rows, pred, after=0.0):
    return next((r for r in rows if r['wall'] >= after and pred(r)), None)


def rows_of(p):
    for f in p.files.values():
        f.flush()                                                        # cmd/events are read back from disk
    with p.lock:
        return list(p.rows)


# ---------- scenarios ----------
def s1(p, a):
    sm = {'verdict': 'FAIL', 'checks': {}}
    prep(p, (-1.2696, 0.40, -math.pi / 2))
    p.cue_fn = lambda s: dict(state='ON_LANE', pose_stamp=s[3])          # LOCALIZED, on the lane
    p.sleep(2.5)
    p.cue_fn = None
    stale = p.last_stamp
    p.action('fleet_no_pose')
    gap_wall = time.time()
    p.sleep(3.3)                                                         # off_map_unseen_s 3.0
    p.cue_fn = lambda s: dict(state='OFF_MAP', pose_stamp=stale)         # Fleet: _last_stamp
    off_wall = time.time()
    latched = p.wait(lambda r: r.get('reason') == 'fleet_off_map', 5, 'off_map latch')
    p.sleep(3.0)                                                         # Fleet still blind: OFF_MAP
    p.cue_fn = None                                                      # then silent: latch outlives ttl
    p.sleep(3.0)
    probes = {
        'off_lane_same_epoch': p.post_cue('OFF_LANE', p.fresh(), side='left', offset_m=-0.08),
        'on_lane_other_epoch': p.post_cue('ON_LANE', p.fresh(), epoch='other-epoch', seq=1),
        'on_lane_old_seq': p.post_cue('ON_LANE', p.fresh(), seq=1),
    }
    p.sleep(2.0)
    hold_end = time.time()
    rel_code = p.post_cue('ON_LANE', p.fresh())
    rel_wall = time.time()
    p.cue_fn = lambda s: dict(state='ON_LANE', pose_stamp=s[3])
    released = p.wait(lambda r: r['wall'] > rel_wall and r.get('reason') != 'fleet_off_map', 3, 'release')
    p.sleep(4.0)
    moved_wall = time.time()
    # mode-change release
    p.cue_fn = None
    p.sleep(1.2)
    p.post_cue('OFF_MAP', stale)
    latched2 = p.wait(lambda r: r.get('reason') == 'fleet_off_map', 4, 'off_map latch 2')
    p.mode('OFF')
    time.sleep(0.5)
    p.mode('CAMERA_LINE')
    mc_wall = time.time()
    p.sleep(3.0)
    rows = rows_of(p)
    first_off = next((json.loads(l) for l in open(p.out / 'cues.jsonl') if '"OFF_MAP"' in l), None)
    lat_t = latched['wall'] if latched else None
    c = sm['checks']
    c['off_map_accepted'] = bool(first_off and first_off['resp'].get('accepted'))
    c['off_map_stamp_age_s'] = first_off and first_off['stamp_age_s']
    c['latch_after_post_s'] = None if not (latched and first_off) else round(latched['wall'] - first_off['wall'], 2)
    c['gap_travel_m'] = disp(rows, gap_wall, off_wall)[0]               # cue expired: today's keep drives
    hold = disp(rows, (lat_t or 0) + 1.0, hold_end) if lat_t else (None, None)
    c['hold_travel_m'], c['hold_yaw_deg'] = hold
    sim1 = max((r['sim_t'] for r in rows if r['wall'] <= hold_end and r.get('sim_t')), default=None)
    sim0 = sim_at(rows, (lat_t or 0) + 0.3) if lat_t else None
    nz = [x for x in cmds(p, sim0, sim1) if abs(x['lin']) > 1e-6 or abs(x['ang']) > 1e-6] if sim0 and sim1 else ['?']
    c['nonzero_cmd_in_hold'] = len(nz)
    c['probes'] = {k: v[1] for k, v in probes.items()}
    c['latched_through_probes'] = all(r.get('reason') == 'fleet_off_map' for r in rows if lat_t and lat_t + 0.5 <= r['wall'] <= hold_end)
    c['release_accepted'] = rel_code[1]
    c['released'] = released is not None
    c['moved_after_release_m'] = disp(rows, rel_wall, moved_wall)[0]
    s_rel = sim_at(rows, rel_wall)
    c['drive_cmd_after_release_s'] = next((round(x['sim_t'] - s_rel, 2) for x in cmds(p, s_rel or 0, 1e12)
                                           if x['lin'] > 1e-6), None) if s_rel else None
    c['latched_again'] = latched2 is not None
    after = [r for r in rows if r['wall'] > mc_wall + 0.5]
    c['mode_change_cleared'] = bool(after) and all(r.get('reason') != 'fleet_off_map' for r in after)
    sm['timeline'] = reasons(rows)
    ok = (c['off_map_accepted'] and c['latch_after_post_s'] is not None and c['latch_after_post_s'] <= 1.0
          and c['hold_travel_m'] is not None and c['hold_travel_m'] <= 0.01 and c['nonzero_cmd_in_hold'] == 0
          and c['latched_through_probes'] and c['released'] and le(c['drive_cmd_after_release_s'], 2.0)
          and c['latched_again'] and c['mode_change_cleared'])
    sm['verdict'] = 'PASS' if ok else 'FAIL'
    return sm


def s2(p, a):
    sm = {'verdict': 'FAIL', 'checks': {}}
    prep(p, a.pose)
    lane = wrap(p.get('gt')[2] + math.radians(a.turn))
    p.cue_fn = lambda s: dict(state='WRONG_WAY', pose_stamp=s[3],
                              turn_deg=round(deg(wrap(lane - s[2][2])) + p.rng.uniform(-2, 2), 2))
    started = p.wait(is_turn, 10, 'pivot start')
    y0 = (started or {}).get('odom')

    def turned(r):
        return abs(deg(wrap(r['odom'][2] - y0[2]))) if y0 and r.get('odom') else 0.0
    mid = p.wait(lambda r: turned(r) >= a.drop_deg or latch_of(r), 12, 'mid-turn')
    p.cue_fn = None
    drop_wall = time.time()
    p.action('fleet_drop', turned_deg=round(turned(p.last()), 1), reason=p.last().get('reason'))
    latched = p.wait(lambda r: r['wall'] > drop_wall and r.get('reason') in LATCHES, 6, 'latch')
    p.sleep(10.0)
    end = time.time()
    rows = rows_of(p)
    c = sm['checks']
    c['pivot_started'] = started is not None
    c['turned_at_drop_deg'] = round(turned(mid), 1) if mid else None
    c['latch_reason'] = latched and latched.get('reason')
    lp = p.last_post or drop_wall
    s_lp, s_l = sim_at(rows, lp), (latched or {}).get('sim_t')
    c['latch_after_last_cue_sim_s'] = None if s_l is None or s_lp is None else round(s_l - s_lp, 2)
    c['latch_after_last_cue_wall_s'] = None if not latched else round(latched['wall'] - lp, 2)
    c['max_turned_deg'] = round(max((turned(r) for r in rows if started and r['wall'] >= started['wall']), default=0.0), 1)
    c['budget_deg'] = abs(a.turn) + 30
    if latched:
        c['travel_after_latch_m'], c['yaw_after_latch_deg'] = disp(rows, latched['wall'] + 0.3, end)
        sim0, sim1 = sim_at(rows, latched['wall'] + 0.3), sim_at(rows, end)
        c['nonzero_cmd_after_latch'] = sum(1 for x in cmds(p, sim0, sim1 or 1e12) if abs(x['ang']) > 1e-6 or abs(x['lin']) > 1e-6)
        c['still_latched_at_end'] = p.last().get('reason') in LATCHES
    sm['timeline'] = reasons(rows)
    ok = (c['pivot_started'] and c['latch_reason'] in ('fleet_cue_lost', 'fleet_turn_unconfirmed')
          and c['latch_after_last_cue_sim_s'] is not None and c['latch_after_last_cue_sim_s'] <= TTL_S + PERIOD_S + 0.2
          and c['max_turned_deg'] <= c['budget_deg'] and c.get('nonzero_cmd_after_latch') == 0
          and le(c.get('yaw_after_latch_deg'), 3.0) and c.get('still_latched_at_end'))
    sm['verdict'] = 'PASS' if ok else 'FAIL'
    return sm


class FleetWrongWay:
    """Fleet ReturnTracker in short: raw WRONG_WAY while |turn| > 135 (heading_gate 45), the reported
    state follows raw after return_persist_s 1.0, detail fields only while reported == raw."""

    def __init__(self, p, lane, noise, exact180):
        self.p, self.lane, self.noise, self.exact = p, lane, noise, exact180
        self.state = self.cand = None

    def __call__(self, s):
        wall, _, gt, stamp = s
        turn = deg(wrap(self.lane - gt[2])) + self.p.rng.uniform(-self.noise, self.noise)
        turn = (turn + 180.0) % 360.0 - 180.0
        if self.exact and abs(turn) > 170:
            turn = self.p.rng.choice((-1, 1)) * self.p.rng.choice((180.0, 179.5, 179.0))   # sign noise at 180
        raw = 'WRONG_WAY' if abs(turn) > 135 else 'ON_LANE'
        if self.cand is None or self.cand[0] != raw:
            self.cand = (raw, wall)
        if wall - self.cand[1] >= 1.0:
            self.state = raw
        if self.state is None:
            return None
        cur = self.state == raw
        return dict(state=self.state, pose_stamp=stamp, lane_heading_deg=round(deg(self.lane), 1),
                    turn_deg=round(turn, 2) if cur and self.state == 'WRONG_WAY' else None)


def is_turn(r):
    return r.get('reason') in ('fleet_wrong_way_turn', 'fleet_off_lane_turn')


def latch_of(r):
    return r.get('reason') if r and r.get('reason') in LATCHES else None


def cue_events(p, action):
    """``nav.lane_cue`` events of one action (pivot, latched, unlatched, state)."""
    out = []
    for line in open(p.out / 'events.jsonl'):
        e = json.loads(line)
        if 'nav.lane_cue' in json.dumps(e) and (e.get('data') or {}).get('action') == action:
            out.append(e)
    return out


def pivot_rows(rows):
    """First and last status row of the first pivot (reason fleet_*_turn), or (None, None)."""
    i = next((k for k, r in enumerate(rows) if is_turn(r)), None)
    if i is None:
        return None, None
    j = next((k for k in range(i, len(rows)) if not is_turn(rows[k])), len(rows))
    return rows[i], rows[j - 1]


def s3(p, a):
    sm = {'verdict': 'FAIL', 'checks': {}}
    prep(p, a.pose, box=a.box)
    ff = FleetWrongWay(p, a.lane, a.noise, a.exact180)
    p.cue_fn = ff
    p.sleep(20.0 if a.box else 30.0)                                    # whole episode, incl. any stuck
    p.cue_fn = None
    p.sleep(1.5)
    rows = rows_of(p)
    c = sm['checks']
    cues = [json.loads(l) for l in open(p.out / 'cues.jsonl')]
    tds = [x['body'].get('turn_deg') for x in cues if x['body'].get('turn_deg') is not None]
    c['cue_turn_signs'] = {'+': sum(1 for t in tds if t > 0), '-': sum(1 for t in tds if t < 0)}
    c['cues_refused'] = [x['resp'] for x in cues if not x['resp'].get('accepted')]
    a0, a1 = pivot_rows(rows)
    c['pivot_started'] = a0 is not None
    if a.box:
        ev = cue_events(p, 'pivot')                                      # held at once: no turn reason row
        a0 = first(rows, lambda r: r['t'] >= ev[0]['t'] - 0.2) if ev else a0
        c['pivot_started'] = a0 is not None
        ob = first(rows, lambda r: r.get('reason') == 'obstacle_ahead', after=(a0 or {}).get('wall', 0))
        c['obstacle_ahead_seen'] = ob is not None
        c['turning_reason_seen'] = any(r.get('reason') in ('fleet_wrong_way_turn',) for r in rows)
        sim0 = (a0 or {}).get('sim_t')
        angs = [x for x in cmds(p, sim0, 1e12) if abs(x['ang']) > 1e-6] if sim0 else []
        c['nonzero_angular_after_pivot_start'] = len(angs)
        c['yaw_change_deg'] = disp(rows, a0['wall'], rows[-1]['wall'])[1] if a0 else None
        c['body_gap_m'] = sorted({r.get('body_gap_m') for r in rows if r.get('reason') == 'obstacle_ahead'} - {None})[:3]
        c['after'] = reasons(rows, (a0 or rows[0])['wall'])[-4:]
        ok = c['pivot_started'] and c['obstacle_ahead_seen'] and le(c['yaw_change_deg'], 5.0)
        sm['timeline'] = reasons(rows)
        sm['verdict'] = 'PASS' if ok else 'FAIL'
        return sm
    if a0 is None:
        sm['timeline'] = reasons(rows)
        return sm
    sim0, sim1 = a0['sim_t'], a1['sim_t']
    angs = [x['ang'] for x in cmds(p, sim0 - 0.05, sim1 + 0.15) if x['lin'] == 0 and abs(x['ang']) > 0.05]
    c['pivot_cmd_count'] = len(angs)
    c['pivot_sign_changes'] = sum(1 for u, v in zip(angs, angs[1:]) if (u > 0) != (v > 0))
    c['pivot_duration_sim_s'] = round(sim1 - sim0, 2)
    end_row = first(rows, lambda r: not is_turn(r), after=a1['wall'])
    c['pivot_end_reason'] = end_row and end_row.get('reason')
    c['latched'] = latch_of(end_row) or [e.get('data') for e in cue_events(p, 'latched')]
    # Settled pose 1 s after the pivot ended (before the keep drives far).
    settle = first(rows, lambda r: r['wall'] >= (end_row or a1)['wall'] + 0.6) or rows[-1]
    o0, o1, g0, g1 = a0['odom'], settle['odom'], a0['gt'], settle['gt']
    lane_odom = o0[2] + wrap(a.lane - g0[2])        # lane direction in the odom frame at pivot start
    c['odom_turned_deg'] = round(deg(wrap(o1[2] - o0[2])), 1)
    c['yaw_err_odom_deg'] = round(deg(wrap(o1[2] - lane_odom)), 1)
    c['yaw_err_gt_deg'] = round(deg(wrap(g1[2] - a.lane)), 1)
    c['start_err_gt_deg'] = round(deg(wrap(g0[2] - a.lane)), 1)
    c['pivots_started'] = len(cue_events(p, 'pivot'))
    c['halt_turned_deg'] = round(deg(wrap(a1['odom'][2] - o0[2])), 1)   # first pivot, last turning row
    c['all_reasons_after_first_pivot'] = [t[1:] for t in reasons(rows, a1['wall'])][:10]
    sm['timeline'] = reasons(rows)
    ok = (not c['latched'] and c['pivot_sign_changes'] == 0 and abs(c['yaw_err_odom_deg']) <= 10
          and abs(c['odom_turned_deg']) >= 150 and c['pivot_duration_sim_s'] >= 2.0 and c['pivots_started'] == 1)
    sm['verdict'] = 'PASS' if ok else 'FAIL'
    return sm


def s4(p, a):
    sm = {'verdict': 'FAIL', 'checks': {}}
    prep(p, a.pose, box=True)
    p.cue_fn = FleetWrongWay(p, a.lane, a.noise, False)
    stuck = p.wait(lambda r: r.get('stuck') is not None, 25, 'stuck open')
    st_wall = time.time()
    p.cue_fn = lambda s: dict(state='ON_LINE', pose_stamp=s[3], side='left', offset_m=-0.08)   # side cues
    p.sleep(6.0)
    p.cue_fn = None
    end = time.time()
    rows = rows_of(p)
    c = sm['checks']
    c['pivot_started'] = bool(cue_events(p, 'pivot'))
    c['stuck'] = stuck and stuck.get('stuck')
    open_rows = [r for r in rows if r.get('stuck')]                    # while a D-407 stuck is open
    c['pivot_while_stuck'] = sum(1 for r in open_rows if is_turn(r))
    c['latch_while_stuck'] = sorted({latch_of(r) for r in open_rows} - {None})
    c['reasons_while_stuck'] = sorted({str(r.get('reason')) for r in open_rows})
    c['cue_reason_while_stuck'] = [x for x in c['reasons_while_stuck'] if x.startswith(('cue_', 'fleet_'))]
    c['stuck_open_rows'] = len(open_rows)
    c['side_cue_rows_while_stuck'] = sum(1 for r in open_rows if r['wall'] >= st_wall)
    c['yaw_change_while_stuck_deg'] = disp(open_rows, st_wall, end)[1]
    c['after_close'] = reasons(rows, max((r['wall'] for r in open_rows), default=end))[:6]
    c['events_pivot_latched'] = [e.get('data') for e in cue_events(p, 'pivot') + cue_events(p, 'latched')]
    sm['timeline'] = reasons(rows)
    ok = (c['pivot_started'] and stuck is not None and c['pivot_while_stuck'] == 0 and not c['latch_while_stuck']
          and not c['cue_reason_while_stuck'] and le(c['yaw_change_while_stuck_deg'], 5.0))
    sm['verdict'] = 'PASS' if ok else 'FAIL'
    return sm


def plot(p, title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows = [json.loads(l) for l in open(p.out / 'log.jsonl')]
    cm = [json.loads(l) for l in open(p.out / 'cmd.jsonl')]
    cues = [json.loads(l) for l in open(p.out / 'cues.jsonl')]
    rows = [r for r in rows if r.get('sim_t') is not None]
    if not rows:
        return
    t0 = rows[0]['sim_t']
    fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    ax[0].plot([r['sim_t'] - t0 for r in rows if r.get('gt')], [deg(r['gt'][2]) for r in rows if r.get('gt')], label='gt yaw')
    ax[0].plot([r['sim_t'] - t0 for r in rows if r.get('odom')], [deg(r['odom'][2]) for r in rows if r.get('odom')], '--', label='odom yaw')
    ax[0].set_ylabel('deg')
    ax[0].legend(loc='upper right')
    ax[1].step([c['sim_t'] - t0 for c in cm if c.get('sim_t')], [c['lin'] for c in cm if c.get('sim_t')], where='post', label='cmd lin m/s')
    ax[1].step([c['sim_t'] - t0 for c in cm if c.get('sim_t')], [c['ang'] for c in cm if c.get('sim_t')], where='post', label='cmd ang rad/s')
    ax[1].legend(loc='upper right')
    for cu in cues:
        if cu.get('sim_t'):
            ax[1].axvline(cu['sim_t'] - t0, color='0.85', lw=0.6, zorder=0)
    names = []
    for r in rows:
        k = f"{r.get('state')}/{r.get('reason')}"
        if k not in names:
            names.append(k)
    ax[2].plot([r['sim_t'] - t0 for r in rows], [names.index(f"{r.get('state')}/{r.get('reason')}") for r in rows], '.', ms=3)
    ax[2].set_yticks(range(len(names)), names, fontsize=7)
    ax[2].set_xlabel('sim s (grey: cue posts)')
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(p.out / 'plot.png', dpi=110)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario', choices=('s1', 's2', 's3', 's4'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--site-token', required=True)
    ap.add_argument('--base', default='http://127.0.0.1:8671')
    ap.add_argument('--token', default='rosy-dev-operator')
    ap.add_argument('--lat-min', type=float, default=0.4)
    ap.add_argument('--lat-max', type=float, default=0.8)
    ap.add_argument('--noise', type=float, default=3.0)
    ap.add_argument('--turn', type=float, default=120.0, help='s2 turn_deg')
    ap.add_argument('--drop-deg', type=float, default=50.0, help='s2: stop cues once the pivot turned this much')
    ap.add_argument('--pose', default=None, help='x,y,yaw_deg (s2: inner road facing the lane way)')
    ap.add_argument('--lane', type=float, default=-90.0, help='s3/s4: lane direction (deg, map)')
    ap.add_argument('--exact180', action='store_true')
    ap.add_argument('--box', action='store_true')
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    x, y, yd = map(float, (a.pose or (INNER if a.scenario != 's2' else '0.327,0.27,-90')).split(','))
    a.pose, a.lane_deg, a.lane = (x, y, math.radians(yd)), a.lane, math.radians(a.lane)
    p = CueProbe(a)
    sm = {'s1': s1, 's2': s2, 's3': s3, 's4': s4}[a.scenario](p, a)
    sm.update(scenario=a.scenario, args={k: v for k, v in vars(a).items() if k != 'token'})
    rows = rows_of(p)
    if len(rows) > 10 and rows[-1].get('sim_t') and rows[0].get('sim_t'):
        sm['rtf'] = round((rows[-1]['sim_t'] - rows[0]['sim_t']) / (rows[-1]['wall'] - rows[0]['wall']), 2)
    p.cue_fn = None
    p.unbox('lcbox')
    p.close(sm)
    plot(p, f"{a.scenario} {Path(a.out).name}: {sm['verdict']}")


if __name__ == '__main__':
    main()
