"""D-491 decision 4 / D-492: one pending junction instruction from Fleet, applied in CORE's tick.

Perception gives CORE no branch candidates (D-491 implementation appendix 2026-10-07). The gate
keeps or zeroes the tick's decision, with one bounded exception: a 'left'/'right' carrying
`turn_deg` (D-492) turns in place on odom yaw, advances `advance_m`, then hands back to lane
following and must reacquire the lane within REACQUIRE_M. Any doubt aborts to a zero command.
'left'/'right' without `turn_deg` HOLD as 'unresolved'; 'straight' leaves the ordinary path
(keeper, D-476 bridge) alone; 'stop' HOLDs after `stop_after_m` of measured odom. A detected
junction with no live instruction HOLDs as 'waiting'. Detection is the keep-mode keeper's own
junction HOLD reason (line/keep_debug). Never changes mode; the twist goes out through the same
decision the manager already returns to CommandManager (D-18).
"""
from __future__ import annotations

import math
from dataclasses import replace

from core_common.protocol.schemas import LineJunctionStatus

JUNCTION_ACTIONS = ('straight', 'left', 'right', 'stop')
JUNCTION_REASONS = frozenset({'junction_transverse', 'junction_fork'})
MAX_EXPIRES_S = 30.
MAX_STOP_AFTER_M = 2.
#: Odom sample freshness for every distance and yaw used here (same bound as the D-476 bridge).
POSE_MAX_AGE_S = .3
#: D-492 decision 1 bounds.
MAX_TURN_DEG = 150.
MAX_ADVANCE_M = .30
DEFAULT_ADVANCE_M = .10
REACQUIRE_M = .20
TURN_TOLERANCE_RAD = math.radians(5.)
TURN_GAIN = 2.            # rad/s per rad of yaw error, clipped to [TURN_MIN_W, angular cap]
TURN_MIN_W = .3           # rad/s floor (or the cap, if lower); sets the turn time limit
TURN_TIME_MARGIN_S = 2.
STEP_TIME_S = 5.          # advance and reacquire, each
MANEUVER = ('turning', 'advancing', 'reacquiring')
#: keep_debug arrives only in keep mode; this recent a frame with corner_turning proves both.
KEEP_EVIDENCE_S = 2.
#: Base reasons a maneuver may run over: the lane is (expectedly) out of view, or D-468/D-476
#: bookkeeping. Anything else (driver release, limits, IR guard, sensor stale) aborts.
_CONTINUE = frozenset({'tracking', 'line_not_visible', 'observation_stale', 'no_observation',
                       'low_confidence', 'lane_recovery', 'invalid_observation',
                       'lane_edge_left', 'lane_edge_right', 'reselection_required',
                       'lane_bridge', 'lane_bridge_blocked', 'lane_bridge_motion_unconfirmed'})
