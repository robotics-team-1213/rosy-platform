"""Per-arm Cell Job ledger tables (D-779 §1, §3, §8), stage 1: schema, backfill and a mirror.

Stage 1 changes no behaviour. ``fleet_cell_jobs`` and ``fleet_cell_steps`` stay the source of
truth and every existing write path is untouched. A single-arm Cell Job (one with CELL_TRANSFER
steps) gets one arm row (``SINGLE_ARM_ROLE``) and one Action row per step, and SQLite triggers
mirror the Job and step writes into them, so the per-arm tables are always readable and
consistent. TRIP Jobs (D-763) share ``fleet_cell_jobs`` but drive a robot, not an arm, so they get
no arm rows. A later stage makes the per-arm tables the source of truth and drops the triggers.

``ensure`` runs inside the caller's open migration transaction, after ``step_ledger_schema``:
rebuilding ``fleet_cell_steps`` drops its triggers, so they are dropped and recreated here every
start (a later definition always replaces an earlier one). Arm status is a mirror only: PROPOSED,
ACTION_SUCCEEDED and GOAL_CONFIRMED Jobs show READY, so no dispatcher may read it in stage 1.

Stages 2-4 add multi-arm Jobs (``cell_arm_jobs``): a row in ``fleet_cell_arm_jobs`` marks one, its
step placement lives in ``fleet_cell_step_placements``, and for such a Job the per-arm tables are
the source of truth, written by ``cell_arm_store``. Every mirror trigger and the backfill skip a
marked Job, so a single-arm Job is mirrored exactly as before.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

SINGLE_ARM_ROLE = "left"  # D-779 §8: the only arm of a pre-D-778 workcell
ARM_STATUSES = ("READY", "RUNNING", "HOLD", "OFFLINE")
ACTION_STATUSES = ("WAITING", "READY", "RUNNING", "ACTION_SUCCEEDED", "HOLD")

_TABLES = """
CREATE TABLE IF NOT EXISTS fleet_cell_job_arms (
    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
    arm_role TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY', 'RUNNING', 'HOLD', 'OFFLINE')),
    running_step_index INTEGER CHECK(running_step_index IS NULL OR running_step_index >= 0),
    reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(mission_id, arm_role)
);
CREATE TABLE IF NOT EXISTS fleet_cell_step_actions (
    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
    step_index INTEGER NOT NULL CHECK(step_index >= 0),
    arm_role TEXT NOT NULL,
    action_kind TEXT NOT NULL,
    action_id TEXT,  -- not UNIQUE in stage 1: the mirror must never abort a ledger write
    attempt_id TEXT,
    request_digest TEXT,
    grant_json TEXT,
    result_json TEXT,
    claims_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK(status IN ('WAITING', 'READY', 'RUNNING', 'ACTION_SUCCEEDED', 'HOLD')),
    reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(mission_id, step_index, arm_role)
);
CREATE INDEX IF NOT EXISTS fleet_cell_step_actions_status ON fleet_cell_step_actions(status, updated_at);
CREATE INDEX IF NOT EXISTS fleet_cell_step_actions_action ON fleet_cell_step_actions(action_id);
CREATE TABLE IF NOT EXISTS fleet_cell_arm_jobs (
    mission_id TEXT PRIMARY KEY REFERENCES fleet_cell_jobs(mission_id),
    arms_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fleet_cell_step_placements (
    mission_id TEXT NOT NULL REFERENCES fleet_cell_arm_jobs(mission_id),
    step_index INTEGER NOT NULL CHECK(step_index >= 0),
    arms_json TEXT NOT NULL,
    alternates_json TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    coupling TEXT NOT NULL CHECK(coupling IN ('independent', 'loose', 'tight')),
    depends_on_json TEXT NOT NULL,
    payloads_json TEXT NOT NULL,
    assigned_json TEXT NOT NULL,
    PRIMARY KEY(mission_id, step_index)
);
"""

# Job status -> arm status; step status -> Action status (GOAL_CONFIRMED is a step-level fact).
_ARM_STATUS = "CASE {s} WHEN 'RUNNING' THEN 'RUNNING' WHEN 'HOLD' THEN 'HOLD' ELSE 'READY' END"
_ACTION_STATUS = "CASE {s} WHEN 'GOAL_CONFIRMED' THEN 'ACTION_SUCCEEDED' ELSE {s} END"
_ROLE = f"'{SINGLE_ARM_ROLE}'"
# A multi-arm Job (D-779 stages 2-4) owns its per-arm rows; the single-arm mirror never touches it.
_SINGLE = "NOT EXISTS (SELECT 1 FROM fleet_cell_arm_jobs m WHERE m.mission_id = {m})"

_TRIGGERS = f"""
DROP TRIGGER IF EXISTS fleet_cell_arm_mirror_step_insert;
CREATE TRIGGER fleet_cell_arm_mirror_step_insert
AFTER INSERT ON fleet_cell_steps WHEN NEW.action_kind = 'CELL_TRANSFER' AND {_SINGLE.format(m="NEW.mission_id")}
BEGIN
    INSERT OR IGNORE INTO fleet_cell_job_arms
        (mission_id, arm_role, instance_id, status, running_step_index, reason, updated_at)
    SELECT j.mission_id, {_ROLE}, j.instance_id, {_ARM_STATUS.format(s="j.status")},
           CASE WHEN j.status = 'RUNNING' THEN j.current_step_index END, j.reason, j.updated_at
    FROM fleet_cell_jobs j WHERE j.mission_id = NEW.mission_id;
    INSERT OR IGNORE INTO fleet_cell_step_actions
        (mission_id, step_index, arm_role, action_kind, action_id, attempt_id, request_digest,
         grant_json, result_json, status, reason, updated_at)
    VALUES (NEW.mission_id, NEW.step_index, {_ROLE}, NEW.action_kind, NEW.action_id, NEW.attempt_id,
            NEW.request_digest, NEW.grant_json, NEW.result_json, {_ACTION_STATUS.format(s="NEW.status")},
            NEW.reason, NEW.updated_at);
END;
DROP TRIGGER IF EXISTS fleet_cell_arm_mirror_step_update;
CREATE TRIGGER fleet_cell_arm_mirror_step_update
AFTER UPDATE ON fleet_cell_steps WHEN NEW.action_kind = 'CELL_TRANSFER' AND {_SINGLE.format(m="NEW.mission_id")}
BEGIN
    UPDATE fleet_cell_step_actions SET action_id = NEW.action_id, attempt_id = NEW.attempt_id,
        request_digest = NEW.request_digest, grant_json = NEW.grant_json, result_json = NEW.result_json,
        status = {_ACTION_STATUS.format(s="NEW.status")}, reason = NEW.reason, updated_at = NEW.updated_at
    WHERE mission_id = NEW.mission_id AND step_index = NEW.step_index AND arm_role = {_ROLE};
END;
DROP TRIGGER IF EXISTS fleet_cell_arm_mirror_job_update;
CREATE TRIGGER fleet_cell_arm_mirror_job_update
AFTER UPDATE ON fleet_cell_jobs WHEN {_SINGLE.format(m="NEW.mission_id")}
BEGIN
    UPDATE fleet_cell_job_arms SET instance_id = NEW.instance_id,
        status = {_ARM_STATUS.format(s="NEW.status")},
        running_step_index = CASE WHEN NEW.status = 'RUNNING' THEN NEW.current_step_index END,
        reason = NEW.reason, updated_at = NEW.updated_at
    WHERE mission_id = NEW.mission_id AND arm_role = {_ROLE};
END;
"""

_BACKFILL_ARMS = f"""
INSERT OR IGNORE INTO fleet_cell_job_arms
    (mission_id, arm_role, instance_id, status, running_step_index, reason, updated_at)
SELECT j.mission_id, {_ROLE}, j.instance_id, {_ARM_STATUS.format(s="j.status")},
       CASE WHEN j.status = 'RUNNING' THEN j.current_step_index END, j.reason, j.updated_at
FROM fleet_cell_jobs j
WHERE EXISTS (SELECT 1 FROM fleet_cell_steps s WHERE s.mission_id = j.mission_id
              AND s.action_kind = 'CELL_TRANSFER') AND {_SINGLE.format(m="j.mission_id")}
"""

_BACKFILL_ACTIONS = f"""
INSERT OR IGNORE INTO fleet_cell_step_actions
    (mission_id, step_index, arm_role, action_kind, action_id, attempt_id, request_digest,
     grant_json, result_json, status, reason, updated_at)
SELECT mission_id, step_index, {_ROLE}, action_kind, action_id, attempt_id, request_digest,
       grant_json, result_json, {_ACTION_STATUS.format(s="status")}, reason, updated_at
FROM fleet_cell_steps s WHERE action_kind = 'CELL_TRANSFER' AND {_SINGLE.format(m="s.mission_id")}
"""


def ensure(connection: sqlite3.Connection) -> None:
    """Create the per-arm tables and mirror triggers, then backfill rows that are missing.

    Backfill is idempotent (INSERT OR IGNORE): a version-2 ledger gets its rows on the first start
    under version 3, and a later start adds nothing because the triggers kept every row current.
    """
    _run(connection, _TABLES)
    _run(connection, _TRIGGERS)
    connection.execute(_BACKFILL_ARMS)
    connection.execute(_BACKFILL_ACTIONS)


def _run(connection: sqlite3.Connection, script: str) -> None:
    """executescript would COMMIT the caller's transaction; run the statements one by one."""
    for statement in _statements(script):
        connection.execute(statement)


def _statements(script: str) -> list[str]:
    statements, current = [], ""
    for line in script.strip().splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            statements.append(current.strip())
            current = ""
    if current.strip():
        raise ValueError("unterminated SQL statement in the arm ledger schema")
    return statements


def depends_on(step_json: str | Mapping[str, Any], step_index: int) -> tuple[int, ...]:
    """The steps that must be GOAL_CONFIRMED first (D-779 §2).

    A step compiled before D-779 carries no ``depends_on`` and keeps the serial order: the
    previous step, or nothing for the first one. The stored step JSON is never rewritten, so
    Job hashes and grant payloads stay byte-identical (D-401 §3).
    """
    step = json.loads(step_json) if isinstance(step_json, str) else step_json
    declared = step.get("depends_on")
    if declared is None:
        return () if step_index == 0 else (step_index - 1,)
    if (not isinstance(declared, list)
            or any(type(item) is not int or not 0 <= item < step_index for item in declared)):
        raise ValueError("depends_on must list earlier step indexes")
    return tuple(sorted(set(declared)))


def arms(connection: sqlite3.Connection, mission_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM fleet_cell_job_arms WHERE mission_id=? ORDER BY arm_role", (mission_id,)).fetchall()
    return [dict(row) for row in rows]


def step_actions(connection: sqlite3.Connection, mission_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM fleet_cell_step_actions WHERE mission_id=? ORDER BY step_index, arm_role",
        (mission_id,)).fetchall()
    return [dict(row) for row in rows]


__all__ = ["ACTION_STATUSES", "ARM_STATUSES", "SINGLE_ARM_ROLE", "arms", "depends_on", "ensure",
           "step_actions"]
