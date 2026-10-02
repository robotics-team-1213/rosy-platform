"""Typed, durable resource claims shared by task and future Mission dispatch."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable

_RESOURCE_KINDS = {"robot", "workcell", "object", "pallet"}
_OWNER_KINDS = {"task", "mission", "direct_action"}
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


def reserve(connection: sqlite3.Connection, *, owner_kind: str, owner_id: str,
            generation: int, resources: Iterable[tuple[str, str]], phase: str,
            lease_until: str | None = None) -> bool:
    if owner_kind not in _OWNER_KINDS or not isinstance(owner_id, str) \
            or not _IDENTIFIER.fullmatch(owner_id):
        raise ValueError("invalid dispatch claim owner")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("generation must be a non-negative integer")
    if phase not in {"CLAIMED", "DISPATCHING", "UNKNOWN", "HELD"}:
        raise ValueError("invalid dispatch claim phase")
    normalized = normalize_resources(resources)
    connection.execute("SAVEPOINT reserve_dispatch_resources")
    try:
        for kind, identifier, resource_key in normalized:
            connection.execute(
                """INSERT INTO fleet_action_claims
                   (resource_key, resource_kind, resource_id, owner_kind, owner_id,
                    generation, phase, lease_until, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (resource_key, kind, identifier, owner_kind, owner_id,
                 generation, phase, lease_until),
            )
    except sqlite3.IntegrityError:
        connection.execute("ROLLBACK TO reserve_dispatch_resources")
        connection.execute("RELEASE reserve_dispatch_resources")
        return False
    connection.execute("RELEASE reserve_dispatch_resources")
    return True


def release(connection: sqlite3.Connection, *, owner_kind: str, owner_id: str,
            generation: int | None = None) -> int:
    if generation is None:
        cursor = connection.execute(
            "DELETE FROM fleet_action_claims WHERE owner_kind=? AND owner_id=?",
            (owner_kind, owner_id),
        )
    else:
        cursor = connection.execute(
            """DELETE FROM fleet_action_claims
               WHERE owner_kind=? AND owner_id=? AND generation=?""",
            (owner_kind, owner_id, generation),
        )
    return cursor.rowcount
