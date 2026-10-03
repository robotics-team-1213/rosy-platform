"""Fleet-owned robot enrollment register with sealed CORE credentials (D-361 4, 11).

Fleet presents these tokens to robot CORE as a client, so it needs the plaintext and
keeps only AES-256-GCM ciphertext at rest. The key is a separate Compose secret; a
copy of this database alone yields no token. Plaintext never enters rows, audit,
logs, responses or exception messages.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from core_common.protocol.device_kind import ALL as device_kind_values
from core_common.protocol.device_kind import ROBOT
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .sqlite_policy import configure_connection, enable_wal

AAD_LABEL = "rosy-robot-cred/1"
SLOTS = frozenset({"rest", "agent"})
STATES = ("active", "needs_new_code", "address_changed", "pending_logout")
AUDIT_LIMIT = 10_000
NONCE_BYTES = 12
_KEY_LINE = re.compile(rb"[A-Za-z0-9+/]{43}=(\r?\n)?")

_COLUMNS = (
    "robot_id", "hostname", "serial_number", "device_uid", "discovery_name", "address",
    "token_id", "role", "source", "expires_at", "fleet_expires_at", "warn_at",
    "principal_id", "state",
)
_UPDATABLE = (frozenset(_COLUMNS) - {"robot_id"}) | {"logout_attempted"}


class CredentialKeyError(ValueError):
    """The robot credential key is missing or not one base64 line of 32 bytes."""


class SealError(ValueError):
    """A sealed credential did not open with this key and binding."""


def load_key_file(path: Path | str) -> bytes:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise CredentialKeyError("robot credential key file is not readable") from None
    if not _KEY_LINE.fullmatch(raw):
        raise CredentialKeyError("robot credential key must be one base64 line of 32 bytes")
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise CredentialKeyError("robot credential key is not valid base64") from None
    if len(key) != 32:
        raise CredentialKeyError("robot credential key must decode to 32 bytes")
    return key


def _aad(slot: str, robot_id: str, token_id: str) -> bytes:
    if slot not in SLOTS:
        raise ValueError("credential slot must be rest or agent")
    out = bytearray()
    for part in (AAD_LABEL, slot, robot_id, token_id):
        encoded = part.encode("utf-8")
        out += len(encoded).to_bytes(4, "big") + encoded
    return bytes(out)


def seal(key: bytes, token: str, *, slot: str, robot_id: str, token_id: str) -> bytes:
    aad = _aad(slot, robot_id, token_id)
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, token.encode("utf-8"), aad)


def unseal(key: bytes, blob: bytes, *, slot: str, robot_id: str, token_id: str) -> str:
    aad = _aad(slot, robot_id, token_id)
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError):
        raise SealError("sealed robot credential did not open") from None


def ensure_device_pairing_audit(connection: sqlite3.Connection) -> None:
    """Create or migrate the audit table shared by robot enrollment and camera pairing.

    D-341 8 and D-391 4: one table for every device kind. The column default stays for
    rows written before the column existed; every writer passes ``device_kind``.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS device_pairing_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL NOT NULL,
            device_kind TEXT NOT NULL DEFAULT 'overhead-camera',
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            principal_id TEXT,
            target TEXT
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(device_pairing_audit)")}
    if "device_kind" not in columns:
        # D-341 may have created the table first without the column (ADR 11).
        with connection:
            connection.execute(
                "ALTER TABLE device_pairing_audit ADD COLUMN device_kind TEXT "
                "NOT NULL DEFAULT 'overhead-camera'")


def append_device_pairing_audit(connection: sqlite3.Connection, *, at: float, device_kind: str,
                                action: str, outcome: str, principal_id: str | None,
                                target: str | None, limit: int) -> None:
    """Insert one audit row and keep only the newest ``limit`` rows (caller owns the transaction)."""
    if device_kind not in device_kind_values:
        raise ValueError("unknown device kind")
    connection.execute(
        "INSERT INTO device_pairing_audit(at, device_kind, action, outcome, "
        "principal_id, target) VALUES (?, ?, ?, ?, ?, ?)",
        (at, device_kind, action, outcome, principal_id, target))
    connection.execute(
        "DELETE FROM device_pairing_audit WHERE audit_id <= "
        "(SELECT MAX(audit_id) FROM device_pairing_audit) - ?", (limit,))


def device_pairing_audit_rows(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        "SELECT at, device_kind, action, outcome, principal_id, target "
        "FROM device_pairing_audit ORDER BY audit_id").fetchall()
    return [dict(zip(("at", "device_kind", "action", "outcome", "principal_id", "target"), row))
            for row in rows]


