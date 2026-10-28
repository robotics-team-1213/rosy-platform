"""Multi-arm Cell Jobs (D-779 stages 2-4): creation, placement, the Job summary and the stop hooks.

A multi-arm submission names its arms (``arms: [{role, instance_id, workcell_id}]``, the last being
the arm owner's own workcell) and gives every step a
``placement``: the primary arm (one role, or every role of a coordinated step), the ``alternates``
that may run the step instead (D-779 §4), its ``zone``, its ``coupling``, its ``depends_on`` and the
compiled ``pallet.transfer`` inputs of each primary and alternate arm (``actions``, each already in
that arm's base frame). The placement lives in ``fleet_cell_step_placements``; ``step_json`` keeps
the single-arm shape (the primary arm's inputs) plus the optional per-arm ``goal_predicates``
(each arm's item_at_pose predicate in its own frame), and a row in ``fleet_cell_arm_jobs`` marks the Job
so the stage-1 mirror leaves it alone. Single-arm Jobs never reach this module except through the
stop hooks, which select them exactly as before.

The Job claims, from admission until it ends, its cell's workcell and every arm owner's workcell
(safety review 2026-10-17): a single-arm Job on an arm owner, or another Job naming the same arm
owner, is refused at admission instead of driving one owner from two Jobs.

Job status is a summary (D-779 §1): RUNNING while any arm runs, HOLD when no arm is READY, else
READY; ``current_step_index`` is the smallest step not yet GOAL_CONFIRMED.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core_common.protocol.schemas import CellTransferPayload

from .cell_arm_ledger import depends_on as _depends_on
from .cell_arm_claims import resource_keys
from .mission_store import _json, _nonempty, _now
from .step_action_kinds import step_action_kind

ARM_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")  # the D-779 §7 grant arm_role
_INSTANCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
COUPLINGS = ("independent", "loose", "tight")  # D-780 §5
MAX_ARMS = 4
CANCELLED_REASON = "CANCELLED_BY_OPERATOR"  # cell_job_store.CANCELLED_REASON (a test pins them equal)
TIGHT_PARTNER_REASON = "TIGHT_PARTNER_HELD"  # an arm held because its tight partner failed (D-779 §6)
PAIR_PARTIAL_REASON = "PAIR_PARTIALLY_SUCCEEDED"  # a coordinated step one arm finished: never rerun alone
_HASHES = ("recipe_digest", "cell_digest", "process_artifact_digest")
_SUBMISSION = {"job_id", "workcell_id", "arms", "recipe_digest", "cell_digest", "process_artifact_digest",
               "job", "steps", "resources", "ledger_markers"}
_PLACEMENT = {"arm", "alternates", "zone", "coupling", "depends_on", "actions"}


def marked(connection: sqlite3.Connection) -> bool:
    """The multi-arm marker table exists (a ledger opened only by an older Fleet has none)."""
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_cell_arm_jobs'"
                              ).fetchone() is not None


def is_multi_arm(connection: sqlite3.Connection, mission_id: str) -> bool:
    return marked(connection) and connection.execute(
        "SELECT 1 FROM fleet_cell_arm_jobs WHERE mission_id=?", (mission_id,)).fetchone() is not None


def single_arm_jobs(connection: sqlite3.Connection, *statuses: str) -> list[sqlite3.Row]:
    """``fleet_cell_jobs`` rows in ``statuses`` that are not multi-arm (the single-arm stop path)."""
    marks = ", ".join("?" for _ in statuses)
    exclude = " AND mission_id NOT IN (SELECT mission_id FROM fleet_cell_arm_jobs)" if marked(connection) else ""
    return connection.execute(f"SELECT * FROM fleet_cell_jobs WHERE provenance_kind='legacy' "
                              f"AND status IN ({marks}){exclude}", statuses
                              ).fetchall()


def _sha256(name: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _arms(value: object) -> list[tuple[str, str, str]]:
    if not isinstance(value, list) or not 2 <= len(value) <= MAX_ARMS:
        raise ValueError(f"a multi-arm Cell Job names 2 to {MAX_ARMS} arms")
    arms = []
    for arm in value:
        if not isinstance(arm, Mapping) or set(arm) != {"role", "instance_id", "workcell_id"}:
            raise ValueError("each arm is {role, instance_id, workcell_id}")
        role, instance, owner = arm["role"], arm["instance_id"], arm["workcell_id"]
        if not isinstance(role, str) or not ARM_ROLE.fullmatch(role):
            raise ValueError("arm role must be a lowercase identifier")
        if any(not isinstance(value, str) or not _INSTANCE.fullmatch(value) for value in (instance, owner)):
            raise ValueError("arm instance_id and owner workcell_id must be trimmed identifiers")
        arms.append((role, instance, owner))
    for position in range(3):
        if len({arm[position] for arm in arms}) != len(arms):
            raise ValueError("arm roles, arm instances and arm owner workcells must be distinct")
    return arms


def _payload(submission: Mapping[str, Any], index: int, inputs: object) -> None:
    """Each arm's inputs must compile to a valid CELL_TRANSFER body now, not at dispatch."""
    job = {"job_id": submission["job_id"], "recipe_digest": submission["recipe_digest"],
           "cell_digest": submission["cell_digest"]}
    try:
        if not isinstance(inputs, Mapping):
            raise TypeError("inputs must be an object")
        CellTransferPayload.model_validate(step_action_kind("CELL_TRANSFER").body(job, index, inputs))
    except (KeyError, TypeError, ValidationError) as exc:
        raise ValueError(f"step {index} has an invalid per-arm transfer payload") from exc


