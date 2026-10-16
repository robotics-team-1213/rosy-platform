"""Per-Action arm and zone claim phases of a multi-arm Cell Job (D-779 §5, §6).

Every arm and zone claim is owned by the Job (owner ``mission``) at the Job's dispatch generation,
like its Job-level ``workcell`` and ``pallet`` claims; an Action lists the keys it holds in its
``claims_json``. This module is the only place that moves those keys between phases:

- reserve: all keys of one step (every arm of a coordinated step and the zone) are taken
  DISPATCHING in one savepoint through ``dispatch_admission.reserve``, or none is;
- a device-confirmed success releases the Action's keys (``action_claims.release_keys``), except a
  key another unfinished Action of the Job still lists (the zone of a coordinated step);
- a failure parks the keys HELD and an unknown outcome pins them UNKNOWN; neither is ever released
  here (D-403 1b): only an operator resume of the arm releases HELD keys, and an UNKNOWN key first
  needs a device readback;
- Job-level claims are never touched here.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence

from .action_claims import release_held_keys, release_keys
from .dispatch_admission import normalize_resources, reserve

_OWNER = "mission"
_UNFINISHED = ("RUNNING", "HOLD")


def action_resources(workcell_id: str, roles: Iterable[str], zone_id: str) -> list[tuple[str, str]]:
    """The arm claim of each role and the step's zone claim (``<workcell>.<role>``, ``<workcell>.<zone>``)."""
    return sorted({("arm", f"{workcell_id}.{role}") for role in roles} | {("zone", f"{workcell_id}.{zone_id}")})


def resource_keys(resources: Iterable[tuple[str, str]]) -> list[str]:
    return [key for _, _, key in normalize_resources(resources)]


def _resources(keys: Iterable[str]) -> list[tuple[str, str]]:
    return [tuple(key.split(":", 1)) for key in keys]


def reserve_step(connection: sqlite3.Connection, mission_id: str, generation: int,
                 resources: Sequence[tuple[str, str]]) -> bool:
    """All arm and zone keys of one step DISPATCHING, or none (a held key means: not now)."""
    return reserve(connection, owner_kind=_OWNER, owner_id=mission_id, generation=generation,
                   resources=resources, phase="DISPATCHING")


def phases(connection: sqlite3.Connection, mission_id: str, keys: Iterable[str]) -> set[str]:
    keys = list(keys)
    if not keys:
        return set()
    marks = ", ".join("?" for _ in keys)
    return {row[0] for row in connection.execute(
        f"SELECT phase FROM fleet_action_claims WHERE owner_kind=? AND owner_id=? AND resource_key IN ({marks})",
        (_OWNER, mission_id, *keys))}


def held_anywhere(connection: sqlite3.Connection, keys: Iterable[str]) -> set[str]:
    """Keys someone (any owner) holds now: a step whose arm or zone is taken is not ready."""
    keys = list(keys)
    if not keys:
        return set()
    marks = ", ".join("?" for _ in keys)
    return {row[0] for row in connection.execute(
        f"SELECT resource_key FROM fleet_action_claims WHERE resource_key IN ({marks})", keys)}


def set_phase(connection: sqlite3.Connection, mission_id: str, action_key: tuple[int, str],
              keys: Iterable[str], phase: str) -> int:
    """Park one Action's keys HELD or pin them UNKNOWN (a failure or unknown outcome; never a release).

    The Action's own keys take ``phase`` (a readback may settle its UNKNOWN as HELD). A key another
    unfinished Action shares (the zone of a coordinated step) keeps UNKNOWN while a sharer is still
    unresolved (RUNNING, or its own arm claim UNKNOWN or DISPATCHING): HELD never hides it.
    """
    if phase not in {"HELD", "UNKNOWN"}:
        raise ValueError("an arm or zone claim is parked HELD or pinned UNKNOWN, never released here")
    keys = list(keys)
    pending = _unresolved_sharers(connection, mission_id, action_key, keys) if phase == "HELD" else set()
    updated = 0
    for key in keys:
        guard = " AND phase != 'UNKNOWN'" if key in pending else ""
        updated += connection.execute(
            "UPDATE fleet_action_claims SET phase=?, lease_until=NULL WHERE owner_kind=? AND owner_id=? "
            "AND resource_key=? AND resource_kind IN ('arm', 'zone')" + guard,
            (phase, _OWNER, mission_id, key)).rowcount
    return updated


def arm_key(workcell_id: str, role: str) -> str:
    """The arm claim key: unique to the one Action an arm runs, so it marks that Action's outcome."""
    return f"arm:{workcell_id}.{role}"


