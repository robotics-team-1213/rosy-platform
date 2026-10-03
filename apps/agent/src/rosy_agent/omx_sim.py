"""Declarative OMX simulation profile selection and injected app composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Mapping

import yaml


PROVIDER_ID = "omx.cell-transfer.sim.v1"
_SCHEMA = "rosy.installation-profile.v1"
_WHEELS = frozenset({
    "rosy-contracts-skill", "rosy-world", "rosy-skill-api", "rosy-skill-manipulation", "rosy-execution",
    "rosy-palletizing", "rosy-integration-robot-omx", "rosy-app-agent",
})
_ROS_PACKAGES = frozenset({"omx_adapter"})
_FIELDS = frozenset({
    "schema", "profile_id", "provider_id", "wheels", "ros_packages",
    "hardware_dispatch_enabled",
})


@dataclass(frozen=True)
class OmxSimProfile:
    profile_id: str
    provider_id: str
    wheels: tuple[str, ...]
    ros_packages: tuple[str, ...]
    hardware_dispatch_enabled: bool


def load_profile(path: Path | str) -> OmxSimProfile:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or set(document) != _FIELDS:
        raise ValueError("OMX simulation profile has missing or unsupported fields")
    if document["schema"] != _SCHEMA:
        raise ValueError("OMX simulation profile schema is unsupported")
    if document["provider_id"] != PROVIDER_ID:
        raise ValueError("OMX simulation provider is not allowlisted")
    wheels = document["wheels"]
    ros_packages = document["ros_packages"]
    if (not isinstance(wheels, list) or any(not isinstance(item, str) for item in wheels)
            or set(wheels) != _WHEELS
            or len(wheels) != len(_WHEELS)):
        raise ValueError("OMX simulation wheel set is not the minimal allowlisted set")
    if (not isinstance(ros_packages, list)
            or any(not isinstance(item, str) for item in ros_packages)
            or set(ros_packages) != _ROS_PACKAGES
            or len(ros_packages) != len(_ROS_PACKAGES)):
        raise ValueError("OMX simulation ROS package set is not allowlisted")
    profile_id = document["profile_id"]
    if not isinstance(profile_id, str) or profile_id != "omx-cell-sim":
        raise ValueError("OMX simulation profile_id is unsupported")
    if document["hardware_dispatch_enabled"] is not False:
        raise ValueError("hardware dispatch must stay disabled in the OMX simulation profile")
    return OmxSimProfile(
        profile_id=profile_id, provider_id=PROVIDER_ID,
        wheels=tuple(wheels), ros_packages=tuple(ros_packages),
        hardware_dispatch_enabled=False,
    )


def compose(profile: OmxSimProfile,
            provider_factories: Mapping[str, Callable[[OmxSimProfile], object]]) -> object:
    """Select one registered provider; profile text never becomes an import path."""
    if not isinstance(profile, OmxSimProfile):
        raise ValueError("a validated OMX simulation profile is required")
    factory = provider_factories.get(profile.provider_id)
    if not callable(factory):
        raise ValueError("OMX simulation provider is unavailable")
    return factory(profile)