def _placement(submission: Mapping[str, Any], roles: set[str], index: int,
               step: object) -> tuple[dict[str, Any], dict[str, Any]]:
    if (not isinstance(step, Mapping)
            or set(step) - {"goal_predicate", "goal_predicates"} != {"skill_id", "version", "placement"}):
        raise ValueError("multi-arm Cell Job step has an invalid execution shape")
    if step["skill_id"] != "pallet.transfer" or step["version"] != "1.0.0":
        raise ValueError("Cell Job steps must use pallet.transfer/1.0.0")
    placement = step["placement"]
    if not isinstance(placement, Mapping) or set(placement) != _PLACEMENT:
        raise ValueError("step placement must be {arm, alternates, zone, coupling, depends_on, actions}")
    primary = [placement["arm"]] if isinstance(placement["arm"], str) else placement["arm"]
    alternates = placement["alternates"]
    if (not isinstance(primary, list) or not primary or not isinstance(alternates, list)
            or any(not isinstance(role, str) or role not in roles for role in [*primary, *alternates])
            or len(set(primary)) != len(primary) or len(set(alternates)) != len(alternates)
            or set(primary) & set(alternates)):
        raise ValueError(f"step {index} names an unknown, repeated or overlapping arm")
    coupling = placement["coupling"]
    if coupling not in COUPLINGS:
        raise ValueError(f"step {index} coupling must be one of {COUPLINGS}")
    if len(primary) > 2:
        raise ValueError("a coordinated step pairs exactly two arms (D-778 §4 pair grants)")
    if len(primary) > 1 and alternates:
        raise ValueError("a coordinated step has no alternate arm (D-779 §4)")
    if coupling == "tight" and len(primary) < 2:
        raise ValueError("tight coupling belongs to a coordinated step of two or more arms")
    zone = _nonempty("zone", placement["zone"], limit=64)
    workcell = submission["workcell_id"]
    resource_keys([("zone", f"{workcell}.{zone}"), *(("arm", f"{workcell}.{role}") for role in roles)])
    if not isinstance(placement["depends_on"], list):
        raise ValueError("a multi-arm step declares depends_on explicitly")
    dependencies = list(_depends_on({"depends_on": placement["depends_on"]}, index))
    actions = placement["actions"]
    if not isinstance(actions, Mapping) or set(actions) != set(primary) | set(alternates):
        raise ValueError(f"step {index} needs compiled inputs for exactly its primary and alternate arms")
    for role in sorted(actions):
        _payload(submission, index, actions[role])
    predicates = step.get("goal_predicates")
    if predicates is not None and (
            not isinstance(predicates, Mapping) or set(predicates) != set(actions)
            or any(not isinstance(value, Mapping) or value.get("frame") != "robot_base"
                   for value in predicates.values())):
        raise ValueError(f"step {index} needs one robot_base goal predicate per primary and alternate arm")
    step_json = {"skill_id": step["skill_id"], "version": step["version"], "inputs": dict(actions[primary[0]]),
                 **({"goal_predicate": step["goal_predicate"]} if "goal_predicate" in step else {}),
                 **({"goal_predicates": {role: dict(predicates[role]) for role in sorted(predicates)}}
                    if predicates is not None else {})}
    return step_json, {"arms": primary, "alternates": alternates, "zone_id": zone, "coupling": coupling,
                       "depends_on": dependencies, "payloads": {role: dict(actions[role]) for role in actions},
                       "assigned": primary}


