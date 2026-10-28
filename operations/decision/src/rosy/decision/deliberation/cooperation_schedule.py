"""Pure, replayable mode selection; host admission still has to reserve capacity."""
from dataclasses import asdict, dataclass
import hashlib
import math

from . import canonical, identifier


def number(value, *, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError('INVALID_COOPERATION_NUMBER')
    return value


@dataclass(frozen=True)
class ExecutionEnvironment:
    revision: str
    expires_at: float
    sequential_ready: bool
    parallel_ready: bool
    workload_key: str

    def __post_init__(self):
        identifier(self.revision)
        identifier(self.workload_key)
        number(self.expires_at)
        if any(type(v) is not bool for v in (self.sequential_ready, self.parallel_ready)):
            raise ValueError('INVALID_CAPACITY_ADMISSION')


@dataclass(frozen=True)
class ExecutionMeasurements:
    revision: str
    profile_keys: tuple[str, str]
    expires_at: float
    sequential_s: float
    parallel_s: float | None
    cost_caps: tuple[float, float]
    min_gain_s: float
    parallel_accepted: bool
    workload_key: str

    def __post_init__(self):
        identifier(self.revision)
        identifier(self.workload_key)
        if (type(self.profile_keys) is not tuple or len(self.profile_keys) != 2
                or type(self.cost_caps) is not tuple or len(self.cost_caps) != 2):
            raise ValueError('EXPLICIT_PROFILE_PAIR_REQUIRED')
        for key in self.profile_keys:
            identifier(key)
        for value in (self.expires_at, self.sequential_s, self.min_gain_s, *self.cost_caps):
            number(value)
        if self.parallel_s is not None:
            number(self.parallel_s)
        if type(self.parallel_accepted) is not bool or self.sequential_s <= 0:
            raise ValueError('INVALID_EXECUTION_MEASUREMENT')


@dataclass(frozen=True)
class ModeDecision:
    requested_mode: str
    mode: str
    reason: str
    environment: ExecutionEnvironment
    measurements: ExecutionMeasurements
    profile_keys: tuple[str, str]
    input_hash: str
    now: float
    remaining_s: float
    remaining_usd: float

    @property
    def cost_caps(self):
        return self.measurements.cost_caps

    @property
    def decision_hash(self):
        return hashlib.sha256(canonical({'policy': 'conditional-cooperation-v1', **asdict(self)}).encode()).hexdigest()


def select_mode(*, requested_mode, environment, measurements, profile_keys, input_hash,
                now, remaining_s, remaining_usd):
    if (requested_mode not in ('auto', 'sequential', 'parallel')
            or type(environment) is not ExecutionEnvironment or type(measurements) is not ExecutionMeasurements
            or type(profile_keys) is not tuple or len(profile_keys) != 2):
        raise ValueError('INVALID_MODE_SELECTION')
    identifier(input_hash)
    for key in profile_keys:
        identifier(key)
    for value in (now, remaining_s, remaining_usd):
        number(value)
    mode, reason = 'hold', 'NO_FEASIBLE_MODE'
    valid = (environment.expires_at > now and measurements.expires_at > now
             and environment.workload_key == measurements.workload_key
             and profile_keys == measurements.profile_keys and remaining_s > 0
             and sum(measurements.cost_caps) <= remaining_usd)
    if valid:
        sequential = environment.sequential_ready and measurements.sequential_s < remaining_s
        parallel = (environment.parallel_ready and measurements.parallel_accepted
                    and measurements.parallel_s is not None and 0 < measurements.parallel_s < remaining_s)
        if requested_mode == 'sequential' and sequential:
            mode, reason = 'sequential', 'EXPLICIT_SEQUENTIAL'
        elif requested_mode == 'parallel' and parallel:
            mode, reason = 'parallel', 'EXPLICIT_PARALLEL'
        elif requested_mode == 'auto':
            gain = measurements.sequential_s - (measurements.parallel_s or measurements.sequential_s)
            if parallel and (not sequential or gain > 0 and gain >= measurements.min_gain_s):
                mode, reason = 'parallel', 'MEASURED_PARALLEL_BENEFIT'
            elif sequential:
                mode, reason = 'sequential', 'CONSERVATIVE_SEQUENTIAL'
    else:
        reason = 'STALE_PROFILE_OR_BUDGET'
    return ModeDecision(requested_mode, mode, reason, environment, measurements, profile_keys,
                        input_hash, now, remaining_s, remaining_usd)
