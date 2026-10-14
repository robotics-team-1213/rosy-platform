"""D-507 addendum (2026-10-08): the map-based bend pass on odometry. Mixed into JunctionMixin.

Fleet sends action 'bend' for a site-map bend place: the lane distance to the arc start
(bend_in_m, within bend_tol_m), the signed turn and the centre-line radius. While 'armed' the
camera follows and CORE sums fresh odom travel; every straight confident tick anchors the line
the body followed (D-476 rev 1). Inside the lead window CORE takes over at the first tick where
the camera stops following straight (its own HOLD or loss, a large error, a sighting), or at the
earliest arc start (bend_in - tol; D-759: the anchor line then runs on the lane's map heading when
Fleet's map_entry placed one near the body's own); any other HOLD (obstacle, IR, limits) just holds: 'bending' pursues the anchor line, the arc and the exit line (pure pursuit
at the D-476 bridge_lookahead_m: on a circle it commands that circle's curvature, and on a
corner it turns in early, inside the arc, away from the wall outside the turn), then
'reacquiring' keeps to the exit line until D-495 M5 reacquisition or the next junction's
sighting, else 'unresolved'. Every tick judges the pass's own twist by D-422: a blocked sweep is
a zero command (HOLD junction_bend_blocked) that resumes when clear, within the time bound (as
following holds and resumes); every moving tick then goes through the D-495 maneuver twist
(D-422 again, enforce probe) and motion_admitted kind 'bend'; distance and time are bounded.
"""
from __future__ import annotations

import math

from core_features.line_follow.authority import ARC_ANCHOR_MAX_CARRY_M
from core_features.line_follow.recovery.junction.approach import (
    CORRIDOR_HALF_M, MAX_AHEAD_M, MAX_PIVOT_PAST_LINE_M, REACQUIRE_HEADING_RAD, REACQUIRE_M, STEP_MARGIN_S,
    STEP_TIME_S)

MAX_BEND_DEG, MAX_BEND_IN_M, MAX_BEND_TOL_M, MAX_BEND_RADIUS_M = 90., 2., .30, .5
BEND_FIELDS = ('bend_in_m', 'bend_tol_m', 'bend_radius_m')
MAP_ENTRY_FIELDS = ('yaw_rad', 'pose_yaw_rad', 'odom_stamp_s')  # D-759 1
#: D-759 4: the placed lane heading replaces the anchor's own yaw only within this of it: the
#: bound inside which this module already takes a heading as the lane's (the reacquisition check).
#: Gazebo 2026-10-14 measured 21.6 deg at a take-over; more is a wrong map yaw or a lost lane.
MAP_ENTRY_MAX_HEADING_RAD = REACQUIRE_HEADING_RAD
NEXT_LINE = 'next_line_in_m'  # D-754, optional: the vertex to the next junction's line, [0, MAX_AHEAD_M]
#: ponytail: the 260919 camera/keeper sees a 63 deg bend's new lines ~0.22 m before the arc
#: start (B8 misread onset 0.22 m, B9 gate-on HOLD 0.21 m); a plausibility value, SIM-tuned.
BEND_LEAD_M = .25
BEND_STEP_M = .005      # path sample spacing
_SEARCH = 40            # nearest-point search window (0.2 m of path) after the first tick
#: Cross-track bound (review M2): a side IR (0.020 m off the centre) meets the 25 mm tape's inner
#: edge (0.080 m off the lane centre, 260919) at 0.06 m, the IR fence of the site basis; enforce
#: has no IR verdict, so the pass bounds itself the same.
OFF_PATH_M = .06
#: The camera's own holds: the lane is out of view or unreadable. Any other HOLD (D-422 obstacle,
#: IR guard, limits, driver, LOST) is not the bend coming into view, so the bend stays armed.
CAMERA_HOLDS = frozenset({'line_not_visible', 'observation_stale', 'no_observation', 'low_confidence',
                          'lane_recovery', 'invalid_observation', 'lane_bridge', 'lane_bridge_blocked',
                          'lane_bridge_motion_unconfirmed'})


