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
    def _view(row) -> dict:
        body = json.loads(row["body_json"])
        document = {"proposal_id": row["proposal_id"], "principal_id": row["principal_id"],
                    "request_key": row["request_key"], **body}
        if sha256(_json(body).encode()).hexdigest() != row["request_digest"]:
            raise ValueError("trip proposal does not match its digest")
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
            connection.commit()
            return self._view(prior)

    def get(self, *, proposal_id: str | None = None, principal_id: str | None = None,
            request_key: str | None = None) -> dict | None:
        where, args = (("proposal_id=?", (proposal_id,)) if proposal_id is not None
                       else ("principal_id=? AND request_key=?", (principal_id, request_key)))
        with closing(self.store._connect()) as connection:
            row = connection.execute(f"SELECT * FROM fleet_trip_proposals WHERE {where}", args).fetchone()
            return None if row is None else self._view(row)

    def dispatch_generation(self) -> int | None:
        """The open dispatch generation, or None while dispatch is stopped."""
        with closing(self.store._connect()) as connection:
            row = connection.execute("SELECT generation, dispatch_enabled FROM fleet_dispatch_control "
                                     "WHERE control_id=1").fetchone()
        return row["generation"] if row is not None and row["dispatch_enabled"] else None

    def admitted(self, proposal_id: str, *, approver: str, generation: int, mission_id: str) -> dict:
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE fleet_trip_proposals SET status='ADMITTED', approved_by=?, "
                               "dispatch_generation=?, mission_id=? WHERE proposal_id=? AND status='PROPOSED'",
                               (approver, generation, mission_id, proposal_id))
            row = connection.execute("SELECT * FROM fleet_trip_proposals WHERE proposal_id=?",
                                     (proposal_id,)).fetchone()
            connection.commit()
            return self._view(row)
