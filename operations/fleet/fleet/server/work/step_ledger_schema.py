"""The step ledger's ``fleet_cell_steps`` table: its ``action_kind`` CHECK is the registry's kinds (D-763 7).

사용자 결정 2026-10-15 "작게 풀고 진행": the CHECK that held only ``CELL_TRANSFER`` takes exactly the kinds
of ``step_action_kinds``; nothing else of D-420 §3 (S1-S12) changes here. A table created with another CHECK
is rebuilt in place in one savepoint (SQLite cannot alter a CHECK) and keeps every row.
"""

from __future__ import annotations

import re
import sqlite3

from .step_action_kinds import _KINDS


def kinds_check() -> str:
    return "CHECK(action_kind IN ({}))".format(", ".join(f"'{kind}'" for kind in sorted(_KINDS)))


def _table(name: str) -> str:
    return f"""CREATE TABLE {name} (
    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
    step_index INTEGER NOT NULL CHECK(step_index >= 0),
    step_id TEXT NOT NULL UNIQUE,
    action_kind TEXT NOT NULL {kinds_check()},
    step_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'WAITING', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
        'GOAL_CONFIRMED', 'HOLD'
    )),
    action_id TEXT,
    attempt_id TEXT,
    request_digest TEXT,
    grant_json TEXT,
    result_json TEXT,
    goal_evidence_json TEXT,
    reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(mission_id, step_index)
)"""


def ensure(connection: sqlite3.Connection) -> None:
    """Create the table, or rebuild one whose kind CHECK is not the registry's (rows kept, then its index)."""
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fleet_cell_steps'").fetchone()
    if row is None:
        connection.execute(_table("fleet_cell_steps"))
    elif kinds_check() not in row[0]:
        if not re.search(r"CHECK\(action_kind[ =]", row[0]):
            raise RuntimeError("fleet_cell_steps has no action_kind CHECK to migrate")
        connection.execute("SAVEPOINT step_ledger_kinds")  # all or nothing: a crash leaves the old table
        connection.execute(_table("fleet_cell_steps_migrating"))
        connection.execute("INSERT INTO fleet_cell_steps_migrating SELECT * FROM fleet_cell_steps")
        connection.execute("DROP TABLE fleet_cell_steps")
        connection.execute("ALTER TABLE fleet_cell_steps_migrating RENAME TO fleet_cell_steps")
        connection.execute("RELEASE step_ledger_kinds")
    connection.execute("CREATE INDEX IF NOT EXISTS fleet_cell_steps_status ON fleet_cell_steps(status, updated_at)")


__all__ = ["ensure", "kinds_check"]
