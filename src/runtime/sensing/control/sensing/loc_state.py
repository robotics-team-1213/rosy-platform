"""Subject: the robot-owned localization state, UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT (D-395 §5).

Power-on is always UNKNOWN: Nav2's `set_initial_pose` (0, 0, 0) is not evidence.
Candidates move UNKNOWN or SUSPECT to CANDIDATES under a fresh request id. A
decision must name that id, arrive within `ttl_s` of its receipt, and name at
least one scan-asymmetric cue unless a human made it; then it must pass
`InjectionCheck`. Only then is the robot LOCALIZED, and any running Nav2 goal
is cancelled and replanned. A failed check, a pickup, a sustained fit drop, or
Fleet's monitor send it to SUSPECT with a reason. Autonomy runs in LOCALIZED
only; teleop, check manoeuvres and homing are the caller's to allow elsewhere.

Why the cue rule: on the 180-degree symmetric track the mirror fits the scan
exactly as well as the truth, so the 3 s check passes either. Only a cue the
scan cannot fake (a square seen, paint, a peer, a start slot) tells them apart.
Why receipt time: Fleet and robot clocks are not synchronised (D-395 rev. 3).

Pure logic: the node feeds time, fits and events and executes `Step.actions`.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass

from .loc_verify import FAILED, PASSED, InjectionCheck

#: Cues that differ between a pose and its 180-degree mirror. `last_good` and
#: `overhead` are not here: they may support a decision but never carry it.
ASYMMETRIC_CUES = frozenset({'square', 'paint', 'peers', 'slot'})
DECISION_TTL_S = 5.


class LocState(str, enum.Enum):
    UNKNOWN = 'UNKNOWN'
    CANDIDATES = 'CANDIDATES'
    LOCALIZED = 'LOCALIZED'
    SUSPECT = 'SUSPECT'


@dataclass(frozen=True)
class Step:
    """What changed and what the node must do: 'report_candidates', 'inject_pose',
    'reject_decision', 'cancel_nav_goal', 'report_status'."""
    state: LocState
    actions: tuple = ()
    reason: str | None = None
    pose: tuple | None = None


class LocalizationStateMachine:
    def __init__(self, new_request_id, hold_s=3., settle_s=.5, min_fit=.85, fit_drop_s=1.):
        self._new_id = new_request_id
        self._check_args = dict(hold_s=hold_s, settle_s=settle_s, min_fit=min_fit)
        self.min_fit, self.fit_drop_s = float(min_fit), float(fit_drop_s)
        self.state, self.reason = LocState.UNKNOWN, None
        self.request_id, self.candidates = None, ()
        self.check, self.pose, self.source = None, None, None
        self.pickup = False
        self._low_since = None

    @property
    def autonomy_allowed(self):
        return self.state is LocState.LOCALIZED

    def offer(self, candidates, now_s):
        """New candidates from the global/slot search; ignored while LOCALIZED."""
        if self.state is LocState.LOCALIZED:
            return Step(self.state)
        if not candidates:
            return Step(self.state, reason='no_candidates')
        self.request_id, self.candidates = self._new_id(), tuple(candidates)
        self.check, self.state = None, LocState.CANDIDATES
        return Step(self.state, ('report_candidates',))

    def decide(self, request_id, now_s, candidate_index=None, pose=None, source='candidate',
               cues=(), received_s=None, ttl_s=DECISION_TTL_S):
        """A Fleet (or human) decision: a candidate index or a direct (x, y, yaw).

        `cues` names what carried it; `received_s` is when this robot got it
        (default now) and the decision lapses `ttl_s` later."""
        if self.state is LocState.LOCALIZED:
            return self._reject('already_localized')
        if request_id != self.request_id:
            return self._reject('stale_request')
        received_s = now_s if received_s is None else received_s
        if not now_s - received_s < ttl_s:
            return self._reject('expired')
        if self.check is not None:
            return self._reject('busy')
        if (candidate_index is None) == (pose is None):
            return self._reject('ambiguous_decision')
        if source != 'human' and not ASYMMETRIC_CUES & set(cues):
            return self._reject('no_asymmetric_cue')
        if candidate_index is not None:
            if not 0 <= candidate_index < len(self.candidates):
                return self._reject('bad_index')
            c = self.candidates[candidate_index]
            pose = (c.x, c.y, c.yaw)
        if not all(math.isfinite(v) for v in pose):
            return self._reject('bad_pose')
        self.pose, self.source = tuple(float(v) for v in pose), source
        self.check = InjectionCheck(now_s, **self._check_args)
        return Step(self.state, ('inject_pose',), pose=self.pose)

    def observe_fit(self, now_s, fit):
        """One fresh scan/map fit at the current AMCL pose (None: a tick without a scan)."""
        if self.check is not None:
            result = self.check.observe(now_s, fit)
            if result == PASSED:
                self.state, self.reason, self.check = LocState.LOCALIZED, None, None
                self.pickup, self._low_since = False, None
                return Step(self.state, ('cancel_nav_goal', 'report_status'))
            if result == FAILED:
                return self._suspect('inject_rejected')
            return Step(self.state)
        if self.state is LocState.LOCALIZED and fit is not None:
            if fit >= self.min_fit:
                self._low_since = None
            elif self._low_since is None:
                self._low_since = now_s
            elif now_s - self._low_since >= self.fit_drop_s:
                return self._suspect('fit_drop')
        return Step(self.state)

    def picked_up(self, now_s):
        """Wheel slip or IMU tilt: the last good pose is no longer a cue."""
        self.pickup = True
        if self.state in (LocState.LOCALIZED, LocState.CANDIDATES):
            return self._suspect('pickup')
        return Step(self.state)

    def mark_suspect(self, reason):
        """Fleet's monitor saw this robot elsewhere (D-395 §9)."""
        if self.state is LocState.LOCALIZED:
            return self._suspect(reason)
        return Step(self.state)

    def _suspect(self, reason):
        self.state, self.reason = LocState.SUSPECT, reason
        self.check, self.request_id, self._low_since = None, None, None
        return Step(self.state, ('report_status',), reason=reason)

    def _reject(self, reason):
        return Step(self.state, ('reject_decision',), reason=reason)
