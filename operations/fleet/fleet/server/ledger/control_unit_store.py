"""Durable delegation identity and owner-sourced results in the Fleet journal."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from core_common.protocol.control_units import ControlDelegationState
from fleet.server.control_unit_config import UNIT_IDENTIFIER_ALIASES, _identifier
from fleet.server.sqlite_policy import configure_connection, enable_wal


STATES = frozenset(state.value for state in ControlDelegationState)
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELED", "EXPIRED"})

# D-1011: journal tables whose unit-id columns follow the identifier rename.
_UNIT_COLUMNS = {
    "fleet_control_unit_identity": ("unit_id",),
    "fleet_control_delegations": ("origin_id", "owner_unit"),
    "fleet_control_delegation_history": ("origin_id",),
    "fleet_control_stops": ("origin_id", "unit_id", "target_unit"),
    "fleet_control_stop_deliveries": ("origin_id", "delivery_unit"),
}
# JSON columns whose exactly-matching unit-id values follow the rename (never substrings).
_UNIT_DOCUMENTS = {
    "fleet_control_delegations": ("request_json", "result_json"),
    "fleet_control_stops": ("body_json",),
    "fleet_control_stop_deliveries": ("assigned_json", "results_json", "original_json", "reconcile_json"),
}


def _rewrite_ids(value, old, new):
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_rewrite_ids(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_ids(item, old, new) for key, item in value.items()}
    return value


def migrate_unit_identifier(connection, unit_id):
    """D-1011: rewrite a pre-rename journal to the renamed unit once, with an audit row."""
    old = next((source for source, target in UNIT_IDENTIFIER_ALIASES.items() if target == unit_id), None)
    if old is None:
        return
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    rewritten = 0
    for table, columns in _UNIT_COLUMNS.items():
        if table not in tables:
            continue
        for column in columns:
            rewritten += connection.execute(
                f"UPDATE {table} SET {column}=? WHERE {column}=?", (unit_id, old)).rowcount
    for table, columns in _UNIT_DOCUMENTS.items():
        if table not in tables:
            continue
        for column in columns:
            rows = connection.execute(
                f"SELECT rowid, {column} FROM {table} WHERE {column} LIKE ?", (f"%{old}%",)).fetchall()
            for rowid, payload in rows:
                try:
                    document = json.loads(payload)
                except (TypeError, ValueError):
                    continue
                migrated = _rewrite_ids(document, old, unit_id)
                if migrated != document:
                    connection.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?",
                                       (json.dumps(migrated, sort_keys=True,
                                                   separators=(",", ":"), allow_nan=False), rowid))
                    rewritten += 1
    if not rewritten:  # fresh or already-migrated journal: nothing renamed, no audit row
        return
    connection.execute("""CREATE TABLE IF NOT EXISTS fleet_control_unit_identifier_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
        applied_at TEXT NOT NULL)""")
    connection.execute(
        "INSERT INTO fleet_control_unit_identifier_events (from_id,to_id,applied_at) VALUES (?,?,?)",
        (old, unit_id, datetime.now(timezone.utc).isoformat()))


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
                CREATE INDEX IF NOT EXISTS fleet_control_delegation_tasks
                    ON fleet_control_delegations(local_task_id);
                CREATE INDEX IF NOT EXISTS fleet_control_delegation_recent
                    ON fleet_control_delegations(updated_at DESC,origin_id,delegation_id);
                CREATE INDEX IF NOT EXISTS fleet_control_delegation_active
                    ON fleet_control_delegations(updated_at,origin_id,delegation_id)
                    WHERE status NOT IN ('COMPLETED','FAILED','CANCELED','EXPIRED');
                CREATE INDEX IF NOT EXISTS fleet_control_delegation_result_mission
                    ON fleet_control_delegations(origin_id, json_extract(result_json,'$.job.mission_id'));
            """)
            # D-965 added the origin's cancel reason; older journals gain the column empty.
            if "cancel_reason" not in {c[1] for c in connection.execute("PRAGMA table_info(fleet_control_delegations)")}:
                connection.execute("ALTER TABLE fleet_control_delegations ADD COLUMN cancel_reason TEXT")
        with self._transaction() as connection:
            migrate_unit_identifier(connection, self.unit_id)  # D-1011 rename, idempotent + audited
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
            existing = connection.execute("SELECT 1 FROM fleet_control_delegations "
                                          "WHERE origin_id=? AND delegation_id=?",
                                          (origin_id, delegation_id)).fetchone()
            if existing is None and connection.execute(
                    "SELECT COUNT(*) FROM fleet_control_delegations "
                    "WHERE status NOT IN ('COMPLETED','FAILED','CANCELED','EXPIRED')").fetchone()[0] >= 256:
                raise ValueError("CONTROL_UNIT_ACTIVE_CAPACITY")
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

    def owns_task(self, task_id):
        with closing(self._connect()) as connection:
            return connection.execute("SELECT 1 FROM fleet_control_delegations "
                                      "WHERE local_task_id=? LIMIT 1", (task_id,)).fetchone() is not None

    def for_local_task(self, task_id):
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM fleet_control_delegations WHERE local_task_id=?",
                                      (task_id,)).fetchall()
            return [self._document(row) for row in rows]

    def by_result_mission(self, origin_id, mission_id):
        """The delegation whose owner projected this ARM mission (D-965 relay); KeyError when none."""
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_control_delegations WHERE origin_id=? "
                                     "AND json_extract(result_json,'$.job.mission_id')=?",
                                     (origin_id, mission_id)).fetchone()
        if row is None:
            raise KeyError(mission_id)
        return self._document(row)

    def list(self, *, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("INVALID_DELEGATION_LIMIT")
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM fleet_control_delegations "
                                      "ORDER BY updated_at DESC,origin_id,delegation_id LIMIT ?", (limit,)).fetchall()
            return [self._document(row) for row in rows]

    def active(self):
        with closing(self._connect()) as connection:
            return [self._document(row) for row in connection.execute(
                "SELECT * FROM fleet_control_delegations "
                "WHERE status NOT IN ('COMPLETED','FAILED','CANCELED','EXPIRED') "
                "ORDER BY updated_at,origin_id,delegation_id")]

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

    def approve(self, origin_id, delegation_id, *, actor_id, expected_revision=None):
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 96:
            raise ValueError("INVALID_LOCAL_APPROVAL")
        with self._transaction() as connection:
            row = self._read(connection, origin_id, delegation_id)
            if expected_revision is not None and (type(expected_revision) is not int
                                                  or expected_revision != row["revision"]):
                raise ValueError("CONTROL_UNIT_REVISION_CHANGED")
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
        if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 96:
            raise ValueError("INVALID_LOCAL_APPROVAL")
        def bind(connection, task_id):
            row = self._read(connection, origin_id, delegation_id)
            if not row["local_actor"] or row["local_actor"] != actor_id or row["owner_unit"] != self.unit_id:
                raise ValueError("LOCAL_APPROVAL_REQUIRED")
            if row["local_task_id"] == task_id:
                return
            if row["local_task_id"]:
                raise ValueError("LOCAL_TASK_IDENTITY_CONFLICT")
            if row["cancel_requested"] or row["status"] in TERMINAL:
                raise ValueError("LOCAL_APPROVAL_REFUSED")
            self._update(connection, row, {"local_task_id": task_id}, "TASK_BOUND")
        return bind

    def bind_local(self, origin_id, delegation_id, local_id, *, connection=None):
        """Bind an owner-local ARM proposal (D-965); approval stays with that proposal's own admit."""
        local_id = _identifier(local_id, limit=128)
        if connection is None:
            with self._transaction() as connection:
                return self.bind_local(origin_id, delegation_id, local_id, connection=connection)
        row = self._read(connection, origin_id, delegation_id)
        if row["owner_unit"] != self.unit_id:
            raise ValueError("LOCAL_BINDING_REFUSED")
        if row["local_task_id"] == local_id:
            return self._document(row)
        if row["local_task_id"]:
            raise ValueError("LOCAL_TASK_IDENTITY_CONFLICT")
        if row["cancel_requested"] or row["status"] in TERMINAL:
            raise ValueError("LOCAL_BINDING_REFUSED")
        return self._update(connection, row, {"local_task_id": local_id}, "ARM_JOB_BOUND")

    def request_cancel(self, origin_id, delegation_id, reason=None):
        with self._transaction() as connection:
            row = self._read(connection, origin_id, delegation_id)
            if row["cancel_requested"] or row["status"] in TERMINAL:
                return self._document(row)
            return self._update(connection, row, {"cancel_requested": 1, "cancel_reason": reason}, "CANCEL_REQUESTED")

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
