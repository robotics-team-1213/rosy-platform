"""D-520 step 1: map-guided arc following after a junction instruction's turn (feed-forward only).

A 'left'/'right' instruction carrying `exit_segment` is done when its turn ends (pivot basis map or
segment_end); a 'straight' one carrying it is done where the previous arc ended. Either opens one
`line_follow.arc` record: omega = g*v*kappa on odom path length to `length_m`, under the IR guard
(one correction per arc), the D-422 sweep of the arc twist and motion_admitted kind 'arc'. The
keeper's reasons, the loss clock, D-476 and D-468 (1)/(3) are off while it runs. At the end an
armed instruction for `end_place_id` pivots right there (segment_end); none (or another place's,
'arc_mismatch') goes back to today's following with nav.lane_arc_end_unarmed. A stop holds until
the next mode change. No camera fit (step 2), no own lock, thread, store or publisher.
"""
from __future__ import annotations

import math

from core_common.protocol.line_arc import LineArcStatus
from core_features.line_follow.crosswalk_zone import CORRIDOR_HALF_M
from core_features.line_follow.model import LineFollowDecision
from core_features.line_follow.recovery.junction import DEFAULT_ADVANCE_M, JunctionRefused
from core_features.line_follow.recovery.junction_approach import STEP_MARGIN_S

MIN_CURVATURE, MAX_CURVATURE = .5, 5.
MAX_LENGTH_M = 1.
MIN_OFFSET_M, MAX_OFFSET_M = .05, .20
#: D-520 2 IR one-time correction (code constants, no config).
ARC_START_IR_GRACE_M = .03
ARC_IR_AWAY_M = .12
ARC_IR_LEVEL_MAX_M = 1.5*ARC_IR_AWAY_M
#: HOLD reasons of a stopped arc (besides today's mode and limit reasons). lane_arc_entry is step 2:
#: the first confident fit within 0.10 m with |e_theta| > 5 deg; it needs lane_arc_fit.py.
ARC_STOP_REASONS = ('lane_arc_edge', 'lane_arc_entry', 'obstacle_ahead', 'lane_arc_pose_lost',
                    'lane_arc_motion_unconfirmed', 'lane_arc_timeout', 'lane_arc_blind')


