"""Per-Action arm and zone claims (D-779 §5), beside the Job-level claims of dispatch_admission.

An arm or a zone of a workcell is held for one Action, not for the whole Job. Reserving uses
``dispatch_admission.reserve`` unchanged (same savepoint, same primary key, same exclusivity);
this module only adds the narrow release of one Action's arm and zone claims.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .dispatch_admission import normalize_resources

ACTION_SCOPED_KINDS = frozenset({"arm", "zone"})


def release_keys(connection: sqlite3.Connection, *, owner_kind: str, owner_id: str, generation: int,
                 resources: Iterable[tuple[str, str]]) -> int:
    """Release only the named arm and zone claims of one owner (one Action's claims).

    Only ``arm`` and ``zone`` kinds, only at ``generation`` and only in phase CLAIMED or
    DISPATCHING: a HELD or UNKNOWN claim stays until its device outcome is settled (D-403 1b),
    and a Job-level claim is never released here. Another owner's claim is never touched.
    """
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("generation must be a non-negative integer")
    normalized = normalize_resources(resources)
    if any(kind not in ACTION_SCOPED_KINDS for kind, _, _ in normalized):
        raise ValueError("only arm and zone claims are released per Action")
    released = 0
    for _, _, resource_key in normalized:
        released += connection.execute(
            "DELETE FROM fleet_action_claims WHERE owner_kind=? AND owner_id=? AND resource_key=? "
            "AND generation=? AND phase IN ('CLAIMED', 'DISPATCHING')",
            (owner_kind, owner_id, resource_key, generation),
        ).rowcount
    return released


__all__ = ["ACTION_SCOPED_KINDS", "release_keys"]
