"""Explicit v2 consumer of an admitted isolated raw CLI transport, never activation."""
from dataclasses import asdict
import asyncio
import math

from . import canonical
from .cli import CliProvider, _argv, _decode_result
from .judgment import Judgment, judgment, judgment_schema
from .profiles import AdapterCapabilities, BoundProfile, ModelProfile, bind_profile


class VersionedCliProvider:
    def __init__(self, *, profile, adapter, launch, cli_version='2.0.22'):
        if type(profile) is not ModelProfile or type(adapter) is not AdapterCapabilities:
            raise ValueError('EXPLICIT_MODEL_PROFILE_REQUIRED')
        self.transport = CliProvider(kind=profile.provider_kind, model=profile.model_id,
                                     profile_id=profile.profile_id, launch=launch, cli_version=cli_version)
        self.profile, self.adapter = profile, adapter
        self.profile_id = profile.profile_id

    async def __call__(self, problem, bound, prior, remaining, *, budget_usd, missing_allowlist=()):
        if type(bound) is not BoundProfile or bound.profile != self.profile:
            raise ValueError('CASE_OR_PROFILE_CHANGED')
        bound.validate(problem, self.profile)
        admitted = bind_profile(problem, self.profile, self.adapter, required_modalities=('text',))
        launch = self.transport.launch
        if (admitted != bound or getattr(launch, 'adapter_capabilities', None) != self.adapter
                or type(getattr(launch, 'schema_versions', None)) is not tuple
                or 2 not in launch.schema_versions or getattr(launch, 'cost_verified', None) is not True):
            raise ValueError('VERSIONED_TRANSPORT_NOT_ADMITTED')
        if (type(remaining) not in (int, float) or not math.isfinite(remaining)
                or not 0 < remaining <= self.profile.timeout_s
                or type(budget_usd) not in (int, float) or not math.isfinite(budget_usd)
                or not 0 <= budget_usd <= self.profile.max_cost_usd
                or type(prior) not in (tuple, list) or len(prior) > 2):
            raise ValueError('INVALID_VERSIONED_CALL_BUDGET')
        checked_prior = []
        for pair in prior:
            if (type(pair) not in (tuple, list) or len(pair) != 2
                    or type(pair[0]) is not BoundProfile or type(pair[1]) is not Judgment):
                raise ValueError('INVALID_VERSIONED_PRIOR')
            previous, checked = pair
            previous.validate(problem)
            verified = judgment(problem, previous, checked.payload, missing_allowlist=missing_allowlist)
            checked_prior.append({'profile_id': previous.profile.profile_id, **verified.payload})
        if len({item['profile_id'] for item in checked_prior}) != len(checked_prior):
            raise ValueError('INVALID_VERSIONED_PRIOR')
        schema = judgment_schema(problem, bound, missing_allowlist=missing_allowlist)
        body = canonical({'problem': {**asdict(problem), 'input_hash': problem.digest},
                          'profile_revision': self.profile.profile_revision, 'schema': schema,
                          'prior': checked_prior, 'instruction': 'Return only schema version 2 advisory JSON. '
                          'Never use tools or claim verified physical success or calibration.'}).encode()
        argv = _argv(self.transport.kind, self.transport.model, self.transport.cli_version, schema, budget_usd)
        async with asyncio.timeout(remaining):
            code, raw = await launch(argv, body, remaining, self.profile.max_output_bytes, budget_usd)
        payload, cost = _decode_result(self.transport.kind, launch, code, raw, self.profile.max_output_bytes, budget_usd)
        return judgment(problem, bound, payload, missing_allowlist=missing_allowlist), cost
