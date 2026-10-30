"""D-908: durable neutral trip proposals. A proposal holds no robot, lease or claim until an operator admits it."""
from contextlib import closing
from hashlib import sha256
import json
from uuid import uuid4

from fleet.server.mission_store import MissionConflict, _json, _now

# shortcut: own table created on first use; move it into the CellJobStore schema if a migration guard is wanted
_SCHEMA = """CREATE TABLE IF NOT EXISTS fleet_trip_proposals (
    proposal_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL, body_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PROPOSED',
    dispatch_generation INTEGER, approved_by TEXT, mission_id TEXT, created_at TEXT NOT NULL,
    UNIQUE (principal_id, request_key))"""


class TripProposalStore:
    def __init__(self, store) -> None:  # a CellJobStore: its journal and connection settings
        self.store = store
        with closing(store._connect()) as connection:
            connection.execute(_SCHEMA)
            connection.commit()

    @staticmethod
    def _view(row, connection) -> dict:
        body = json.loads(row["body_json"])
        if not isinstance(body, dict) or set(body) != {"candidates", "steps"}:
            raise ValueError("trip proposal body is invalid")
        document = {"proposal_id": row["proposal_id"], "principal_id": row["principal_id"],
                    "request_key": row["request_key"], **body}
        if sha256(_json(body).encode()).hexdigest() != row["request_digest"]:
            raise ValueError("trip proposal does not match its digest")
        if row["status"] == "ADMITTED":
            job = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?",
                                     (row["mission_id"],)).fetchone()
            admissions = connection.execute("SELECT actor_id, detail_json FROM fleet_cell_events WHERE mission_id=? "
                                            "AND event_type='CELL_JOB_ADMITTED'", (row["mission_id"],)).fetchall()
            if (job is None or len(admissions) != 1 or not row["approved_by"]
                    or row["approved_by"] == row["principal_id"] or row["dispatch_generation"] is None):
                raise MissionConflict("trip proposal has no independent committed admission")
            admission = json.loads(admissions[0]["detail_json"])
            actual = json.loads(job["job_json"])
            if (job["proposal_principal_id"] != row["principal_id"]
                    or job["request_key"] != "trip-pool:" + row["request_key"]
                    or job["request_digest"] != row["request_digest"]
                    or actual["robot_id"] != job["instance_id"]
                    or actual["robot_id"] not in body["candidates"] or actual["steps"] != body["steps"]
                    or admissions[0]["actor_id"] != row["approved_by"]
                    or admission.get("approval") != "proposal"
                    or admission.get("proposed_by") != row["principal_id"]
                    or type(admission.get("dispatch_generation")) is not int
                    or admission["dispatch_generation"] != row["dispatch_generation"]):
                raise MissionConflict("trip proposal and committed admission disagree")
        return {"proposal_id": row["proposal_id"], "proposal_principal_id": row["principal_id"],
                "request_key": row["request_key"], "request_digest": row["request_digest"],
                "proposal_digest": sha256(_json(document).encode()).hexdigest(),
                "candidate_robot_ids": body["candidates"], "steps": body["steps"], "status": row["status"],
                "dispatch_generation": row["dispatch_generation"], "approved_by": row["approved_by"],
                "mission_id": row["mission_id"]}

    def create(self, principal_id: str, request_key: str, candidates: list, steps: list) -> dict:
        body = {"candidates": candidates, "steps": steps}  # same bytes the candidate path digests
        digest = sha256(_json(body).encode()).hexdigest()
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute("SELECT * FROM fleet_trip_proposals WHERE principal_id=? AND request_key=?",
                                       (principal_id, request_key)).fetchone()
            if prior is None:
                connection.execute("INSERT INTO fleet_trip_proposals (proposal_id, principal_id, request_key, "
                                   "request_digest, body_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                   ("trip-prop-" + uuid4().hex, principal_id, request_key, digest, _json(body), _now()))
                prior = connection.execute("SELECT * FROM fleet_trip_proposals WHERE principal_id=? AND request_key=?",
                                           (principal_id, request_key)).fetchone()
            elif prior["request_digest"] != digest:
                raise MissionConflict("trip proposal key was reused with a different request")
            view = self._view(prior, connection)
            connection.commit()
            return view

    def get(self, *, proposal_id: str | None = None, principal_id: str | None = None,
            request_key: str | None = None) -> dict | None:
        where, args = (("proposal_id=?", (proposal_id,)) if proposal_id is not None
                       else ("principal_id=? AND request_key=?", (principal_id, request_key)))
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            row = connection.execute(f"SELECT * FROM fleet_trip_proposals WHERE {where}", args).fetchone()
            return None if row is None else self._view(row, connection)

    def dispatch_generation(self) -> int | None:
        """The open dispatch generation, or None while dispatch is stopped."""
        with closing(self.store._connect()) as connection:
            row = connection.execute("SELECT generation, dispatch_enabled FROM fleet_dispatch_control "
                                     "WHERE control_id=1").fetchone()
        return row["generation"] if row is not None and row["dispatch_enabled"] else None
