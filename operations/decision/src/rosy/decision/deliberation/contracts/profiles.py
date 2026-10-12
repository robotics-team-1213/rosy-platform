"""Trusted, immutable model capability profiles; binding grants no execution authority."""
from dataclasses import dataclass
import math

from .. import identifier


def capabilities(value, allowed):
    if (type(value) not in (list, tuple) or not value or len(value) > len(allowed)
            or any(type(item) is not str or item not in allowed for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('INVALID_PROFILE_CAPABILITIES')
    return tuple(value)


@dataclass(frozen=True)
class AdapterCapabilities:
    provider_kind: str
    model_id: str
    model_revision: str
    adapter: str
    schema_version: int
    domains: tuple[str, ...]
    modalities: tuple[str, ...]
    ready: bool
    isolated: bool
    cost_verified: bool

    def __post_init__(self):
        for value in (self.provider_kind, self.model_id, self.model_revision, self.adapter):
            identifier(value)
        if self.provider_kind not in {'local', 'http', 'claude', 'opencode'} or type(self.schema_version) is not int:
            raise ValueError('INVALID_ADAPTER_IDENTITY')
        for field, allowed in (('domains', {'line_follow', 'door', 'arm_target', 'fleet_status'}), ('modalities', {'text', 'image'})):
            object.__setattr__(self, field, capabilities(getattr(self, field), allowed))
        if any(type(getattr(self, field)) is not bool for field in ('ready', 'isolated', 'cost_verified')):
            raise ValueError('INVALID_ADAPTER_ADMISSION')


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    profile_revision: str
    role: str
    provider_kind: str
    model_id: str
    model_revision: str
    adapter: str
    domains: tuple[str, ...]
    modalities: tuple[str, ...]
    timeout_s: float
    max_output_bytes: int
    max_calls: int
    max_cost_usd: float
    calibration_revision: str | None = None
    schema_version: int = 2

    def __post_init__(self):
        for value in (self.profile_id, self.profile_revision):
            identifier(value)
        if self.calibration_revision is not None:
            identifier(self.calibration_revision)
        descriptor = AdapterCapabilities(self.provider_kind, self.model_id, self.model_revision, self.adapter,
                                         self.schema_version, self.domains, self.modalities, True, True, True)
        object.__setattr__(self, 'domains', descriptor.domains)
        object.__setattr__(self, 'modalities', descriptor.modalities)
        if (self.role not in {'primary', 'reviewer', 'evaluator'} or self.schema_version != 2
                or type(self.timeout_s) not in (int, float) or not math.isfinite(self.timeout_s)
                or not 0 < self.timeout_s <= 30 or type(self.max_output_bytes) is not int
                or not 1 <= self.max_output_bytes <= 16384 or type(self.max_calls) is not int
                or not 1 <= self.max_calls <= 8 or type(self.max_cost_usd) not in (int, float)
                or not math.isfinite(self.max_cost_usd) or not 0 <= self.max_cost_usd <= 10):
            raise ValueError('INVALID_MODEL_PROFILE')


@dataclass(frozen=True)
class BoundProfile:
    profile: ModelProfile
    input_hash: str

    def validate(self, problem, current_profile=None):
        if (self.input_hash != problem.digest or problem.domain not in self.profile.domains
                or (current_profile is not None and current_profile != self.profile)):
            raise ValueError('CASE_OR_PROFILE_CHANGED')


def incident_profiles(value):
    if (type(value) is not tuple or len(value) not in (1, 2)
            or any(type(p) is not ModelProfile for p in value)
            or tuple(p.role for p in value) != ('primary', 'reviewer')[:len(value)]
            or len({p.profile_id for p in value}) != len(value)):
        raise ValueError('INVALID_INCIDENT_PROFILE_MANIFEST')
    return value


def bind_profile(problem, profile, adapter, *, required_modalities):
    needed = capabilities(required_modalities, {'text', 'image'})
    if (type(profile) is not ModelProfile or type(adapter) is not AdapterCapabilities
            or not all((adapter.ready, adapter.isolated, adapter.cost_verified))
            or any(getattr(profile, field) != getattr(adapter, field) for field in
                   ('provider_kind', 'model_id', 'model_revision', 'adapter', 'schema_version'))
            or problem.domain not in profile.domains or problem.domain not in adapter.domains
            or not set(needed) <= set(profile.modalities) & set(adapter.modalities)):
        raise ValueError('MODEL_PROFILE_NOT_ADMITTED')
    return BoundProfile(profile, problem.digest)