def check_bend(action, turn_deg, expect):
    """The bend fields belong to 'bend' and 'bend' needs all of them (the API answers 400 first)."""
    e = expect or {}
    entry = e.get('map_entry')
    if entry is not None and not ((action == 'bend' or action in ('left', 'right') and turn_deg is not None)
            and isinstance(entry, dict) and all(  # D-759 rev 1: a turn's exit heading too
            type(entry.get(k)) in (int, float) and math.isfinite(entry[k]) for k in MAP_ENTRY_FIELDS)
            and entry['odom_stamp_s'] > 0):
        raise ValueError('map_entry belongs to bend or a turn: finite yaw_rad, pose_yaw_rad and odom_stamp_s > 0')
    if action != 'bend':
        if any(e.get(k) is not None for k in (*BEND_FIELDS, NEXT_LINE)):
            raise ValueError('bend_in_m, bend_tol_m, bend_radius_m and next_line_in_m belong to bend')
        return
    b_in, tol, radius = (e.get(k) for k in BEND_FIELDS)
    if e.get(NEXT_LINE) is not None and not 0 <= e[NEXT_LINE] <= MAX_AHEAD_M:  # nan fails too
        raise ValueError('next_line_in_m must be in [0, 2]')
    if (turn_deg is None or not math.isfinite(turn_deg) or not 0 < abs(turn_deg) <= MAX_BEND_DEG
            or e.get('map_id') is None or None in (b_in, tol, radius)
            or not (0 < b_in <= MAX_BEND_IN_M and 0 < tol <= MAX_BEND_TOL_M
                    and 0 < radius <= MAX_BEND_RADIUS_M)
            or any(e.get(k) is not None for k in ('expect_in_m', 'expect_tol_m', 'pivot_past_line_m'))):
        raise ValueError('bend needs turn_deg (0 < |turn_deg| <= 90), map_id, bend_in_m (0, 2], '
                         'bend_tol_m (0, 0.30] and bend_radius_m (0, 0.5], and no window or pivot')

#: D-507 note 9: from this turn the bend's own outer line and a line along the exit separate.
OWN_LINE_MIN_TURN_RAD = math.radians(60.)


def bend_path(x, y, yaw, line, radius, turn, tail):
    """Odom points every BEND_STEP_M: `line` straight on yaw, the arc of `radius` through `turn`
    (rad, left +), then `tail` on the exit heading; and the index where the arc ends."""
    arc, points = radius*abs(turn), [(x, y)]
    arc_end = math.ceil((line+arc)/BEND_STEP_M)
    for i in range(arc_end+math.ceil(tail/BEND_STEP_M)):
        s = (i+.5)*BEND_STEP_M  # midpoint heading of this step
        h = yaw+math.copysign(min(max(s-line, 0.), arc)/radius, turn)
        x, y = x+BEND_STEP_M*math.cos(h), y+BEND_STEP_M*math.sin(h)
        points.append((x, y))
    return points, arc_end


