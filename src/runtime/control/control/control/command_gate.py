"""Semantic command restrictions shared by the legacy node and CORE adapters.

This layer consumes already classified sensor state. It neither establishes
sensor freshness nor replaces the downstream calibrated swept-footprint check.
"""
import math
from dataclasses import dataclass, replace
from threading import Lock
from uuid import uuid4
from .lidar_guard import TranslationEvidence, command_translation_bumpers
from .obstacle_risk import TrackedEvidence


@dataclass(frozen=True)
class GateInputs:
    estop: bool = False
    profile_valid: bool = True
    observation_failure: str | None = None
    localization_ready: bool = True
    pickup: bool = False
    obstacle_hold: str | None = None
    command_age: float = 0.
    rotation_trial: bool = False
    translation_trial: bool = False
    tilt: bool = False
    rear_blocked: bool = False
    obstacle: bool = False
    cliff: bool = False
    can_rotate: bool = True
    bounded_motion: bool = False
    legacy_tilt_recovery: bool = False


@dataclass(frozen=True)
class GateResult:
    linear: float
    angular: float
    reason: str
    discard: bool = False


@dataclass(frozen=True)
class GateSnapshot:
    session: str
    sequence: int
    calibration_revision: str
    observed_at: float
    expires_at: float
    inputs: GateInputs
    translation: TranslationEvidence | None = None
    tracking: TrackedEvidence | None = None
    linear_limit: float | None = None


class CommandPolicy:
    """In-process handoff of classified sensor state, never a motor publisher.

    A producer must use the oldest required sensor deadline, not its publish
    time. Revision identifies the applied calibration; it is not a file loader.
    """
    def __init__(self, calibration_revision):
        if not isinstance(calibration_revision, str) or not calibration_revision.strip():
            raise ValueError('Applied calibration revision is required')
        self._revision = calibration_revision
        self._session = uuid4().hex
        self._sequence = 0
        self._observed_at = None
        self._expires_at = None
        self._snapshot = None
        self._translation_required = False
        self._tracking_required = False
        self._lock = Lock()

    @property
    def revision(self):
        return self._revision

    @property
    def session(self):
        return self._session

    def invalidate(self):
        with self._lock:
            self._snapshot = None

    def update_observations(self, observations, required, inputs, now, sequence, applied_revision, *, translation=None,
                            tracking=None, linear_limit=None):
        """Capture classified state and clocks in one serialized producer callback.

        The producer supplies its actually applied revision. Never label sensor
        state with a requested revision merely because CORE has bound it.
        """
        window = observations.policy_window(required, now)
        if window is None or applied_revision != self.revision:
            self.invalidate()
            return False
        return self.update(GateSnapshot(self.session, sequence, applied_revision, *window, inputs,
                                        translation, tracking, linear_limit))

    def update(self, snapshot):
        if (not isinstance(snapshot, GateSnapshot) or snapshot.session != self.session or
                snapshot.calibration_revision != self.revision or type(snapshot.sequence) is not int or
                not isinstance(snapshot.inputs, GateInputs) or
                not all(type(v) in (int, float) and math.isfinite(v)
                        for v in (snapshot.observed_at, snapshot.expires_at)) or
                not 0 < snapshot.expires_at - snapshot.observed_at <= .5):
            return False
        if (snapshot.linear_limit is not None and
                (type(snapshot.linear_limit) not in (int, float) or
                 not math.isfinite(snapshot.linear_limit) or snapshot.linear_limit < 0)):
            return False
        with self._lock:
            if snapshot.sequence <= self._sequence:
                return False
            if self._observed_at is not None and (
                    snapshot.observed_at < self._observed_at or
                    (snapshot.observed_at == self._observed_at and snapshot.expires_at > self._expires_at)):
                return False
            self._sequence = snapshot.sequence
            self._observed_at = snapshot.observed_at
            self._expires_at = snapshot.expires_at
            if snapshot.translation is not None:
                self._translation_required = True
            elif self._translation_required:
                self._snapshot = None
                return False
            if snapshot.tracking is not None:
                self._tracking_required = True
            elif self._tracking_required:
                self._snapshot = None
                return False
            self._snapshot = snapshot
        return True

    def evaluate(self, linear, angular, now, *, allow_bounded_sweep=False):
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None or not snapshot.observed_at <= now <= snapshot.expires_at:
            return None
        state = snapshot.inputs
        flags = (state.estop, state.profile_valid, state.localization_ready, state.pickup,
                 state.rotation_trial, state.translation_trial, state.tilt, state.rear_blocked,
                 state.obstacle, state.cliff, state.can_rotate, state.bounded_motion, state.legacy_tilt_recovery)
        if any(type(flag) is not bool for flag in flags):
            result = GateResult(0., 0., 'invalid_sensor_state', True)
        elif state.legacy_tilt_recovery or (state.bounded_motion and allow_bounded_sweep is not True):
            # These paths require explicit recovery arbitration / calibrated
            # swept-footprint integration before CORE may activate them.
            result = GateResult(0., 0., 'actuation_policy_unavailable', True)
        else:
            if snapshot.translation is not None:
                front, rear = command_translation_bumpers(snapshot.translation, linear, angular, now)
                state = replace(state, obstacle=state.obstacle or front, rear_blocked=state.rear_blocked or rear)
            result = evaluate_command(linear, angular, replace(state, command_age=0.))
            if snapshot.tracking is not None and result.reason in ('allow', 'motion_limited', 'trajectory_changed'):
                if not isinstance(snapshot.tracking, TrackedEvidence):
                    raise ValueError('Invalid tracking evidence')
                tracking = snapshot.tracking.evaluate(linear, now)
                if tracking['action'] != 'clear':
                    result = GateResult(0., 0., tracking['reason'], tracking['action'] == 'stop')
            if (snapshot.linear_limit is not None and result.linear != 0. and
                    abs(result.linear) > snapshot.linear_limit and
                    result.reason in ('allow', 'motion_limited')):
                factor = snapshot.linear_limit/abs(result.linear)
                result = GateResult(result.linear*factor, result.angular*factor,
                                    'adaptive_speed_limit')
        with self._lock:
            if snapshot is not self._snapshot:
                return None
        return snapshot, result


