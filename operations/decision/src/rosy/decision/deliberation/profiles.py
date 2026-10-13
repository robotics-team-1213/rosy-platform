"""Stable import path; implementation belongs to contracts.profiles."""
from .contracts.profiles import (
    dataclass as dataclass, math as math, identifier as identifier, capabilities as capabilities,
    AdapterCapabilities as AdapterCapabilities, ModelProfile as ModelProfile, BoundProfile as BoundProfile,
    bind_profile as bind_profile, incident_profiles as incident_profiles,
)
