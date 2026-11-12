"""D-341 ``rosy-pair/1`` server state: in-memory requests, one-time delivery, mutual confirm.

Requests live only in memory (D-341 8): a Fleet restart forgets them and the phone asks
again. ``server_nonce`` lives until the phone reveals its nonce; after that only an HMAC
of the code under a key made fresh at every start is kept. A credential becomes active
only when the phone confirms within 120 s of approval; SQLite holds its digest only.

Limits are site wide, never per remote address (D-341 7): 300 s pending lifetime,
16 live requests, 30 requests per minute, one poll per request every 2 s, 4 KiB bodies.
A limit answers 429 and never pushes out an existing request.
"""

from __future__ import annotations

import hmac
import json
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

from core_common.protocol import discovery_txt, pairing, site_link
from core_common.protocol.device_kind import OVERHEAD_CAMERA
from fleet.server.pairing_helpers import (
    CLOSED_RETENTION_S,
    CODE_ATTEMPTS,
    CONFIRM_DEADLINE_S,
    CREDENTIAL_LIFETIME_S,
    MAX_LIVE_REQUESTS,
    MAX_REQUESTS_PER_MINUTE,
    PENDING_LIFETIME_S,
    POLL_INTERVAL_S,
    PairingError,
    PairingStateMixin,
    _CLOSED,
    _LIVE,
    _Request,
    _iso,
    _locked,
)

from .pairing_store import PairingStore

__all__ = [
    "CLOSED_RETENTION_S",
    "CODE_ATTEMPTS",
    "CONFIRM_DEADLINE_S",
    "CREDENTIAL_LIFETIME_S",
    "MAX_LIVE_REQUESTS",
    "MAX_REQUESTS_PER_MINUTE",
    "PENDING_LIFETIME_S",
    "POLL_INTERVAL_S",
    "PairingError",
    "PairingService",
    "PairingStateMixin",
    "_CLOSED",
    "_LIVE",
    "_Request",
    "_iso",
    "_locked",
]


