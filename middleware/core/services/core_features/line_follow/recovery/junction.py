"""D-494 decision 4 / D-495: one pending junction instruction from Fleet, applied in CORE's tick.

Perception gives CORE no branch candidates (D-494 implementation appendix 2026-10-07). The gate
keeps or zeroes the tick's decision, with one bounded exception: a 'left'/'right' carrying
`turn_deg` (D-495) waits for the robot to stand still at the junction, turns in place on odom
yaw (early stop for latency, then settles inside 5 deg), advances `advance_m`, then hands back
to lane following and must reacquire the lane within REACQUIRE_M. Any doubt aborts to a zero
command. 'left'/'right' without `turn_deg` HOLD as 'unresolved'; 'straight' leaves the ordinary
path (keeper, D-476 bridge) alone; 'stop' HOLDs after `stop_after_m` of measured odom or at the
junction, whichever comes first. A detected junction with no live instruction HOLDs as
'waiting'. Detection is the keep-mode keeper's own junction HOLD reason (line/keep_debug), so
all of this is CAMERA_LINE only. Never changes mode; the twist goes out through the same
decision the manager already returns to CommandManager (D-18).
"""
from __future__ import annotations

import math
from dataclasses import replace

from core_common.protocol.schemas import LineJunctionStatus
from core_features.line_follow.recovery.junction_approach import (
    MAX_AHEAD_M, STEP_MARGIN_S, JunctionApproachMixin, check_expect)

JUNCTION_ACTIONS = ('straight', 'left', 'right', 'stop')
JUNCTION_REASONS = frozenset({'junction_transverse', 'junction_fork'})
MAX_EXPIRES_S = 30.
MAX_STOP_AFTER_M = 2.
#: Odom sample freshness for every distance and yaw used here (same bound as the D-476 bridge).
POSE_MAX_AGE_S = .3
#: D-495 decision 1 bounds.
MAX_TURN_DEG = 150.
MAX_ADVANCE_M = .30
DEFAULT_ADVANCE_M = .10
REACQUIRE_M = .20
REACQUIRE_HEADING_RAD = math.radians(30.)
TURN_TOLERANCE_RAD = math.radians(5.)
TURN_GAIN = 2.            # rad/s per rad of yaw error, clipped to [TURN_MIN_W, angular cap]
TURN_MIN_W = .3           # rad/s floor (or the cap, if lower); sets the turn time limit
TURN_TIME_MARGIN_S = 2.
SETTLE_S = .3             # inside the tolerance this long before the turn counts as done
#: Review L1: the turn starts only after odom shows the robot standing still this long.
#: Speeds are config (junction_still_linear / junction_still_angular, review L3).
STILL_S, STILL_LIMIT_S = .2, 2.
STEP_TIME_S = 5.          # reacquire
MANEUVER = ('approaching', 'turning', 'advancing', 'reacquiring')
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


