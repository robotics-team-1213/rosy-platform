"""D-491 decision 4: one pending junction instruction from Fleet, applied as a stop gate.

Perception gives CORE no branch candidates (D-491 implementation appendix 2026-10-07), so the
gate only keeps or zeroes the tick's decision: it never adds motion and never changes mode.
'left'/'right' cannot be resolved and HOLD at once; 'straight' leaves the ordinary path (keeper,
D-476 bridge) alone; 'stop' HOLDs after `stop_after_m` of measured odom. A detected junction
with no live instruction HOLDs as 'waiting'. Detection is the keep-mode keeper's own junction
HOLD reason (line/keep_debug), used here only to stop.
"""
from __future__ import annotations

import math
from dataclasses import replace

from core_common.protocol.schemas import LineJunctionStatus

JUNCTION_ACTIONS = ('straight', 'left', 'right', 'stop')
JUNCTION_REASONS = frozenset({'junction_transverse', 'junction_fork'})
MAX_EXPIRES_S = 30.
MAX_STOP_AFTER_M = 2.
#: Odom sample freshness for the stop distance (same bound as the D-476 bridge).
POSE_MAX_AGE_S = .3
_HOLD_REASON = {'waiting': 'junction_waiting', 'unresolved': 'junction_unresolved'}


class JunctionMixin:
    def _init_junction(self):
        self._junction_seq = 0
        self._junction = None  # None (idle) | dict: action, place_id, seq, state, ...
        self._junction_seen_at = None

    def _reset_junction(self):
        """A line-follow session owns its instruction and its junction sighting."""
        self._junction = None
        self._junction_seen_at = None

    def observe_junction(self, reason, received_at):
        """Keeper reason from line/keep_debug; only junction reasons count as a sighting."""
        if reason in JUNCTION_REASONS and math.isfinite(received_at):
            with self._lock:
                self._junction_seen_at = float(received_at)

    def set_junction(self, action, place_id, expires_s, stop_after_m=None, now=None):
        """Store the next-junction instruction. None when line-follow is not CAMERA/IR_LINE."""
        if action not in JUNCTION_ACTIONS:
            raise ValueError('junction action must be straight, left, right or stop')
        if not (isinstance(expires_s, (int, float)) and 0 < expires_s <= MAX_EXPIRES_S):
            raise ValueError('expires_s must be in (0, 30]')
        if stop_after_m is not None and (action != 'stop' or not 0 <= stop_after_m <= MAX_STOP_AFTER_M):
            raise ValueError('stop_after_m belongs to stop and must be in [0, 2]')
        with self._lock:
            if self._mode.value not in ('CAMERA_LINE', 'IR_LINE'):
                return None
            current = self._clock() if now is None else now
            self._junction_seq += 1
            state = {'straight': 'armed', 'stop': 'executing'}.get(action, 'unresolved')
            self._junction = dict(action=action, place_id=place_id, seq=self._junction_seq,
                                  state=state, expires_at=current+float(expires_s),
                                  stop_after_m=float(stop_after_m or 0.), travel=0.,
                                  last=None, held=False)
            self._bridge_hint = None if action == 'stop' else action  # D-476 route hint
            return self._junction_seq, state

    def _junction_status(self):
        j = self._junction or {}
        return LineJunctionStatus(pending_action=j.get('action'), place_id=j.get('place_id'),
                                  state=j.get('state', 'idle'), seq=self._junction_seq)

    def _stop_travelled(self, j, now):
        """True once `stop_after_m` of fresh odom is behind; also when odom cannot prove it."""
        samples = self._return_evidence.trail.samples
        pose = samples[-1] if samples else None
        if pose is None or not 0 <= now-pose.received_at <= POSE_MAX_AGE_S:
            return True
        key = (self._return_evidence.epoch, pose.frame)
        if j['last'] is not None:
            if j['last'][0] != key:
                return True  # odom restarted or jumped: the distance is unknown
            j['travel'] += math.hypot(pose.x-j['last'][1], pose.y-j['last'][2])
        j['last'] = (key, pose.x, pose.y)
        return j['travel'] >= j['stop_after_m']

    def _junction_gate(self, now, decision):
        """Keep or zero this tick's decision (locked). Never adds motion."""
        if self._mode.value == 'OFF':
            return decision
        seen = (self._junction_seen_at is not None
                and 0 <= now-self._junction_seen_at <= self._config.stale_after_s)
        j = self._junction
        if j is None:
            if not seen:
                return decision
            j = self._junction = dict(action=None, place_id=None, state='waiting')
        elif j['state'] == 'armed':
            if now > j['expires_at']:
                self._bridge_hint = None
                if not seen:
                    self._junction = None
                    return decision
                j = self._junction = dict(action=None, place_id=None, state='waiting')
            elif seen:
                j['state'] = 'executing'
        elif j['state'] == 'executing' and j['action'] == 'straight' and not seen:
            self._junction = None  # passed: the keeper no longer sees the junction
            self._bridge_hint = None
            return decision
        if j['state'] in ('armed', 'executing') and j['action'] == 'straight':
            return decision
        if j['action'] == 'stop':
            j['held'] = j['held'] or self._stop_travelled(j, now)
            if not j['held']:
                return decision
            reason = 'junction_stop'
        else:
            reason = _HOLD_REASON[j['state']]
        if self._status.state not in ('LOST', 'OFF'):
            self._status = self._status.model_copy(update={
                'state': 'HOLD', 'reason': reason, 'linear': 0., 'angular': 0.})
        return replace(decision, linear=0., angular=0.)
