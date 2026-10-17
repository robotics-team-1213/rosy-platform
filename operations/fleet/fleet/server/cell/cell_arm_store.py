"""Ledger operations of a multi-arm Cell Job (D-779 §2-§6), beside the single-arm ``CellJobStore``.

Same database, same connection policy, same event writer and the same receipt facts as
``CellJobStore`` (``note_device_receipt``, ``submitted_journal_id`` and ``has_device_receipt`` are
its own methods), so the fence, readback, NOT_FOUND and receipt rules are the single-arm ones. What
differs is the scope: an Action is one arm's share of a step, its arm and zone claims are taken
when it starts and freed when it succeeds, and a failure or unknown outcome holds that arm and its
claims only, or its tight partner too (§6). The Job row is a summary (``cell_arm_jobs.summarize``).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .cell_arm_claims import (action_resources, arm_key, held_anywhere, job_claims_runnable, park_job_claims,
                              phases, release_for_resume, release_succeeded, reserve_step, resource_keys,
                              set_phase)
from . import cell_arm_jobs as arm_jobs
from .cell_arm_jobs import CANCELLED_REASON, TIGHT_PARTNER_REASON, summarize
from .cell_job_store import CellJobStore
from .dispatch_admission import release as release_claims
from .dispatch_admission import reserve as reserve_claims
from .mission_store import MissionConflict, _json, _nonempty, _now
from .step_action_kinds import step_action_kind, step_grant_digest

# Device outcome -> (Action status, phase of the Action's arm and zone claims); None releases (§6).
OUTCOMES = {"SUCCEEDED": ("ACTION_SUCCEEDED", None), "FAILED": ("HOLD", "HELD"), "REJECTED": ("HOLD", "HELD"),
            "NOT_FOUND": ("HOLD", "HELD"), "UNKNOWN": ("HOLD", "UNKNOWN")}
_UNRESOLVED = {"DISPATCHING", "UNKNOWN"}


class ArmJobStore:
    """Multi-arm Job transitions; every method is one ``BEGIN IMMEDIATE`` transaction."""

    def __init__(self, cells: CellJobStore) -> None:
        self.cells, self.path = cells, cells.path

    # Reads and receipt facts shared with the single-arm ledger -----------------------------------
    def get(self, mission_id: str) -> dict[str, Any] | None:
        return self.cells.get(mission_id)

    def note_device_receipt(self, mission_id: str, step_index: int, action_id: str, attempt_id: str) -> None:
        self.cells.note_device_receipt(mission_id, step_index, action_id, attempt_id)

    def submitted_journal_id(self, mission_id: str, action_id: str) -> str | None:
        return self.cells.submitted_journal_id(mission_id, action_id)

    def has_device_receipt(self, mission_id: str, action_id: str, attempt_id: str) -> bool:
        return self.cells.has_device_receipt(mission_id, action_id, attempt_id)

    def _active_ids(self, connection: sqlite3.Connection, limit: str = "") -> list[str]:
        if not arm_jobs.marked(connection):
            return []
        return [row[0] for row in connection.execute(
            "SELECT j.mission_id FROM fleet_cell_jobs j JOIN fleet_cell_arm_jobs m ON m.mission_id=j.mission_id "
            "WHERE j.status IN ('READY', 'RUNNING', 'HOLD') AND j.dispatch_generation IS NOT NULL "
            "AND COALESCE(j.reason, '') != ? ORDER BY j.mission_id" + limit, (CANCELLED_REASON,))]

    def has_active(self) -> bool:
        """Any admitted, unfinished multi-arm Job: the gate of the multi-arm dispatch pass."""
        with closing(self.cells._connect()) as connection:
            return bool(self._active_ids(connection, " LIMIT 1"))

    def active_jobs(self) -> list[dict[str, Any]]:
        with closing(self.cells._connect()) as connection:
            return [CellJobStore._get(connection, mission_id) for mission_id in self._active_ids(connection)]

    def held_keys(self, keys: list[str]) -> set[str]:
        with closing(self.cells._connect()) as connection:
            return held_anywhere(connection, keys)

    def claim_phases(self, mission_id: str, keys: list[str]) -> set[str]:
        with closing(self.cells._connect()) as connection:
            return phases(connection, mission_id, keys)

    # Helpers -------------------------------------------------------------------------------------
    @contextmanager
    def _tx(self, mission_id: str) -> Iterator[tuple[sqlite3.Connection, sqlite3.Row]]:
        """One BEGIN IMMEDIATE transaction on a multi-arm Job; rolled back unless ``_finish`` commits."""
        with closing(self.cells._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                job = CellJobStore._require(connection, mission_id)
                if not arm_jobs.is_multi_arm(connection, mission_id):
                    raise MissionConflict("not a multi-arm Cell Job")
                yield connection, job
            finally:
                if connection.in_transaction:
                    connection.rollback()

    def _finish(self, connection: sqlite3.Connection, mission_id: str, **extra: Any) -> dict[str, Any]:
        result = CellJobStore._get(connection, mission_id)
        connection.commit()
        return {**result, **extra} if extra else result

    @staticmethod
    def _action(connection, mission_id, step_index, role) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND step_index=? "
                                  "AND arm_role=?", (mission_id, step_index, role)).fetchone()

    @staticmethod
    def _arm(connection, mission_id, role) -> sqlite3.Row:
        return connection.execute("SELECT * FROM fleet_cell_job_arms WHERE mission_id=? AND arm_role=?",
                                  (mission_id, role)).fetchone()

    @staticmethod
    def _placement(connection, mission_id, step_index) -> dict[str, Any]:
        return next(item for item in arm_jobs.placements(connection, mission_id) if item["step_index"] == step_index)

    @staticmethod
    def _set_action(connection, row, now, **fields) -> None:
        names = ", ".join(f"{name}=?" for name in fields)
        connection.execute(f"UPDATE fleet_cell_step_actions SET {names}, updated_at=? WHERE mission_id=? "
                           "AND step_index=? AND arm_role=?",
                           (*fields.values(), now, row["mission_id"], row["step_index"], row["arm_role"]))

    @staticmethod
    def _set_arm(connection, mission_id, role, now, status, reason, running=None) -> None:
        connection.execute("UPDATE fleet_cell_job_arms SET status=?, reason=?, running_step_index=?, updated_at=? "
                           "WHERE mission_id=? AND arm_role=?", (status, reason, running, now, mission_id, role))

    @staticmethod
    def _last_outcome(connection, mission_id, action_id) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT event_type, detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type LIKE "
            "'CELL_STEP_ACTION_%' AND json_extract(detail_json, '$.action_id')=? ORDER BY event_id DESC LIMIT 1",
            (mission_id, action_id)).fetchone()

    def _hold_before_send(self, connection, job, roles, reason, event_key, now) -> None:
        """Nothing was sent: hold the READY arms; Job claims released only without progress (1c item 2b)."""
        phase = CellJobStore._pre_send_claim_phase(connection, job)
        if phase is None:
            release_claims(connection, owner_kind="mission", owner_id=job["mission_id"],
                           generation=job["dispatch_generation"])
        else:
            park_job_claims(connection, job["mission_id"])
        held = arm_jobs.hold_arms(connection, job["mission_id"], roles, reason, now)
        arm_jobs.event(connection, job["mission_id"], None, "CELL_JOB_HELD", "fleet", {
            "event_id": f"{event_key}:{','.join(held)}@{CellJobStore._approvals(connection, job)}",
            "reason": reason, "claim_phase": phase, "arm_roles": held})
        summarize(connection, job["mission_id"], now, reason=reason)

    # Start ---------------------------------------------------------------------------------------
    def start_actions(self, mission_id: str, *, step_index: int, grants: Mapping[str, Mapping[str, Any]],
                      now: datetime | None = None,
                      owner_journal_ids: Mapping[str, str | None] | None = None) -> dict[str, Any]:
        """Start one step on ``grants``' arms: claims DISPATCHING, Actions and arms RUNNING, one transaction.

        A coordinated step's arm and zone claims are all taken or none (``state`` CLAIM_BUSY, nothing
        written). A primary arm in HOLD or OFFLINE hands a never-started single-arm step to the
        alternate named in ``grants`` (one-arm mode, D-779 §4), recorded as an event.
        """
        parsed = {}
        for role, grant in grants.items():
            model = FleetCellTransferGrant.model_validate(dict(grant))
            if step_grant_digest(model) != model.request_digest:
                raise ValueError("CELL_TRANSFER request digest does not match the complete grant")
            parsed[role] = model
        now_dt = now or datetime.now(timezone.utc)
        if not parsed or any(g.issued_at > now_dt or g.expires_at <= now_dt for g in parsed.values()):
            raise MissionConflict("CELL_TRANSFER grant is not current")
        stamp, roles = _now(), sorted(parsed)
        with self._tx(mission_id) as (connection, job):
            if job["status"] not in {"READY", "RUNNING"} or job["reason"] == CANCELLED_REASON:
                raise MissionConflict("only a runnable multi-arm Cell Job may start an Action")
            ready_arms = [row[0] for row in connection.execute(
                "SELECT arm_role FROM fleet_cell_job_arms WHERE mission_id=? AND status='READY'", (mission_id,))]
            for check, reason in ((CellJobStore._fence_current, "FLEET_FENCE_CHANGED_BEFORE_SUBMISSION"),
                                  (self._job_claims_ok, "FLEET_CLAIM_MISSING_BEFORE_SUBMISSION")):
                if not check(connection, job):
                    self._hold_before_send(connection, job, ready_arms, reason,
                                           f"hold-before-submit:{step_index}:{reason}", stamp)
                    return self._finish(connection, mission_id, state="HOLD")
            placement = self._placement(connection, mission_id, step_index)
            step = connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                      (mission_id, step_index)).fetchone()
            confirmed = {row[0] for row in connection.execute(
                "SELECT step_index FROM fleet_cell_steps WHERE mission_id=? AND status='GOAL_CONFIRMED'",
                (mission_id,))}
            if step["status"] == "GOAL_CONFIRMED" or not set(placement["depends_on"]) <= confirmed:
                raise MissionConflict("the step's dependencies are not GOAL_CONFIRMED")
            self._reassign(connection, job, placement, roles, stamp)
            rows = {role: self._action(connection, mission_id, step_index, role) for role in roles}
            others = connection.execute(
                "SELECT status FROM fleet_cell_step_actions WHERE mission_id=? AND step_index=?",
                (mission_id, step_index)).fetchall()
            if (any(row is None or row["status"] not in {"WAITING", "READY"} for row in rows.values())
                    or any(other[0] in {"RUNNING", "HOLD"} for other in others)
                    or any(self._arm(connection, mission_id, role)["status"] != "READY" for role in roles)):
                raise MissionConflict("only READY arms may start a step that has not started")
            kind, owners = step_action_kind(step["action_kind"]), arm_jobs.arm_owners(connection, mission_id)
            for role, grant in parsed.items():
                arm = self._arm(connection, mission_id, role)
                if (grant.mission_id != mission_id or grant.step_id != step["step_id"]
                        or grant.workcell_id != owners[role] or grant.instance_id != arm["instance_id"]
                        or grant.cell_transfer.job_id != job["job_id"] or grant.cell_transfer.step_index != step_index
                        or grant.cell_transfer.recipe_sha256 != job["recipe_digest"]
                        or grant.cell_transfer.cell_sha256 != job["cell_digest"]
                        or grant.authority_epoch != job["authority_epoch"]
                        or grant.dispatch_generation != job["dispatch_generation"]
                        or getattr(grant, "arm_role", None) not in {None, role}):
                    raise ValueError("CELL_TRANSFER grant does not match the persisted arm Action")
                expected = kind.body(job, step_index, placement["payloads"][role])
                if getattr(grant, kind.body_field).model_dump(mode="json") != expected:
                    raise ValueError("CELL_TRANSFER payload does not match the persisted per-arm step")
            if len({g.action_id for g in parsed.values()}) != len(parsed):
                raise ValueError("each arm Action needs its own action_id")
            resources = action_resources(job["workcell_id"], roles, placement["zone_id"])
            if not reserve_step(connection, mission_id, job["dispatch_generation"], resources):
                connection.rollback()
                return {"state": "CLAIM_BUSY", "mission_id": mission_id, "status": job["status"],
                        "reason": job["reason"]}
            zone = resource_keys([("zone", f"{job['workcell_id']}.{placement['zone_id']}")])
            for role, grant in parsed.items():
                keys = sorted({arm_key(job["workcell_id"], role), *zone})
                self._set_action(connection, rows[role], stamp, status="RUNNING", reason=None,
                                 action_id=grant.action_id, attempt_id=grant.attempt_id,
                                 request_digest=grant.request_digest,
                                 grant_json=_json(grant.model_dump(mode="json")), claims_json=_json(keys))
                self._set_arm(connection, mission_id, role, stamp, "RUNNING", None, step_index)
                arm_jobs.event(connection, mission_id, step_index, "CELL_STEP_SUBMITTING", "fleet", {
                    "action_id": grant.action_id, "attempt_id": grant.attempt_id, "arm_role": role,
                    "request_digest": grant.request_digest, "authority_epoch": grant.authority_epoch,
                    "dispatch_generation": grant.dispatch_generation, "claims": keys,
                    "owner_journal_id": (owner_journal_ids or {}).get(role)})
            summarize(connection, mission_id, stamp)
            return self._finish(connection, mission_id, state="RUNNING")

    @staticmethod
    def _job_claims_ok(connection, job) -> bool:
        return job_claims_runnable(connection, job["mission_id"], job["dispatch_generation"],
                                          json.loads(job["resources_json"]))

    def _reassign(self, connection, job, placement, roles, now) -> None:
        """One-arm mode (D-779 §4): an alternate takes a never-started step whose single arm is held."""
        assigned = placement["assigned"]
        if roles == sorted(assigned) or set(roles) <= set(assigned):
            return
        primary = assigned[0]
        row = self._action(connection, job["mission_id"], placement["step_index"], primary)
        arm = self._arm(connection, job["mission_id"], primary)
        if (len(assigned) != 1 or len(roles) != 1 or roles[0] not in placement["alternates"]
                or arm["status"] not in {"HOLD", "OFFLINE"} or row is None
                or row["status"] not in {"WAITING", "READY"} or row["action_id"] is not None):
            raise MissionConflict("an alternate arm may only take a never-started step of a held arm")
        connection.execute("DELETE FROM fleet_cell_step_actions WHERE mission_id=? AND step_index=? AND arm_role=?",
                           (job["mission_id"], placement["step_index"], primary))
        arm_jobs.insert_action(connection, job["mission_id"], placement["step_index"], roles[0], now)
        connection.execute("UPDATE fleet_cell_step_placements SET assigned_json=? WHERE mission_id=? AND step_index=?",
                           (_json(roles), job["mission_id"], placement["step_index"]))
        arm_jobs.event(connection, job["mission_id"], placement["step_index"], "CELL_STEP_ALTERNATE_ARM", "fleet", {
            "event_id": f"alternate:{placement['step_index']}:{primary}:{roles[0]}", "primary_arm": primary,
            "alternate_arm": roles[0], "primary_status": arm["status"], "primary_reason": arm["reason"]})

    def hold_unsent(self, mission_id: str, *, action_ids: list[str], reason: str) -> dict[str, Any]:
        """RUNNING -> HOLD with HELD claims for started Actions that were never sent (1d item 1)."""
        reason = _nonempty("reason", reason, limit=96)
        with self._tx(mission_id) as (connection, _):
            now = _now()
            for action_id in action_ids:
                row = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND action_id=?",
                                         (mission_id, action_id)).fetchone()
                seen = connection.execute(
                    "SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND (event_key=? OR (event_type LIKE "
                    "'CELL_STEP_ACTION_%' AND json_extract(detail_json, '$.action_id')=?)) LIMIT 1",
                    (mission_id, f"{mission_id}:device-receipt:{action_id}:{row['attempt_id'] if row else ''}",
                     action_id)).fetchone()
                if row is None or row["status"] != "RUNNING" or seen is not None:
                    raise MissionConflict("only a started, never answered arm Action can be held as unsent")
                self._set_action(connection, row, now, status="HOLD", reason=reason)
                set_phase(connection, mission_id, (row["step_index"], row["arm_role"]),
                                 json.loads(row["claims_json"]), "HELD")
                self._set_arm(connection, mission_id, row["arm_role"], now, "HOLD", reason, row["step_index"])
                arm_jobs.event(connection, mission_id, row["step_index"], "CELL_JOB_HELD", "fleet", {
                    "event_id": f"unsent:{action_id}", "reason": reason, "claim_phase": "HELD",
                    "action_id": action_id, "arm_roles": [row["arm_role"]]})
            summarize(connection, mission_id, now, reason=reason)
            return self._finish(connection, mission_id)

    def hold_before_send(self, mission_id: str, *, roles: list[str], reason: str, event_key: str) -> dict[str, Any]:
        """A grant could not be built for these arms: nothing was started or sent (1b B3)."""
        with self._tx(mission_id) as (connection, job):
            self._hold_before_send(connection, job, roles, _nonempty("reason", reason, limit=96), event_key, _now())
            return self._finish(connection, mission_id)

    # Device outcome ------------------------------------------------------------------------------
    def record_action_result(self, mission_id: str, *, step_index: int, event_id: str, action_id: str,
                             attempt_id: str, outcome: str, result: Mapping[str, Any],
                             reason: str | None = None) -> dict[str, Any]:
        """Record one arm Action's device outcome under ``event_id`` (D-779 §6); a replay is a no-op."""
        event_id = _nonempty("event_id", event_id)
        if outcome not in OUTCOMES:
            raise ValueError("unsupported Action outcome")
        if outcome == "SUCCEEDED" and reason is not None:
            raise ValueError("a successful Action result carries no hold reason")
        reason = None if outcome == "SUCCEEDED" else _nonempty("reason", reason, limit=96)
        with self._tx(mission_id) as (connection, job):
            row = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND step_index=? "
                                      "AND action_id=?", (mission_id, step_index, action_id)).fetchone()
            if row is None:
                raise MissionConflict("Action result does not match an arm Action of this step")
            role = row["arm_role"]
            detail = {"event_id": event_id, "action_id": action_id, "attempt_id": attempt_id, "arm_role": role,
                      "outcome": outcome, "reason": reason, "result": dict(result)}
            event_type = f"CELL_STEP_ACTION_{outcome}"
            if CellJobStore._replayed(connection, mission_id, step_index, event_type, "device", event_id, detail):
                return self._finish(connection, mission_id, **self._arm_view(row))
            arm_phase = phases(connection, mission_id, [arm_key(job["workcell_id"], role)])
            readback = row["status"] == "HOLD" and bool(arm_phase) and arm_phase <= _UNRESOLVED
            if ((row["status"] != "RUNNING" and not readback) or row["attempt_id"] != attempt_id
                    or (readback and outcome == "UNKNOWN")):
                raise MissionConflict("Action result does not match the current arm Action attempt")
            now, keys = _now(), json.loads(row["claims_json"])
            arm = self._arm(connection, mission_id, role)
            status, phase = OUTCOMES[outcome]
            if outcome == "SUCCEEDED":
                own = ((arm["status"] == "RUNNING" and arm["running_step_index"] == step_index)
                       or (arm["status"] == "HOLD" and arm["reason"] == row["reason"]
                           and arm["reason"] != TIGHT_PARTNER_REASON))
                if not (own and CellJobStore._fence_current(connection, job)):
                    # 1c item 2a per arm: the success is kept (resume returns ACTION_SUCCEEDED) but the
                    # arm, which a stop, an authority change or its tight partner held, stays parked.
                    status, phase = "HOLD", "HELD"
                    reason = arm["reason"] if arm["status"] == "HOLD" else "site_stop"
            self._set_action(connection, row, now, status=status, reason=reason, result_json=_json(dict(result)))
            if phase is None:
                release_succeeded(connection, mission_id, job["dispatch_generation"], (step_index, role), keys)
                self._set_arm(connection, mission_id, role, now, "READY", None)
            else:
                set_phase(connection, mission_id, (step_index, role), keys, phase)
                self._set_arm(connection, mission_id, role, now, "HOLD", reason, step_index)
                if outcome != "SUCCEEDED":
                    self._hold_tight_partners(connection, mission_id, step_index, role, now)
            arm_jobs.event(connection, mission_id, step_index, event_type, "device", detail)
            summarize(connection, mission_id, now, reason=reason)
            return self._finish(connection, mission_id,
                                **self._arm_view(self._action(connection, mission_id, step_index, role)))

    @staticmethod
    def _arm_view(row: sqlite3.Row) -> dict[str, Any]:
        """The dispatcher reports one arm Action: its status and reason stand for the Job's."""
        return {"status": row["status"], "reason": row["reason"], "arm_role": row["arm_role"]}

    def _hold_tight_partners(self, connection, mission_id, step_index, role, now) -> None:
        """A tight step's partner arms HOLD with it (D-779 §6); a partner still in flight is UNKNOWN."""
        placement = self._placement(connection, mission_id, step_index)
        if placement["coupling"] != "tight":
            return
        for other in placement["assigned"]:
            row = self._action(connection, mission_id, step_index, other)
            if other == role or row is None:
                continue
            if row["status"] == "RUNNING":
                self._set_action(connection, row, now, status="HOLD", reason=TIGHT_PARTNER_REASON)
                set_phase(connection, mission_id, (step_index, other), json.loads(row["claims_json"]),
                                 "UNKNOWN")
            elif row["status"] in {"WAITING", "READY"}:
                self._set_action(connection, row, now, status="HOLD", reason=TIGHT_PARTNER_REASON)
            arm_jobs.hold_arms(connection, mission_id, [other], TIGHT_PARTNER_REASON, now,
                               statuses=("READY", "RUNNING"))
            arm_jobs.event(connection, mission_id, step_index, "CELL_ARM_HELD", "fleet", {
                "event_id": f"tight-partner:{step_index}:{other}:{row['attempt_id'] or 'unsent'}",
                "arm_role": other, "partner_arm": role, "reason": TIGHT_PARTNER_REASON})

    # Goal ----------------------------------------------------------------------------------------
    def confirm_step_goal(self, mission_id: str, *, step_index: int, action_id: str, attempt_id: str,
                          evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Independent goal evidence for a step whose every arm Action succeeded (D-779 §3, D-403 §5)."""
        required = {"producer_id", "evidence_id", "evidence_source", "action_id", "attempt_id", "satisfied",
                    "gripper_state", "gripper_evidence_id"}
        if not isinstance(evidence, Mapping) or not required <= set(evidence):
            raise ValueError("Cell step goal confirmation requires independent producer and gripper evidence")
        if (evidence["evidence_source"] != "sim_model_pose" or evidence["action_id"] != action_id
                or evidence["attempt_id"] != attempt_id or evidence["gripper_state"] != "OPEN"
                or evidence["satisfied"] is not True):
            raise MissionConflict("Cell step goal evidence does not match a satisfied arm attempt")
        for field in ("producer_id", "evidence_id", "gripper_evidence_id"):
            _nonempty(field, evidence[field], limit=192)
        evidence_json = _json(dict(evidence))
        event_id = f"goal:{step_index}:{evidence['evidence_id']}"
        detail = {**json.loads(evidence_json), "event_id": event_id}
        with self._tx(mission_id) as (connection, job):
            count = connection.execute("SELECT COUNT(*) FROM fleet_cell_steps WHERE mission_id=?",
                                       (mission_id,)).fetchone()[0]
            confirmed = connection.execute("SELECT COUNT(*) FROM fleet_cell_steps WHERE mission_id=? AND "
                                           "status='GOAL_CONFIRMED'", (mission_id,)).fetchone()[0]
            final_type = "CELL_JOB_GOAL_CONFIRMED" if confirmed + 1 == count else "CELL_STEP_GOAL_CONFIRMED"
            prior = connection.execute("SELECT event_type FROM fleet_cell_events WHERE event_key=?",
                                       (f"{mission_id}:{event_id}",)).fetchone()
            if prior is not None and CellJobStore._replayed(  # an exact replay; other evidence raises
                    connection, mission_id, step_index, prior[0], "goal-evidence", event_id, detail):
                return self._finish(connection, mission_id)
            step = connection.execute("SELECT status FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                      (mission_id, step_index)).fetchone()
            row = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND step_index=? "
                                     "AND action_id=?", (mission_id, step_index, action_id)).fetchone()
            last = self._last_outcome(connection, mission_id, action_id)
            if (step is None or step["status"] != "ACTION_SUCCEEDED" or row is None or row["attempt_id"] != attempt_id
                    or last is None or last["event_type"] != "CELL_STEP_ACTION_SUCCEEDED"
                    or json.loads(last["detail_json"]).get("attempt_id") != attempt_id):
                raise MissionConflict("independent goal evidence requires every arm Action of the step to succeed")
            now = _now()
            connection.execute("UPDATE fleet_cell_steps SET status='GOAL_CONFIRMED', goal_evidence_json=?, "
                               "reason=NULL, updated_at=? WHERE mission_id=? AND step_index=?",
                               (evidence_json, now, mission_id, step_index))
            if final_type == "CELL_JOB_GOAL_CONFIRMED":
                connection.execute("UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED', current_step_index=?, "
                                   "reason=NULL, updated_at=? WHERE mission_id=?", (count, now, mission_id))
                release_claims(connection, owner_kind="mission", owner_id=mission_id,
                               generation=job["dispatch_generation"])
            elif not CellJobStore._fence_current(connection, job):
                # Next steps open only under the current fence (main 64b4b1faa); else park and wait.
                park_job_claims(connection, mission_id)
                ready = [r[0] for r in connection.execute("SELECT arm_role FROM fleet_cell_job_arms WHERE "
                                                          "mission_id=? AND status='READY'", (mission_id,))]
                arm_jobs.hold_arms(connection, mission_id, ready, "SITE_AUTHORITY_CHANGED", now)
            arm_jobs.event(connection, mission_id, step_index, final_type, "goal-evidence", detail)
            summarize(connection, mission_id, now)
            return self._finish(connection, mission_id)

    # Operator ------------------------------------------------------------------------------------
    def set_arm_offline(self, mission_id: str, *, arm_role: str, actor_id: str, reason: str) -> dict[str, Any]:
        """An operator or start check takes an idle arm out (D-779 §1 OFFLINE); its steps may go to alternates."""
        actor_id, reason = _nonempty("actor_id", actor_id, limit=96), _nonempty("reason", reason, limit=96)
        with self._tx(mission_id) as (connection, job):
            arm = self._arm(connection, mission_id, arm_role)
            if arm is None or arm["status"] not in {"READY", "HOLD"} or job["reason"] == CANCELLED_REASON:
                raise MissionConflict("only an idle arm of a live multi-arm Cell Job can be taken offline")
            now = _now()
            self._set_arm(connection, mission_id, arm_role, now, "OFFLINE", reason, arm["running_step_index"])
            arm_jobs.event(connection, mission_id, None, "CELL_ARM_OFFLINE", actor_id, {
                "arm_role": arm_role, "reason": reason, "previous_status": arm["status"]})
            summarize(connection, mission_id, now, reason=reason)
            return self._finish(connection, mission_id)

    def _resume_actions(self, connection, job, rows, now) -> None:
        """A held Action goes back to READY, or ACTION_SUCCEEDED when its device last reported success
        (the transfer is never sent again; goal evidence decides), as single-arm resume does."""
        for row in rows:
            last = self._last_outcome(connection, job["mission_id"], row["action_id"]) if row["action_id"] else None
            succeeded = (last is not None and last["event_type"] == "CELL_STEP_ACTION_SUCCEEDED"
                         and json.loads(last["detail_json"]).get("attempt_id") == row["attempt_id"])
            if succeeded:
                self._set_action(connection, row, now, status="ACTION_SUCCEEDED", reason=None)
            else:
                self._set_action(connection, row, now, status="READY", reason=None, action_id=None, attempt_id=None,
                                 request_digest=None, grant_json=None, claims_json="[]")

    def resume_arm(self, mission_id: str, *, arm_role: str, actor_id: str, expected_generation: int) -> dict[str, Any]:
        """Operator resume of one arm under the current fence (D-779 §6): its HELD claims are released.

        Refused while one of its claims is DISPATCHING or UNKNOWN (readback first), for a cancelled
        Job, and after a stop or authority change (the Job's claims are parked: resume the Job).
        """
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with self._tx(mission_id) as (connection, job):
            arm = self._arm(connection, mission_id, arm_role)
            if (arm is None or arm["status"] not in {"HOLD", "OFFLINE"} or job["reason"] == CANCELLED_REASON
                    or job["status"] in {"PROPOSED", "GOAL_CONFIRMED"}):
                raise MissionConflict("only a held arm of a live, uncancelled Cell Job can resume")
            control = connection.execute("SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            if (control is None or control[0] != expected_generation
                    or not CellJobStore._fence_current(connection, job) or not self._job_claims_ok(connection, job)):
                raise MissionConflict("the stop generation or authority changed: resume the whole Job")
            rows = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND arm_role=? "
                                      "AND status='HOLD'", (mission_id, arm_role)).fetchall()
            keys = sorted({key for row in rows for key in json.loads(row["claims_json"])})
            if phases(connection, mission_id, keys) & _UNRESOLVED:
                raise MissionConflict("resume is refused while an arm claim is DISPATCHING or UNKNOWN")
            now = _now()
            for row in rows:
                release_for_resume(connection, mission_id, job["dispatch_generation"],
                                          (row["step_index"], arm_role), json.loads(row["claims_json"]))
            self._resume_actions(connection, job, rows, now)
            self._set_arm(connection, mission_id, arm_role, now, "READY", None)
            resumed = connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE mission_id=? AND "
                                         "event_type='CELL_ARM_RESUMED'", (mission_id,)).fetchone()[0]
            arm_jobs.event(connection, mission_id, None, "CELL_ARM_RESUMED", actor_id, {
                "event_id": f"arm-resume:{arm_role}:{resumed}", "arm_role": arm_role,
                "previous_status": arm["status"], "previous_reason": arm["reason"],
                "dispatch_generation": expected_generation})
            summarize(connection, mission_id, now)
            return self._finish(connection, mission_id)

    def resume(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
        """Operator re-approval of the whole Job under the current fence: every arm resumes (D-779 §6)."""
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with self._tx(mission_id) as (connection, job):
            if job["status"] not in {"HOLD", "READY"} or job["reason"] == CANCELLED_REASON:
                raise MissionConflict("only a held, uncancelled Cell Job can resume")
            if CellJobStore._claim_phases(connection, job) & _UNRESOLVED:
                raise MissionConflict("resume is refused while a claim is DISPATCHING or UNKNOWN")
            control = connection.execute("SELECT authority_epoch, generation, dispatch_enabled FROM "
                                         "fleet_dispatch_control WHERE control_id=1").fetchone()
            if not control["dispatch_enabled"] or control["generation"] != expected_generation:
                raise MissionConflict("stop generation is closed or changed")
            release_claims(connection, owner_kind="mission", owner_id=mission_id)
            if not reserve_claims(connection, owner_kind="mission", owner_id=mission_id,
                                  generation=expected_generation, phase="CLAIMED",
                                  resources=[tuple(item) for item in json.loads(job["resources_json"])]):
                raise MissionConflict("Cell Job resource claim conflicts with another action")
            now = _now()
            rows = connection.execute("SELECT * FROM fleet_cell_step_actions WHERE mission_id=? AND status='HOLD'",
                                      (mission_id,)).fetchall()
            self._resume_actions(connection, job, rows, now)
            connection.execute("UPDATE fleet_cell_job_arms SET status='READY', reason=NULL, running_step_index=NULL, "
                               "updated_at=? WHERE mission_id=?", (now, mission_id))
            connection.execute("UPDATE fleet_cell_jobs SET authority_epoch=?, dispatch_generation=?, updated_at=? "
                               "WHERE mission_id=?", (control["authority_epoch"], expected_generation, now, mission_id))
            arm_jobs.event(connection, mission_id, job["current_step_index"], "CELL_JOB_RESUMED", actor_id, {
                "authority_epoch": control["authority_epoch"], "dispatch_generation": expected_generation,
                "previous_generation": job["dispatch_generation"], "arm_roles": "all",
                "approvals": CellJobStore._approvals(connection, job)})
            summarize(connection, mission_id, now)
            return self._finish(connection, mission_id)

    def cancel(self, mission_id: str, *, actor_id: str) -> dict[str, Any]:
        """Operator cancel of the whole Job (D-779 §6), the single-arm rules in one transaction: terminal,
        refused while a claim is DISPATCHING or UNKNOWN, every claim released, every arm shows it."""
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with self._tx(mission_id) as (connection, job):
            if job["status"] in {"PROPOSED", "GOAL_CONFIRMED", "RUNNING"} or job["reason"] == CANCELLED_REASON:
                raise MissionConflict(f"a {job['status']} Cell Job cannot be cancelled")
            if CellJobStore._claim_phases(connection, job) & _UNRESOLVED:
                raise MissionConflict("cancel is refused while a claim is DISPATCHING or UNKNOWN")
            values = (CANCELLED_REASON, _now(), mission_id)
            connection.execute("UPDATE fleet_cell_steps SET status='HOLD', reason=?, updated_at=? WHERE mission_id=? "
                               "AND status IN ('READY', 'ACTION_SUCCEEDED')", values)
            connection.execute("UPDATE fleet_cell_step_actions SET status='HOLD', reason=?, updated_at=? WHERE "
                               "mission_id=? AND status IN ('WAITING', 'READY', 'ACTION_SUCCEEDED')", values)
            connection.execute("UPDATE fleet_cell_job_arms SET status='HOLD', reason=?, updated_at=? "
                               "WHERE mission_id=? AND status != 'OFFLINE'", values)
            connection.execute("UPDATE fleet_cell_jobs SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                               values)
            release_claims(connection, owner_kind="mission", owner_id=mission_id)
            arm_jobs.event(connection, mission_id, job["current_step_index"], "CELL_JOB_CANCELLED", actor_id,
                           {"previous_status": job["status"], "previous_reason": job["reason"]})
            return self._finish(connection, mission_id)

__all__ = ["ArmJobStore", "OUTCOMES"]