class JunctionBendMixin:
    @property
    def supports_lane_bend(self):
        """Capability lane_bend (review M1): a bend could be admitted at all, i.e. the D-400 proof
        is configured while live, or (not live) the standing D-507 6 site parts are configured."""
        with self._lock:
            if self._proof_live():
                try:
                    return (self._return_motion is not None and self._return_proof_configured is not None
                            and self._return_proof_configured() is True)
                except Exception:  # noqa: BLE001 - an unreadable proof admits nothing
                    return False
            c = self._config
            return (c.site_floor_map_id is not None and c.ir_guard_enabled
                    and c.obstacle_mode == 'path' and c.body_stop_known)

    @property
    def supports_lane_bend_map_entry(self):
        """D-759 2 capability: line_follow.bend_map_entry_enabled (default off) wherever CORE
        takes the bend."""
        return self._config.bend_map_entry_enabled and self.supports_lane_bend

    def _place_map_entry(self, j, entry, now):
        """D-759 3: at receipt, the lane's map heading at the arc start turned into odom through
        Fleet's yaw pair (the map yaw and CORE's odom yaw at `odom_stamp_s`) into j['map_entry']:
        {yaw, path}, or {reason} for today's anchor. check_bend has validated the object."""
        c = self._config  # D-759 rev 1: a turn has its own flag
        found = ('none_sent' if entry is None else
                 'disabled' if not (c.bend_map_entry_enabled if j['action'] == 'bend' else c.turn_map_entry_enabled) else
                 self._odom_at_stamp(entry['odom_stamp_s'], now))
        placed = dict(reason=found) if isinstance(found, str) else dict(
            yaw=math.remainder(found[0].yaw+entry['yaw_rad']-entry['pose_yaw_rad'], math.tau), path=found[2])
        j.update(map_entry=placed, entry_why=placed.get('reason'))

    def _map_entry_yaw(self, j, yaw):
        """D-759 4: the placed lane heading for the pass's entry line, or None for today's anchor
        (whose own `yaw` it is judged against) with the reason on the record. The odom run is the
        pass's own (a new one aborts it). Locked."""
        entry, log = j['map_entry'], self._odom_log
        if 'reason' in entry:
            return None
        j['entry_why'] = why = (
            'carry' if not log or log[-1][3]-entry['path'] > ARC_ANCHOR_MAX_CARRY_M else
            'heading' if abs(math.remainder(yaw-entry['yaw'], math.tau)) > MAP_ENTRY_MAX_HEADING_RAD
            else None)
        j['entry_used'] = why is None
        return None if why else entry['yaw']
    @property
    def supports_lane_bend_next_line(self):
        """Capability lane_bend_next_line (D-754): a bend's next_line_in_m is taken, with lane_bend."""
        return self.supports_lane_bend

    def _bend_armed(self, j, now, seen, decision):
        """Follow and measure until the lead window, then take over. Locked."""
        if now > j['expires_at']:
            self._junction, self._bridge_hint = None, None
            return self._junction_gate(now, decision)  # as any expired instruction
        pose = self._fresh_pose(now)
        if pose is None:
            return self._junction_hold('junction_bend_odom', decision)  # where is the arc?
        key = (self._return_evidence.epoch, pose.frame)
        if j['last'][0] != key:
            return self._abort(j, 'odom', decision)  # odom restarted: the distance is unknown
        # Signed along the heading (review H1): a D-468 retrace while armed counts back.
        j['travel'] += ((pose.x-j['last'][1])*math.cos(pose.yaw)+(pose.y-j['last'][2])*math.sin(pose.yaw))
        j['last'] = (key, pose.x, pose.y)
        st, a = self._status, j['travel']-j['bend_in']
        reason = (st.reason or '').removeprefix('camera_')
        tracking = st.state == 'TRACKING' and reason == 'tracking' and st.error is not None
        straight = tracking and abs(st.error) <= self._config.bridge_arm_max_error and not seen
        camera = seen or tracking or reason in CAMERA_HOLDS  # else an obstacle/IR/limit hold
        if straight and a < -j['tol']:
            j['anchor'] = (pose.x, pose.y, pose.yaw, j['travel'])
        if a < -(j['tol']+BEND_LEAD_M):
            j['outside'] = seen  # D-507 3: a junction this far before the bend is not this place
            return self._junction_hold('junction_unexpected', decision) if seen else decision
        j['outside'] = False
        if not camera or (a < -j['tol'] and (straight or j.get('anchor') is None)):
            return decision  # no anchor yet: the ordinary hold and loss clock, until the arc start
        return self._start_bend(j, now, pose, decision)

    def _start_bend(self, j, now, pose, decision):
        if self._lost_latched:
            return self._abort(j, 'lane_lost_before_bend', decision)
        anchor = j.get('anchor')
        if anchor is None or abs(j['travel']-anchor[3]) > BEND_LEAD_M:
            return self._abort(j, 'no_anchor', decision)
        refusal = self._maneuver_refusal(now)
        if refusal is not None:
            return self._abort(j, refusal, decision)
        speed = self._half_trip_speed()
        if speed <= 0:
            return self._abort(j, 'linear_limit_zero', decision)
        x, y, yaw, travel = anchor
        entry = self._map_entry_yaw(j, yaw)
        if entry is not None:
            # D-759 4: the lane's heading, from where the body is now. The straight-tick point may
            # be BEND_LEAD_M back and off a line on another heading (0.2 m at 21.6 deg: 7 cm, past
            # OFF_PATH_M); the arc start stays bend_in of measured travel from the receipt.
            x, y, yaw, travel = pose.x, pose.y, entry, j['travel']
            j['anchor'] = (x, y, yaw, travel)  # the entry axis _bend_own_line and the target read
        turn, radius = math.radians(j['turn_deg']), j['radius']
        ahead = self._config.bridge_lookahead_m
        points, arc_end = bend_path(x, y, yaw, max(0., j['bend_in']-travel), radius, turn,
                                    REACQUIRE_M+2*ahead)  # the exit line the bounded search drives
        i = min(range(arc_end+1), key=lambda k: math.dist(points[k], (pose.x, pose.y)))
        # Time: the rest of the straight at speed, the arc at the speed the angular cap allows.
        line_left = max(0., (arc_end-i)*BEND_STEP_M-radius*abs(turn))
        arc_speed = min(speed, self._angular_cap()*radius)
        self._loss_started_at, self._lost_latched = None, False
        j.update(basis=self._turn_basis_now, path=points, arc_end=arc_end, i=i, speed=speed, pass_at=now,
                 target=math.remainder(yaw+turn, math.tau),
                 bound=(arc_end-i)*BEND_STEP_M+ahead)
        self._next_phase(j, 'bending', now, line_left/speed+radius*abs(turn)/arc_speed+STEP_MARGIN_S)
        self._odom_travel(j, now)
        return self._maneuver(j, now, decision)

    def _bend_step(self, j, now, pose, decision):
        """'bending' and the bend's 'reacquiring': pursue the path, bounded. Locked."""
        if j['state'] == 'reacquiring':
            seen = self._junction_seen_at is not None and self._junction_seen_at >= j['phase_at']
            # lap SIM A: sighted during the pass, not yet reached (and the next junction's, D-754)
            ahead = self._line_ahead(now, j['pass_at']) and not self._bend_own_line(j)
            if self._reacquired(j, pose) or ((seen or ahead) and abs(
                    math.remainder(pose.yaw-j['target'], math.tau)) <= REACQUIRE_HEADING_RAD):
                self._junction_done(keep_sighting=ahead)
                if not ahead:
                    return decision
                # The next junction's stop begins here, aimed along the exit line (D-507 addendum 3).
                self._junction_held, self._junction_entry = True, (j['target'], j['key'])
                self._junction = dict(action=None, place_id=None, state='waiting')
                return self._junction_hold('junction_waiting', decision)
            if j['travel'] >= REACQUIRE_M:
                return self._unresolved(j, decision)
        elif j['travel']*self._config.bridge_distance_scale > j['bound']:
            return self._abort(j, 'distance', decision)  # measured odom, never the command
        twist = self._bend_twist(j, pose)
        if twist is None:
            return self._abort(j, 'off_path', decision)
        if j['state'] == 'bending' and j['i'] >= j['arc_end']:
            self._next_phase(j, 'reacquiring', now, STEP_TIME_S)
            self._odom_travel(j, now)
            self._junction_entry = None  # a mid-arc heading; a sighting on the arc is the next junction's
        if self._bend_blocked(now, twist):  # D-422 on the pass's own twist: hold, keep the pass
            self._return_controller, self._bridge = None, None
            self._loss_started_at, self._lost_latched = None, False  # the pass owns the loss clock
            return self._junction_hold('junction_bend_blocked', decision)
        out = self._maneuver_twist(j, now, *twist, decision, 'junction_'+j['state'])
        if j['state'] == 'aborted' or j.get('refused_tick') == now:
            return out  # held this tick: a second ask that passes must not confirm it (review)
        if not self.motion_admitted(now, *twist, 'bend', j['map_id']):
            return self._unconfirmed(j, now, decision)
        j.pop('refused_since', None)
        return out

    def _bend_line(self, j):
        """(past, out) of the anchored sighting's line point from the bend's vertex: along the
        entry axis and along the exit line. Locked."""
        a, (x, y, yaw, travel) = self._junction_anchor, j['anchor']
        pose = a['pose']
        vertex = max(0., j['bend_in']-travel)+j['radius']*math.tan(abs(math.radians(j['turn_deg']))/2)
        px = pose.x+a['ahead']*math.cos(pose.yaw)-x-vertex*math.cos(yaw)  # line point from the vertex
        py = pose.y+a['ahead']*math.sin(pose.yaw)-y-vertex*math.sin(yaw)
        return (px*math.cos(yaw)+py*math.sin(yaw),
                px*math.cos(j['target'])+py*math.sin(j['target']))

    def _bend_own_line(self, j):
        """The anchored sighting is not the next junction's line, so it is not handed over. Locked.
        With next_line_in_m (D-754) the map judges: its line point is not where the map puts the
        next junction's line along the exit (Gazebo lap run55: W3's own line read mid-arc, 0.164 m
        out, the next place over 1 m on). Without it, D-507 note 9: the line point lies past the
        vertex on the entry axis and no further along the exit than the lane's own outer line
        reaches there (run53: 0.097 m past W2's vertex); only from 60 deg, where the two separate.
        That shape still drops it when the map's line is beyond that reach (review)."""
        (past, out), a, turn = self._bend_line(j), self._junction_anchor, abs(math.radians(j['turn_deg']))
        reach = CORRIDOR_HALF_M*(1+1/math.tan(turn)) if turn >= OWN_LINE_MIN_TURN_RAD else 0.
        own, line = past > 0 and out <= reach, j.get('next_line')
        if line is None:
            return own
        # the vertex's placement + the keeper's range error + its spread on one line (half a lane);
        # a fork sighting measures the place, up to MAX_PIVOT_PAST_LINE_M short of the line (review)
        tol = j['tol']+self._config.crosswalk_range_error_fraction*a['ahead']+CORRIDOR_HALF_M
        short = MAX_PIVOT_PAST_LINE_M if a['reason'] == 'junction_fork' else 0.
        return (own and line > reach) or not -(tol+short) <= out-line <= tol

    def _bend_blocked(self, now, twist):
        """The D-422 swept body gap of this twist is at or under its restart gap."""
        self._intended = twist
        if not (self._config.body_stop_known and self._scan_points is not None):
            return False  # no own check: _maneuver_twist and motion_admitted decide (fail closed)
        at = self._clearance_at
        if at is None or not 0 <= now-at <= self._config.clearance_stale_s:
            return True  # an old scan proves nothing (review L2)
        gap, _, _, resume = self._body_clearance(now)
        return gap is not None and gap <= resume

    def _bend_twist(self, j, pose):
        """Pure pursuit to the path point bridge_lookahead_m past the nearest one; None when the
        robot is more than OFF_PATH_M off the path or that point is not ahead of it."""
        points, i = j['path'], j['i']
        i = j['i'] = min(range(i, min(i+_SEARCH, len(points))),
                         key=lambda k: math.dist(points[k], (pose.x, pose.y)))
        if math.dist(points[i], (pose.x, pose.y)) > OFF_PATH_M:
            return None
        px, py = points[min(i+round(self._config.bridge_lookahead_m/BEND_STEP_M), len(points)-1)]
        dx, dy = px-pose.x, py-pose.y
        x = math.cos(pose.yaw)*dx+math.sin(pose.yaw)*dy
        y = -math.sin(pose.yaw)*dx+math.cos(pose.yaw)*dy
        if x <= 0:
            return None
        linear = j['speed']
        angular, cap = 2*linear*y/(x*x+y*y), self._angular_cap()
        if abs(angular) > cap:
            linear *= cap/abs(angular)  # keep the arc, go slower (D-344 §13)
            angular = math.copysign(cap, angular)
        return linear, angular

