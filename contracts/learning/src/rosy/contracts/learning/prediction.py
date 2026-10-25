"""D-782 action-conditioned prediction data and the M1 artifact evaluation rule.

A prediction can only support REJECT or HOLD; NO_OBJECTION is not a permission and ABSTAIN leaves the existing
gates unchanged. Stdlib only. No ROS, SDK, issuer, admission or execution authority.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from .digest import is_sha256_hex

ARTIFACT_SCHEMA = 'rosy.world-model-artifact.v1'
VERDICTS = ('NO_OBJECTION', 'HOLD', 'REJECT', 'ABSTAIN')
OBJECT_RESULTS = ('moved_as_intended', 'grasp_missed', 'dropped', 'displaced', 'untouched', 'unknown')
STATE_DIM = 6
MAX_HORIZON = 10


def _require(value, message):
    if not value:
        raise ValueError('prediction: ' + message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value) and value == value.strip()


def _hash(value):
    return is_sha256_hex(value)


def _ns(value):
    return type(value) is int and 0 <= value < 2**63


def _vector(values, size):
    values = tuple(values)
    _require(len(values) == size and all(_finite(v) for v in values), f'{size} finite values required')
    return tuple(float(v) for v in values)


def _matrix(rows, size):
    rows = tuple(rows)
    _require(1 <= len(rows) <= MAX_HORIZON, f'1..{MAX_HORIZON} steps required')
    return tuple(_vector(row, size) for row in rows)


def canonical_sha256(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class StateRef:
    """Where the current state came from. A reference to evidence, not the evidence."""
    sample_id: str
    observed_at_ns: int
    rig_revision: str
    calibration_revision: str

    def __post_init__(self):
        _require(all(_text(v) for v in (self.sample_id, self.rig_revision, self.calibration_revision)),
                 'explicit sample and revisions required')
        _require(_ns(self.observed_at_ns), 'integer observation nanoseconds required')


@dataclass(frozen=True)
class PredictionRequest:
    state_ref: StateRef
    state: tuple
    action: tuple
    step_s: float
    action_source: str

    def __post_init__(self):
        _require(isinstance(self.state_ref, StateRef), 'state reference required')
        object.__setattr__(self, 'state', _vector(self.state, STATE_DIM))
        object.__setattr__(self, 'action', _matrix(self.action, STATE_DIM))
        _require(_finite(self.step_s) and 0 < self.step_s <= 1, 'positive step seconds required')
        _require(_text(self.action_source), 'action source (teacher hash or policy revision) required')

    @property
    def horizon_steps(self):
        return len(self.action)

    def digest(self):
        ref = self.state_ref
        return canonical_sha256(dict(sample_id=ref.sample_id, observed_at_ns=ref.observed_at_ns,
                                     rig_revision=ref.rig_revision, calibration_revision=ref.calibration_revision,
                                     state=list(self.state), action=[list(a) for a in self.action],
                                     step_s=self.step_s, action_source=self.action_source))


@dataclass(frozen=True)
class PredictionResult:
    request_digest: str
    verdict: str
    reason: str
    predicted_states: tuple
    uncertainty: tuple
    object_result: object
    model_digest: str
    dataset_manifest_sha256: str
    produced_at_ns: int
    expires_at_ns: int

    def __post_init__(self):
        _require(_hash(self.request_digest) and _hash(self.model_digest) and _hash(self.dataset_manifest_sha256),
                 'request, model and dataset digests required')
        _require(self.verdict in VERDICTS and _text(self.reason), 'known verdict and reason required')
        _require(_ns(self.produced_at_ns) and _ns(self.expires_at_ns) and self.expires_at_ns > self.produced_at_ns,
                 'expiry after production required')
        if self.verdict == 'ABSTAIN':
            _require(self.predicted_states == () and self.uncertainty == () and self.object_result is None,
                     'abstention carries no prediction')
        else:
            object.__setattr__(self, 'predicted_states', _matrix(self.predicted_states, STATE_DIM))
            object.__setattr__(self, 'uncertainty', _matrix(self.uncertainty, STATE_DIM))
            _require(len(self.uncertainty) == len(self.predicted_states)
                     and all(v >= 0 for row in self.uncertainty for v in row), 'per-step nonnegative uncertainty')
        if self.object_result is not None:
            _require(isinstance(self.object_result, dict) and set(self.object_result) == set(OBJECT_RESULTS)
                     and all(_finite(p) and 0 <= p <= 1 for p in self.object_result.values())
                     and abs(sum(self.object_result.values()) - 1) <= 1e-6, 'object result distribution')

    @property
    def blocks(self):
        """True when this result supports stopping a candidate. Never a permission to run one."""
        return self.verdict in ('HOLD', 'REJECT')

    def is_current(self, now_ns):
        return self.produced_at_ns <= now_ns < self.expires_at_ns

    def to_json(self):
        return dict(request_digest=self.request_digest, verdict=self.verdict, reason=self.reason,
                    predicted_states=[list(r) for r in self.predicted_states],
                    uncertainty=[list(r) for r in self.uncertainty], object_result=self.object_result,
                    model_digest=self.model_digest, dataset_manifest_sha256=self.dataset_manifest_sha256,
                    produced_at_ns=self.produced_at_ns, expires_at_ns=self.expires_at_ns)


def artifact_digest(artifact):
    return canonical_sha256({k: v for k, v in artifact.items() if k != 'digest'})


def validate_artifact(artifact, expected_digest=None):
    """Shape, finiteness and digest of an M1 linear ensemble. Not an accuracy or acceptance claim."""
    _require(isinstance(artifact, dict) and artifact.get('schema') == ARTIFACT_SCHEMA
             and artifact.get('kind') == 'm1_linear_ensemble', 'M1 artifact schema required')
    horizon = artifact.get('horizon')
    _require(type(horizon) is int and 1 <= horizon <= MAX_HORIZON, 'artifact horizon differs')
    width_in, width_out = STATE_DIM * (1 + horizon), STATE_DIM * horizon
    for key in ('rig_revision', 'calibration_revision'):
        _require(_text(artifact.get(key)), 'artifact ' + key + ' required')
    _require(_hash(artifact.get('dataset_manifest_sha256')), 'dataset manifest digest required')
    _require(_finite(artifact.get('step_s')) and 0 < artifact['step_s'] <= 1, 'artifact step seconds')
    _vector(artifact.get('feature_mean', ()), width_in)
    std = _vector(artifact.get('feature_std', ()), width_in)
    _require(all(v > 0 for v in std), 'positive feature scale required')
    for low, high in (('state_min', 'state_max'), ('action_min', 'action_max')):
        lows, highs = _vector(artifact.get(low, ()), STATE_DIM), _vector(artifact.get(high, ()), STATE_DIM)
        _require(all(a <= b for a, b in zip(lows, highs)), 'training range minimum exceeds maximum')
    members = artifact.get('members')
    _require(isinstance(members, list) and len(members) >= 2, 'at least two ensemble members required')
    for member in members:
        _require(isinstance(member, dict) and set(member) == {'bias', 'weights'}, 'member fields differ')
        _vector(member['bias'], width_out)
        _require(isinstance(member['weights'], list) and len(member['weights']) == width_in, 'weight rows differ')
        for row in member['weights']:
            _vector(row, width_out)
    digest = artifact_digest(artifact)
    _require(artifact.get('digest') == digest, 'artifact digest differs')
    _require(expected_digest is None or expected_digest == digest, 'artifact is not the approved revision')
    return artifact


def forward(artifact, state, action):
    """Ensemble mean next states and member spread. The single evaluation rule for training, eval and shadow."""
    horizon = artifact['horizon']
    state, action = _vector(state, STATE_DIM), _matrix(action, STATE_DIM)
    _require(len(action) == horizon, 'action steps must equal the artifact horizon')
    raw = list(state) + [v for row in action for v in row]
    x = [(v - m) / s for v, m, s in zip(raw, artifact['feature_mean'], artifact['feature_std'])]
    outputs = []
    for member in artifact['members']:
        y = list(member['bias'])
        for xi, row in zip(x, member['weights']):
            if xi:
                for j, w in enumerate(row):
                    y[j] += xi * w
        outputs.append(y)
    count = len(outputs)
    mean = [sum(o[j] for o in outputs) / count for j in range(len(outputs[0]))]
    spread = [math.sqrt(sum((o[j] - mean[j])**2 for o in outputs) / count) for j in range(len(mean))]
    states = tuple(tuple(state[i] + mean[k*STATE_DIM + i] for i in range(STATE_DIM)) for k in range(horizon))
    sigma = tuple(tuple(spread[k*STATE_DIM + i] for i in range(STATE_DIM)) for k in range(horizon))
    return states, sigma
