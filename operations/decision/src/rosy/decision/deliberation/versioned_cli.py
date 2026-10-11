"""Stable import path; implementation belongs to providers.versioned_cli."""
from .providers.versioned_cli import (
    asyncio as asyncio, CliProvider as CliProvider, _argv as _argv, _decode_result as _decode_result,
    judgment as judgment, AdapterCapabilities as AdapterCapabilities, BoundProfile as BoundProfile,
    ModelProfile as ModelProfile, bind_profile as bind_profile, prepare_request as prepare_request,
    VersionedCliProvider as VersionedCliProvider,
)