class JunctionRefused(Exception):
    """A junction instruction CORE does not take in the current line-follow mode (409)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class JunctionMixin(JunctionApproachMixin):
    def _init_junction(self):
        self._junction_seq = 0
        self._turn_basis_now = None  # D-498 basis of this tick's maneuver refusal check
        self._junction = None  # None (idle) | dict: action, place_id, seq, state, ...
        self._junction_seen_at = None
        self._junction_first_seen = None  # start of the current run of sightings
        # Review N1: (yaw, odom key) where this junction stop began; every turn instruction
        # during the same stop aims at entry yaw + turn_deg, so a resend after an abort does
        # not add up headings. Ends when the junction is left behind or the mode changes.
        self._junction_entry = None
        # Review R1: (place_id, action) of the last instruction that ran to completion or was
        # cut after the turn; a repeat is refused until another place_id or a mode change.
        self._junction_done_place = None
        self._keep_corner_at = None

    @property
    def supports_junction_turn(self):
        """D-495 capability: live keep-mode keeper evidence with lane_corner_turning on (the
        junction HOLD that starts a turn) and a motion proof that can admit the turn at all.
        The observer's lane mode and flag are perception parameters; CORE learns them only from
        line/keep_debug (published in keep mode only, carrying corner_turning), so no fresh frame
        means False. The motion basis is D-498 _turn_basis, recomputed on every read."""
        with self._lock:
            at = self._keep_corner_at
            return (at is not None and 0 <= self._clock()-at <= KEEP_EVIDENCE_S
                    and self._turn_basis(self._clock()) is not None)

    @property
    def supports_junction_pivot(self):
        """D-507 2 capability: a keep_debug frame with junction_ahead_v >= 1 within
        KEEP_EVIDENCE_S (the same window as corner_turning for junction_turn)."""
        with self._lock:
            at = self._junction_ahead_v_at
            return at is not None and 0 <= self._clock()-at <= KEEP_EVIDENCE_S

    def _turn_basis(self, now):
        """D-498 / D-507 6: 'enforce' (D-400 floor proof), 'site' (site_floor_map_id, fresh IR
        guard without departure, path mode with the URDF body and a fresh scan) or None. The
        twist's own D-422 sweep is _maneuver_twist's. While approaching (D-507 4) the kind is
        'approach' and an IR centre inside the camera's cross-line band is allowed."""
        j = self._junction
        if j is not None and j.get('state') == 'approaching':
            return self._motion_basis(now, 'approach', centre_ok=self._centre_on_cross_line(now))
        return self._motion_basis(now, 'turn')

    def _reset_junction(self):
        """A line-follow session owns its instruction. A maneuver cut by a mode change (incl.
        E-stop) stays visible as 'aborted' until the next mode change or instruction.
        Review N2: the junction stop itself outlives the mode change. The sighting, the entry
        heading and the done (place_id, action) stay, so re-selecting CAMERA_LINE at the same
        junction cannot re-run a turn. The entry heading ends after lost_after_s without a
        sighting; the done record when another place_id is accepted."""
        j = self._junction
        self._junction = (dict(j, state='aborted', reason='mode_change')
                          if j is not None and j['state'] in MANEUVER else None)
        self._cross_band = None  # D-507 6: a mode change or stop ends any crossing

    def observe_junction(self, reason, received_at, corner_turning=False, ahead_m=None, ahead_v=None):
        """One fresh line/keep_debug frame: a junction reason is a sighting (D-507 5: with its
        junction_ahead_m, if any); corner_turning is the keep-mode evidence behind
        supports_junction_turn."""
        if not math.isfinite(received_at):
            return
        with self._lock:
            if reason in JUNCTION_REASONS:
                last = self._junction_seen_at
                episode = (self._junction_entry is not None or (
                    self._junction is not None and self._junction['state'] == 'waiting'))
                if self._junction_first_seen is None or (
                        not episode and not 0 <= received_at-last <= self._config.stale_after_s):
                    # Review R3: a gap while stopped at the junction is the same junction.
                    self._junction_first_seen = float(received_at)
                self._junction_seen_at = float(received_at)
                self._junction_ahead = (float(ahead_m) if type(ahead_m) in (int, float)
                                        and 0 <= ahead_m <= MAX_AHEAD_M else None, reason)
            self._keep_corner_at = float(received_at) if corner_turning is True else None
            # D-507 2: perception announces junction_ahead_m support on every keep_debug frame.
            self._junction_ahead_v_at = (float(received_at) if type(ahead_v) is int and ahead_v >= 1
                                         else None)

    def set_junction(self, action, place_id, expires_s, stop_after_m=None, turn_deg=None,
                     advance_m=None, now=None, expect=None, exit_segment=None):
        """Store the next-junction instruction: (accepted, seq, state). Raises JunctionRefused
        unless line-follow is CAMERA_LINE (IR_LINE has no junction detection). During a
        maneuver the same instruction is a no-op; a different one aborts it, unaccepted.
        D-520: with exit_segment advance_m is ignored; during an arc every instruction is armed."""
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
        check_expect(expect, action, turn_deg)  # D-507 2; None is an old client
        self._check_exit_segment(exit_segment, action, turn_deg, expect)
        advance = (0. if exit_segment is not None else DEFAULT_ADVANCE_M if advance_m is None
                   else float(advance_m))
        with self._lock:
            if self._mode.value == 'IR_LINE':
                raise JunctionRefused('JUNCTION_CAMERA_ONLY',
                                      'junction instructions need CAMERA_LINE (IR has no junction detection)')
            if self._mode.value != 'CAMERA_LINE':
                raise JunctionRefused('LINE_FOLLOW_NOT_ACTIVE', 'line-follow must be CAMERA_LINE')
            if self._junction_done_place == (place_id, action):
                raise JunctionRefused('JUNCTION_ALREADY_DONE',
                                      f'{action} at {place_id} already ran; send the next place')
            j = self._junction
            if j is not None and j['state'] in MANEUVER:
                if (j['action'], j['place_id'], j['turn_deg'], j['advance_m']) == (
                        action, place_id, turn_deg, advance):
                    return True, j['seq'], j['state']  # a resend of the running instruction
                self._mark_done(j)
                j.update(state='aborted', reason='new_instruction')
                self._bridge_hint = None
                return False, j['seq'], 'aborted'
            if self._junction_done_place is not None and self._junction_done_place[0] != place_id:
                self._junction_done_place = None
            current = self._clock() if now is None else now
            window = self._expect_window(expect, current)
            if window is False:
                raise JunctionRefused('JUNCTION_ODOM_STALE', 'no fresh odom to place the expected junction')
            self._junction_seq += 1
            self._cross_band = None  # a past straight crossing's band ends with the next instruction
            state = ('armed' if action == 'straight' or turn_deg is not None or self._arc_running()
                     else 'executing' if action == 'stop' else 'unresolved')
            self._junction = dict(action=action, place_id=place_id, seq=self._junction_seq,
                                  state=state, expires_at=current+float(expires_s),
                                  stop_after_m=float(stop_after_m or 0.), travel=0.,
                                  last=None, held=False, turn_deg=turn_deg, advance_m=advance,
                                  window=window, map_id=(expect or {}).get('map_id'),
                                  pivot=(expect or {}).get('pivot_past_line_m'), exit_segment=exit_segment)
            self._bridge_hint = None if action == 'stop' else action  # D-476 route hint
            return True, self._junction_seq, state

    def _junction_status(self):
        j = self._junction or {}
        state = 'unexpected' if j.get('outside') and j['state'] == 'armed' else j.get('state', 'idle')
        return LineJunctionStatus(pending_action=j.get('action'), place_id=j.get('place_id'),
                                  state=state, seq=self._junction_seq, turn_deg=j.get('turn_deg'),
                                  reason=j.get('reason'), pivot_basis=j.get('pivot_basis'))

    def _fresh_pose(self, now):
        samples = self._return_evidence.trail.samples
        pose = samples[-1] if samples else None
        return pose if pose is not None and 0 <= now-pose.received_at <= POSE_MAX_AGE_S else None

    def _standing_still(self, now):
        """Odom over its last STILL_S shows |v| < junction_still_linear, |w| < junction_still_angular."""
        trail = self._return_evidence.trail.samples
        if not trail:
            return False
        latest = trail[-1].received_at  # a lagging odom is judged over its own last STILL_S
        samples = [p for p in trail if latest-p.received_at <= STILL_S+.06]
        if len(samples) < 2 or samples[-1].received_at-samples[0].received_at < STILL_S-1e-6:
            return False
        for a, b in zip(samples, samples[1:]):
            dt = b.received_at-a.received_at
            if (dt <= 0 or math.hypot(b.x-a.x, b.y-a.y)/dt >= self._config.junction_still_linear
                    or abs(_wrap(b.yaw-a.yaw))/dt >= self._config.junction_still_angular):
                return False
        return True

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

    def _mark_done(self, j):
        """Review R1: an instruction past its turn (or passed straight) is not run again."""
        if j.get('place_id') is not None and (
                j['state'] in ('advancing', 'reacquiring') or j['action'] == 'straight'):
            self._junction_done_place = (j['place_id'], j['action'])

    def _abort(self, j, reason, decision):
        self._mark_done(j)
        j.update(state='aborted', reason=reason)
        self._bridge_hint = None
        return self._junction_hold('junction_aborted', decision)

    def _unresolved(self, j, decision):
        """Reacquisition failed after the turn (D-495 SIM finding 4): done like an abort, since
        the entry heading is already cleared and a resend would stack a second turn."""
        self._mark_done(j)  # still 'reacquiring' here, so R1 records it
        j['state'] = 'unresolved'
        self._bridge_hint = None
        return self._junction_hold('junction_unresolved', decision)

    def _junction_done(self):
        if self._junction is not None:
            self._mark_done(self._junction)
        self._junction = None
        self._bridge_hint = None
        self._junction_seen_at = self._junction_first_seen = self._junction_anchor = None  # not the next
        self._junction_entry = None

    def _junction_gate(self, now, decision):
        """Keep or zero this tick's decision (locked); a D-495 maneuver supplies its own twist."""
        if self._mode.value == 'OFF':
            if self._junction is not None and self._junction['state'] in MANEUVER:
                self._abort(self._junction, 'mode_change', decision)  # e.g. driver released
            return decision
        if self._mode.value != 'CAMERA_LINE':
            return decision  # review M4: no junction detection on IR_LINE
        seen = (self._junction_seen_at is not None
                and 0 <= now-self._junction_seen_at <= self._config.stale_after_s)
        if seen and self._junction_entry is None:
            pose = self._fresh_pose(now)
            if pose is not None:
                self._junction_entry = (pose.yaw, (self._return_evidence.epoch, pose.frame))
        if seen:
            self._anchor_sighting()  # D-507 3-4
        j = self._junction
        if j is not None and j.get('reason') == 'arc_mismatch':
            j = None  # D-520 2: an arc end with another place's instruction is an unarmed end
        if j is None:
            if not seen:
                if (self._junction_seen_at is None
                        or not 0 <= now-self._junction_seen_at <= self._config.lost_after_s):
                    self._junction_entry = None  # review N2: the junction is left behind
                return decision
            j = self._junction = dict(action=None, place_id=None, state='waiting')
        if j['state'] == 'armed':
            if j.get('window') is not None:
                self._track_retreat(j['window'])  # D-507 2: see every odom sample since receipt
            if now > j['expires_at']:
                self._bridge_hint = None
                if not seen:
                    self._junction = None
                    return decision
                j = self._junction = dict(action=None, place_id=None, state='waiting')
            elif not seen:
                j['outside'] = False
                return decision
            else:
                j['outside'] = not self._in_window(j, now)
                if j['outside']:  # D-507 3: not this instruction's junction; it stays armed
                    return self._junction_hold('junction_unexpected', decision)
                if j['action'] != 'straight':
                    return self._start_turn(j, now, decision)
                j['state'] = 'executing'
                entry = self._junction_entry
                self._set_band('straight', None if entry is None else entry[0], now, j.get('pivot'))
        if j['state'] == 'executing' and j['action'] == 'straight':
            if not seen:
                self._junction_done()  # passed: the keeper no longer sees the junction
            return decision
        if j['state'] in MANEUVER:
            return self._maneuver(j, now, decision)
        if j['action'] == 'stop' and j['state'] == 'executing':
            # Review M7: stop after the distance or at the junction, whichever comes first.
            j['held'] = (j['held'] or seen or not self._odom_travel(j, now)
                         or j['travel'] >= j['stop_after_m'])
            return self._junction_hold('junction_stop', decision) if j['held'] else decision
        return self._junction_hold(_HOLD_REASON[j['state']], decision)

    def _maneuver_refusal(self, now):
        """Why the bounded turn may not run this tick, or None (D-468/D-476 authority rules)."""
        if self._provided('calibration_active') is not False:
            return 'calibration_active'
        self._turn_basis_now = self._turn_basis(now)
        if self._turn_basis_now is None:
            return 'motion_unconfirmed'  # review L2 / D-498: no enforce proof and no site basis
        if self._recovery.stuck_id is not None:
            return 'stuck'
        if self._angular_cap() <= 0:
            return 'angular_limit_zero'
        return None

    def _start_turn(self, j, now, decision):
        """D-495 (a): the junction is seen; stand still, then turn from the measured yaw."""
        pose = self._fresh_pose(now)
        if pose is None:
            # D-495 SIM finding 3: a mode select empties the trail; stay armed and stopped
            # until the first odom sample, at most POSE_MAX_AGE_S, then abort as before.
            waited_from = j.setdefault('odom_wait_at', now)
            if now-waited_from <= POSE_MAX_AGE_S:
                return self._junction_hold('junction_stopping', decision)
            return self._abort(j, 'odom', decision)
        j.pop('odom_wait_at', None)
        # Review M8: the instruction may clear LOST only if the junction sighting (the keeper's
        # junction HOLD) started the loss clock; a lane lost before the junction stays LOST.
        first = self._junction_first_seen
        if (self._loss_started_at is not None and first is not None
                and self._loss_started_at < first-self._config.stale_after_s):
            return self._abort(j, 'lane_lost_before_junction', decision)
        refusal = self._maneuver_refusal(now)
        if refusal is not None:
            return self._abort(j, refusal, decision)
        key, j['basis'] = (self._return_evidence.epoch, pose.frame), self._turn_basis_now
        if self._junction_entry is not None and self._junction_entry[1] != key:
            return self._abort(j, 'odom', decision)  # entry yaw no longer comparable
        self._loss_started_at, self._lost_latched = None, False
        j.update(state='turning', sub='stopping', key=key,
                 phase_at=now, limit=STILL_LIMIT_S, w=0., settled_at=None)
        return self._maneuver(j, now, decision)

    def _next_phase(self, j, state, now, limit):
        j.update(state=state, phase_at=now, limit=limit, travel=0., last=None, frames=0,
                 frame_at=None)

    def _maneuver(self, j, now, decision):
        pose = self._fresh_pose(now)
        if pose is None or (self._return_evidence.epoch, pose.frame) != j['key']:
            return self._abort(j, 'odom', decision)
        refusal = self._maneuver_refusal(now)
        if refusal == 'stuck' and j['state'] == 'reacquiring':
            # The lane stayed out of view past lost_after_s: D-407 asks the console. That is a
            # failed reacquisition, not a broken maneuver.
            return self._unresolved(j, decision)
        if refusal == 'motion_unconfirmed' and j.get('basis') == 'site':
            refusal = 'turn_basis_lost'  # D-498 decision 3
        if refusal is not None:
            return self._abort(j, refusal, decision)
        own_body_check = self._config.body_stop_known and self._scan_points is not None
        reason = (self._status.reason or '').removeprefix('camera_')
        if not (reason in _CONTINUE or reason.startswith(('lane_return_', 'junction_'))
                or (reason == 'obstacle_ahead' and own_body_check and j['state'] != 'reacquiring')):
            return self._abort(j, reason or 'hold', decision)
        if now-j['phase_at'] > j['limit']:
            if j['state'] == 'reacquiring':
                return self._unresolved(j, decision)
            return self._abort(j, 'not_still' if j.get('sub') == 'stopping' else 'timeout', decision)
        if j['state'] != 'turning' and not self._odom_travel(j, now):
            return self._abort(j, 'odom', decision)
        if (j['state'] == 'turning' and j['sub'] == 'stopping' and 'pivot_basis' not in j
                and self._standing_still(now)):
            refusal = self._start_approach(j, now, pose)  # D-507 4
            if refusal is not None:
                return self._abort(j, refusal, decision)
        if j['state'] == 'approaching':
            twist = self._approach_twist(j, pose)
            if twist is not None:
                return self._maneuver_twist(j, now, *twist, decision, 'junction_approaching')
            j.update(state='turning', sub='stopping', phase_at=now, limit=STILL_LIMIT_S, w=0.)
            self._cross_band = None  # not for the turn
        if j['state'] == 'turning':
            twist = self._turn_step(j, now, pose)
            if twist is not None:
                return self._maneuver_twist(j, now, 0., twist, decision,
                                            'junction_stopping' if j['sub'] == 'stopping'
                                            else 'junction_turning')
            if j.get('exit_segment') is not None:  # D-520: stop_point or a crosswalk: today's advance
                arc = self._open_arc(j, now) if j.get('pivot_basis') != 'stop_point' else False
                if arc is not False:
                    return arc or replace(decision, linear=0., angular=0.)
                j['advance_m'] = DEFAULT_ADVANCE_M
            j['speed'] = self._half_trip_speed()  # at most half the trip speed (D-495 1b)
            if j['speed'] <= 0:
                return self._abort(j, 'linear_limit_zero', decision)
            self._next_phase(j, 'advancing', now, j['advance_m']/j['speed']+STEP_MARGIN_S)
            self._odom_travel(j, now)
        if j['state'] == 'advancing':
            if j['travel'] < j['advance_m']:
                return self._maneuver_twist(j, now, j['speed'], 0., decision, 'junction_advancing')
            self._next_phase(j, 'reacquiring', now, STEP_TIME_S)
            self._odom_travel(j, now)
            self._junction_seen_at = self._junction_first_seen = self._junction_anchor = None
            self._junction_entry = None  # the junction stop is over; the robot left it
            self._loss_started_at, self._lost_latched = None, False
            return self._junction_hold('junction_reacquiring', decision)  # follow from next frame
        # reacquiring: ordinary lane following drives; done on N consecutive confident frames.
        if self._reacquired(j, pose):
            self._junction_done()
            return decision
        if j['travel'] >= REACQUIRE_M:
            return self._unresolved(j, decision)
        return decision

    def _turn_step(self, j, now, pose):
        """This tick's angular speed, or None once the turn has settled. Locked."""
        tolerance = TURN_TOLERANCE_RAD
        cap = self._angular_cap()
        floor = min(cap, TURN_MIN_W)
        if j['sub'] == 'stopping':
            if not self._standing_still(now):
                return 0.
            # Review N1: aim from the junction's entry heading, not wherever an earlier
            # (aborted) attempt left the robot.
            base = pose.yaw if self._junction_entry is None else self._junction_entry[0]
            j['target'] = _wrap(base+math.radians(j['turn_deg']))
            error = _wrap(j['target']-pose.yaw)
            j.update(sub='rotating', phase_at=now, limit=abs(error)/floor+TURN_TIME_MARGIN_S)
        error = _wrap(j['target']-pose.yaw)
        if j['sub'] == 'rotating':
            # Review M6: stop early by what the commanded rate turns during the latency.
            if abs(error) > max(tolerance, abs(j['w'])*self._config.junction_turn_lead_s):
                j['w'] = math.copysign(min(cap, max(floor, TURN_GAIN*abs(error))), error)
                return j['w']
            j.update(sub='settling', w=0., settled_at=None)
        # settling: inside the tolerance for SETTLE_S, small corrections at the floor rate.
        if abs(error) > tolerance:
            j['settled_at'] = None
            j['w'] = math.copysign(floor, error)
            return j['w']
        if j['settled_at'] is None:
            j['settled_at'] = now
        j['w'] = 0.
        # Review R2: also standing still on odom, not only inside 5 deg of a lagging yaw.
        return None if now-j['settled_at'] >= SETTLE_S and self._standing_still(now) else 0.

    def _reacquired(self, j, pose):
        """Review M5: N consecutive fresh frames (confidence >= min) received after the hand-
        back, each within 30 deg of the turned heading when containment gives a lane heading."""
        obs, at = self._observation, self._received_at
        if obs is None or at is None or at < j['phase_at'] or at == j['frame_at']:
            return False
        j['frame_at'] = at
        good = obs.visible and obs.confidence >= self._config.min_confidence
        edges = obs.containment.boundaries if good and obs.containment is not None else ()
        if edges:
            lane = pose.yaw + sum(math.atan(b.slope) for b in edges)/len(edges)
            good = abs(_wrap(lane-j['target'])) <= REACQUIRE_HEADING_RAD
        j['frames'] = j['frames']+1 if good else 0
        return j['frames'] >= self._config.junction_reacquire_frames

    def _maneuver_twist(self, j, now, linear, angular, decision, reason):
        """The maneuver's own twist, judged by D-422 along that twist and the D-468 motion proof."""
        self._intended = (linear, angular)
        if (linear or angular) and self._config.body_stop_known and self._scan_points is not None:
            gap, _, _, resume = self._body_clearance(now)
            if gap is not None and gap <= resume:
                return self._abort(j, 'near_stop', decision)
        if self._turn_basis_now == 'enforce' and not self._return_probe(now, linear, angular):
            return self._abort(j, 'motion_unconfirmed', decision)  # site basis: D-422 above
        # D-468 measured the old lane; it starts afresh after the maneuver, not toward it.
        self._return_controller, self._bridge = None, None
        self._loss_started_at, self._lost_latched = None, False
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': reason, 'linear': linear, 'angular': angular})
        return replace(decision, linear=linear, angular=angular)
