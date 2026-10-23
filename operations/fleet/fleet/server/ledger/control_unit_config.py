"""Validated, immutable direct ownership for independent and nested Fleet units."""

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping


def _identifier(value, *, limit=64):
    if (not isinstance(value, str) or not 1 <= len(value) <= limit
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value)):
        raise ValueError("INVALID_CONTROL_UNIT_IDENTIFIER")
    return value


@dataclass(frozen=True)
class ControlUnit:
    unit_id: str
    parent: str | None
    resources: frozenset[str]


@dataclass(frozen=True)
class ControlUnitTopology:
    revision: str
    units: Mapping[str, ControlUnit]

    @classmethod
    def from_mapping(cls, document):
        if not isinstance(document, Mapping) or set(document) != {"revision", "units"}:
            raise ValueError("INVALID_CONTROL_UNIT_MANIFEST")
        revision = _identifier(document["revision"])
        entries = document["units"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError("INVALID_CONTROL_UNIT_COUNT")
        units, owned = {}, set()
        for entry in entries:
            if (not isinstance(entry, Mapping) or "id" not in entry
                    or set(entry) - {"id", "parent", "resources"}):
                raise ValueError("INVALID_CONTROL_UNIT")
            unit_id = _identifier(entry["id"])
            parent = entry.get("parent")
            if parent is not None:
                parent = _identifier(parent)
            resources = entry.get("resources", [])
            if not isinstance(resources, list) or len(resources) > 256:
                raise ValueError("INVALID_CONTROL_UNIT_RESOURCES")
            resources = [_identifier(resource, limit=128) for resource in resources]
            if (unit_id in units or len(set(resources)) != len(resources)
                    or owned.intersection(resources)):
                raise ValueError("DUPLICATE_CONTROL_UNIT_OWNERSHIP")
            units[unit_id] = ControlUnit(unit_id, parent, frozenset(resources))
            owned.update(resources)
        for unit in units.values():
            path, current = set(), unit
            while current is not None:
                if current.unit_id in path:
                    raise ValueError("CONTROL_UNIT_CYCLE")
                path.add(current.unit_id)
                if len(path) > 3:
                    raise ValueError("CONTROL_UNIT_DEPTH_EXCEEDED")
                if current.parent is not None and current.parent not in units:
                    raise ValueError("UNKNOWN_CONTROL_UNIT_PARENT")
                current = units.get(current.parent)
        return cls(revision, MappingProxyType(units))

    def unit(self, unit_id):
        try:
            return self.units[unit_id]
        except (KeyError, TypeError):
            raise ValueError("UNKNOWN_CONTROL_UNIT") from None

    def child(self, parent_id, child_id):
        parent, child = self.unit(parent_id), self.unit(child_id)
        if child.parent != parent.unit_id:
            raise ValueError("CONTROL_UNIT_NOT_DIRECT_CHILD")
        return child

    def next_hop(self, parent_id, target_id):
        self.unit(parent_id)
        current = self.unit(target_id)
        while current.parent is not None:
            if current.parent == parent_id:
                return current.unit_id
            current = self.unit(current.parent)
        raise ValueError("CONTROL_UNIT_OUTSIDE_SCOPE")
