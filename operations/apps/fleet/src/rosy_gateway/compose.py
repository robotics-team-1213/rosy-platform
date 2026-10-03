"""Bind the site-cell installation profile to the existing Fleet gateway."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


_SCHEMA = "rosy.installation-profile.v1"
_FIELDS = frozenset({"schema", "profile_id", "provider_id", "wheels", "hardware_dispatch_enabled"})
_PROVIDER_ID = "fleet.site-cell.v1"


@dataclass(frozen=True)
class SiteCellProfile:
    profile_id: str
    provider_id: str
    wheels: tuple[str, ...]
    hardware_dispatch_enabled: bool


def load_site_profile(path: Path | str) -> SiteCellProfile:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or set(document) != _FIELDS:
        raise ValueError("site-cell profile has missing or unsupported fields")
    if document["schema"] != _SCHEMA or document["profile_id"] != "site-cell":
        raise ValueError("site-cell profile identity is unsupported")
    if document["provider_id"] != _PROVIDER_ID:
        raise ValueError("site-cell provider is not allowlisted")
    wheels = document["wheels"]
    if wheels != ["rosy-app-gateway"]:
        raise ValueError("site-cell profile must select only the gateway wheel")
    if document["hardware_dispatch_enabled"] is not False:
        raise ValueError("site-cell profile cannot enable physical dispatch")
    return SiteCellProfile("site-cell", _PROVIDER_ID, tuple(wheels), False)


def compose_site(profile: SiteCellProfile,
                 fleet_factory: Callable[[SiteCellProfile], object]) -> object:
    if not isinstance(profile, SiteCellProfile) or not callable(fleet_factory):
        raise ValueError("validated site profile and existing Fleet factory are required")
    return fleet_factory(profile)


def main(argv=None):
    """Keep the existing Fleet CLI as the gateway's command and service owner."""
    from fleet.cli import _main_impl

    return _main_impl(argv)