def evaluate_command(linear: float, angular: float, state: GateInputs) -> GateResult:
    def stop(reason, discard=False):
        return GateResult(0., 0., reason, discard)

    if state.estop:
        return stop('estop', True)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (linear, angular)):
        return stop('invalid_command', True)
    if not state.profile_valid or state.observation_failure:
        return stop(state.observation_failure or 'invalid_geometry', True)
    if not state.localization_ready:
        return stop('localization_unavailable', True)
    if state.pickup:
        return stop('pickup')
    if state.obstacle_hold:
        return stop(state.obstacle_hold)
    age_valid = (isinstance(state.command_age, (int, float)) and
                 not isinstance(state.command_age, bool) and math.isfinite(state.command_age) and
                 state.command_age >= 0.)
    if not age_valid or (state.command_age > .5 and not (state.tilt and state.legacy_tilt_recovery)):
        return stop('command_stale')
    if state.rotation_trial and (linear != 0. or abs(angular) > .06):
        return stop('rotation_trial_domain')
    if state.translation_trial and (angular != 0. or abs(linear) > .014):
        return stop('translation_trial_domain')

    v, w = linear, angular
    # Only the legacy comparison runtime may synthesize this recovery candidate.
    # CORE recovery must submit its own candidate through the command arbiter.
    if state.tilt and state.legacy_tilt_recovery and not state.rear_blocked and v >= 0.:
        v = -.003
    elif state.tilt and state.rear_blocked:
        v = 0.
    if (state.obstacle or state.cliff or state.tilt) and v > 0.:
        v = 0.
    if v < 0. and state.rear_blocked:
        v = 0.
    if not state.can_rotate and not state.bounded_motion:
        w = 0.
    if linear != 0. and angular != 0. and (v != linear or w != angular):
        return stop('trajectory_changed')
    return GateResult(v, w, 'allow' if (v, w) == (linear, angular) else 'motion_limited')
