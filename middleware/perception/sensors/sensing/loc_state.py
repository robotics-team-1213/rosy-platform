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

import math
from dataclasses import dataclass

from core_common.protocol.localization import LocState

from .loc_verify import FAILED, PASSED, InjectionCheck
from .localization import wrap

#: Cues that differ between a pose and its 180-degree mirror. `last_good` and
#: `overhead` are not here: they may support a decision but never carry it.
ASYMMETRIC_CUES = frozenset({'square', 'paint', 'peers', 'slot'})
DECISION_TTL_S = 5.
TWIN_SEPARATION_M = 1.0
TWIN_OPPOSITE_TOL_RAD = math.radians(25.0)
TWIN_FIT_GAP = 0.10
TWIN_POSE_TOL_M = 0.05
TWIN_POSE_TOL_RAD = 0.05
UNIQUE_MIN_FIT = 0.90
UNIQUE_MIN_MARGIN = 0.15


@dataclass(frozen=True)
class Step:
    """What changed and what the node must do: 'report_candidates', 'inject_pose',
    'reject_decision', 'cancel_nav_goal', 'report_status'."""
    state: LocState
    actions: tuple = ()
    reason: str | None = None
    pose: tuple | None = None


class LocalizationStateMachine:
    def __init__(self, new_request_id, hold_s=3., settle_s=.5, min_fit=.85, fit_drop_s=1., max_gap_s=.5,
                 drop_fit=None):
        self._new_id = new_request_id
        # max_gap_s: the longest scan silence the 3 s check tolerates (InjectionCheck).
        self._check_args = dict(hold_s=hold_s, settle_s=settle_s, min_fit=min_fit, max_gap_s=max_gap_s)
        self.min_fit, self.fit_drop_s = float(min_fit), float(fit_drop_s)
        self.drop_fit = self.min_fit if drop_fit is None else float(drop_fit)
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
        self.check, self.state, self.reason = None, LocState.CANDIDATES, None
        return Step(self.state, ('report_candidates',))

    def _is_verified_overhead_twin_tiebreak(self, candidate_index, pose, source, cue_set, evidence) -> bool:
        """Accept overhead-only twin tiebreak (2 mirrors) or unique corroboration (1 strong laser candidate)."""
        if source != 'overhead' or 'overhead' not in cue_set or not isinstance(evidence, dict):
            return False
        mode = evidence.get('tiebreak')
        if mode == 'twin':
            if len(self.candidates) != 2:
                return False
            a, b = self.candidates
            if not (isinstance(a.scan_fit, (int, float)) and isinstance(b.scan_fit, (int, float))
                    and math.isfinite(a.scan_fit) and math.isfinite(b.scan_fit)):
                return False
            if a.scan_fit < self.min_fit or b.scan_fit < self.min_fit:
                return False
            if abs(a.scan_fit - b.scan_fit) > TWIN_FIT_GAP:
                return False
            if math.hypot(a.x - b.x, a.y - b.y) < TWIN_SEPARATION_M:
                return False
            if abs(abs(wrap(a.yaw - b.yaw)) - math.pi) > TWIN_OPPOSITE_TOL_RAD:
                return False
        elif mode == 'unique':
            if len(self.candidates) != 1:
                return False
            c = self.candidates[0]
            if (not isinstance(c.scan_fit, (int, float)) or isinstance(c.scan_fit, bool)
                    or not math.isfinite(c.scan_fit) or c.scan_fit < max(self.min_fit, 0.85)):
                return False
            cam_dist = evidence.get('camera_to_chosen_m')
            if (not isinstance(cam_dist, (int, float)) or isinstance(cam_dist, bool)
                    or not math.isfinite(cam_dist) or not 0.0 <= cam_dist <= 0.35):
                return False
        else:
            return False
        if candidate_index is not None:
            if not 0 <= candidate_index < len(self.candidates):
                return False
            c = self.candidates[candidate_index]
            target = (c.x, c.y, c.yaw)
        else:
            target = pose
        if (not isinstance(target, (tuple, list)) or len(target) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and math.isfinite(v) for v in target)):
            return False
        return any(
            math.hypot(target[0] - c.x, target[1] - c.y) <= TWIN_POSE_TOL_M
            and abs(wrap(target[2] - c.yaw)) <= TWIN_POSE_TOL_RAD
            for c in self.candidates
        )

    def decide(self, request_id, now_s, candidate_index=None, pose=None, source='candidate',
               cues=(), received_s=None, ttl_s=DECISION_TTL_S, evidence=None):
        """A Fleet (or human) decision: a candidate index or a direct (x, y, yaw).

        `cues` names what carried it; `received_s` is when this robot got it
        (default now) and the decision lapses `ttl_s` later."""
        if self.state is LocState.LOCALIZED:
            return self._reject('already_localized')
        if self.request_id is None or request_id != self.request_id:
            return self._reject('stale_request')
        received_s = now_s if received_s is None else received_s
        if not now_s - received_s < ttl_s:
            return self._reject('expired')
        if self.check is not None:
            return self._reject('busy')
        if (candidate_index is None) == (pose is None):
            return self._reject('ambiguous_decision')
        cue_set = set(cues)
        if source != 'human' and not ASYMMETRIC_CUES & cue_set:
            if not self._is_verified_overhead_twin_tiebreak(
                    candidate_index, pose, source, cue_set, evidence):
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

    def auto_lock_unique(self, now_s, *, min_fit=UNIQUE_MIN_FIT, min_margin=UNIQUE_MIN_MARGIN):
        """Auto-inject a single candidate whose geometric unique_margin satisfies thresholds."""
        if self.state is not LocState.CANDIDATES or self.check is not None or len(self.candidates) != 1:
            return Step(self.state)
        c = self.candidates[0]
        margin = getattr(c, 'unique_margin', None)
        if (not isinstance(c.scan_fit, (int, float)) or isinstance(c.scan_fit, bool)
                or not math.isfinite(c.scan_fit) or c.scan_fit < max(self.min_fit, min_fit)):
            return Step(self.state)
        if (not isinstance(margin, (int, float)) or isinstance(margin, bool)
                or not math.isfinite(margin) or margin < min_margin):
            return Step(self.state)
        if not all(math.isfinite(v) for v in (c.x, c.y, c.yaw)):
            return Step(self.state)
        self.pose, self.source = (float(c.x), float(c.y), float(c.yaw)), 'unique_map'
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
            if fit >= self.drop_fit:
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

    def retire_candidates(self, reason):
        """Discard a stopped candidate set invalidated by newer scan evidence."""
        if self.state is LocState.CANDIDATES and self.check is None:
            self.candidates = ()
            return self._suspect(reason)
        return Step(self.state)

    def _suspect(self, reason):
        self.state, self.reason = LocState.SUSPECT, reason
        self.check, self.request_id, self._low_since = None, None, None
        return Step(self.state, ('report_status',), reason=reason)

    def _reject(self, reason):
        return Step(self.state, ('reject_decision',), reason=reason)
