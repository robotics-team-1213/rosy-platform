"""Version two consumer of a trusted local transport with explicit model provenance."""
import asyncio
import json
import math

from ..contracts.judgment import judgment
from ..contracts.profiles import AdapterCapabilities, BoundProfile, ModelProfile, bind_profile
from ..contracts.billing import RejectedJudgment
from .versioned_request import prepare_request


class VersionedLocalProvider:
    def __init__(self, *, profile, adapter, launch):
        if (type(profile) is not ModelProfile or type(adapter) is not AdapterCapabilities
                or profile.provider_kind != 'local' or adapter.provider_kind != 'local'
                or not callable(launch)):
            raise ValueError('EXPLICIT_LOCAL_PROFILE_REQUIRED')
        self.profile, self.adapter, self.launch = profile, adapter, launch
        self.profile_id = profile.profile_id

    async def __call__(self, problem, bound, prior, remaining, *, budget_usd, missing_allowlist=()):
        if type(bound) is not BoundProfile or bound.profile != self.profile:
            raise ValueError('CASE_OR_PROFILE_CHANGED')
        admitted = bind_profile(problem, self.profile, self.adapter, required_modalities=('text',))
        if (admitted != bound or getattr(self.launch, 'adapter_capabilities', None) != self.adapter
                or type(getattr(self.launch, 'schema_versions', None)) is not tuple
                or 2 not in self.launch.schema_versions or getattr(self.launch, 'cost_verified', None) is not True):
            raise ValueError('VERSIONED_LOCAL_TRANSPORT_NOT_ADMITTED')
        _, body = prepare_request(problem, bound, prior, remaining, budget_usd=budget_usd,
                                  missing_allowlist=missing_allowlist)
        async with asyncio.timeout(remaining):
            code, raw = await self.launch(body, remaining, self.profile.max_output_bytes)
        if code != 0 or type(raw) is not bytes or len(raw) > self.profile.max_output_bytes:
            raise ValueError('LOCAL_RESULT_UNKNOWN')
        result = json.loads(raw)
        if (type(result) is not dict or set(result) != {'model_id', 'model_revision', 'cost_usd', 'usage', 'judgment'}
                or result['model_id'] != self.profile.model_id or result['model_revision'] != self.profile.model_revision
                or type(result['cost_usd']) not in (int, float) or not math.isfinite(result['cost_usd'])
                or result['cost_usd'] != 0 or type(result['usage']) is not dict
                or set(result['usage']) != {'input_tokens', 'output_tokens'}
                or any(type(value) is not int or value < 0 for value in result['usage'].values())):
            raise ValueError('LOCAL_PROVENANCE_OR_COST_UNKNOWN')
        raw = result['judgment']
        try: checked = judgment(problem, bound, raw, missing_allowlist=missing_allowlist)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            unsafe = type(raw) is dict and type(raw.get('objections')) is list and 'unsafe' in raw['objections']
            raise RejectedJudgment(bound, 0.0, unsafe) from None
        return checked, 0.0
