"""D-507 addendum (2026-10-08): the map-based bend pass on odometry. Mixed into JunctionMixin.

Fleet sends action 'bend' for a site-map bend place: the lane distance to the arc start
(bend_in_m, within bend_tol_m), the signed turn and the centre-line radius. While 'armed' the
camera follows and CORE sums fresh odom travel; every straight confident tick anchors the line
the body followed (D-476 rev 1). Inside the lead window CORE takes over at the first tick where
the camera stops following straight (its own HOLD or loss, a large error, a sighting), or at the
earliest arc start (bend_in - tol); any other HOLD (obstacle, IR, limits) just holds: 'bending' pursues the anchor line, the arc and the exit line (pure pursuit
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

from core_features.line_follow.recovery.junction_approach import (
    REACQUIRE_HEADING_RAD, REACQUIRE_M, STEP_MARGIN_S, STEP_TIME_S)

MAX_BEND_DEG, MAX_BEND_IN_M, MAX_BEND_TOL_M, MAX_BEND_RADIUS_M = 90., 2., .30, .5
BEND_FIELDS = ('bend_in_m', 'bend_tol_m', 'bend_radius_m')
#: ponytail: the 260919 camera/keeper sees a 63 deg bend's new lines ~0.22 m before the arc
#: start (B8 misread onset 0.22 m, B9 gate-on HOLD 0.21 m); a plausibility value, SIM-tuned.
BEND_LEAD_M = .25
BEND_STEP_M = .005      # path sample spacing
_SEARCH = 40            # nearest-point search window (0.2 m of path) after the first tick
#: The camera's own holds: the lane is out of view or unreadable. Any other HOLD (D-422 obstacle,
#: IR guard, limits, driver, LOST) is not the bend coming into view, so the bend stays armed.
CAMERA_HOLDS = frozenset({'line_not_visible', 'observation_stale', 'no_observation', 'low_confidence',
                          'lane_recovery', 'invalid_observation', 'lane_bridge', 'lane_bridge_blocked',
                          'lane_bridge_motion_unconfirmed'})


def check_bend(action, turn_deg, expect):
    """The bend fields belong to 'bend' and 'bend' needs all of them (the API answers 400 first)."""
    e = expect or {}
    if action != 'bend':
        if any(e.get(k) is not None for k in BEND_FIELDS):
            raise ValueError('bend_in_m, bend_tol_m and bend_radius_m belong to bend')
        return
    b_in, tol, radius = (e.get(k) for k in BEND_FIELDS)
    if (turn_deg is None or not math.isfinite(turn_deg) or not 0 < abs(turn_deg) <= MAX_BEND_DEG
            or e.get('map_id') is None or None in (b_in, tol, radius)
            or not (0 < b_in <= MAX_BEND_IN_M and 0 < tol <= MAX_BEND_TOL_M
                    and 0 < radius <= MAX_BEND_RADIUS_M)
            or any(e.get(k) is not None for k in ('expect_in_m', 'expect_tol_m', 'pivot_past_line_m'))):
        raise ValueError('bend needs turn_deg (0 < |turn_deg| <= 90), map_id, bend_in_m (0, 2], '
                         'bend_tol_m (0, 0.30] and bend_radius_m (0, 0.5], and no window or pivot')


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
    supports_lane_bend = True  # capability lane_bend: CORE takes action 'bend'

    def _bend_armed(self, j, now, seen, decision):
        """Follow and measure until the lead window, then take over. Locked."""
        if now > j['expires_at']:
            self._junction, self._bridge_hint = None, None
            return self._junction_gate(now, decision)  # as any expired instruction
        pose = self._fresh_pose(now)
        if pose is None:
            return self._junction_hold('junction_bend_odom', decision)  # where is the arc?
        if not self._odom_travel(j, now):
            return self._abort(j, 'odom', decision)  # odom restarted: the distance is unknown
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
        if anchor is None or j['travel']-anchor[3] > BEND_LEAD_M:
            return self._abort(j, 'no_anchor', decision)
        refusal = self._maneuver_refusal(now)
        if refusal is not None:
            return self._abort(j, refusal, decision)
        speed = self._half_trip_speed()
        if speed <= 0:
            return self._abort(j, 'linear_limit_zero', decision)
        x, y, yaw, travel = anchor
        turn, radius = math.radians(j['turn_deg']), j['radius']
        ahead = self._config.bridge_lookahead_m
        points, arc_end = bend_path(x, y, yaw, max(0., j['bend_in']-travel), radius, turn,
                                    REACQUIRE_M+2*ahead)  # the exit line the bounded search drives
        i = min(range(arc_end+1), key=lambda k: math.dist(points[k], (pose.x, pose.y)))
        # Time: the rest of the straight at speed, the arc at the speed the angular cap allows.
        line_left = max(0., (arc_end-i)*BEND_STEP_M-radius*abs(turn))
        arc_speed = min(speed, self._angular_cap()*radius)
        self._loss_started_at, self._lost_latched = None, False
        j.update(basis=self._turn_basis_now, path=points, arc_end=arc_end, i=i, speed=speed,
                 target=math.remainder(yaw+turn, math.tau),
                 bound=(arc_end-i)*BEND_STEP_M+ahead)
        self._next_phase(j, 'bending', now, line_left/speed+radius*abs(turn)/arc_speed+STEP_MARGIN_S)
        self._odom_travel(j, now)
        return self._maneuver(j, now, decision)

    def _bend_step(self, j, now, pose, decision):
        """'bending' and the bend's 'reacquiring': pursue the path, bounded. Locked."""
        if j['state'] == 'reacquiring':
            seen = self._junction_seen_at is not None and self._junction_seen_at >= j['phase_at']
            if self._reacquired(j, pose) or (
                    seen and abs(math.remainder(pose.yaw-j['target'], math.tau)) <= REACQUIRE_HEADING_RAD):
                self._junction_done()
                return decision
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
            self._junction_seen_at = self._junction_first_seen = self._junction_anchor = None
            self._junction_entry = None
        if self._bend_blocked(now, twist):  # D-422 on the pass's own twist: hold, keep the pass
            self._return_controller, self._bridge = None, None
            self._loss_started_at, self._lost_latched = None, False  # the pass owns the loss clock
            return self._junction_hold('junction_bend_blocked', decision)
        out = self._maneuver_twist(j, now, *twist, decision, 'junction_'+j['state'])
        if j['state'] == 'aborted':
            return out
        if not self.motion_admitted(now, *twist, 'bend', j['map_id']):
            return self._abort(j, 'motion_unconfirmed', decision)
        return out

    def _bend_blocked(self, now, twist):
        """The D-422 swept body gap of this twist is at or under its restart gap."""
        self._intended = twist
        if not (self._config.body_stop_known and self._scan_points is not None):
            return False  # no own check: _maneuver_twist and motion_admitted decide (fail closed)
        gap, _, _, resume = self._body_clearance(now)
        return gap is not None and gap <= resume

    def _bend_twist(self, j, pose):
        """Pure pursuit to the path point bridge_lookahead_m past the nearest one; None when that
        point is not ahead of the robot."""
        points, i = j['path'], j['i']
        i = j['i'] = min(range(i, min(i+_SEARCH, len(points))),
                         key=lambda k: math.dist(points[k], (pose.x, pose.y)))
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

