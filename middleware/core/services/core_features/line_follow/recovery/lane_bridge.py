"""D-476 expected-road bridge: a short, slow drive along the followed lane's extension, straight
or (rev 2) along the arc of a steady curvature.

Runs inside the manager lock next to the D-468 arbitration (lane_return_decision.py), so the
same generation/evidence_revision and CommandManager path apply, with or without D-468.
Armed by the follower's own confident following (rev 2026-10-07), not by D-468 containment:
the anchor is the D-468 evidence ledger's odom pose at the last confident tick, plus its
corridor when D-468 certified one. Safety stays in body_stop.py (D-422): the bridge arc becomes
the manager's intent and its swept body gap must be clear. The D-468 worker floor proof must
also admit the twist whenever it is live (sensor adapter enforce). The bridge never touches
the loss clock.
"""
from __future__ import annotations

import math
from dataclasses import replace

from core_features.line_follow.model import LineFollowMode

#: Short breaks only (D-476 decision 3). Image quality, obstacle, departure, stuck never enter.
BRIDGE_REASONS = frozenset({'line_not_visible', 'observation_stale', 'no_observation'})
ROUTE_HINTS = (None, 'left', 'straight', 'right')
#: Rev 2 arc: the lane-centre circle's curvature is kappa/(1 - kappa*center) (concentric with the
#: body's circle, `center` to its left). 1 - kappa*center must be >= this, i.e. the lane turns at
#: most twice as tight as the body drove (|kappa_c| <= 2|kappa|). A narrow lane bounds |center| by
#: the per-side play (23.5 mm), so a followed lane has kappa*center <= 4.0 x 0.0235 ~ 0.09; a
#: corridor centre half the body's turning radius inward is not the lane the body ran parallel
#: to, and kappa*center -> 1 puts the lane on the turning centre (singular; sign flips past it).
ARC_MIN_RADIUS_RATIO = .5


def bridge_target(anchor, corridor, pose, lookahead, kappa=0.):
    """Robot-frame (x, y) of the point `lookahead` past the robot's projection on the
    anchored lane's centre line, extended in odom (D-476 decision 2): straight, or (rev 2)
    along the arc of the body's steady curvature `kappa` (1/m, left positive).

    corridor None: no certified corridor, the line the body itself followed (anchor pose and
    heading). On a narrow lane the play bounds that line's offset from the centre."""
    center, heading = (0., 0.) if corridor is None else (corridor.center, corridor.heading)
    ca, sa = math.cos(anchor.yaw), math.sin(anchor.yaw)
    ox, oy = anchor.x - sa*center, anchor.y + ca*center
    heading += anchor.yaw
    if kappa:
        # The lane centre runs concentric with the body's circle, `center` to its left.
        k = kappa/(1-kappa*center)
        cx, cy = ox - math.sin(heading)/k, oy + math.cos(heading)/k
        theta = math.atan2(pose.y-cy, pose.x-cx) + k*lookahead
        dx, dy = cx + math.cos(theta)/abs(k) - pose.x, cy + math.sin(theta)/abs(k) - pose.y
    else:
        ux, uy = math.cos(heading), math.sin(heading)
        s = (pose.x-ox)*ux + (pose.y-oy)*uy + lookahead
        dx, dy = ox + s*ux - pose.x, oy + s*uy - pose.y
    cp, sp = math.cos(pose.yaw), math.sin(pose.yaw)
    return cp*dx + sp*dy, -sp*dx + cp*dy