def create(connection: sqlite3.Connection, *, mission_id: str, proposal_principal_id: str, request_key: str,
           request_digest: str, submission: Mapping[str, Any]) -> None:
    """Insert a PROPOSED multi-arm Job in the caller's transaction (identity already checked there)."""
    if set(submission) != _SUBMISSION:
        raise ValueError("multi-arm Cell Job submission has an invalid shape (no operator checkpoints yet)")
    for field in _HASHES:
        _sha256(field, submission[field])
    workcell = _nonempty("workcell_id", submission["workcell_id"], limit=96)
    arms = _arms(submission["arms"])
    resources, steps = submission["resources"], submission["steps"]
    if not isinstance(steps, list) or not steps or not isinstance(resources, list) or not resources:
        raise ValueError("Cell Job requires ordered steps and resource claims")
    keys = resource_keys(tuple(item) for item in resources)
    if any(key.split(":", 1)[0] in {"arm", "zone"} for key in keys):
        raise ValueError("arm and zone claims are taken per Action, not by the Job (D-779 §5)")
    if any(f"workcell:{name}" not in keys for name in (workcell, *(owner for _, _, owner in arms))):
        raise ValueError("a multi-arm Cell Job claims its workcell and every arm owner's workcell")
    roles = {role for role, _, _ in arms}
    compiled = [_placement(submission, roles, index, step) for index, step in enumerate(steps)]
    now = _now()
    connection.execute(
        """INSERT INTO fleet_cell_jobs
           (mission_id, proposal_principal_id, request_key, request_digest, job_id,
            workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest,
            job_json, resources_json, ledger_markers_json, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
        (mission_id, proposal_principal_id, request_key, request_digest, _nonempty("job_id", submission["job_id"]),
         workcell, arms[0][1], submission["recipe_digest"], submission["cell_digest"],
         submission["process_artifact_digest"], _json(submission["job"]), _json(resources),
         _json(submission["ledger_markers"]), now, now))
    connection.execute("INSERT INTO fleet_cell_arm_jobs (mission_id, arms_json, created_at) VALUES (?, ?, ?)",
                       (mission_id, _json([{"role": role, "instance_id": inst, "workcell_id": owner}
                                           for role, inst, owner in arms]), now))
    for role, instance, _ in arms:
        connection.execute(
            "INSERT INTO fleet_cell_job_arms (mission_id, arm_role, instance_id, status, updated_at) "
            "VALUES (?, ?, ?, 'READY', ?)", (mission_id, role, instance, now))
    for index, (step_json, placement) in enumerate(compiled):
        connection.execute(
            "INSERT INTO fleet_cell_steps (mission_id, step_index, step_id, action_kind, step_json, status, "
            "updated_at) VALUES (?, ?, ?, 'CELL_TRANSFER', ?, 'WAITING', ?)",
            (mission_id, index, f"{mission_id}:step-{index + 1}", _json(step_json), now))
        connection.execute(
            "INSERT INTO fleet_cell_step_placements (mission_id, step_index, arms_json, alternates_json, zone_id, "
            "coupling, depends_on_json, payloads_json, assigned_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mission_id, index, _json(placement["arms"]), _json(placement["alternates"]), placement["zone_id"],
             placement["coupling"], _json(placement["depends_on"]), _json(placement["payloads"]),
             _json(placement["assigned"])))
        for role in placement["assigned"]:
            insert_action(connection, mission_id, index, role, now)


def insert_action(connection: sqlite3.Connection, mission_id: str, step_index: int, role: str, now: str) -> None:
    connection.execute(
        "INSERT INTO fleet_cell_step_actions (mission_id, step_index, arm_role, action_kind, status, updated_at) "
        "VALUES (?, ?, ?, 'CELL_TRANSFER', 'WAITING', ?)", (mission_id, step_index, role, now))


def placements(connection: sqlite3.Connection, mission_id: str) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM fleet_cell_step_placements WHERE mission_id=? ORDER BY step_index",
                              (mission_id,)).fetchall()
    return [{"step_index": row["step_index"], "arms": json.loads(row["arms_json"]),
             "alternates": json.loads(row["alternates_json"]), "zone_id": row["zone_id"],
             "coupling": row["coupling"], "depends_on": json.loads(row["depends_on_json"]),
             "payloads": json.loads(row["payloads_json"]), "assigned": json.loads(row["assigned_json"])}
            for row in rows]


def actions(connection: sqlite3.Connection, mission_id: str) -> list[dict[str, Any]]:
    result = []
    for row in connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? "
                                  "ORDER BY step_index, arm_role", (mission_id,)):
        action = dict(row)
        for source, target in (("grant_json", "grant"), ("result_json", "result"), ("claims_json", "claims")):
            raw = action.pop(source)
            action[target] = json.loads(raw) if raw is not None else None
        result.append(action)
    return result


def arm_owners(connection: sqlite3.Connection, mission_id: str) -> dict[str, str]:
    """Each arm's owner workcell as created: the grant's workcell and a Job-level claim."""
    row = connection.execute("SELECT arms_json FROM fleet_cell_arm_jobs WHERE mission_id=?", (mission_id,)).fetchone()
    return {arm["role"]: arm["workcell_id"] for arm in json.loads(row[0])}


def attach(connection: sqlite3.Connection, job: dict[str, Any]) -> None:
    """Add the per-arm view to a multi-arm Job read; a single-arm Job read is left unchanged."""
    if not is_multi_arm(connection, job["mission_id"]):
        return
    owners = arm_owners(connection, job["mission_id"])
    job["arms"] = [{**dict(row), "owner_workcell": owners[row["arm_role"]]} for row in connection.execute(
        "SELECT * FROM fleet_cell_job_arms WHERE mission_id=? ORDER BY arm_role", (job["mission_id"],))]
    job["placements"] = placements(connection, job["mission_id"])
    job["step_actions"] = actions(connection, job["mission_id"])


def refresh_steps(connection: sqlite3.Connection, mission_id: str, now: str) -> None:
    """Step status follows its Actions (D-779 §3) and its depends_on (§2); GOAL_CONFIRMED is final."""
    steps = {row["step_index"]: row for row in connection.execute(
        "SELECT step_index, status, reason FROM fleet_cell_steps WHERE mission_id=?", (mission_id,))}
    confirmed = {index for index, row in steps.items() if row["status"] == "GOAL_CONFIRMED"}
    rows = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=?", (mission_id,)).fetchall()
    by_step: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_step.setdefault(row["step_index"], []).append(row)
    for placement in placements(connection, mission_id):
        index = placement["step_index"]
        if index in confirmed:
            continue
        ready = set(placement["depends_on"]) <= confirmed
        mine = by_step.get(index, [])
        statuses = {row["status"] for row in mine}
        held = [row for row in mine if row["status"] == "HOLD"]
        if held:
            status, reason = "HOLD", held[0]["reason"]
        elif "RUNNING" in statuses:
            status, reason = "RUNNING", None
        elif mine and statuses == {"ACTION_SUCCEEDED"}:
            status, reason = "ACTION_SUCCEEDED", None
        elif len(placement["assigned"]) > 1 and "ACTION_SUCCEEDED" in statuses:
            status, reason = "HOLD", PAIR_PARTIAL_REASON  # shown to the operator; only cancel ends it
        else:
            status, reason = ("READY" if ready else "WAITING"), None
        if (steps[index]["status"], steps[index]["reason"]) != (status, reason):
            connection.execute("UPDATE fleet_cell_steps SET status=?, reason=?, updated_at=? "
                               "WHERE mission_id=? AND step_index=?", (status, reason, now, mission_id, index))
        connection.execute(
            "UPDATE fleet_cell_step_actions SET status=?, updated_at=? WHERE mission_id=? AND step_index=? "
            "AND status IN ('WAITING', 'READY') AND status != ?",
            ("READY" if ready else "WAITING", now, mission_id, index, "READY" if ready else "WAITING"))


def summarize(connection: sqlite3.Connection, mission_id: str, now: str, *, reason: str | None = None) -> str:
    """Recompute the Job summary (D-779 §1); a PROPOSED, finished or cancelled Job keeps its row."""
    refresh_steps(connection, mission_id, now)
    job = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
    if job["status"] in {"PROPOSED", "GOAL_CONFIRMED"} or job["reason"] == CANCELLED_REASON:
        return job["status"]
    arms = connection.execute("SELECT status, reason FROM fleet_cell_job_arms WHERE mission_id=? ORDER BY arm_role",
                              (mission_id,)).fetchall()
    statuses = {arm["status"] for arm in arms}
    if "RUNNING" in statuses:
        status, why = "RUNNING", None
    elif "READY" in statuses:
        status, why = "READY", None
    else:
        status = "HOLD"
        why = reason or (job["reason"] if job["status"] == "HOLD" and job["reason"] else None) or next(
            (arm["reason"] for arm in arms if arm["reason"]), "NO_RUNNABLE_ARM")
    current = connection.execute(
        "SELECT COALESCE(MIN(step_index), (SELECT COUNT(*) FROM fleet_cell_steps WHERE mission_id=?)) "
        "FROM fleet_cell_steps WHERE mission_id=? AND status != 'GOAL_CONFIRMED'", (mission_id, mission_id)
    ).fetchone()[0]
    if (job["status"], job["reason"], job["current_step_index"]) != (status, why, current):
        connection.execute("UPDATE fleet_cell_jobs SET status=?, reason=?, current_step_index=?, updated_at=? "
                           "WHERE mission_id=?", (status, why, current, now, mission_id))
    return status


def event(connection: sqlite3.Connection, mission_id: str, step_index: int | None, event_type: str,
          actor_id: str, detail: Mapping[str, Any]) -> None:
    from .cell_job_store import CellJobStore  # the one Cell event writer (idempotent event keys)
    CellJobStore._event(connection, mission_id, step_index, event_type, actor_id, detail)


def hold_arms(connection: sqlite3.Connection, mission_id: str, roles: list[str], reason: str, now: str,
              *, statuses: tuple[str, ...] = ("READY",)) -> list[str]:
    held = []
    for role in roles:
        held += [role] * connection.execute(
            f"UPDATE fleet_cell_job_arms SET status='HOLD', reason=?, updated_at=? WHERE mission_id=? "
            f"AND arm_role=? AND status IN ({', '.join('?' for _ in statuses)})",
            (reason, now, mission_id, role, *statuses)).rowcount
    return held


def site_stop(connection: sqlite3.Connection, *, now: str, hold_reason: str | None) -> None:
    """Inside the stop latch, before it parks CLAIMED claims HELD (D-779 §5).

    Every READY arm of a running multi-arm Job goes to HOLD; a RUNNING arm keeps its DISPATCHING
    arm and zone claims and is settled by its own device outcome. None leaves the status to
    ``recover``, as for single-arm Jobs.
    """
    if hold_reason is None or not marked(connection):
        return
    generation = connection.execute("SELECT generation FROM fleet_dispatch_control WHERE control_id=1"
                                    ).fetchone()[0]
    for job in connection.execute(
            "SELECT j.mission_id FROM fleet_cell_jobs j JOIN fleet_cell_arm_jobs m ON m.mission_id=j.mission_id "
            "WHERE j.status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')").fetchall():
        roles = [row[0] for row in connection.execute(
            "SELECT arm_role FROM fleet_cell_job_arms WHERE mission_id=? AND status='READY' ORDER BY arm_role",
            (job["mission_id"],))]
        held = hold_arms(connection, job["mission_id"], roles, hold_reason, now)
        if held:
            event(connection, job["mission_id"], None, "CELL_JOB_HELD", "site-stop", {
                "event_id": f"site-stop:{generation}", "reason": hold_reason, "claim_phase": "HELD",
                "arm_roles": held})
        summarize(connection, job["mission_id"], now, reason=hold_reason)


def recover(connection: sqlite3.Connection, now: str, control: Mapping[str, Any]) -> int:
    """Startup: a multi-arm Job admitted under an older fence goes to HOLD (D-403 1c N1 per arm).

    An Action in flight across the restart has an unknown outcome: its DISPATCHING keys become
    UNKNOWN (readback path) and its arm, every other arm and the Job go to HOLD.
    """
    if not marked(connection):
        return 0
    rows = connection.execute(
        "SELECT j.* FROM fleet_cell_jobs j JOIN fleet_cell_arm_jobs m ON m.mission_id=j.mission_id "
        "WHERE j.status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED') "
        "AND (j.authority_epoch != ? OR j.dispatch_generation != ?)",
        (control["authority_epoch"], control["generation"])).fetchall()
    reason = "SITE_AUTHORITY_CHANGED"
    for job in rows:
        mission_id = job["mission_id"]
        connection.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_kind='mission' "
                           "AND owner_id=? AND phase='DISPATCHING'", (mission_id,))
        connection.execute("UPDATE fleet_cell_step_actions SET status='HOLD', reason=?, updated_at=? "
                           "WHERE mission_id=? AND status='RUNNING'", (reason, now, mission_id))
        roles = [row[0] for row in connection.execute(
            "SELECT arm_role FROM fleet_cell_job_arms WHERE mission_id=? ORDER BY arm_role", (mission_id,))]
        held = hold_arms(connection, mission_id, roles, reason, now, statuses=("READY", "RUNNING"))
        event(connection, mission_id, job["current_step_index"], "CELL_JOB_STARTUP_HOLD", "system", {
            "reason": reason, "previous_authority_epoch": job["authority_epoch"],
            "previous_dispatch_generation": job["dispatch_generation"],
            "authority_epoch": control["authority_epoch"], "dispatch_generation": control["generation"],
            "arm_roles": held})
        summarize(connection, mission_id, now, reason=reason)
    return len(rows)


__all__ = ["ARM_ROLE", "CANCELLED_REASON", "COUPLINGS", "PAIR_PARTIAL_REASON", "TIGHT_PARTNER_REASON", "actions",
           "arm_owners", "attach", "create", "event", "hold_arms", "insert_action", "is_multi_arm", "marked",
           "placements", "recover", "refresh_steps", "single_arm_jobs", "site_stop", "summarize"]
