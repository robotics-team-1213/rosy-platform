"""Persistent, one-way binding of a physical owner journal to Fleet-only motion."""
from contextlib import closing
from dataclasses import dataclass
import re
import uuid


@dataclass(frozen=True)
class ManagedTransferScope:
    workcell_id: str
    instance_id: str
    policy_digest: str
    journal_id: str


def initialize_journal(connection, schema):
    # executescript commits a prior transaction; BEGIN must be in the script itself.
    connection.executescript("BEGIN IMMEDIATE;\n" + schema)
    try:
        read_scope(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        connection.execute(f"PRAGMA user_version={max(2, version)}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def read_scope(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > 3:
        raise RuntimeError(f"unsupported Action database schema version {version}")
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='omx_managed_transfer_scope'"
    ).fetchone()
    if not exists:
        if version == 3:
            raise RuntimeError("managed Action journal has lost its scope")
        return None
    rows = connection.execute(
        "SELECT workcell_id, instance_id, policy_digest, journal_id FROM omx_managed_transfer_scope"
    ).fetchall()
    if version != 3 or len(rows) != 1:
        raise RuntimeError("invalid managed Action journal scope")
    scope = ManagedTransferScope(*rows[0])
    if (not scope.workcell_id or not scope.instance_id
            or not isinstance(scope.policy_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", scope.policy_digest) is None
            or not isinstance(scope.journal_id, str) or not scope.journal_id):
        raise RuntimeError("invalid managed Action journal identity")
    return scope


def load_scope(store, workcell_id, instance_id):
    with closing(store._connect()) as connection:
        scope = read_scope(connection)
    if scope is not None and (scope.workcell_id, scope.instance_id) != (workcell_id, instance_id):
        raise PermissionError("managed Action journal belongs to another physical owner")
    return scope


def bind_scope(store, workcell_id, instance_id, policy_digest):
    if not isinstance(policy_digest, str) or re.fullmatch(r"[0-9a-f]{64}", policy_digest) is None:
        raise ValueError("a SHA-256 resource policy digest is required")
    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = read_scope(connection)
            if existing is not None:
                if (existing.workcell_id, existing.instance_id, existing.policy_digest) != (
                        workcell_id, instance_id, policy_digest):
                    raise PermissionError("managed physical scope cannot be changed")
                connection.commit()
                return existing
            if connection.execute(
                    "SELECT 1 FROM omx_actions WHERE state NOT IN ('SUCCEEDED', 'FAILED') LIMIT 1"
            ).fetchone():
                raise PermissionError("unresolved local Actions block managed activation")
            scope = ManagedTransferScope(workcell_id, instance_id, policy_digest, str(uuid.uuid4()))
            connection.execute("""CREATE TABLE omx_managed_transfer_scope (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                workcell_id TEXT NOT NULL, instance_id TEXT NOT NULL,
                policy_digest TEXT NOT NULL, journal_id TEXT NOT NULL)""")
            connection.execute("INSERT INTO omx_managed_transfer_scope VALUES (1, ?, ?, ?, ?)",
                               (scope.workcell_id, scope.instance_id, scope.policy_digest, scope.journal_id))
            connection.execute("PRAGMA user_version=3")
            connection.commit()
            return scope
        except BaseException:
            connection.rollback()
            raise