def check_exit_segment(segment, action, turn_deg, expect, arc_enabled):
    """D-520 1: the range and pairing of `exit_segment` (the API answers 400 before this)."""
    if segment is None:
        return
    try:
        k, length, offset, end = (segment[n] for n in (
            'curvature_1pm', 'length_m', 'outer_line_offset_m', 'end_place_id'))
        ok = (MIN_CURVATURE <= abs(k) <= MAX_CURVATURE and 0 < length <= MAX_LENGTH_M
              and MIN_OFFSET_M <= offset <= MAX_OFFSET_M and isinstance(end, str) and end != '')
    except (KeyError, TypeError):
        ok = False
    if not ok or not (expect or {}).get('map_id') or not (
            action == 'straight' or (action in ('left', 'right') and turn_deg is not None)):
        raise ValueError('exit_segment needs map_id, 0.5 <= |curvature_1pm| <= 5, length_m (0, 1], '
                         'outer_line_offset_m [0.05, 0.20], end_place_id and straight or a turn')
    if not arc_enabled:
        raise JunctionRefused('LANE_ARC_UNAVAILABLE', 'exit_segment needs line_follow.arc_enabled')


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class ArcMixin:
    """LineFollowManager mixin (manager lock, generation and decision; see the module docstring)."""

    def _init_arc(self):
        self._arc_seq = 0
        self._arc = None  # the latest arc record of this process, or None
        self._arc_out = None  # the decision an arc owned this tick (tick() then skips the rest)

    @property
    def supports_lane_arc(self):
        """D-520 1 capability: arc_enabled, which the config refuses without site_floor_map_id."""
        return self._config.arc_enabled

    def _check_exit_segment(self, segment, action, turn_deg, expect):
        check_exit_segment(segment, action, turn_deg, expect, self._config.arc_enabled)

    def _arc_running(self):
        a = self._arc
        return a is not None and a['state'] == 'running' and a['generation'] == self._generation

    def _reset_arc(self, reason):
        """A mode change (incl. E-stop, driver release) stops a running arc with today's reason."""
        if self._arc is not None and self._arc['state'] == 'running':
            self._arc.update(state='stopped', reason=reason)

    def _arc_status(self):
        a = self._arc
        if a is None:
            return None
        c = a['corr'] or {}
        return LineArcStatus(
            arc_seq=a['seq'], from_place_id=a['from'], end_place_id=a['end'], curvature_1pm=a['k'],
            length_m=a['length'], travelled_m=round(a['travelled'], 4), state=a['state'],
            reason=a['reason'], ir_correction=dict(
                side=c.get('side'), phase=c.get('phase'), away_m=round(c.get('away_m', 0.), 4),
                level_m=round(c.get('level_m', 0.), 4), used=bool(c)))

    def _arc_speed(self):
        """The trip's lane speed: min(cruise_speed, max_linear, live manual linear limit); 0 unknown."""
        ceiling = self._provided('linear_ceiling')
        if type(ceiling) not in (int, float) or not math.isfinite(ceiling):
            return 0.
        return max(0., min(self._config.cruise_speed, self._config.max_linear, float(ceiling)))

    def _arc_on_crosswalk(self, pose, k):
        """D-491 / D-520 1: a known crosswalk zone (odom-anchored, this epoch) under the first
        crosswalk_zone_max_m of the map arc from pose. Fleet has no zone data, so CORE checks."""
        ev = self._return_evidence
        for z in self._crosswalks._zones:  # ponytail: reads the zone list; a zones_on(path) API if reused
            anchor = z['anchor'] or (ev._image_pose(z['stamp_ns']) if z['epoch'] == ev.epoch else None)
            if anchor is None or z['epoch'] != ev.epoch:
                continue
            c, n = math.cos(anchor.yaw), math.sin(anchor.yaw)
            for i in range(5):
                d = self._config.crosswalk_zone_max_m*i/4
                x = pose.x + (math.sin(pose.yaw+k*d)-math.sin(pose.yaw))/k - anchor.x
                y = pose.y - (math.cos(pose.yaw+k*d)-math.cos(pose.yaw))/k - anchor.y
                along, across = c*x+n*y, -n*x+c*y
                if (z['near']-z['uncertainty'] <= along <= z['far']+z['uncertainty']
                        and abs(across) <= CORRIDOR_HALF_M+z['uncertainty']):
                    return True
        return False

    def _open_arc(self, j, now):
        """Instruction j is done (its turn ended, or a straight at an arc end); open its arc.
        Returns None, the HOLD decision when the arc cannot start, or False when a known
        crosswalk lies on the arc start: then j keeps today's path (advance or straight pass)."""
        segment, pose, v = j['exit_segment'], self._fresh_pose(now), self._arc_speed()
        if pose is not None and self._arc_on_crosswalk(pose, float(segment['curvature_1pm'])):
            j.update(exit_segment=None, reason='arc_crosswalk', advance_m=DEFAULT_ADVANCE_M)
            return False
        if j.get('place_id') is not None:
            self._junction_done_place = (j['place_id'], j['action'])
        self._junction_done()
        self._arc_seq += 1
        a = self._arc = {
            'seq': self._arc_seq, 'generation': self._generation, 'from': j.get('place_id'),
            'end': segment['end_place_id'], 'k': float(segment['curvature_1pm']),
            'length': float(segment['length_m']), 'map_id': j.get('map_id'), 'travelled': 0.,
            'state': 'running', 'reason': None, 'corr': None, 'grace': set(), 'checked': False,
            'deadline': now + STEP_MARGIN_S}
        v = self._arc_capped(v, 0.)
        a['deadline'] += segment['length_m']/v if v > 0 else 0.
        if pose is None:
            return self._arc_stop('lane_arc_pose_lost')
        a.update(key=(self._return_evidence.epoch, pose.frame), last=(pose.x, pose.y, pose.yaw),
                 yaw0=pose.yaw)
        if v <= 0:
            return self._arc_stop('linear_limit_zero')
        self._arc_quiet()
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': 'lane_arc', 'linear': 0., 'angular': 0.})
        return None

    def _arc_capped(self, v, bias):
        """The speed the angular cap leaves for curvature g*|kappa| + bias (D-344 13), for limits."""
        turn, cap = self._config.arc_curvature_gain*abs(self._arc['k']) + bias, self._angular_cap()
        return min(v, cap/turn) if turn > 0 else v

    def _arc_quiet(self):
        """While the arc runs: no loss clock, no D-476 bridge, no D-468 controller (D-520 2)."""
        self._loss_started_at, self._lost_latched = None, False
        self._return_controller, self._bridge = None, None
        self._confident_frames = 0

    def _arc_stop(self, reason):
        self._arc.update(state='stopped', reason=reason)
        return self._stop_decision('HOLD', reason)

    def _arc_tick(self, now):
        """This tick's decision if an arc owns it (running, or stopped in this session), else None.
        Locked; _tick_locked calls it after the mode and driver checks."""
        a, self._arc_out = self._arc, None
        if a is None or a['generation'] != self._generation or a['state'] == 'ended':
            return None
        self._arc_out = (self._arc_step(a, now) if a['state'] == 'running'
                         else self._stop_decision('HOLD', a['reason']))
        return self._arc_out

    def _arc_step(self, a, now):
        c, cfg = a['corr'], self._config
        samples = self._return_evidence.trail.samples
        pose = samples[-1] if samples else None
        if (pose is None or not 0 <= now-pose.received_at <= cfg.stale_after_s
                or (self._return_evidence.epoch, pose.frame) != a['key']):
            return self._arc_stop('lane_arc_pose_lost')
        x, y, yaw = a['last']
        step = (pose.x-x)*math.cos(yaw)+(pose.y-y)*math.sin(yaw)  # D-507 3 signed projection
        a['last'] = (pose.x, pose.y, pose.yaw)
        a['travelled'] += step
        if c is not None and c['phase'] in ('away', 'level'):
            c[c['phase']+'_m'] += step
        cap, busy = self._angular_cap(), c is not None and c['phase'] in ('away', 'level')
        for reason, failed in (
                ('angular_limit_zero', cap <= 0),
                ('limit_level_too_low', self._below_lane_auto_level()),
                ('calibration_active', self._provided('calibration_active') is not False),
                ('lane_arc_motion_unconfirmed', self._clearance_at is None
                 or not 0 <= now-self._clearance_at <= cfg.clearance_stale_s),
                ('lane_arc_timeout', now > a['deadline']),
                # a correction never runs into the next place's instruction or past its limit
                ('lane_arc_edge', busy and (now > c['deadline'] or a['travelled'] >= a['length']))):
            if failed:
                return self._arc_stop(reason)
        if a['travelled'] >= a['length']:
            return self._arc_end(a, now)
        if a['travelled'] > cfg.arc_blind_max_m:  # step 1: no fit, so all of it is blind
            return self._arc_stop('lane_arc_blind')
        # lane_arc_entry (D-520 6, step 2): the first confident fit's |e_theta| is checked here.
        sigma, kind, side = self._arc_ir(a, now, pose)
        if kind is None:
            return self._arc_stop(side)
        v = self._arc_speed()*(cfg.ir_guard_speed_scale if sigma else 1.)
        if v <= 0:
            return self._arc_stop('linear_limit_zero')
        # REP-103: a line under the left IR (sigma +1) bends right, as today's IR guard.
        w = cfg.arc_curvature_gain*v*a['k'] - sigma*v*cfg.bridge_arm_max_curvature
        if abs(w) > cap:  # D-344 13: the same curvature, slower
            v, w = v*cap/abs(w), math.copysign(cap, w)
        if cfg.body_stop_known and self._scan_points is not None and not self._sweep_clear(now, v, w):
            return self._arc_stop('obstacle_ahead')
        if not self.motion_admitted(now, v, w, kind, a['map_id'], ir_side=side):
            return self._arc_stop('lane_arc_motion_unconfirmed')
        self._intended = (v, w)
        self._arc_quiet()
        self._status = self._status.model_copy(update={
            'state': 'RECOVERING', 'reason': 'lane_arc_correcting' if sigma else 'lane_arc',
            'linear': v, 'angular': w, 'clearance_m': self._clearance})
        return LineFollowDecision(linear=v, angular=w, generation=self._generation,
                                  evidence_revision=self._evidence_revision, mode=self._mode)

    def _arc_ir(self, a, now, pose):
        """(sigma, motion kind, ir_side) of this tick, or (0, None, stop reason). D-520 2."""
        ir, c = self._ir_guard(now), a['corr']
        if ir == 'stale':
            return 0, None, 'lane_arc_motion_unconfirmed'
        if ir == 'centre':
            return 0, None, 'lane_arc_edge'  # the body is on the line
        side = ir if ir in ('left', 'right') else None
        if side is None and self._ir_observation.visible and (c is None or c['phase'] != 'away'):
            return 0, None, 'lane_arc_motion_unconfirmed'  # a clear must be confident (not visible)
        if c is None and a['travelled'] < ARC_START_IR_GRACE_M:  # entry grace: spoke line ends
            if side:
                a['grace'].add(side)
            return 0, 'arc_edge' if side else 'arc', side
        first, a['checked'] = not a['checked'], True
        if c is None or c['phase'] == 'done':
            if side is None:
                return 0, 'arc', None
            if c is not None or (first and side in a['grace']):
                return 0, None, 'lane_arc_edge'  # a second verdict, or the body was there already
            v_c = self._arc_capped(self._arc_speed()*self._config.ir_guard_speed_scale,
                                   self._config.bridge_arm_max_curvature)
            if v_c <= 0:
                return 0, None, 'lane_arc_edge'
            limit = (ARC_IR_AWAY_M+ARC_IR_LEVEL_MAX_M)/v_c + STEP_MARGIN_S
            c = a['corr'] = dict(side=side, phase='away', away_m=0., level_m=0., deadline=now+limit)
            a['deadline'] += limit  # the arc's own limit does not run out during the correction
        s = 1 if c['side'] == 'left' else -1
        if c['phase'] == 'away':
            if side not in (None, c['side']):
                return 0, None, 'lane_arc_edge'
            if c['away_m'] < ARC_IR_AWAY_M:
                return s, 'arc_edge', c['side']
            if side is not None or self._ir_observation.visible:  # only a confident clear ends it
                return 0, None, 'lane_arc_edge'
            c['phase'] = 'level'
        if side is not None:
            return 0, None, 'lane_arc_edge'
        reference = a['yaw0'] + a['k']*a['travelled']  # psi(s) = psi0 + kappa*s
        if s*_wrap(reference-pose.yaw) > 0:
            if c['level_m'] > ARC_IR_LEVEL_MAX_M:
                return 0, None, 'lane_arc_edge'
            return -s, 'arc_edge', c['side']
        c['phase'] = 'done'
        return 0, 'arc', None

    def _arc_end(self, a, now):
        """Segment end on odom length: an armed instruction for end_place_id pivots right here."""
        j, a['state'] = self._junction, 'ended'
        self._loss_started_at, self._lost_latched = None, False  # the loss clock starts afresh
        if j is not None and j['state'] == 'armed' and now > j['expires_at']:
            j = self._junction = None
        if j is not None and j['state'] == 'armed' and j['action'] == 'stop':
            a['reason'] = 'segment_end'  # review: an armed stop always holds, whatever its place
            j.update(state='executing', held=True)
            return None  # the junction gate holds junction_stop
        if j is None or j['state'] != 'armed' or j['place_id'] != a['end']:
            if j is not None and j['state'] == 'armed':
                j.update(state='aborted', reason='arc_mismatch')
            a['reason'] = 'lane_arc_end_unarmed'  # Fleet reads this on the record (mismatch included)
            self._events.publish('nav.lane_arc_end_unarmed', severity='warning',
                                 source='line_follow_manager',
                                 data={'end_place_id': a['end'], 'arc_seq': a['seq'],
                                       'travelled_m': round(a['travelled'], 4)})
            return None  # today's following
        a['reason'], j['pivot_basis'] = 'segment_end', 'segment_end'
        self._junction_seen_at = self._junction_first_seen = self._junction_anchor = None
        self._junction_entry = None
        if j['action'] == 'straight':
            if j.get('exit_segment') is not None:
                out = self._open_arc(j, now)
                if out is not False:
                    return out or self._arc_step(self._arc, now)
            j['state'] = 'executing'  # passes the place as today's straight
            return None
        if j['turn_deg'] is None:
            j['state'] = 'unresolved'
            return None
        self._status = self._status.model_copy(update={'reason': 'junction_stopping'})
        return self._start_turn(j, now, LineFollowDecision(
            generation=self._generation, evidence_revision=self._evidence_revision, mode=self._mode))
