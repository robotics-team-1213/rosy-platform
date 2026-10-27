"""Explicit v2 consumer of an admitted isolated raw CLI transport, never activation."""
import asyncio

from .cli import CliProvider, _argv, _decode_result
from ..contracts.judgment import judgment
from ..contracts.profiles import AdapterCapabilities, BoundProfile, ModelProfile, bind_profile
from .versioned_request import prepare_request
from .cost_evidence import project
from ..contracts.billing import CallResult, RejectedJudgment


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
        schema, body = prepare_request(problem, bound, prior, remaining, budget_usd=budget_usd,
                                       missing_allowlist=missing_allowlist)
        argv = _argv(self.transport.kind, self.transport.model, self.transport.cli_version, schema, budget_usd)
        async with asyncio.timeout(remaining):
            code, raw = await launch(argv, body, remaining, self.profile.max_output_bytes, budget_usd)
        payload, cost = _decode_result(self.transport.kind, launch, code, raw, self.profile.max_output_bytes, budget_usd, bound=bound)
        billing = getattr(launch, 'billing_receipt', None)
        try: checked = judgment(problem, bound, payload, missing_allowlist=missing_allowlist)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            if billing is not None: raise
            unsafe = type(payload) is dict and type(payload.get('objections')) is list and 'unsafe' in payload['objections']
            raise RejectedJudgment(bound, cost, unsafe) from None
        if billing is None: return checked, cost
        try: evidence = project(problem, bound, checked, cost, body, billing)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            return CallResult(checked, cost, evidence_error=True)
        return CallResult(checked, cost, evidence)
