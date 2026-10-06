"""D-476 expected-road bridge: a short, slow drive along the D-468 checkpoint lane's extension.

Runs inside the manager lock as part of the D-468 arbitration (lane_return_decision.py), so the
same generation/evidence_revision and CommandManager path apply. No new store and no map pose:
the target comes from the D-468 checkpoint in odom. Safety stays in body_stop.py (D-422): the
bridge arc becomes the manager's intent and its swept body gap must be clear, and the D-468
motion proof (floor + swept body) must admit the twist. The bridge never touches the loss clock.
"""
from __future__ import annotations

import math
from dataclasses import replace

#: Short breaks only (D-476 decision 3). Image quality, obstacle, departure, stuck never enter.
BRIDGE_REASONS = frozenset({'line_not_visible', 'observation_stale', 'no_observation'})
ROUTE_HINTS = (None, 'left', 'straight', 'right')


def bridge_target(anchor, corridor, pose, lookahead):
    """Robot-frame (x, y) of the point `lookahead` past the robot's projection on the
    checkpoint lane's centre line, extended straight in odom (D-476 decision 2)."""
    ca, sa = math.cos(anchor.yaw), math.sin(anchor.yaw)
    ox, oy = anchor.x - sa*corridor.center, anchor.y + ca*corridor.center
    heading = anchor.yaw + corridor.heading
    ux, uy = math.cos(heading), math.sin(heading)
    s = (pose.x-ox)*ux + (pose.y-oy)*uy + lookahead
    dx, dy = ox + s*ux - pose.x, oy + s*uy - pose.y
    cp, sp = math.cos(pose.yaw), math.sin(pose.yaw)
    return cp*dx + sp*dy, -sp*dx + cp*dy


class LaneBridgeMixin:
    def _init_bridge(self):
        self._bridge = None  # None | 'armed' (last tick verified contained FOLLOW) | dict (bridging)
        self._bridge_hint = None

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

    def _end_bridge(self):
        if isinstance(self._bridge, dict) and self._return_controller is not None:
            # A stopped bridge hands D-468 a retrace path that includes the bridged travel.
            self._return_controller.rebase_retrace()
        self._bridge = None

    def _bridge_step(self, now, state, view, authority, linear_limit, decision):
        """This tick's bridge decision, or None (D-468 owns the tick). Locked."""
        c, ctrl = self._config, self._return_controller
        reason = (self._status.reason or '').removeprefix('camera_')
        if not c.bridge_enabled or state is None or reason not in BRIDGE_REASONS:
            return None
        if state == 'armed':
            if ctrl.phase != 'tracking' or ctrl.checkpoint is None:
                return None
            state = {'epoch': view.epoch, 'last': None, 'travel': 0.}
        anchor, corridor = ctrl.checkpoint
        pose = view.pose
        guard = self._ir_guard(now) if c.ir_guard_enabled else 'clear'
        if (not authority or self._bridge_hint not in (None, 'straight') or guard != 'clear'
                or pose is None or not 0 <= now-pose.received_at <= .3
                or view.epoch != state['epoch'] or pose.frame != anchor.frame
                or not c.body_stop_known or self._scan_points is None
                or self._loss_started_at is None):
            return None
        if state['last'] is not None:
            state['travel'] += math.hypot(pose.x-state['last'][0], pose.y-state['last'][1])
        state['last'] = (pose.x, pose.y)
        travel = state['travel']*c.bridge_distance_scale  # measured odom, never the command
        if (travel >= c.bridge_slow_m
                or now-self._loss_started_at >= c.lost_after_s-c.bridge_time_margin_s):
            return None
        linear = min(c.cruise_speed, linear_limit)
        if travel >= c.bridge_coast_m:
            linear *= c.bridge_slow_scale
        x, y = bridge_target(anchor, corridor, pose, c.bridge_lookahead_m)
        if x <= 0 or linear <= 0:
            return None
        angular = 2*linear*y/(x*x+y*y)  # pure pursuit onto the extended centre line
        cap = self._angular_cap()
        if abs(angular) > cap:
            linear *= cap/abs(angular)  # keep the arc, go slower (D-344 §13)
            angular = math.copysign(cap, angular)
        self._intended = (linear, angular)  # D-422 sweeps this arc from now on
        gap, _, _, resume = self._body_clearance(now)
        if gap is not None and gap <= resume:
            return self._stop_decision('HOLD', 'lane_bridge_blocked')
        if not self._return_probe(now, linear, angular):
            return self._stop_decision('HOLD', 'lane_bridge_motion_unconfirmed')
        self._bridge = state
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': 'lane_bridge', 'linear': linear, 'angular': angular})
        return replace(decision, linear=linear, angular=angular)
