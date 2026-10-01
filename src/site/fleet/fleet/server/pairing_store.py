"""Fleet SQLite rows for D-341 device credentials: digest and metadata only (D-341 8).

No plaintext token, poll secret, nonce or confirmation code has a column here. The
audit table is the shared ``device_pairing_audit`` (D-361 S1); every write passes
``device_kind`` explicitly.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from core_common.protocol.device_kind import OVERHEAD_CAMERA

from .enrollment_store import (
    append_device_pairing_audit,
    device_pairing_audit_rows,
    ensure_device_pairing_audit,
)
from .sqlite_policy import configure_connection, enable_wal

AUDIT_LIMIT = 10_000
STATES = ("pending_confirm", "active", "revoked")
_COLUMNS = ("credential_id", "device_kind", "source_id", "token_sha256", "state", "device_label",
            "principal_id", "created_at", "confirmed_at", "revoked_at", "revoked_by",
            "revoke_reason", "expires_at")


class PairingStore:
    """``device_credentials`` plus the shared audit table, in the Fleet database."""

    def __init__(self, path: Path | str, *, audit_limit: int = AUDIT_LIMIT,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_limit = audit_limit
        self._clock = clock
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS device_credentials (
                    credential_id TEXT PRIMARY KEY,
                    device_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    token_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN {STATES!r}),
                    device_label TEXT,
                    principal_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    confirmed_at REAL,
                    revoked_at REAL,
                    revoked_by TEXT,
                    revoke_reason TEXT,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS device_credentials_source
                    ON device_credentials(device_kind, source_id, state);
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

    def insert_pending(self, *, credential_id: str, source_id: str, token_sha256: str,
                       device_label: str, principal_id: str, expires_at: float) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO device_credentials(credential_id, device_kind, source_id, "
                    "token_sha256, state, device_label, principal_id, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, 'pending_confirm', ?, ?, ?, ?)",
                    (credential_id, OVERHEAD_CAMERA, source_id, token_sha256, device_label,
                     principal_id, self._clock(), expires_at))

    def activate(self, credential_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE device_credentials SET state='active', confirmed_at=? "
                "WHERE credential_id=? AND state='pending_confirm'",
                (self._clock(), credential_id))
        return cursor.rowcount == 1

    def revoke(self, credential_id: str, *, principal_id: str | None, reason: str) -> bool:
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE device_credentials SET state='revoked', revoked_at=?, revoked_by=?, "
                    "revoke_reason=? WHERE credential_id=? AND state != 'revoked'",
                    (self._clock(), principal_id, reason, credential_id))
        return cursor.rowcount == 1

    def revoke_all_pending(self, *, reason: str) -> list[str]:
        """Approvals never confirmed before a restart lose their in-memory request (D-341 8)."""
        with closing(self._connect()) as connection:
            with connection:
                ids = [row[0] for row in connection.execute(
                    "SELECT credential_id FROM device_credentials WHERE state='pending_confirm'")]
                connection.execute(
                    "UPDATE device_credentials SET state='revoked', revoked_at=?, "
                    "revoke_reason=? WHERE state='pending_confirm'", (self._clock(), reason))
        return ids

    def credential_rows(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM device_credentials "
                "ORDER BY created_at, credential_id").fetchall()
        return [dict(row) for row in rows]

    def get(self, credential_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM device_credentials WHERE credential_id=?",
                (credential_id,)).fetchone()
        return dict(row) if row is not None else None

    def audit(self, *, action: str, outcome: str, principal_id: str | None,
              target: str | None, device_kind: str) -> None:
        with closing(self._connect()) as connection, connection:
            append_device_pairing_audit(
                connection, at=self._clock(), device_kind=device_kind, action=action,
                outcome=outcome, principal_id=principal_id, target=target,
                limit=self._audit_limit)

    def audit_rows(self) -> list[dict]:
        with closing(self._connect()) as connection:
            return device_pairing_audit_rows(connection)
