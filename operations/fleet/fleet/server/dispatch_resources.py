"""Pure resource-key validation shared by policies and the claim transaction owner."""
from __future__ import annotations

from collections.abc import Iterable
import re

_RESOURCE_KINDS = {"robot", "workcell", "object", "pallet", "station", "arm", "zone"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def normalize_resources(resources: Iterable[tuple[str, str]]) -> list[tuple[str, str, str]]:
    normalized = set()
    for kind, identifier in resources:
        if kind not in _RESOURCE_KINDS or not isinstance(identifier, str):
            raise ValueError("invalid dispatch resource")
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError("invalid dispatch resource identifier")
        normalized.add((kind, identifier, f"{kind}:{identifier}"))
    if not normalized:
        raise ValueError("at least one dispatch resource is required")
    return sorted(normalized)