class EnrollmentStore:
    """`robot_enrollments` rows plus the shared `device_pairing_audit` table."""

    def __init__(self, path: Path | str, *, audit_limit: int = AUDIT_LIMIT) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_limit = audit_limit
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS robot_enrollments (
                    robot_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    serial_number TEXT,
                    device_uid TEXT,
                    discovery_name TEXT,
                    address TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    source TEXT NOT NULL,
                    expires_at TEXT,
                    fleet_expires_at REAL,
                    warn_at REAL,
                    ciphertext BLOB NOT NULL,
                    principal_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN {STATES!r}),
                    logout_attempted INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            ensure_device_pairing_audit(connection)
        if os.name != "nt":
            for path in (self.path, self.path.with_name(self.path.name + "-wal"),
                         self.path.with_name(self.path.name + "-shm")):
                if path.exists():
                    path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    def insert(self, row: dict, ciphertext: bytes) -> None:
        if row.get("state") not in STATES:
            raise ValueError("unknown enrollment state")
        now = time.time()
        values = [row.get(column) for column in _COLUMNS]
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    f"INSERT INTO robot_enrollments({', '.join(_COLUMNS)}, ciphertext, "
                    f"created_at, updated_at) VALUES ({', '.join('?' * len(_COLUMNS))}, ?, ?, ?)",
                    (*values, ciphertext, now, now),
                )

    def rows(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_COLUMNS)}, logout_attempted, created_at, updated_at "
                "FROM robot_enrollments "
                "ORDER BY robot_id").fetchall()
        return [dict(row) for row in rows]

    def get(self, robot_id: str) -> dict | None:
        return next((row for row in self.rows() if row["robot_id"] == robot_id), None)

    def ciphertext(self, robot_id: str) -> bytes:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT ciphertext FROM robot_enrollments WHERE robot_id=?",
                                     (robot_id,)).fetchone()
        if row is None:
            raise KeyError(robot_id)
        return bytes(row["ciphertext"])

    def update(self, robot_id: str, **fields) -> None:
        if not fields or not set(fields) <= _UPDATABLE:
            raise ValueError("unknown enrollment fields")
        if "state" in fields and fields["state"] not in STATES:
            raise ValueError("unknown enrollment state")
        assignments = ", ".join(f"{name}=?" for name in fields)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    f"UPDATE robot_enrollments SET {assignments}, updated_at=? WHERE robot_id=?",
                    (*fields.values(), time.time(), robot_id))

    def rebind(self, robot_id: str, ciphertext: bytes, **fields) -> None:
        """Replace the sealed token and its fields in one transaction (move to a new address)."""
        if not fields or not set(fields) <= _UPDATABLE:
            raise ValueError("unknown enrollment fields")
        if "state" in fields and fields["state"] not in STATES:
            raise ValueError("unknown enrollment state")
        assignments = ", ".join(f"{name}=?" for name in fields)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    f"UPDATE robot_enrollments SET {assignments}, ciphertext=?, updated_at=? "
                    "WHERE robot_id=?", (*fields.values(), ciphertext, time.time(), robot_id))

    def delete(self, robot_id: str) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM robot_enrollments WHERE robot_id=?", (robot_id,))

    def audit(self, *, action: str, outcome: str, principal_id: str | None,
              target: str | None, device_kind: str = ROBOT) -> None:
        with closing(self._connect()) as connection:
            with connection:
                append_device_pairing_audit(
                    connection, at=time.time(), device_kind=device_kind, action=action,
                    outcome=outcome, principal_id=principal_id, target=target,
                    limit=self._audit_limit)

    def audit_rows(self) -> list[dict]:
        with closing(self._connect()) as connection:
            return device_pairing_audit_rows(connection)

    def retired_robot_ids(self) -> set[str]:
        """Robots once enrolled here that are not on the roster now (D-361 5)."""
        with closing(self._connect()) as connection:
            pending = connection.execute(
                "SELECT robot_id FROM robot_enrollments WHERE state='pending_logout'").fetchall()
            removed = connection.execute(
                "SELECT target FROM device_pairing_audit WHERE device_kind=? "
                "AND action='unenroll' AND target IS NOT NULL", (ROBOT,)).fetchall()
        return {row[0] for row in pending} | {row[0] for row in removed}


def rekey(path: Path | str, old_key: bytes, new_key: bytes) -> int:
    """Reseal every stored credential in one transaction; Fleet must be stopped."""
    store = EnrollmentStore(path)
    with closing(store._connect()) as connection:
        rows = connection.execute(
            "SELECT robot_id, token_id, ciphertext FROM robot_enrollments").fetchall()
        resealed = []
        for row in rows:
            token = unseal(old_key, bytes(row["ciphertext"]), slot="rest",
                           robot_id=row["robot_id"], token_id=row["token_id"])
            resealed.append((seal(new_key, token, slot="rest", robot_id=row["robot_id"],
                                  token_id=row["token_id"]), row["robot_id"]))
        with connection:
            connection.executemany(
                "UPDATE robot_enrollments SET ciphertext=? WHERE robot_id=?", resealed)
    return len(resealed)
