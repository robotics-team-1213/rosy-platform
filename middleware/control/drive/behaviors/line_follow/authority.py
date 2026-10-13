"""D-517 4 (M2): Fleet movement authority, enforced with config ``authority_required`` or, for the rest
of a line-follow session, once Fleet sent one. ``until_m`` counts from the odom sample at ``pose_stamp``
(CORE wall clock, as snapshot ``odom_pose.stamp``); travel since is the odom path length (unsigned:
reversing never adds room). The gate only zeroes a tick's decision, so the body stop (D-422), IR guard
(D-491) and E-stop, which zero it first, always win. Manager lock throughout; a mode change resets it."""
import logging
import math
import time
from collections import deque
from dataclasses import replace

from core_common.protocol.line_authority import SHRINK_TOL_M, STAMP_TOL_S, AuthorityRefused, LineAuthorityStatus


class AuthorityMixin:
    _wall = staticmethod(time.time)  # CORE wall clock, the one odom_pose.stamp is on

    def _init_authority(self):  # odom log: (wall, (epoch, frame), stamp_ns, path_m, x, y), >= 4 s at 50 Hz
        self._odom_log, self._authority, self._authority_seen, self._authority_held = deque(maxlen=200), None, False, False

    def observe_return_pose(self, **sample):
        accepted = super().observe_return_pose(**sample)
        with self._lock:
            ev, log = self._return_evidence, self._odom_log
            p = ev.trail.samples[-1] if ev.trail.samples else None
            key = None if p is None else (ev.epoch, p.frame)
            if p is None or (log and log[-1][1:3] == (key, p.stamp_ns)):
                return accepted  # refused or already logged
            if not (log and log[-1][1] == key):
                log.clear()  # a new odom run: travel across the gap is unknown
            path = log[-1][3]+math.hypot(p.x-log[-1][4], p.y-log[-1][5]) if log else 0.
            log.append((self._wall(), key, p.stamp_ns, path, p.x, p.y))
        return accepted

    def set_authority(self, authority_id, leg_id, pose_stamp, until_m, ttl_s, now=None):
        """Store Fleet's authority. ``AuthorityRefused`` drops the held one too (the robot stands)."""
        with self._lock:
            if self._mode.value == 'OFF':
                raise AuthorityRefused('LINE_FOLLOW_NOT_ACTIVE', 'line-follow is OFF')
            now, log, ev = self._clock() if now is None else now, self._odom_log, self._return_evidence
            self._authority_seen, pose = True, self._fresh_pose(now)
            fresh = pose is not None and bool(log) and log[-1][1] == (ev.epoch, pose.frame)
            # The sample at or before pose_stamp: never less travel than since the pose.
            base = next((e for e in reversed(log) if e[0] <= pose_stamp), None) if fresh else None
            refusal = (('AUTHORITY_ODOM_STALE', 'no fresh odom to measure travel') if not fresh else
                       ('AUTHORITY_POSE_FUTURE', 'pose_stamp is newer than CORE odom')
                       if pose_stamp > log[-1][0]+STAMP_TOL_S else
                       ('AUTHORITY_POSE_STALE', 'pose_stamp is older than CORE odom history') if base is None else None)
            if refusal is not None:
                self._authority = None
                raise AuthorityRefused(*refusal)
            end, a = base[3]+until_m, self._authority
            if a is not None and (a['leg_id'], a['key']) == (leg_id, base[1]) and now <= a['expires_at']:
                if end < a['end']-SHRINK_TOL_M:  # never shrinks: ignored, so it expires unless extended
                    logging.getLogger(__name__).info('authority %s on leg %s ignored: %.3f m short', authority_id, leg_id, a['end']-end)
                    return dict(accepted=False, reason='shrink', authority=self.authority_status(now))
                end = max(end, a['end'])
            self._authority = dict(authority_id=authority_id, leg_id=leg_id, end=end, key=base[1], expires_at=now+ttl_s)
            return dict(accepted=True, reason=None, authority=self.authority_status(now))

    def _authority_state(self, now):
        """(state, remaining_m, reason); HOLDING latches with the D-422 stop gap + hysteresis. Locked."""
        a, log, c = self._authority, self._odom_log, self._config
        if a is None or now > a['expires_at']:
            return ('NONE', None, 'authority_none') if a is None else ('EXPIRED', None, 'authority_expired')
        if self._fresh_pose(now) is None or not log or log[-1][1] != a['key']:
            return 'HOLDING', None, 'authority_odom_stale'
        remaining, stop = a['end']-log[-1][3], c.derived_stop_gap_m(c.max_linear)  # fastest line follow commands
        self._authority_held = remaining <= stop+(c.obstacle_resume_hysteresis_m if self._authority_held else 0.)
        return ('HOLDING', remaining, 'authority_end') if self._authority_held else ('FREE', remaining, None)

    def authority_status(self, now=None):
        """GET /line-follow ``authority`` while enforced, else None (the response stays as before)."""
        with self._lock:
            if not (self._config.authority_required or self._authority_seen):
                return None
            now = self._clock() if now is None else now
            (state, remaining, reason), a = self._authority_state(now), self._authority or {}
            return LineAuthorityStatus(state=state, authority_id=a.get('authority_id'), leg_id=a.get('leg_id'),
                reason=reason, remaining_m=None if remaining is None else round(remaining, 3),
                expires_in_s=None if not a else round(max(0., a['expires_at']-now), 3)).model_dump()

    def _authority_gate(self, now, decision):
        state = (self._config.authority_required or self._authority_seen) and self._authority_state(now)
        if not state or state[0] == 'FREE' or not (decision.linear or decision.angular):
            return decision
        if self._status.state not in ('LOST', 'OFF'):
            self._status = self._status.model_copy(update={'state': 'HOLD', 'reason': state[2], 'linear': 0., 'angular': 0.})
        return replace(decision, linear=0., angular=0.)