def _sharers(connection: sqlite3.Connection, mission_id: str, action_key: tuple[int, str]) -> list[sqlite3.Row]:
    """The Job's other RUNNING or HOLD Actions, with the keys they list."""
    return [row for row in connection.execute(
        "SELECT step_index, arm_role, status, claims_json FROM fleet_cell_step_actions WHERE mission_id=? "
        "AND status IN (?, ?)", (mission_id, *_UNFINISHED)) if (row[0], row[1]) != tuple(action_key)]


def shared_with_unfinished(connection: sqlite3.Connection, mission_id: str, action_key: tuple[int, str],
                           keys: Iterable[str]) -> set[str]:
    """Keys another RUNNING or HOLD Action of the Job still lists (they stay with that Action)."""
    others = {key for row in _sharers(connection, mission_id, action_key) for key in json.loads(row[3])}
    return set(keys) & others


def _unresolved_sharers(connection: sqlite3.Connection, mission_id: str, action_key: tuple[int, str],
                        keys: Iterable[str]) -> set[str]:
    """Keys a sharer whose own outcome is still open lists (RUNNING, or its arm claim not settled)."""
    pending = set()
    for row in _sharers(connection, mission_id, action_key):
        listed = json.loads(row[3])
        own_arm = [key for key in listed if key.startswith("arm:")]
        if row[2] == "RUNNING" or phases(connection, mission_id, own_arm) & {"UNKNOWN", "DISPATCHING"}:
            pending.update(listed)
    return set(keys) & pending


def release_succeeded(connection: sqlite3.Connection, mission_id: str, generation: int,
                      action_key: tuple[int, str], keys: Iterable[str]) -> int:
    """A device-confirmed success frees the Action's own keys (D-779 §6 row 1).

    An UNKNOWN key whose readback is now this success is first confirmed CLAIMED, exactly as a
    single-arm UNKNOWN readback success returns the Job's claims to CLAIMED; then
    ``release_keys`` frees it at this generation. HELD keys are never released here.
    """
    own = sorted(set(keys) - shared_with_unfinished(connection, mission_id, action_key, keys))
    if not own:
        return 0
    for key in own:
        connection.execute(
            "UPDATE fleet_action_claims SET phase='CLAIMED' WHERE owner_kind=? AND owner_id=? AND resource_key=? "
            "AND generation=? AND phase='UNKNOWN' AND resource_kind IN ('arm', 'zone')",
            (_OWNER, mission_id, key, generation))
    return release_keys(connection, owner_kind=_OWNER, owner_id=mission_id, generation=generation,
                        resources=_resources(own))


def release_for_resume(connection: sqlite3.Connection, mission_id: str, generation: int,
                       action_key: tuple[int, str], keys: Iterable[str]) -> int:
    """Operator resume of one arm: free its HELD keys (D-779 §6), not a key another held Action lists."""
    own = sorted(set(keys) - shared_with_unfinished(connection, mission_id, action_key, keys))
    if not own:
        return 0
    return release_held_keys(connection, owner_kind=_OWNER, owner_id=mission_id, generation=generation,
                             resources=_resources(own))


def job_claims_runnable(connection: sqlite3.Connection, mission_id: str, generation: int,
                        job_resources: Iterable[Sequence[str]]) -> bool:
    """The Job still holds every Job-level claim CLAIMED at its generation (arm/zone keys aside)."""
    expected = {key for _, _, key in normalize_resources(tuple(item) for item in job_resources)}
    rows = connection.execute(
        "SELECT resource_key, phase FROM fleet_action_claims WHERE owner_kind=? AND owner_id=? AND generation=? "
        "AND resource_kind NOT IN ('arm', 'zone')", (_OWNER, mission_id, generation)).fetchall()
    return {row[0] for row in rows} == expected and all(row[1] == "CLAIMED" for row in rows)


def park_job_claims(connection: sqlite3.Connection, mission_id: str) -> int:
    """CLAIMED -> HELD for the whole Job (a pre-send fence hold); DISPATCHING and UNKNOWN stay."""
    return connection.execute(
        "UPDATE fleet_action_claims SET phase='HELD', lease_until=NULL WHERE owner_kind=? AND owner_id=? "
        "AND phase='CLAIMED'", (_OWNER, mission_id)).rowcount


__all__ = ["action_resources", "arm_key", "held_anywhere", "job_claims_runnable", "park_job_claims", "phases",
           "release_for_resume", "release_succeeded", "reserve_step", "resource_keys", "set_phase",
           "shared_with_unfinished"]
