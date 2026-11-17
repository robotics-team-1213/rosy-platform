"""In-memory request model, error type, and state/listing helpers for ``rosy-pair/1`` (D-341)."""

from __future__ import annotations

import hmac
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256

from core_common.protocol import pairing
from core_common.protocol.device_kind import OVERHEAD_CAMERA

PENDING_LIFETIME_S = 300.0
CONFIRM_DEADLINE_S = 120.0
MAX_LIVE_REQUESTS = 16
MAX_REQUESTS_PER_MINUTE = 30
POLL_INTERVAL_S = 2.0
CODE_ATTEMPTS = 3
CREDENTIAL_LIFETIME_S = 180 * 86400.0
CLOSED_RETENTION_S = 300.0
_LIVE = frozenset({"pending", "revealed", "approved", "delivered"})
_CLOSED = frozenset({"rejected", "expired", "confirmed"})


class PairingError(Exception):
    """A refusal with its HTTP status; the body never carries a secret."""

    def __init__(self, status: int, code: str, message: str, *, retry_after: int | None = None,
                 **extra) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.extra = extra

    def body(self) -> dict:
        return {"code": self.code, "message": str(self), **self.extra}


@dataclass
class _Request:
    request_id: str
    device_label: str
    app_version: str
    poll_sha256: str = field(repr=False)
    created: float
    created_wall: float
    client_commit: str | None = field(repr=False)
    server_nonce: str | None = field(repr=False)
    state: str = "pending"
    closed_at: float | None = None
    last_poll: float | None = None
    attempts_left: int = CODE_ATTEMPTS
    code_mac: bytes | None = field(default=None, repr=False)
    approved_at: float | None = None
    credential_id: str | None = None
    source_id: str | None = None
    replaces: str | None = None  # D-999: revoked in the same transaction that activates this one
    token: str | None = field(default=None, repr=False)
    expires_at: str | None = None


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _locked(method):
    """Sync FastAPI routes run on a thread pool; one lock serialises the state machine."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class PairingStateMixin:
    """Housekeeping, source replacement checks, and read listings for PairingService."""

    def _close(self, entry: _Request, state: str, now: float) -> None:
        entry.state = state
        entry.closed_at = now
        entry.token = None
        entry.server_nonce = None
        entry.client_commit = None
        entry.code_mac = None

    @_locked
    def sweep(self) -> None:
        now = self._monotonic()
        for request_id, entry in list(self._requests.items()):
            if entry.state in ("pending", "revealed") and now - entry.created >= PENDING_LIFETIME_S:
                self._close(entry, "expired", now)
            elif (entry.state in ("approved", "delivered")
                  and now - entry.approved_at >= CONFIRM_DEADLINE_S):
                self.store.revoke(entry.credential_id, principal_id=None, reason="unconfirmed")
                self.store.audit(action="expire", outcome="unconfirmed", principal_id=None,
                                 target=entry.credential_id, device_kind=OVERHEAD_CAMERA)
                self._close(entry, "expired", now)
            elif entry.closed_at is not None and now - entry.closed_at >= CLOSED_RETENTION_S:
                del self._requests[request_id]
        while self._recent and now - self._recent[0] >= 60.0:
            self._recent.popleft()

    def _entry(self, request_id: str) -> _Request:
        self.sweep()
        entry = self._requests.get(request_id)
        if entry is None:
            raise PairingError(404, "UNKNOWN_PAIRING_REQUEST", "no such pairing request")
        return entry

    def _phone_entry(self, request_id: str, authorization: str | None) -> _Request:
        entry = self._entry(request_id)
        supplied = (authorization[len("Bearer "):]
                    if authorization and authorization.startswith("Bearer ") else "")
        if not hmac.compare_digest(pairing.sha256_text(supplied), entry.poll_sha256):
            raise PairingError(401, "POLL_SECRET_INVALID", "poll secret does not match")
        return entry

    def _code_mac(self, code: str) -> bytes:
        return hmac.new(self._code_key, code.encode("ascii"), sha256).digest()

    def _live_rows(self, source_id: str) -> list[dict]:
        wall = self._wall()
        return [row for row in self.store.credential_rows()
                if row["source_id"] == source_id and row["state"] in ("pending_confirm", "active")
                and row["expires_at"] > wall]

    def _peer_owned(self, source_id: str) -> bool:
        return self.peer_source_owned is not None and bool(self.peer_source_owned(source_id))

    def _source_has_credential(self, source_id: str) -> bool:
        return self._peer_owned(source_id) or bool(self._live_rows(source_id))

    def _replaceable(self, row: dict) -> bool:
        return (row["state"] == "active" and row.get("peer_relationship_id") is None
                and not row["credential_id"].startswith("cam-peer-"))

    def _check_replace(self, source_id: str, replace_credential_id: str | None) -> None:
        """Refuse unless the source is free, or is held by exactly the credential the operator named."""
        if self._peer_owned(source_id):
            raise PairingError(409, "SOURCE_HAS_CREDENTIAL",
                               "source is held by a remembered peer connection; revoke that connection")
        rows = self._live_rows(source_id)
        if replace_credential_id is None:
            if rows:
                raise PairingError(409, "SOURCE_HAS_CREDENTIAL",
                                   "source already has a credential; choose to replace it",
                                   replace_credential_id=next(
                                       (r["credential_id"] for r in rows if self._replaceable(r)), None))
            return
        if any(row["state"] == "pending_confirm" for row in rows):
            raise PairingError(409, "SOURCE_PENDING_CONFIRM",
                               "another approval for this source is waiting for its phone")
        if len(rows) != 1 or rows[0]["credential_id"] != replace_credential_id or not self._replaceable(rows[0]):
            raise PairingError(409, "REPLACE_TARGET_CHANGED",
                               "the credential to replace changed or was revoked; reload the list")

    def _repeat_confirm(self, entry: _Request, credential_id: str) -> bool:
        """Same id, still inside the confirm window, and the credential is still active."""
        if entry.credential_id is None or entry.approved_at is None:
            return False
        if not hmac.compare_digest(credential_id.encode(), entry.credential_id.encode()):
            return False
        if self._monotonic() - entry.approved_at >= CONFIRM_DEADLINE_S:
            return False
        return any(row["credential_id"] == entry.credential_id and row["state"] == "active"
                   for row in self.store.credential_rows())

    def _source_listing(self, source: str) -> dict:
        rows = self._live_rows(source)
        held = next((r for r in rows if self._replaceable(r)), None)
        return {"source_id": source,
                "has_credential": self._peer_owned(source) or bool(rows),
                "credential_id": held["credential_id"] if held else None,
                "device_label": held["device_label"] if held else None,
                "replaceable": held is not None and len(rows) == 1 and not self._peer_owned(source)}
