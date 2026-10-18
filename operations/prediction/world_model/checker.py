"""D-782 pre-execution checker over an approved M1 artifact. ROS-free, stdlib only.

It answers one question about a candidate action chunk: is there a predicted reason to stop it? REJECT and HOLD
support stopping; NO_OBJECTION grants nothing; ABSTAIN leaves the existing Fleet admission and owner recheck
unchanged. No owner, lease, admission, ROS or device call happens here. Live use is W4 and is not wired.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
from rosy.contracts.learning.prediction import (STATE_DIM, PredictionRequest, PredictionResult, StateRef,
                                                forward, validate_artifact)

NORMALIZED_LOW = (-100.0,)*5 + (0.0,)
NORMALIZED_HIGH = (100.0,)*6


@dataclass(frozen=True)
class CheckerConfig:
    max_input_age_s: float = 0.5
    validity_s: float = 0.5
    hold_sigma: float = 5.0
    range_margin: float = 5.0
    limits_low: tuple = NORMALIZED_LOW
    limits_high: tuple = NORMALIZED_HIGH

    def __post_init__(self):
        for value in (self.max_input_age_s, self.validity_s, self.hold_sigma):
            if not (type(value) in (int, float) and 0 < value <= 60):
                raise ValueError('checker: positive bounded thresholds required')
        if not (type(self.range_margin) in (int, float) and 0 <= self.range_margin <= 100):
            raise ValueError('checker: bounded range margin required')
        if (len(self.limits_low) != STATE_DIM or len(self.limits_high) != STATE_DIM
                or any(lo >= hi or lo < nl or hi > nh for lo, hi, nl, nh
                       in zip(self.limits_low, self.limits_high, NORMALIZED_LOW, NORMALIZED_HIGH))):
            raise ValueError('checker: limits must narrow the normalized range')


def request_from_arm_state(arm_state, action, *, step_s, action_source):
    """Bind a World arm-state fact (rosy.world.state.projections.arm_state.ArmState) to a candidate action."""
    return PredictionRequest(state_ref=StateRef(sample_id=arm_state.sample_id,
                                                observed_at_ns=arm_state.observed_at_ns,
                                                rig_revision=arm_state.rig_revision,
                                                calibration_revision=arm_state.calibration_revision),
                             state=arm_state.joints, action=action, step_s=step_s, action_source=action_source)


class WorldModelChecker:
    def __init__(self, artifact_path, expected_digest, config=CheckerConfig()):
        if not expected_digest:
            raise ValueError('checker: an approved artifact digest is required')
        self.artifact = validate_artifact(json.loads(Path(artifact_path).read_text(encoding='utf-8')),
                                          expected_digest)
        self.config = config

    def _result(self, request, now_ns, verdict, reason, states=(), sigma=()):
        artifact = self.artifact
        return PredictionResult(request_digest=request.digest(), verdict=verdict, reason=reason,
                                predicted_states=states, uncertainty=sigma, object_result=None,
                                model_digest=artifact['digest'],
                                dataset_manifest_sha256=artifact['dataset_manifest_sha256'],
                                produced_at_ns=now_ns, expires_at_ns=now_ns + int(self.config.validity_s*1e9))

    def _outside_training(self, values, low_key, high_key):
        margin = self.config.range_margin
        return any(v < lo - margin or v > hi + margin
                   for v, lo, hi in zip(values, self.artifact[low_key], self.artifact[high_key]))

    def abstention(self, request, now_ns):
        """Why this checker must not speak about the request, or None."""
        artifact, ref = self.artifact, request.state_ref
        if (ref.rig_revision, ref.calibration_revision) != (artifact['rig_revision'],
                                                            artifact['calibration_revision']):
            return 'rig or calibration revision differs from the training data'
        age = (now_ns - ref.observed_at_ns) / 1e9
        if not 0 <= age <= self.config.max_input_age_s:
            return 'input state is stale or from the future'
        if request.horizon_steps != artifact['horizon']:
            return 'action steps differ from the artifact horizon'
        if abs(request.step_s - artifact['step_s']) > 1e-6:
            return 'action step period differs from the training data'
        if self._outside_training(request.state, 'state_min', 'state_max') or any(
                self._outside_training(a, 'action_min', 'action_max') for a in request.action):
            return 'state or action outside the training range'
        return None

    def check(self, request, now_ns):
        if not isinstance(request, PredictionRequest) or type(now_ns) is not int:
            raise ValueError('checker: PredictionRequest and integer nanoseconds required')
        reason = self.abstention(request, now_ns)
        if reason:
            return self._result(request, now_ns, 'ABSTAIN', reason)
        states, sigma = forward(self.artifact, request.state, request.action)
        low, high = self.config.limits_low, self.config.limits_high
        for k, row in enumerate(states):
            for j, value in enumerate(row):
                if not low[j] <= value <= high[j]:
                    return self._result(request, now_ns, 'REJECT',
                                        f'step {k+1} joint {j} predicted at {value:.2f} outside [{low[j]}, {high[j]}]',
                                        states, sigma)
        peak = max(v for row in sigma for v in row)
        if peak > self.config.hold_sigma:
            return self._result(request, now_ns, 'HOLD',
                                f'ensemble spread {peak:.2f} exceeds {self.config.hold_sigma}', states, sigma)
        return self._result(request, now_ns, 'NO_OBJECTION', 'no predicted limit violation; not a permission',
                            states, sigma)
