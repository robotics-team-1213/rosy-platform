"""D-763 7: the step-ledger rows of a job whose steps are trips (``TRIP``), one SQLite transaction each.

The job lives in the step ledger beside Cell Jobs (``CellJobStore`` tables, fence and durable ``robot`` claim,
D-420 §4.5): admitted with its claim at creation (one named operator, registry ``one_person``), RUNNING with the
step's trip id as its attempt, GOAL_CONFIRMED only on that trip's ``arrived``, HOLD (claim HELD) on anything else.
The Cell identity columns hold the job's own: the robot is its device, the digests are its step list's. Callers
run these in a worker thread, never on the trip loop's event loop.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing

from fleet.server.cell_job_store import CANCELLED_REASON, CellJobStore
from fleet.server.dispatch_admission import release as release_claims, reserve as reserve_claims
from fleet.server.mission_store import MissionConflict, _json, _now
from fleet.server.trip_ports import TripError

KIND = "TRIP"
ACTIVE = ("READY", "RUNNING", "ACTION_SUCCEEDED")
ADMISSIONS = ("CELL_JOB_ADMITTED", "CELL_JOB_RESUMED")  # a named operator's approval


class TripJobRows:
    def __init__(self, store: CellJobStore) -> None:
        self.store = store

    def _write(self, mission_id: str, change):
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = change(connection, CellJobStore._require(connection, mission_id))
            connection.commit()
            return result

    def ids(self, statuses) -> list:
        """Trip jobs in ``statuses`` whose current step is a trip, oldest update first."""
        with closing(self.store._connect()) as connection:
            return [row[0] for row in connection.execute(
                f"SELECT j.mission_id FROM fleet_cell_jobs j JOIN fleet_cell_steps s ON s.mission_id=j.mission_id "
                f"AND s.step_index=j.current_step_index WHERE s.action_kind=? AND j.status IN "
                f"({', '.join('?' * len(statuses))}) ORDER BY j.updated_at", (KIND, *statuses))]

    def find_request(self, principal_id: str, request_key: str, request_digest: str) -> dict | None:
        with closing(self.store._connect()) as connection:
            row = connection.execute("SELECT mission_id,request_digest FROM fleet_cell_jobs "
                                     "WHERE proposal_principal_id=? AND request_key=?",
                                     (principal_id, request_key)).fetchone()
            if row is None:
                return None
            if row["request_digest"] != request_digest:
                raise TripError(409, "TRIP_REQUEST_CONFLICT")
            return CellJobStore._get(connection, row["mission_id"])

    def read(self, principal_id: str, *, mission_id: str | None = None,
             request_key: str | None = None) -> dict | None:
        """Read a principal's transport-only job in one consistent SQLite snapshot."""
        if (mission_id is None) == (request_key is None):
            raise ValueError("Supply exactly one mission ID or candidate request key")
        field, value = ("mission_id", mission_id) if mission_id is not None else ("request_key", "trip-pool:" + request_key)
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                f"SELECT j.* FROM fleet_cell_jobs j WHERE j.proposal_principal_id=? AND j.{field}=? "
                "AND EXISTS (SELECT 1 FROM fleet_cell_steps s WHERE s.mission_id=j.mission_id AND s.action_kind=?) "
                "AND NOT EXISTS (SELECT 1 FROM fleet_cell_steps s WHERE s.mission_id=j.mission_id AND s.action_kind!=?)",
                (principal_id, value, KIND, KIND)).fetchone()
            if row is None:
                return None
            steps = [dict(step) for step in connection.execute(
                "SELECT step_index,step_json,status,action_id,attempt_id,reason FROM fleet_cell_steps "
                "WHERE mission_id=? ORDER BY step_index", (row["mission_id"],))]
            for step in steps:
                step["step"] = json.loads(step.pop("step_json"))
            key = row["request_key"]
            return {"mission_id": row["mission_id"],
                    "request_key": key.removeprefix("trip-pool:") if key.startswith("trip-pool:") else None,
                    "request_digest": row["request_digest"], "robot_id": row["instance_id"],
                    "status": row["status"], "current_step_index": row["current_step_index"],
                    "steps": steps, "reason": row["reason"], "updated_at": row["updated_at"]}

    def create(self, mission_id: str, robot_id: str, principal_id: str, steps: list, *,
               request_key: str | None = None, request_digest: str | None = None,
               approved_by: str | None = None, proposal_id: str | None = None,
               expected_proposal_digest: str | None = None, expected_generation: int | None = None) -> dict:
        body = _json({"robot_id": robot_id, "steps": steps})
        digest, now = hashlib.sha256(body.encode()).hexdigest(), _now()
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if request_key is not None and connection.execute(
                    "SELECT 1 FROM fleet_cell_jobs WHERE proposal_principal_id=? AND request_key=?",
                    (principal_id, request_key)).fetchone() is not None:
                raise MissionConflict("trip request already committed")
            control = connection.execute("SELECT authority_epoch, generation, dispatch_enabled FROM "
                                         "fleet_dispatch_control WHERE control_id=1").fetchone()
            if control is None or not control["dispatch_enabled"]:
                raise MissionConflict("dispatch is stopped (site stop latch)")
            if any(value is not None for value in
                   (approved_by, proposal_id, expected_proposal_digest, expected_generation)):
                if (not proposal_id or not approved_by or approved_by == principal_id
                        or not expected_proposal_digest or isinstance(expected_generation, bool)
                        or not isinstance(expected_generation, int) or expected_generation != control["generation"]):
                    raise MissionConflict("proposal approval generation or identity changed")
                proposal = connection.execute("SELECT * FROM fleet_trip_proposals WHERE proposal_id=?",
                                              (proposal_id,)).fetchone()
                if (proposal is None or proposal["status"] != "PROPOSED"
                        or proposal["principal_id"] != principal_id
                        or request_key != "trip-pool:" + proposal["request_key"]
                        or proposal["request_digest"] != request_digest
                        or any(proposal[field] is not None for field in
                               ("approved_by", "dispatch_generation", "mission_id"))):
                    raise MissionConflict("trip proposal does not match this admission")
                proposed = json.loads(proposal["body_json"])
                document = {"proposal_id": proposal_id, "principal_id": principal_id,
                            "request_key": proposal["request_key"], **proposed}
                if (hashlib.sha256(_json(proposed).encode()).hexdigest() != proposal["request_digest"]
                        or hashlib.sha256(_json(document).encode()).hexdigest() != expected_proposal_digest
                        or robot_id not in proposed["candidates"] or steps != proposed["steps"]):
                    raise MissionConflict("trip proposal content changed")
            connection.execute(
                "INSERT INTO fleet_cell_jobs (mission_id, proposal_principal_id, request_key, request_digest, job_id, "
                "workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest, job_json, "
                "resources_json, ledger_markers_json, status, authority_epoch, dispatch_generation, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'READY', ?, ?, ?, ?)",
                (mission_id, principal_id, request_key or mission_id, request_digest or digest, mission_id,
                 robot_id, robot_id, digest, digest, digest,
                 body, _json([["robot", robot_id]]), control["authority_epoch"], control["generation"], now, now))
            for index, step in enumerate(steps):
                connection.execute("INSERT INTO fleet_cell_steps (mission_id, step_index, step_id, action_kind, "
                                   "step_json, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (mission_id, index, f"{mission_id}:step-{index + 1}", KIND, _json(step),
                                    "WAITING" if index else "READY", now))
            if not reserve_claims(connection, owner_kind="mission", owner_id=mission_id, phase="CLAIMED",
                                  generation=control["generation"], resources=[("robot", robot_id)]):
                raise MissionConflict("another task or job claims this robot")
            CellJobStore._event(connection, mission_id, None, "CELL_JOB_ADMITTED", approved_by or principal_id, {
                "authority_epoch": control["authority_epoch"], "dispatch_generation": control["generation"],
                "approval": "one_person" if approved_by is None else "proposal", "proposed_by": principal_id})
            if proposal_id is not None:
                changed = connection.execute(
                    "UPDATE fleet_trip_proposals SET status='ADMITTED', approved_by=?, dispatch_generation=?, "
                    "mission_id=? WHERE proposal_id=? AND status='PROPOSED'",
                    (approved_by, control["generation"], mission_id, proposal_id)).rowcount
                if changed != 1:
                    raise MissionConflict("trip proposal admission changed")
            job = CellJobStore._get(connection, mission_id)
            connection.commit()
            return job

    def started(self, mission_id: str, index: int, trip_id: str, actor: str) -> bool:
        def change(connection, job):
            if job["status"] != "READY" or job["current_step_index"] != index:
                return False
            if not CellJobStore._fence_current(connection, job):  # a site stop since approval: no new trip
                raise TripError(409, "FLEET_FENCE_CHANGED_BEFORE_SUBMISSION")
            now = _now()
            connection.execute("UPDATE fleet_cell_steps SET status='RUNNING', action_id=?, attempt_id=?, updated_at=? "
                               "WHERE mission_id=? AND step_index=?", (trip_id, trip_id, now, mission_id, index))
            connection.execute("UPDATE fleet_cell_jobs SET status='RUNNING', updated_at=? WHERE mission_id=?",
                               (now, mission_id))
            CellJobStore._event(connection, mission_id, index, "CELL_STEP_SUBMITTING", actor,
                                {"action_id": trip_id, "trip_id": trip_id})
            return True
        return self._write(mission_id, change)

    def arrived(self, mission_id: str, index: int, trip_id: str) -> None:
        """The step's trip arrived (its goal evidence): the next step READY, or the job done and its claim released."""
        def change(connection, job):
            step = connection.execute("SELECT action_id FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                      (mission_id, index)).fetchone()
            if job["status"] != "RUNNING" or job["current_step_index"] != index or step["action_id"] != trip_id:
                return
            count = connection.execute("SELECT COUNT(*) FROM fleet_cell_steps WHERE mission_id=?",
                                       (mission_id,)).fetchone()[0]
            last, now = index + 1 == count, _now()
            connection.execute("UPDATE fleet_cell_steps SET status='GOAL_CONFIRMED', goal_evidence_json=?, "
                               "reason=NULL, updated_at=? WHERE mission_id=? AND step_index=?",
                               (_json({"trip_id": trip_id, "trip_state": "arrived"}), now, mission_id, index))
            connection.execute("UPDATE fleet_cell_jobs SET status=?, current_step_index=?, updated_at=? WHERE "
                               "mission_id=?", ("GOAL_CONFIRMED" if last else "READY", index + 1, now, mission_id))
            if last:
                release_claims(connection, owner_kind="mission", owner_id=mission_id)
            else:
                connection.execute("UPDATE fleet_cell_steps SET status='READY', updated_at=? WHERE mission_id=? "
                                   "AND step_index=?", (now, mission_id, index + 1))
            CellJobStore._event(connection, mission_id, index, "CELL_JOB_GOAL_CONFIRMED" if last
                                else "CELL_STEP_GOAL_CONFIRMED", "trip", {"trip_id": trip_id})
            if not last and not CellJobStore._fence_current(connection, job):  # a site stop: no next step
                self._held(connection, CellJobStore._require(connection, mission_id), "SITE_AUTHORITY_CHANGED", {})
        self._write(mission_id, change)

    @staticmethod
    def _held(connection, job, reason: str, detail: dict) -> bool:
        if job["status"] not in ACTIVE:
            return False
        # Keyed by the count of earlier holds: a resume under an unchanged fence adds no new event to count on.
        holds = connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE mission_id=? AND "
                                   "event_type='CELL_JOB_HELD'", (job["mission_id"],)).fetchone()[0]
        CellJobStore._hold_in_transaction(
            connection, job, reason=reason[:96], claim_phase="HELD", actor_id="fleet", detail=detail, strict=False,
            event_key=f"trip-hold:{job['current_step_index']}:{holds}")
        return True

    def uncased(self) -> list:
        """HOLD trip jobs whose newest hold has no case yet (any writer: this loop, the stop latch, a restart)."""
        with closing(self.store._connect()) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT j.mission_id, j.instance_id, j.reason, e.event_id, e.detail_json FROM fleet_cell_jobs j "
                "JOIN fleet_cell_events e ON e.event_id=(SELECT MAX(event_id) FROM fleet_cell_events WHERE "
                "mission_id=j.mission_id AND event_type IN ('CELL_JOB_HELD', 'CELL_JOB_STARTUP_HOLD')) "
                "WHERE j.status='HOLD' AND j.reason!=? AND EXISTS (SELECT 1 FROM fleet_cell_steps s WHERE "
                "s.mission_id=j.mission_id AND s.action_kind=?) AND NOT EXISTS (SELECT 1 FROM fleet_cell_events c "
                "WHERE c.event_key=j.mission_id || ':case:' || e.event_id)", (CANCELLED_REASON, KIND))]

    def cased(self, mission_id: str, held_event_id: int) -> None:
        self._write(mission_id, lambda connection, job: CellJobStore._event(
            connection, mission_id, job["current_step_index"], "JOB_CASE_OPENED", "fleet",
            {"event_id": f"case:{held_event_id}"}))

    def hold(self, mission_id: str, reason: str, detail: dict) -> bool:
        """HOLD an active job (claim HELD, its reason and detail in the event); False when it is not active."""
        return self._write(mission_id, lambda connection, job: self._held(connection, job, reason, detail))


__all__ = ["ACTIVE", "ADMISSIONS", "KIND", "TripJobRows"]