_HOLD_REASON = {'waiting': 'junction_waiting', 'unresolved': 'junction_unresolved',
                'aborted': 'junction_aborted'}


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class JunctionMixin:
    def _init_junction(self):
        self._junction_seq = 0
        self._junction = None  # None (idle) | dict: action, place_id, seq, state, ...
        self._junction_seen_at = None
        self._keep_corner_at = None

    @property
    def supports_junction_turn(self):
        """D-492 capability: live keep-mode keeper evidence with lane_corner_turning on (the
        junction HOLD that starts a turn) and the bounded turn in this manager. The observer's
        lane mode and flag are perception parameters; CORE learns them only from line/keep_debug
        (published in keep mode only, carrying corner_turning), so no fresh frame means False."""
        with self._lock:
            at = self._keep_corner_at
            return at is not None and 0 <= self._clock()-at <= KEEP_EVIDENCE_S

    def _reset_junction(self):
        """A line-follow session owns its instruction. A maneuver cut by a mode change (incl.
        E-stop) stays visible as 'aborted' until the next mode change or instruction."""
        j = self._junction
        self._junction = (dict(j, state='aborted', reason='mode_change')
                          if j is not None and j['state'] in MANEUVER else None)
        self._junction_seen_at = None

    def observe_junction(self, reason, received_at, corner_turning=False):
        """One fresh line/keep_debug frame: a junction reason is a sighting; corner_turning
        is the keep-mode evidence behind supports_junction_turn."""
        if not math.isfinite(received_at):
            return
        with self._lock:
            if reason in JUNCTION_REASONS:
                self._junction_seen_at = float(received_at)
            self._keep_corner_at = float(received_at) if corner_turning is True else None

    def set_junction(self, action, place_id, expires_s, stop_after_m=None, turn_deg=None,
                     advance_m=None, now=None):
        """Store the next-junction instruction: (accepted, seq, state), or None when line-follow
        is not CAMERA/IR_LINE. During a maneuver the new instruction aborts it, unaccepted."""
        if action not in JUNCTION_ACTIONS:
            raise ValueError('junction action must be straight, left, right or stop')
        if not (isinstance(expires_s, (int, float)) and 0 < expires_s <= MAX_EXPIRES_S):
            raise ValueError('expires_s must be in (0, 30]')
        if stop_after_m is not None and (action != 'stop' or not 0 <= stop_after_m <= MAX_STOP_AFTER_M):
            raise ValueError('stop_after_m belongs to stop and must be in [0, 2]')
        if turn_deg is not None and (action not in ('left', 'right') or not math.isfinite(turn_deg)
                                     or not 0 < abs(turn_deg) <= MAX_TURN_DEG
                                     or (turn_deg > 0) != (action == 'left')):
            raise ValueError('turn_deg belongs to left (+) or right (-), 0 < |turn_deg| <= 150')
        if advance_m is not None and (turn_deg is None or not 0 <= advance_m <= MAX_ADVANCE_M):
            raise ValueError('advance_m belongs to a turn and must be in [0, 0.30]')
        with self._lock:
            if self._mode.value not in ('CAMERA_LINE', 'IR_LINE'):
                return None
            j = self._junction
            if j is not None and j['state'] in MANEUVER:
                j.update(state='aborted', reason='new_instruction')
                self._bridge_hint = None
                return False, j['seq'], 'aborted'
            current = self._clock() if now is None else now
            self._junction_seq += 1
            state = ('armed' if action == 'straight' or turn_deg is not None
                     else 'executing' if action == 'stop' else 'unresolved')
            self._junction = dict(action=action, place_id=place_id, seq=self._junction_seq,
                                  state=state, expires_at=current+float(expires_s),
                                  stop_after_m=float(stop_after_m or 0.), travel=0.,
                                  last=None, held=False, turn_deg=turn_deg,
                                  advance_m=DEFAULT_ADVANCE_M if advance_m is None else float(advance_m))
            self._bridge_hint = None if action == 'stop' else action  # D-476 route hint
            return True, self._junction_seq, state

    def _junction_status(self):
        j = self._junction or {}
        return LineJunctionStatus(pending_action=j.get('action'), place_id=j.get('place_id'),
                                  state=j.get('state', 'idle'), seq=self._junction_seq,
                                  turn_deg=j.get('turn_deg'), reason=j.get('reason'))

    def _fresh_pose(self, now):
        samples = self._return_evidence.trail.samples
        pose = samples[-1] if samples else None
        return pose if pose is not None and 0 <= now-pose.received_at <= POSE_MAX_AGE_S else None

    def _odom_travel(self, j, now):
        """Fresh odom travel since the last call into j['travel']; False if odom cannot prove it."""
        pose = self._fresh_pose(now)
        if pose is None:
            return False
        key = (self._return_evidence.epoch, pose.frame)
        if j['last'] is not None:
            if j['last'][0] != key:
                return False  # odom restarted or jumped: the distance is unknown
            j['travel'] += math.hypot(pose.x-j['last'][1], pose.y-j['last'][2])
        j['last'] = (key, pose.x, pose.y)
        return True

    def _junction_hold(self, reason, decision):
        if self._status.state not in ('LOST', 'OFF'):
            self._status = self._status.model_copy(update={
                'state': 'HOLD', 'reason': reason, 'linear': 0., 'angular': 0.})
        return replace(decision, linear=0., angular=0.)

    def _abort(self, j, reason, decision):
        j.update(state='aborted', reason=reason)
        self._bridge_hint = None
        return self._junction_hold('junction_aborted', decision)

    def _junction_done(self):
        self._junction = None
        self._bridge_hint = None
        self._junction_seen_at = None  # the junction just left behind is not the next one

    def _junction_gate(self, now, decision):
        """Keep or zero this tick's decision (locked); a D-492 maneuver supplies its own twist."""
        if self._mode.value == 'OFF':
            if self._junction is not None and self._junction['state'] in MANEUVER:
                self._abort(self._junction, 'mode_change', decision)  # e.g. driver released
            return decision
        seen = (self._junction_seen_at is not None
                and 0 <= now-self._junction_seen_at <= self._config.stale_after_s)
        j = self._junction
        if j is None:
            if not seen:
                return decision
            j = self._junction = dict(action=None, place_id=None, state='waiting')
        if j['state'] == 'armed':
            if now > j['expires_at']:
                self._bridge_hint = None
                if not seen:
                    self._junction = None
                    return decision
                j = self._junction = dict(action=None, place_id=None, state='waiting')
            elif not seen:
                return decision
            elif j['action'] == 'straight':
                j['state'] = 'executing'
            else:
                return self._start_turn(j, now, decision)
        if j['state'] == 'executing' and j['action'] == 'straight':
            if not seen:
                self._junction_done()  # passed: the keeper no longer sees the junction
            return decision
        if j['state'] in MANEUVER:
            return self._maneuver(j, now, decision)
        if j['action'] == 'stop' and j['state'] == 'executing':
            j['held'] = j['held'] or not self._odom_travel(j, now) or j['travel'] >= j['stop_after_m']
            return self._junction_hold('junction_stop', decision) if j['held'] else decision
        return self._junction_hold(_HOLD_REASON[j['state']], decision)

    def _start_turn(self, j, now, decision):
        """D-492 (a): the junction is seen; turn from here on fresh odom yaw."""
        pose, cap = self._fresh_pose(now), self._angular_cap()
        if pose is None:
            return self._abort(j, 'odom', decision)
        if cap <= 0:
            return self._abort(j, 'angular_limit_zero', decision)
        if self._recovery.stuck_id is not None:
            return self._abort(j, 'stuck', decision)
        turn = math.radians(j['turn_deg'])
        j.update(state='turning', target=_wrap(pose.yaw+turn), key=(self._return_evidence.epoch, pose.frame),
                 phase_at=now, limit=abs(turn)/min(cap, TURN_MIN_W)+TURN_TIME_MARGIN_S)
        # The instruction is the operator's reselection: the keeper's junction HOLD started a
        # loss clock that must not latch LOST under the maneuver (D-492, appendix).
        self._loss_started_at, self._lost_latched = None, False
        return self._maneuver(j, now, decision)

    def _next_phase(self, j, state, now):
        j.update(state=state, phase_at=now, limit=STEP_TIME_S, travel=0., last=None)

    def _maneuver(self, j, now, decision):
        pose = self._fresh_pose(now)
        if pose is None or (self._return_evidence.epoch, pose.frame) != j['key']:
            return self._abort(j, 'odom', decision)
        if self._recovery.stuck_id is not None:
            return self._abort(j, 'stuck', decision)
        own_body_check = self._config.body_stop_known and self._scan_points is not None
        reason = (self._status.reason or '').removeprefix('camera_')
        if not (reason in _CONTINUE or reason.startswith(('lane_return_', 'junction_'))
                or (reason == 'obstacle_ahead' and own_body_check and j['state'] != 'reacquiring')):
            return self._abort(j, reason or 'hold', decision)
        if now-j['phase_at'] > j['limit']:
            if j['state'] == 'reacquiring':
                j['state'] = 'unresolved'
                self._bridge_hint = None
                return self._junction_hold('junction_unresolved', decision)
            return self._abort(j, 'timeout', decision)
        if j['state'] != 'turning' and not self._odom_travel(j, now):
            return self._abort(j, 'odom', decision)
        if j['state'] == 'turning':
            error = _wrap(j['target']-pose.yaw)
            if abs(error) > TURN_TOLERANCE_RAD:
                cap = self._angular_cap()
                if cap <= 0:
                    return self._abort(j, 'angular_limit_zero', decision)
                w = math.copysign(min(cap, max(min(cap, TURN_MIN_W), TURN_GAIN*abs(error))), error)
                return self._maneuver_twist(j, now, 0., w, decision, 'junction_turning')
            self._next_phase(j, 'advancing', now)
            self._odom_travel(j, now)
        if j['state'] == 'advancing':
            if j['travel'] < j['advance_m']:
                ceiling = self._provided('linear_ceiling')
                trip_max = (min(self._config.max_linear, float(ceiling))
                            if type(ceiling) in (int, float) and math.isfinite(ceiling) else 0.)
                if trip_max <= 0:
                    return self._abort(j, 'linear_limit_zero', decision)
                return self._maneuver_twist(j, now, .5*trip_max, 0., decision, 'junction_advancing')
            self._next_phase(j, 'reacquiring', now)
            self._odom_travel(j, now)
            self._junction_seen_at = None
            self._loss_started_at, self._lost_latched = None, False
            return self._junction_hold('junction_reacquiring', decision)  # follow from next frame
        # reacquiring: ordinary lane following drives; done on a fresh confident frame.
        obs = self._observation
        if (obs is not None and obs.visible and obs.confidence >= self._config.min_confidence
                and self._received_at is not None and self._received_at >= j['phase_at']):
            self._junction_done()
            return decision
        if j['travel'] >= REACQUIRE_M:
            j['state'] = 'unresolved'
            self._bridge_hint = None
            return self._junction_hold('junction_unresolved', decision)
        return decision

    def _maneuver_twist(self, j, now, linear, angular, decision, reason):
        """The maneuver's own twist, judged by D-422 along that twist and the D-468 motion proof."""
        self._intended = (linear, angular)
        if self._config.body_stop_known and self._scan_points is not None:
            gap, _, _, resume = self._body_clearance(now)
            if gap is not None and gap <= resume:
                return self._abort(j, 'near_stop', decision)
        if self._return_motion is not None and not self._return_probe(now, linear, angular):
            return self._abort(j, 'motion_unconfirmed', decision)
        # D-468 measured the old lane; it starts afresh after the maneuver, not toward it.
        self._return_controller, self._bridge = None, None
        self._loss_started_at, self._lost_latched = None, False
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': reason, 'linear': linear, 'angular': angular})
        return replace(decision, linear=linear, angular=angular)
