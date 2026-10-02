"""Versioned, ordered Fleet journal for fixed-cell transfer Missions (D-403)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .cell_job_codec import _json, cell_transfer_grant_digest
from .cell_job_readback import CellJobReadbackMixin
from .dispatch_admission import release as release_claims
from .dispatch_admission import reserve as reserve_claims
from .dispatch_admission import normalize_resources
from .mission_store import MissionConflict, _nonempty, _now
from .sqlite_policy import configure_connection, enable_wal

_MIGRATION_VERSION = 1
_IDENTIFIER_HASH_FIELDS = ("recipe_digest", "cell_digest", "process_artifact_digest")


class CellJobStore(CellJobReadbackMixin):
    """Persist Cell Job ordering beside, but separate from, legacy PICK_PLACE rows."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_component_migrations (
                    component TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY(component, version)
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_jobs (
                    mission_id TEXT PRIMARY KEY,
                    proposal_principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    recipe_digest TEXT NOT NULL,
                    cell_digest TEXT NOT NULL,
                    process_artifact_digest TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    ledger_markers_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                        'GOAL_CONFIRMED', 'HOLD'
                    )),
                    current_step_index INTEGER NOT NULL DEFAULT 0 CHECK(current_step_index >= 0),
                    authority_epoch INTEGER,
                    dispatch_generation INTEGER,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_steps (
                    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
                    step_index INTEGER NOT NULL CHECK(step_index >= 0),
                    step_id TEXT NOT NULL UNIQUE,
                    action_kind TEXT NOT NULL CHECK(action_kind='CELL_TRANSFER'),
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
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
                    step_index INTEGER,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS fleet_cell_steps_status
                    ON fleet_cell_steps(status, updated_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO fleet_component_migrations(component, version, applied_at) "
                "VALUES ('cell_jobs', ?, ?)", (_MIGRATION_VERSION, _now()),
            )
            applied = connection.execute(
                "SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'",
            ).fetchone()[0]
            if applied > _MIGRATION_VERSION:
                raise RuntimeError(f"unsupported Cell Job journal migration version {applied}")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        configure_connection(connection)
        return connection

    def create(self, *, mission_id: str, proposal_principal_id: str, request_key: str,
               request_digest: str, submission: Mapping[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self.create_in_transaction(
                connection, mission_id=mission_id,
                proposal_principal_id=proposal_principal_id, request_key=request_key,
                request_digest=request_digest, submission=submission,
            )
            connection.commit()
        return result

    @staticmethod
    def create_in_transaction(connection: sqlite3.Connection, *, mission_id: str,
                              proposal_principal_id: str, request_key: str,
                              request_digest: str, submission: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a fully recompiled proposal and its ordered steps in caller's transaction."""
        mission_id = _nonempty("mission_id", mission_id)
        proposal_principal_id = _nonempty(
            "proposal_principal_id", proposal_principal_id, limit=96,
        )
        request_key = _nonempty("request_key", request_key, limit=160)
        if (not isinstance(request_digest, str) or len(request_digest) != 64
                or any(char not in "0123456789abcdef" for char in request_digest)):
            raise ValueError("request_digest must be lowercase SHA-256")
        if connection.execute(
                "SELECT 1 FROM fleet_missions WHERE mission_id=?", (mission_id,),
        ).fetchone() is not None:
            raise ValueError("Cell Job mission_id is already used by the legacy Mission journal")
        required = {
            "job_id", "workcell_id", "instance_id", "recipe_digest", "cell_digest",
            "process_artifact_digest", "job", "steps", "resources", "ledger_markers",
        }
        if set(submission) != required:
            raise ValueError("compiled Cell Job submission has an invalid shape")
        steps = submission["steps"]
        resources = submission["resources"]
        markers = submission["ledger_markers"]
        if not isinstance(steps, list) or not steps or not isinstance(resources, list) or not resources:
            raise ValueError("Cell Job requires ordered steps and resource claims")
        for field in _IDENTIFIER_HASH_FIELDS:
            value = submission[field]
            if (not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError(f"{field} must be lowercase SHA-256")
        now = _now()
        encoded_job = _json(submission["job"])
        resources_json = _json(resources)
        markers_json = _json(markers)
        connection.execute(
            """INSERT INTO fleet_cell_jobs
               (mission_id, proposal_principal_id, request_key, request_digest, job_id,
                workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest,
                job_json, resources_json, ledger_markers_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
            (mission_id, proposal_principal_id, request_key, request_digest,
             _nonempty("job_id", submission["job_id"]),
             _nonempty("workcell_id", submission["workcell_id"], limit=96),
             _nonempty("instance_id", submission["instance_id"], limit=96),
             submission["recipe_digest"], submission["cell_digest"],
             submission["process_artifact_digest"], encoded_job, resources_json,
             markers_json, now, now),
        )
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping) or set(step) != {"skill_id", "version", "inputs"}:
                raise ValueError("Cell Job step has an invalid execution shape")
            if step["skill_id"] != "pallet.transfer" or step["version"] != "1.0.0":
                raise ValueError("Cell Job steps must use pallet.transfer/1.0.0")
            step_id = f"{mission_id}:step-{index + 1}"
            connection.execute(
                """INSERT INTO fleet_cell_steps
                   (mission_id, step_index, step_id, action_kind, step_json, status, updated_at)
                   VALUES (?, ?, ?, 'CELL_TRANSFER', ?, 'WAITING', ?)""",
                (mission_id, index, step_id, _json(dict(step)), now),
            )
        return CellJobStore._get(connection, mission_id)

    @staticmethod
    def _get(connection: sqlite3.Connection, mission_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
        ).fetchone()
        if row is None:
            return None
        job = dict(row)
        for source, target in (("job_json", "job"), ("resources_json", "resources"),
                               ("ledger_markers_json", "ledger_markers")):
            job[target] = json.loads(job.pop(source))
        job["steps"] = []
        for step_row in connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? ORDER BY step_index",
                (mission_id,)):
            step = dict(step_row)
            step["step"] = json.loads(step.pop("step_json"))
            for source, target in (("grant_json", "grant"), ("result_json", "result"),
                                   ("goal_evidence_json", "goal_evidence")):
                raw = step.pop(source)
                step[target] = json.loads(raw) if raw is not None else None
            job["steps"].append(step)
        job["events"] = [
            {**dict(event), "detail": json.loads(event["detail_json"])}
            for event in connection.execute(
                "SELECT * FROM fleet_cell_events WHERE mission_id=? ORDER BY event_id",
                (mission_id,),
            )
        ]
        for event in job["events"]:
            event.pop("detail_json", None)
        return job

    def get(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            return self._get(connection, mission_id)

    def recover_after_startup(self) -> int:
        """Fence obsolete admitted Jobs while preserving attempts and occupancy claims."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT authority_epoch, generation FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            rows = connection.execute(
                """SELECT mission_id, current_step_index, authority_epoch, dispatch_generation
                   FROM fleet_cell_jobs WHERE status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')
                     AND (authority_epoch != ? OR dispatch_generation != ?)""",
                (control["authority_epoch"], control["generation"]),
            ).fetchall()
            for job in rows:
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                    "updated_at=? WHERE mission_id=?", (now, job["mission_id"]),
                )
                connection.execute(
                    "UPDATE fleet_cell_steps SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                    "updated_at=? WHERE mission_id=? AND step_index=? "
                    "AND status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')",
                    (now, job["mission_id"], job["current_step_index"]),
                )
                self._event(connection, job["mission_id"], job["current_step_index"],
                            "CELL_JOB_STARTUP_HOLD", "system", {
                                "reason": "SITE_AUTHORITY_CHANGED",
                                "previous_authority_epoch": job["authority_epoch"],
                                "previous_dispatch_generation": job["dispatch_generation"],
                                "authority_epoch": control["authority_epoch"],
                                "dispatch_generation": control["generation"],
                            })
            connection.commit()
        return len(rows)

    def admit(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if job is None:
                raise KeyError(mission_id)
            if job["status"] != "PROPOSED":
                raise MissionConflict("only a proposed Cell Job can be admitted")
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            if (control is None or not control["dispatch_enabled"]
                    or control["generation"] != expected_generation):
                raise MissionConflict("stop generation is closed or changed")
            if not reserve_claims(
                    connection, owner_kind="mission", owner_id=mission_id,
                    generation=expected_generation,
                    resources=[tuple(item) for item in json.loads(job["resources_json"])],
                    phase="CLAIMED"):
                raise MissionConflict("Cell Job resource claim conflicts with another action")
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='READY', authority_epoch=?, "
                "dispatch_generation=?, updated_at=? WHERE mission_id=?",
                (control["authority_epoch"], expected_generation, now, mission_id),
            )
            connection.execute(
                "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                "WHERE mission_id=? AND step_index=0 AND status='WAITING'",
                (now, mission_id),
            )
            self._event(connection, mission_id, None, "CELL_JOB_ADMITTED", actor_id,
                        {"authority_epoch": control["authority_epoch"],
                         "dispatch_generation": expected_generation})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def start_step(self, mission_id: str, *, step_index: int, action_id: str,
                   attempt_id: str, grant: Mapping[str, Any]) -> dict[str, Any]:
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        parsed = FleetCellTransferGrant.model_validate(dict(grant))
        canonical_grant = parsed.model_dump(mode="json")
        if cell_transfer_grant_digest(canonical_grant) != parsed.request_digest:
            raise ValueError("CELL_TRANSFER request digest does not match the complete grant")
        now_dt = datetime.now(timezone.utc)
        if parsed.issued_at > now_dt or parsed.expires_at <= now_dt:
            raise MissionConflict("CELL_TRANSFER grant is not current")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if job is None:
                raise KeyError(mission_id)
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if step is None:
                raise KeyError((mission_id, step_index))
            if (job["status"] != "READY" or step["status"] != "READY"
                    or job["current_step_index"] != step_index):
                raise MissionConflict("only the current READY Cell Job step may start")
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            if (control is None or not control["dispatch_enabled"]
                    or control["authority_epoch"] != job["authority_epoch"]
                    or control["generation"] != job["dispatch_generation"]):
                raise MissionConflict("Fleet authority or stop generation changed before submission")
            if (parsed.mission_id != mission_id or parsed.step_id != step["step_id"]
                    or parsed.action_id != action_id or parsed.attempt_id != attempt_id
                    or parsed.workcell_id != job["workcell_id"]
                    or parsed.instance_id != job["instance_id"]
                    or parsed.cell_transfer.job_id != job["job_id"]
                    or parsed.cell_transfer.step_index != step_index
                    or parsed.cell_transfer.recipe_sha256 != job["recipe_digest"]
                    or parsed.cell_transfer.cell_sha256 != job["cell_digest"]
                    or parsed.authority_epoch != job["authority_epoch"]
                    or parsed.dispatch_generation != job["dispatch_generation"]):
                raise ValueError("CELL_TRANSFER grant does not match the current persisted step")
            execution_step = json.loads(step["step_json"])
            inputs = execution_step["inputs"]

            def wire_pose(value: Mapping[str, Any]) -> dict[str, float]:
                return {"x": value["x_m"], "y": value["y_m"],
                        "z": value["z_m"], "yaw": value["yaw_rad"]}

            expected_payload = {
                "job_id": job["job_id"], "recipe_sha256": job["recipe_digest"],
                "cell_sha256": job["cell_digest"], "step_index": step_index,
                "item": inputs["item"], "pallet": inputs["pallet_id"],
                "layer": inputs["layer_index"], "frame": "robot_base",
                "home": wire_pose(inputs["home_pose_base"]),
                "pick": wire_pose(inputs["source_pose_base"]),
                "place": wire_pose(inputs["destination_pose_base"]),
                "pick_approach_z": inputs["source_approach_z_base_m"],
                "place_approach_z": inputs["destination_approach_z_base_m"],
                "carry_z": inputs["carry_z_base_m"],
            }
            if parsed.cell_transfer.model_dump(mode="json") != expected_payload:
                raise ValueError("CELL_TRANSFER payload does not match the persisted PlanBundle step")
            claims = connection.execute(
                "SELECT resource_key, phase FROM fleet_action_claims "
                "WHERE owner_kind='mission' AND owner_id=? AND generation=?",
                (mission_id, job["dispatch_generation"]),
            ).fetchall()
            expected_keys = {key for _, _, key in normalize_resources(json.loads(job["resources_json"]))}
            if ({claim["resource_key"] for claim in claims} != expected_keys
                    or any(claim["phase"] not in {"CLAIMED", "DISPATCHING"} for claim in claims)):
                raise MissionConflict("Cell Job no longer owns all durable resource claims")
            connection.execute(
                "UPDATE fleet_action_claims SET phase='DISPATCHING', lease_until=NULL "
                "WHERE owner_kind='mission' AND owner_id=? AND generation=?",
                (mission_id, job["dispatch_generation"]),
            )
            connection.execute(
                """UPDATE fleet_cell_steps SET status='RUNNING', action_id=?, attempt_id=?,
                   request_digest=?, grant_json=?, updated_at=?
                   WHERE mission_id=? AND step_index=?""",
                (action_id, attempt_id, parsed.request_digest,
                 _json(canonical_grant), now, mission_id, step_index),
            )
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='RUNNING', updated_at=? WHERE mission_id=?",
                (now, mission_id),
            )
            self._event(connection, mission_id, step_index, "CELL_STEP_SUBMITTING", "fleet",
                        {"action_id": action_id, "attempt_id": attempt_id,
                         "request_digest": parsed.request_digest})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def confirm_step_goal(self, mission_id: str, *, step_index: int,
                          action_id: str, attempt_id: str,
                          evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Record already authenticated sim-model and post-action gripper evidence."""
        required_evidence = {
            "producer_id", "evidence_id", "evidence_source", "action_id", "attempt_id",
            "satisfied", "gripper_state", "gripper_evidence_id",
        }
        if not isinstance(evidence, Mapping) or not required_evidence.issubset(evidence):
            raise ValueError("Cell step goal confirmation requires independent producer and gripper evidence")
        if (evidence["evidence_source"] != "sim_model_pose"
                or evidence["action_id"] != action_id or evidence["attempt_id"] != attempt_id
                or evidence["gripper_state"] != "OPEN"
                or type(evidence["satisfied"]) is not bool):
            raise MissionConflict("Cell step goal evidence does not match the current transfer attempt")
        if evidence["satisfied"] is not True:
            raise MissionConflict("unsatisfied Cell step goal evidence cannot advance the Job")
        evidence_json = _json(dict(evidence))
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if job is None or step is None:
                raise KeyError(mission_id if job is None else (mission_id, step_index))
            if (job["status"] != "ACTION_SUCCEEDED" or step["status"] != "ACTION_SUCCEEDED"
                    or step["action_id"] != action_id or step["attempt_id"] != attempt_id):
                raise MissionConflict("independent goal evidence requires this step's terminal Action success")
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_steps SET status='GOAL_CONFIRMED', goal_evidence_json=?, "
                "reason=NULL, updated_at=? WHERE mission_id=? AND step_index=?",
                (evidence_json, now, mission_id, step_index),
            )
            next_index = step_index + 1
            next_step = connection.execute(
                "SELECT step_index FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, next_index),
            ).fetchone()
            if next_step is not None:
                connection.execute(
                    "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                    "WHERE mission_id=? AND step_index=? AND status='WAITING'",
                    (now, mission_id, next_index),
                )
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='READY', current_step_index=?, "
                    "reason=NULL, updated_at=? WHERE mission_id=?",
                    (next_index, now, mission_id),
                )
                event_type = "CELL_STEP_GOAL_CONFIRMED"
            else:
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED', current_step_index=?, "
                    "reason=NULL, updated_at=? WHERE mission_id=?",
                    (next_index, now, mission_id),
                )
                release_claims(connection, owner_kind="mission", owner_id=mission_id,
                               generation=job["dispatch_generation"])
                event_type = "CELL_JOB_GOAL_CONFIRMED"
            self._event(connection, mission_id, step_index, event_type, "goal-evidence",
                        json.loads(evidence_json))
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    @staticmethod
    def _event(connection: sqlite3.Connection, mission_id: str, step_index: int | None,
               event_type: str, actor_id: str, detail: Mapping[str, Any]) -> None:
        identity = detail.get("event_id") or (
            f"{event_type}:{step_index}:"
            f"{hashlib.sha256(_json(dict(detail)).encode()).hexdigest()}"
        )
        key = f"{mission_id}:{identity}"
        encoded = _json(dict(detail))
        prior = connection.execute(
            "SELECT * FROM fleet_cell_events WHERE event_key=?", (key,),
        ).fetchone()
        if prior is not None:
            if (prior["mission_id"] != mission_id or prior["step_index"] != step_index
                    or prior["event_type"] != event_type or prior["actor_id"] != actor_id
                    or prior["detail_json"] != encoded):
                raise MissionConflict("Cell Job event identity was reused with different evidence")
            return
        connection.execute(
            """INSERT INTO fleet_cell_events
               (event_key, mission_id, step_index, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, mission_id, step_index, event_type, actor_id, encoded, _now()),
        )