class LaneBridgeMixin:
    def _init_bridge(self):
        # None | (epoch, pose, corridor|None) armed by the last confident tick | dict (bridging)
        self._bridge = None
        self._bridge_open = False  # a bridge ran last tick and has not yet been handed to D-468
        self._bridge_hint = None
        self._confident_frames = 0  # consecutive accepted confident camera frames
        # Rev 2: this streak's ticks (frame count, error, curvature, (epoch, frame), pose, odom
        # travel); the frame count after the
        # last tick outside the straight band (rev 1 restarted its count there). Cleared by a
        # new streak (lane_return_wiring.py).
        self._arm_ticks, self._straight_from = [], 0
        self._bridge_kappa = 0.  # curvature of the armed anchor; 0 = straight (rev 1)
        self._floor_proof_live = None  # () -> bool: worker floor proof is live (enforce)
        self._return_proof_configured = None  # () -> bool: the motion proof can admit at all
        # After a bridge: [odom travel while confidently tracking, (epoch, pose)]; None = none yet.
        self._rearm = None

    def _arm_bridge(self, now):
        """End of a lane tick: arm from this tick's own straight confident following. Locked."""
        c, st = self._config, self._status
        if (not c.bridge_enabled or isinstance(self._bridge, dict)
                or self._mode is not LineFollowMode.CAMERA_LINE):
            return
        view = self.return_evidence(now=now) if st.state == 'TRACKING' else None
        pose = view and view.pose
        if (st.reason != 'tracking' or pose is None or not 0 <= now-pose.received_at <= .3
                or self._confident_frames == 0):
            self._confident_frames = 0  # following broke: a new streak is needed
            if self._rearm is not None:
                self._rearm[1] = None
            return
        if self._rearm is not None:  # chained bridges: the camera must confirm road between them
            last = self._rearm[1]
            if last is not None and last[0] == view.epoch and last[1].frame == pose.frame:
                self._rearm[0] += math.hypot(pose.x-last[1].x, pose.y-last[1].y)
            self._rearm[1] = (view.epoch, pose)
        n = self._confident_frames
        if abs(st.error) > c.bridge_arm_max_error or abs(st.angular) > c.bridge_arm_max_angular:
            self._straight_from = n  # a curve or a correction: no straight extension (rev 1)
        kappa = st.angular/st.linear if st.linear > 0 else math.inf
        ticks, key = self._arm_ticks, (view.epoch, pose.frame)
        if ticks and ticks[-1][3] != key:
            ticks.clear()  # odom reset: travel and yaw no longer compare
        s = ticks[-1][5] + math.hypot(pose.x-ticks[-1][4].x, pose.y-ticks[-1][4].y) if ticks else 0.
        ticks.append((n, st.error, kappa, key, pose, s))
        while len(ticks) > 1 and self._arc_window(ticks[1:]):
            ticks.pop(0)  # keep the shortest recent window that still spans frames and travel
        if self._rearm is not None and self._rearm[0] < c.bridge_slow_m:
            return
        if n-self._straight_from >= c.bridge_arm_frames:
            kappa = 0.  # rev 1: straight extension
        elif self._arc_window(ticks):
            # Rev 2: a steady arc (steady error and curvature: the body runs parallel to the
            # lane, so its heading is the lane's tangent). Corrections change the error. The
            # odom turn per odom travel over the same ticks must agree with the commanded
            # curvature: a steady command the wheels did not drive (slip, clipping) is no arc.
            _, errors, kappas, _, poses, dist = zip(*ticks)
            kappa = sum(kappas)/len(kappas)
            turn = math.remainder(poses[-1].yaw-poses[0].yaw, math.tau)
            if not (max(errors)-min(errors) <= c.bridge_arm_error_spread
                    and max(kappas)-min(kappas) <= c.bridge_arm_curvature_tolerance
                    and abs(kappa) <= c.bridge_arm_max_curvature
                    and abs(turn/(dist[-1]-dist[0])-kappa) <= c.bridge_arm_curvature_tolerance):
                return
        else:
            return
        self._bridge, self._bridge_kappa = (view.epoch, pose, view.corridor), kappa

    def _arc_window(self, ticks):
        """Rev 2: ticks span bridge_arm_frames distinct frames and bridge_arm_min_travel_m odom."""
        c = self._config
        return (len({t[0] for t in ticks}) >= c.bridge_arm_frames
                and ticks[-1][5]-ticks[0][5] >= c.bridge_arm_min_travel_m)

    def _junction_pending(self, now):
        """A junction instruction other than 'straight', or a sighting within stale_after_s (D-494)."""
        j, seen = self._junction, self._junction_seen_at
        return ((j is not None and j.get('action') != 'straight')
                or (seen is not None and 0 <= now-seen <= self._config.stale_after_s))

    def _floor_proof_required(self):
        """The worker floor proof gates the bridge unless it is known not to be live."""
        try:
            return self._floor_proof_live is None or self._floor_proof_live() is not False
        except Exception:
            return True

    def _bridge_body_clear(self, now):
        """D-422 swept body gap along the bridge arc (self._intended) on a fresh scan."""
        at = self._clearance_at
        if at is None or not 0 <= now-at <= self._config.clearance_stale_s:
            return False
        gap, _, _, resume = self._body_clearance(now)
        return gap is None or gap > resume

    def set_bridge_route_hint(self, hint):
        """Expected road direction at the next junction (D-476 decision 2); None = unknown.

        CORE holds no junction geometry, so only None/'straight' bridge (straight extension);
        'left'/'right' mean the road bends where CORE cannot draw it, so the bridge holds.
        Nothing feeds this yet: route_hint (D-384) and the mission's next lane_graph edge
        have no CORE contract (D-476 open question).
        """
        if hint not in ROUTE_HINTS:
            raise ValueError("bridge route hint must be None, 'left', 'straight' or 'right'")
        with self._lock:
            self._bridge_hint = hint

    def _hand_back_bridge(self):
        """Once, when a bridge stops: D-468 retraces over the measured trail incl. the bridge,
        and the next bridge waits for bridge_slow_m of camera-confirmed travel."""
        if self._bridge_open and not isinstance(self._bridge, dict):
            self._rearm = [0., None]
            if self._return_controller is not None:
                self._return_controller.rebase_retrace()
        self._bridge_open = False

    def _end_bridge(self):
        """Stop a bridge outside the D-468 arbitration (invalid vision)."""
        self._bridge_open = isinstance(self._bridge, dict)
        self._bridge = None
        self._hand_back_bridge()

    def _bridge_step(self, now, state, view, authority, linear_limit, decision):
        """This tick's bridge decision, or None (D-468 or today's path owns the tick). Locked."""
        c, ctrl = self._config, self._return_controller
        reason = (self._status.reason or '').removeprefix('camera_')
        if not c.bridge_enabled or state is None or reason not in BRIDGE_REASONS:
            return None
        if not isinstance(state, dict):
            if ctrl is not None and ctrl.phase != 'tracking':
                return None  # an active D-468 return owns the robot
            epoch, anchor, corridor = state
            state = {'epoch': epoch, 'anchor': anchor, 'corridor': corridor,
                     'last': None, 'travel': 0., 'kappa': self._bridge_kappa}
        anchor, corridor, kappa = state['anchor'], state['corridor'], state.get('kappa', 0.)
        pose = view.pose
        guard = self._ir_guard(now) if c.ir_guard_enabled else 'clear'
        if (not authority or self._recovery.stuck_id is not None
                or not (c.site_floor_map_id is not None or self._floor_proof_required())
                or self._bridge_hint not in (None, 'straight') or guard != 'clear'
                or (kappa and self._junction_pending(now))  # rev 2: no arc into a junction
                or (kappa and 1-kappa*(corridor.center if corridor else 0.) < ARC_MIN_RADIUS_RATIO)
                or pose is None or not 0 <= now-pose.received_at <= .3
                or view.epoch != state['epoch'] or pose.frame != anchor.frame
                or not c.body_stop_known or self._scan_points is None
                or self._loss_started_at is None):
            return None
        if state['last'] is not None:
            state['travel'] += math.hypot(pose.x-state['last'][0], pose.y-state['last'][1])
        state['last'] = (pose.x, pose.y)
        travel = state['travel']*c.bridge_distance_scale  # measured odom, never the command
        elapsed = now-self._loss_started_at
        if (travel >= c.bridge_slow_m or elapsed < 0
                or elapsed >= c.lost_after_s-c.bridge_time_margin_s):
            return None  # a clock that ran backwards cannot prove the time bound
        linear = min(c.cruise_speed, linear_limit)
        if travel >= c.bridge_coast_m:
            linear *= c.bridge_slow_scale
        x, y = bridge_target(anchor, corridor, pose, c.bridge_lookahead_m, kappa)
        if x <= 0 or linear <= 0:
            return None
        angular = 2*linear*y/(x*x+y*y)  # pure pursuit onto the extended centre line
        cap = self._angular_cap()
        if abs(angular) > cap:
            linear *= cap/abs(angular)  # keep the arc, go slower (D-344 §13)
            angular = math.copysign(cap, angular)
        # The arc is the intent even if this tick is blocked: D-422 must keep judging the arc
        # the bridge would drive (not the stale follow intent) until the path is clear again.
        self._intended = (linear, angular)
        if not self._bridge_body_clear(now):
            return self._stop_decision('HOLD', 'lane_bridge_blocked')
        if self._floor_proof_required() and not self._return_probe(now, linear, angular):
            return self._stop_decision('HOLD', 'lane_bridge_motion_unconfirmed')
        self._bridge = state
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': 'lane_bridge', 'linear': linear, 'angular': angular})
        return replace(decision, linear=linear, angular=angular)
