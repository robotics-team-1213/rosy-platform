"""Durable delegation identity and owner-sourced results in the Fleet journal."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from fleet.server.control_unit_config import _identifier
from fleet.server.sqlite_policy import configure_connection, enable_wal


STATES = frozenset({"PENDING", "APPROVING", "REQUESTED", "QUEUED", "ACCEPTED",
                    "RUNNING", "UNKNOWN", "HOLD", "COMPLETED", "FAILED", "CANCELED", "EXPIRED"})
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELED", "EXPIRED"})


def _json(value):
    if not isinstance(value, dict):
        raise ValueError("INVALID_DELEGATION_DOCUMENT")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_DELEGATION_DOCUMENT") from exc
    if len(encoded.encode("utf-8")) > 65_536:
        raise ValueError("DELEGATION_DOCUMENT_TOO_LARGE")
    return encoded


class ControlUnitStore:
    def __init__(self, path, *, unit_id):
        self.unit_id = _identifier(unit_id)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS fleet_control_unit_identity (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), unit_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fleet_control_delegations (
                    origin_id TEXT NOT NULL, delegation_id TEXT NOT NULL,
                    request_json TEXT NOT NULL, owner_unit TEXT NOT NULL,
                    config_revision TEXT NOT NULL, status TEXT NOT NULL,
                    revision INTEGER NOT NULL, owner_revision INTEGER NOT NULL DEFAULT 0,
                    local_actor TEXT, local_task_id TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
                    PRIMARY KEY(origin_id, delegation_id));
                CREATE TABLE IF NOT EXISTS fleet_control_delegation_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin_id TEXT NOT NULL, delegation_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, event TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)
        with self._transaction() as connection:
            connection.execute("INSERT OR IGNORE INTO fleet_control_unit_identity VALUES (1, ?)",
                               (self.unit_id,))
            if connection.execute("SELECT unit_id FROM fleet_control_unit_identity").fetchone()[0] != self.unit_id:
                raise ValueError("CONTROL_UNIT_DATABASE_IDENTITY_CONFLICT")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    @contextmanager
    def _transaction(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    @staticmethod
    def _read(connection, origin_id, delegation_id):
        row = connection.execute("SELECT * FROM fleet_control_delegations "
                                 "WHERE origin_id=? AND delegation_id=?",
                                 (origin_id, delegation_id)).fetchone()
        if row is None:
            raise KeyError(delegation_id)
        return row

    @staticmethod
    def _document(row):
        row = dict(row)
        row["request"] = json.loads(row.pop("request_json"))
        row["result"] = json.loads(row.pop("result_json"))
        row["cancel_requested"] = bool(row["cancel_requested"])
        return row

    @staticmethod
    def _event(connection, row, event):
        connection.execute("INSERT INTO fleet_control_delegation_history "
                           "(origin_id,delegation_id,revision,event,status,created_at) VALUES (?,?,?,?,?,?)",
                           (row["origin_id"], row["delegation_id"], row["revision"], event,
                            row["status"], row["updated_at"]))

    def create(self, origin_id, delegation_id, request, *, owner_unit, config_revision):
        origin_id, delegation_id = _identifier(origin_id), _identifier(delegation_id, limit=128)
        owner_unit, config_revision = _identifier(owner_unit), _identifier(config_revision)
        payload = _json(request)
        with self._transaction() as connection:
            connection.execute("INSERT OR IGNORE INTO fleet_control_delegations "
                               "(origin_id,delegation_id,request_json,owner_unit,config_revision,status,revision,updated_at) "
                               "VALUES (?,?,?,?,?,'PENDING',1,?)",
                               (origin_id, delegation_id, payload, owner_unit, config_revision,
                                datetime.now(timezone.utc).isoformat()))
            created = connection.execute("SELECT changes()").fetchone()[0] == 1
            row = self._read(connection, origin_id, delegation_id)
            if row["request_json"] != payload or row["owner_unit"] != owner_unit:
                raise ValueError("DELEGATION_IDENTITY_CONFLICT")
            if created:
                self._event(connection, row, "CREATED")
            return self._document(row)

    def get(self, origin_id, delegation_id):
        with closing(self._connect()) as connection:
            return self._document(self._read(connection, origin_id, delegation_id))

    def list(self, *, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("INVALID_DELEGATION_LIMIT")
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM fleet_control_delegations "
                                      "ORDER BY updated_at DESC,origin_id,delegation_id LIMIT ?", (limit,)).fetchall()
            return [self._document(row) for row in rows]

    def _update(self, connection, row, values, event):
        values = dict(values, revision=row["revision"] + 1,
                      updated_at=datetime.now(timezone.utc).isoformat())
        # Column names come only from this module's fixed mutations.
        connection.execute("UPDATE fleet_control_delegations SET "
                           + ",".join(f"{key}=?" for key in values)
                           + " WHERE origin_id=? AND delegation_id=?",
                           (*values.values(), row["origin_id"], row["delegation_id"]))
        changed = self._read(connection, row["origin_id"], row["delegation_id"])
        self._event(connection, changed, event)
        return self._document(changed)

    def approve(self, origin_id, delegation_id, *, actor_id):
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 96:
            raise ValueError("INVALID_LOCAL_APPROVAL")
        with self._transaction() as connection:
            row = self._read(connection, origin_id, delegation_id)
            if row["local_actor"] and row["local_actor"] != actor_id:
                raise ValueError("LOCAL_APPROVAL_IDENTITY_CONFLICT")
            if (row["owner_unit"] != self.unit_id or row["cancel_requested"]
                    or row["status"] in TERMINAL):
                raise ValueError("LOCAL_APPROVAL_REFUSED")
            if row["local_actor"]:
                return self._document(row)
            return self._update(connection, row, {"local_actor": actor_id, "status": "APPROVING"}, "APPROVED")

    def task_admission(self, origin_id, delegation_id, *, actor_id):
        """Bind inside FleetTaskStore.create_task's transaction, before dispatch."""
        def bind(connection, task_id):
            row = self._read(connection, origin_id, delegation_id)
            if row["local_actor"] != actor_id or row["owner_unit"] != self.unit_id:
                raise ValueError("LOCAL_APPROVAL_REQUIRED")
            if row["local_task_id"] == task_id:
                return
            if row["local_task_id"]:
                raise ValueError("LOCAL_TASK_IDENTITY_CONFLICT")
            if row["cancel_requested"] or row["status"] in TERMINAL:
                raise ValueError("LOCAL_APPROVAL_REFUSED")
            self._update(connection, row, {"local_task_id": task_id}, "TASK_BOUND")
        return bind

    def request_cancel(self, origin_id, delegation_id):
        with self._transaction() as connection:
            row = self._read(connection, origin_id, delegation_id)
            if row["cancel_requested"] or row["status"] in TERMINAL:
                return self._document(row)
            return self._update(connection, row, {"cancel_requested": 1}, "CANCEL_REQUESTED")

    def project(self, origin_id, delegation_id, *, owner_unit, owner_revision, status, result):
        if (status not in STATES or isinstance(owner_revision, bool)
                or not isinstance(owner_revision, int) or owner_revision < 1):
            raise ValueError("INVALID_OWNER_RESULT")
        payload = _json(result)
        with self._transaction() as connection:
            row = self._read(connection, origin_id, delegation_id)
            if row["owner_unit"] != owner_unit:
                raise ValueError("WRONG_RESULT_OWNER")
            if owner_revision < row["owner_revision"]:
                return self._document(row)
            same_result = row["status"] == status and row["result_json"] == payload
            if same_result:
                if owner_revision > row["owner_revision"]:
                    return self._update(connection, row, {"owner_revision": owner_revision}, "OWNER_REFRESHED")
                return self._document(row)
            if row["status"] in TERMINAL or owner_revision == row["owner_revision"]:
                raise ValueError("OWNER_RESULT_CONFLICT")
            return self._update(connection, row, {"owner_revision": owner_revision,
                                "status": status, "result_json": payload}, "OWNER_RESULT")

    def history(self, origin_id, delegation_id):
        with closing(self._connect()) as connection:
            self._read(connection, origin_id, delegation_id)
            return [dict(row) for row in connection.execute(
                "SELECT * FROM fleet_control_delegation_history WHERE origin_id=? AND delegation_id=? "
                "ORDER BY event_id", (origin_id, delegation_id))]