class PairingService(PairingStateMixin):
    """The only Fleet write path without a site credential; side effects are bounded memory."""

    def __init__(self, store: PairingStore, *, leaf_cert_sha256: str, site_ca_pem: str,
                 tls_host: str, site_name: str, sources: Mapping[str, str],
                 monotonic: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 credential_lifetime_s: float = CREDENTIAL_LIFETIME_S,
                 served_leaf_pem: str | None = None) -> None:
        if not isinstance(leaf_cert_sha256, str) or not pairing.SHA256_HEX.fullmatch(leaf_cert_sha256):
            raise ValueError("pairing needs the served leaf certificate's DER SHA-256")
        reason = site_link._ca_pem_reason(site_ca_pem)
        if reason is not None:
            raise ValueError(f"pairing site CA must be a CA certificate, never a leaf ({reason})")
        if not isinstance(tls_host, str) or not discovery_txt.HOSTNAME.fullmatch(tls_host):
            raise ValueError("pairing tls_host must be an mDNS .local host name")
        if not isinstance(site_name, str) or not site_name.strip():
            raise ValueError("pairing site name is required")
        if any(kind not in ("static", "paired") for kind in sources.values()):
            raise ValueError("source credential kind must be static or paired")
        if not math.isfinite(credential_lifetime_s) or credential_lifetime_s <= 0:
            raise ValueError("credential lifetime must be positive")
        self.store = store
        self.served_leaf_pem = served_leaf_pem
        self.peer_credential_allowed = None
        self.peer_source_owned = None
        self.leaf_cert_sha256 = leaf_cert_sha256
        self.site_ca_pem = site_ca_pem
        self.site_ca_fingerprint = pairing.site_fingerprint(site_ca_pem)
        self.tls_host = tls_host
        self.site_name = site_name.strip()
        self.sources = dict(sources)
        self._monotonic = monotonic
        self._wall = wall
        self._lifetime_s = credential_lifetime_s
        self._code_key = secrets.token_bytes(32)  # fresh at every start (D-341 8)
        self._requests: dict[str, _Request] = {}
        self._recent: deque[float] = deque()
        self._unauthenticated_requests = 0
        self._refused_requests = 0
        self._commit_mismatches = 0
        self._lock = threading.RLock()
        for credential_id in store.revoke_all_pending(reason="fleet_restart"):
            store.audit(action="expire", outcome="revoked_on_restart", principal_id=None,
                        target=credential_id, device_kind=OVERHEAD_CAMERA)

    @property
    def paired_source_ids(self) -> list[str]:
        return [source for source, kind in self.sources.items() if kind == "paired"]

    # -- phone ------------------------------------------------------------

    @_locked
    def create(self, raw: bytes) -> dict:
        reason = pairing.validate_request_bytes(raw)
        if reason is not None:
            raise PairingError(400, "PAIRING_REQUEST_INVALID", "pairing request refused",
                               reason=reason)
        body = json.loads(raw.decode("utf-8"))
        self.sweep()
        now = self._monotonic()
        if len(self._recent) >= MAX_REQUESTS_PER_MINUTE:
            self._refused_requests += 1
            wait = max(1, math.ceil(60.0 - (now - self._recent[0])))
            raise PairingError(429, "PAIRING_RATE_LIMITED", "too many pairing requests on this site",
                               retry_after=wait)
        if sum(entry.state in _LIVE for entry in self._requests.values()) >= MAX_LIVE_REQUESTS:
            self._refused_requests += 1
            raise PairingError(429, "PAIRING_PENDING_FULL", "too many pending pairing requests",
                               retry_after=10)
        request_id = "pr-" + secrets.token_urlsafe(12)
        server_nonce = pairing.new_secret()
        entry = _Request(request_id=request_id, device_label=body["device_label"].strip(),
                         app_version=body["app_version"], poll_sha256=body["poll_secret_sha256"],
                         created=now, created_wall=self._wall(),
                         client_commit=body["client_commit"], server_nonce=server_nonce)
        self._requests[request_id] = entry
        self._recent.append(now)
        # Unauthenticated events are counted in memory, never written to the audit
        # table: anonymous requests must not be able to evict operator rows.
        self._unauthenticated_requests += 1
        return {"request_id": request_id, "server_nonce": server_nonce,
                "expires_at": _iso(entry.created_wall + PENDING_LIFETIME_S)}

    @_locked
    def reveal(self, request_id: str, authorization: str | None, raw: bytes) -> dict:
        reason = pairing.validate_reveal_bytes(raw)
        if reason is not None:
            raise PairingError(400, "PAIRING_REVEAL_INVALID", "reveal refused", reason=reason)
        entry = self._phone_entry(request_id, authorization)
        if entry.state in _CLOSED:
            raise PairingError(410, "PAIRING_REQUEST_CLOSED", f"pairing request is {entry.state}")
        if entry.state != "pending":
            raise PairingError(409, "ALREADY_REVEALED", "client nonce was already revealed")
        client_nonce = json.loads(raw.decode("utf-8"))["client_nonce"]
        if not hmac.compare_digest(pairing.commit(client_nonce), entry.client_commit):
            self._close(entry, "rejected", self._monotonic())
            self._commit_mismatches += 1
            raise PairingError(400, "COMMIT_MISMATCH", "revealed nonce does not match the commit")
        code = pairing.confirmation_code(role=pairing.ROLE, request_id=request_id,
                                         leaf_cert_sha256=self.leaf_cert_sha256,
                                         client_nonce=client_nonce, server_nonce=entry.server_nonce)
        entry.code_mac = self._code_mac(code)
        entry.server_nonce = None
        entry.client_commit = None
        entry.state = "revealed"
        return {"state": "revealed"}

    @_locked
    def poll(self, request_id: str, authorization: str | None) -> dict:
        entry = self._phone_entry(request_id, authorization)
        now = self._monotonic()
        if entry.last_poll is not None and now - entry.last_poll < POLL_INTERVAL_S:
            raise PairingError(429, "POLL_TOO_FAST", "poll at most every 2 s",
                               retry_after=math.ceil(POLL_INTERVAL_S))
        entry.last_poll = now
        if entry.state in ("delivered", "confirmed"):
            raise PairingError(410, "PAIRING_RESULT_GONE", "the result was already delivered")
        if entry.state != "approved":
            return {"state": entry.state}
        result = {
            "proto": pairing.PROTO, "role": pairing.ROLE, "site_name": self.site_name,
            "source_id": entry.source_id, "tls_host": self.tls_host,
            "site_ca_pem": self.site_ca_pem, "token": entry.token,
            "credential_id": entry.credential_id, "expires_at": entry.expires_at,
        }
        entry.token = None  # one delivery only; the server keeps the digest
        entry.state = "delivered"
        return {"state": "approved", "result": result}

    @_locked
    def confirm(self, request_id: str, authorization: str | None, credential_id: str) -> dict:
        entry = self._phone_entry(request_id, authorization)
        if entry.state == "confirmed" and self._repeat_confirm(entry, credential_id):
            # The phone lost the first reply: answer the same 200 so it can tell the
            # credential is live instead of discarding it (rosy-84 client review).
            return {"state": "confirmed", "credential_id": credential_id}
        if entry.state in _CLOSED:
            raise PairingError(410, "PAIRING_REQUEST_CLOSED", f"pairing request is {entry.state}")
        if entry.state != "delivered":
            raise PairingError(409, "NOT_DELIVERED", "the result has not been collected")
        if not hmac.compare_digest(credential_id.encode(), entry.credential_id.encode()):
            raise PairingError(409, "CREDENTIAL_MISMATCH", "credential id does not match")
        if not self.store.activate(entry.credential_id, replaces=entry.replaces):
            self._close(entry, "rejected", self._monotonic())
            if entry.replaces is not None:
                # The new credential was rolled back to pending: do not leave it dangling.
                self.store.revoke(entry.credential_id, principal_id=None, reason="replace_target_changed")
                self.store.audit(action="replace", outcome="target_changed", principal_id=None,
                                 target=entry.replaces, device_kind=OVERHEAD_CAMERA)
                raise PairingError(409, "REPLACE_TARGET_CHANGED",
                                   "the credential being replaced changed; ask the operator to approve again")
            raise PairingError(410, "PAIRING_REQUEST_CLOSED", "credential is no longer pending")
        self.store.audit(action="confirm", outcome="active", principal_id=None,
                         target=entry.credential_id, device_kind=OVERHEAD_CAMERA)
        if entry.replaces is not None:
            self.store.audit(action="replace", outcome="revoked", principal_id=None,
                             target=entry.replaces, device_kind=OVERHEAD_CAMERA)
        self._close(entry, "confirmed", self._monotonic())
        return {"state": "confirmed", "credential_id": credential_id}

    # -- console ----------------------------------------------------------

    @_locked
    def approve(self, request_id: str, *, code: str, source_id: str, principal_id: str,
                replace_credential_id: str | None = None) -> dict:
        entry = self._entry(request_id)
        if entry.state in _CLOSED:
            raise PairingError(410, "PAIRING_REQUEST_CLOSED", f"pairing request is {entry.state}")
        if entry.state == "pending":
            raise PairingError(409, "NOT_REVEALED", "the phone has not shown its code yet")
        if entry.state != "revealed":
            raise PairingError(409, "ALREADY_APPROVED", "pairing request is already approved")
        kind = self.sources.get(source_id)
        if kind is None:
            raise PairingError(404, "UNKNOWN_SOURCE", "no such camera source")
        if kind != "paired":
            raise PairingError(409, "SOURCE_NOT_PAIRED",
                               "static sources use their configured token, not pairing")
        self._check_replace(source_id, replace_credential_id)
        supplied = code if isinstance(code, str) and pairing.CODE_PATTERN.fullmatch(code) else ""
        if not hmac.compare_digest(self._code_mac(supplied), entry.code_mac):
            entry.attempts_left -= 1
            closed = entry.attempts_left <= 0
            self.store.audit(action="approve", outcome="closed" if closed else "code_mismatch",
                             principal_id=principal_id, target=request_id,
                             device_kind=OVERHEAD_CAMERA)
            if closed:
                self._close(entry, "rejected", self._monotonic())
            raise PairingError(409, "CODE_MISMATCH", "code does not match the phone",
                               attempts_left=max(entry.attempts_left, 0))
        token = pairing.new_secret()
        credential_id = "cred-" + secrets.token_hex(6)
        expires_wall = self._wall() + self._lifetime_s
        self.store.insert_pending(credential_id=credential_id, source_id=source_id,
                                  token_sha256=pairing.sha256_text(token),
                                  device_label=entry.device_label, principal_id=principal_id,
                                  expires_at=expires_wall)
        self.store.audit(action="approve", outcome="approved", principal_id=principal_id,
                         target=credential_id, device_kind=OVERHEAD_CAMERA)
        entry.replaces = replace_credential_id
        entry.state = "approved"
        entry.approved_at = self._monotonic()
        entry.code_mac = None
        entry.credential_id = credential_id
        entry.source_id = source_id
        entry.token = token
        entry.expires_at = _iso(expires_wall)
        return {"request_id": request_id, "credential_id": credential_id, "source_id": source_id,
                "replaces": replace_credential_id,
                "site_ca_fingerprint": self.site_ca_fingerprint, "expires_at": entry.expires_at,
                "confirm_within_s": int(CONFIRM_DEADLINE_S)}

    @_locked
    def reject(self, request_id: str, *, principal_id: str) -> dict:
        entry = self._entry(request_id)
        if entry.state in _CLOSED:
            raise PairingError(410, "PAIRING_REQUEST_CLOSED", f"pairing request is {entry.state}")
        if entry.state not in ("pending", "revealed"):
            raise PairingError(409, "ALREADY_APPROVED", "revoke the credential instead")
        self._close(entry, "rejected", self._monotonic())
        self.store.audit(action="reject", outcome="rejected", principal_id=principal_id,
                         target=request_id, device_kind=OVERHEAD_CAMERA)
        return {"request_id": request_id, "state": "rejected"}

    @_locked
    def revoke(self, credential_id: str, *, principal_id: str) -> dict:
        self.sweep()
        row = self.store.get(credential_id)
        if row is None:
            raise PairingError(404, "UNKNOWN_CREDENTIAL", "no such credential")
        if not self.store.revoke(credential_id, principal_id=principal_id, reason="operator"):
            raise PairingError(409, "ALREADY_REVOKED", "credential is already revoked")
        self.store.audit(action="revoke", outcome="revoked", principal_id=principal_id,
                         target=credential_id, device_kind=OVERHEAD_CAMERA)
        for entry in self._requests.values():
            if entry.credential_id == credential_id and entry.state in _LIVE:
                self._close(entry, "rejected", self._monotonic())
        return {"credential_id": credential_id, "state": "revoked"}

    @_locked
    def pending_listing(self) -> dict:
        self.sweep()
        now = self._monotonic()
        rows = [{
            "request_id": entry.request_id, "device_label": entry.device_label,
            "app_version": entry.app_version, "state": entry.state,
            "requested_at": _iso(entry.created_wall),
            "expires_in_s": max(0, math.ceil(PENDING_LIFETIME_S - (now - entry.created))),
            "attempts_left": entry.attempts_left,
        } for entry in self._requests.values() if entry.state in ("pending", "revealed")]
        return {
            "requests": rows,
            "paired_sources": [self._source_listing(source) for source in self.paired_source_ids],
            "site_ca_fingerprint": self.site_ca_fingerprint,
            "unauthenticated_requests": self._unauthenticated_requests,
            "refused_requests": self._refused_requests,
            "commit_mismatches": self._commit_mismatches,
        }

    @_locked
    def credentials_summary(self) -> dict:
        self.sweep()
        wall = self._wall()
        return {"credentials": [{
            "credential_id": row["credential_id"], "source_id": row["source_id"],
            "state": row["state"], "device_label": row["device_label"],
            "approved_by": row["principal_id"], "approved_at": _iso(row["created_at"]),
            "confirmed_at": _iso(row["confirmed_at"]) if row["confirmed_at"] else None,
            "expires_at": _iso(row["expires_at"]), "expired": row["expires_at"] <= wall,
            **({'relationship_id': row['peer_relationship_id']} if row.get('peer_relationship_id') else {}),
        } for row in self.store.credential_rows()],
            "site_ca_fingerprint": self.site_ca_fingerprint}

    # -- Vision -----------------------------------------------------------

    @_locked
    def sync_listing(self) -> list[dict]:
        """Active, unexpired credentials as digests only (D-341 12)."""
        self.sweep()
        wall = self._wall()
        return [{"credential_id": row["credential_id"], "source_id": row["source_id"],
                 "token_sha256": row["token_sha256"], "expires_at": _iso(row["expires_at"])}
                for row in self.store.credential_rows()
                if row["state"] == "active" and row["expires_at"] > wall
                and (not (row.get('peer_relationship_id') is not None or row.get('peer_generation') is not None
                          or row['credential_id'].startswith('cam-peer-'))
                     or (self.peer_credential_allowed is not None and self.peer_credential_allowed(row)))]
