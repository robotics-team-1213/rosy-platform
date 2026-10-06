"""Bounded receiver consent and P-256 proof; no actuator/control port."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading

from .peer_crypto import PeerIdentity, ProofDenied, fingerprint, verify
from core_common.protocol.peer_pairing import (APPROVAL_CODE_ALPHABET, APPROVAL_CODE_LENGTH, SCREEN_CODE_ISSUER,
                                               RepositoryDenied, screen_code_dated)

_log = logging.getLogger(__name__)
#: D-483 4: wrong approval codes per request before it is rejected.
APPROVAL_CODE_ATTEMPTS = 5
#: D-483 3: the hand-over file rosy-face reads (live pending requests, newest first).
DISPLAY_FILE = "approval.json"
DISPLAY_REQUESTS = 3
#: D-483 4: live pending requests overall and per source; terminal rows do not count.
#: Overall equals DISPLAY_REQUESTS so every live request is always on the LCD (review R2).
PENDING_LIMIT, SOURCE_PENDING_LIMIT = DISPLAY_REQUESTS, 2
#: Rows kept for status reads (pending + terminal); only unapproved terminal rows are evicted early.
ROW_LIMIT = 256
_UNSYNCED = object()


class Refused(ValueError):
    pass


class RateLimited(Refused):
    pass


class RoleRefused(Refused):
    pass


class WrongCode(Refused):
    def __init__(self, remaining):
        super().__init__("wrong approval code")
        self.remaining = remaining


def _code_hash(code):
    return hashlib.sha256(code.encode()).digest()


class PeerReceiver:
    def __init__(self, receiver_id, key_path, repository, clock=lambda: datetime.now(timezone.utc), anchor=None,
                 display_dir=None):
        self.receiver_id, self.repo, self.clock = receiver_id, repository, clock
        # D-483 3: None (tests, hosts without an LCD hand-over) writes no display file.
        self._display_dir = display_dir
        self._display_shown = _UNSYNCED  # L1: the first sync always writes or removes the file
        self._display_warned = False
        self._anchor = anchor or (lambda: {})
        self._lock = threading.RLock()
        grants = repository.grants()
        self._identity = PeerIdentity(key_path, [g["receiver_key_sha256"] for g in grants.values()])
        self._pending = {}
        self._rates = {}
        self._challenges = {}
        self._sync_display()  # A file a previous CORE left behind names no live request.

    def identity(self):
        return {"receiver_id": self.receiver_id, "receiver_public_key": self._identity.public_key,
                "receiver_key_sha256": self._identity.fingerprint, **self._anchor()}

    def _prune(self):
        now = self.clock()
        self._pending = {k: v for k, v in self._pending.items() if now < v["keep_until"]}
        self._challenges = {k: v for k, v in self._challenges.items() if now < v["expires"]}
        self._rates = {k: [t for t in values if (now-t).total_seconds() < 60]
                       for k, values in self._rates.items() if values and (now-values[-1]).total_seconds() < 60}
        self._sync_display()

    def _sync_display(self):
        """D-483 3: approval.json lists up to three live pending requests (newest first), or is absent.

        A newer request never hides an older one, so each requester finds the code next to its own
        display code. Called under the lock (or from __init__).
        """
        if self._display_dir is None:
            return
        live = sorted(self._live(), key=lambda row: row["created"], reverse=True)[:DISPLAY_REQUESTS]
        shown = {"requests": [{"display_code": row["display_code"], "approval_code": row["approval_code"],
                               "expires_at": row["expires"].isoformat()}
                              for row in live]} if live else None
        if shown == self._display_shown:
            return
        target = os.path.join(self._display_dir, DISPLAY_FILE)
        try:
            if shown is None:
                try:
                    os.unlink(target)
                except FileNotFoundError:
                    pass
            else:
                temporary = target + ".tmp"
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                                     0o640)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(shown, handle)
                os.chmod(temporary, 0o640)
                os.replace(temporary, target)
            self._display_shown = shown
        except OSError as exc:
            if not self._display_warned:  # The type only: never the code.
                self._display_warned = True
                _log.warning("peer approval display hand-over unavailable (%s)", type(exc).__name__)

    def _live(self, source=None):
        now = self.clock()
        return [row for row in self._pending.values() if row["state"] == "pending" and now < row["expires"]
                and (source is None or row["source"] == source)]

    def _admit_source(self, source):
        if len(self._rates.get(source, [])) >= 30 or (source not in self._rates and len(self._rates) >= 128):
            raise RateLimited("source rate limit reached")
        self._rates.setdefault(source, []).append(self.clock())

    def request(self, fields, signature, source):
        from core_common.protocol.peer_pairing import PeerRequest
        with self._lock:
            self._prune()
            self._admit_source(source)
        try:
            fields = PeerRequest(**fields).model_dump()
            if len(json.dumps(fields).encode()) > 4096:
                raise Refused("request too large")
            if fields["receiver_id"] != self.receiver_id or fields["receiver_key_sha256"] != self._identity.fingerprint:
                raise Refused("receiver identity mismatch")
            verify(fields["client_public_key"], signature, "request", fields)
        except (ValueError, ProofDenied) as exc:
            raise Refused("request proof rejected") from exc
        with self._lock:
            self._prune()
            if len(self._live()) >= PENDING_LIMIT:
                raise Refused("request limit reached")
            if len(self._live(source)) >= SOURCE_PENDING_LIMIT:
                raise Refused("source pending limit reached")
            if len(self._pending) >= ROW_LIMIT:
                # An approved row stays until keep_until (_prune) so its requester can still read the result.
                ended = sorted((k for k, v in self._pending.items() if v["state"] in ("rejected", "cancelled", "expired")),
                               key=lambda k: self._pending[k]["created"])
                if not ended:
                    raise Refused("request limit reached")
                del self._pending[ended[0]]
            if any(v["fields"]["client_public_key"] == fields["client_public_key"] and
                   v["fields"]["nonce"] == fields["nonce"] for v in self._pending.values()):
                raise Refused("request replay")
            now = self.clock()
            request_id, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            row = {"fields": fields, "secret_hash": hashlib.sha256(secret.encode()).digest(),
                   "revision": 0, "state": "pending", "expires": now+timedelta(seconds=300),
                   "keep_until": now+timedelta(seconds=600), "created": now, "source": source,
                   "display_code": ''.join(secrets.choice('23456789ABCDEFGHJKMNPQRSTUVWXYZ') for _ in range(4))}
            # D-483 2: the plaintext stays in this row for the LCD hand-over only; checks use the hash.
            row["approval_code"] = ''.join(secrets.choice(APPROVAL_CODE_ALPHABET) for _ in range(APPROVAL_CODE_LENGTH))
            row["code_hash"], row["code_failures"] = _code_hash(row["approval_code"]), 0
            self._pending[request_id] = row
            self._sync_display()
            return {"request_id": request_id, "request_secret": secret, "display_code": row["display_code"],
                    "state": "pending", "paired": False, "expires_at": row["expires"].isoformat()}

    def admit_proof(self, source):
        """Shared pre-crypto budget for anonymous identity/challenge/session calls."""
        with self._lock:
            self._prune()
            key = 'proof:' + source
            if len(self._rates.get(key, [])) >= 30 or (key not in self._rates and len(self._rates) >= 128):
                raise Refused('proof rate limit reached')
            self._rates.setdefault(key, []).append(self.clock())

    def _row(self, request_id, secret=None):
        row = self._pending.get(request_id)
        if not row or (secret is not None and not hmac.compare_digest(row["secret_hash"], hashlib.sha256(secret.encode()).digest())):
            raise Refused("request unavailable")
        if row['state'] == 'pending':
            stored = self.repo.grants().get(request_id)
            if stored is not None:
                fields = row['fields']
                if any(stored.get(key) != fields.get(key) for key in ('client_id', 'client_public_key', 'role', 'label')):
                    raise Refused('stored approval changed')
                row.update(state='approved', relationship_id=stored['id'], persistent=stored['persistent'],
                           authorization_expires_at=stored['expires_at'], generation=stored['generation'], revision=row['revision']+1)
        if self.clock() >= row["expires"] and row["state"] == "pending":
            row["state"] = "expired"
            row["revision"] += 1
        return row

    def _view(self, request_id, row):
        result = {"request_id": request_id, "state": row["state"], "revision": row["revision"],
                  "paired": False, "display_code": row["display_code"], "expires_at": row["expires"].isoformat()}
        if "relationship_id" in row:
            result["relationship_id"] = row["relationship_id"]
            result["authorization_expires_at"] = row["authorization_expires_at"]
            result["persistent"] = row["persistent"]
            result['generation'] = row['generation']
            try:
                self._grant(row['relationship_id'])
                result['authorization_available'] = True
            except Refused:
                result['authorization_available'] = False
        return result

    def status(self, request_id, secret):
        with self._lock:
            self._prune()
            row = self._row(request_id, secret)
            if row.get('last_poll') and (self.clock() - row['last_poll']).total_seconds() < 2:
                raise Refused('status polling interval is two seconds')
            row['last_poll'] = self.clock()
            return self._view(request_id, row)

    def pending(self, token_id):
        try:
            self.repo.owner(token_id)
        except RepositoryDenied as exc:
            raise Refused("receiver owner required") from exc
        with self._lock:
            self._prune()
            rows = []
            for key, row in self._pending.items():
                self._row(key)
                if row["state"] == "pending":
                    rows.append(dict(self._view(key, row), client_id=row["fields"]["client_id"],
                                     label=row["fields"]["label"], role=row["fields"]["role"],
                                     client_key_sha256=fingerprint(row["fields"]["client_public_key"])))
            return rows

    def decide(self, token_id, request_id, action, revision, persist_requested=False):
        if action not in {"approve", "reject"}:
            raise Refused("invalid decision")
        with self._lock:
            row = self._row(request_id)
            if row["state"] != "pending" or revision != row["revision"]:
                raise Refused("request changed")
            try:
                self.repo.owner(token_id)
                if action == "approve":
                    fields = row["fields"]
                    relationship = {"id": request_id, "receiver_id": self.receiver_id,
                                    "receiver_key_sha256": self._identity.fingerprint,
                                    "client_id": fields["client_id"], "client_public_key": fields["client_public_key"],
                                    "label": fields["label"], "role": fields["role"], "generation": 0,
                                    "persist_requested": persist_requested,
                                    "revoked": False, "used_challenges": [],
                                    "expires_at": (self.clock()+timedelta(hours=168)).isoformat()}
                    persisted = self.repo.approve(token_id, relationship, row['expires'])
                    row["relationship_id"] = persisted["id"]
                    row["authorization_expires_at"] = persisted["expires_at"]
                    row["persistent"] = persisted["persistent"]
                    row['generation'] = persisted['generation']
                    row["state"] = "approved"
                else:
                    row["state"] = "rejected"
                row["revision"] += 1
            except RepositoryDenied as exc:
                raise Refused("owner approval unavailable") from exc
            self._sync_display()
            return self._view(request_id, row)

    def confirm(self, request_id, secret, code, source):
        """D-483 4: the requester enters the code the robot's LCD shows; it approves like decide()."""
        with self._lock:
            self._prune()
            self._admit_source(source)
            row = self._row(request_id, secret)
            if row["state"] != "pending":
                raise Refused("request changed")
            fields = row["fields"]
            if fields["role"] not in {"viewer", "operator"}:
                raise RoleRefused("screen code approves operator at most")
            if not hmac.compare_digest(row["code_hash"], _code_hash(code)):
                row["code_failures"] += 1
                remaining = APPROVAL_CODE_ATTEMPTS - row["code_failures"]
                if remaining <= 0:
                    row["state"] = "rejected"
                    row["revision"] += 1
                    self._sync_display()
                raise WrongCode(max(remaining, 0))
            relationship = {"id": request_id, "receiver_id": self.receiver_id,
                            "receiver_key_sha256": self._identity.fingerprint,
                            "client_id": fields["client_id"], "client_public_key": fields["client_public_key"],
                            "label": fields["label"], "role": fields["role"], "generation": 0,
                            "persist_requested": False, "persistent": False,
                            "issuer_id": SCREEN_CODE_ISSUER, "issuer_source": SCREEN_CODE_ISSUER,
                            "issuer_digest": self._identity.fingerprint, "approved_by": SCREEN_CODE_ISSUER,
                            "revoked": False, "used_challenges": [], "approved_at": self.clock().isoformat(),
                            "expires_at": (self.clock()+timedelta(hours=168)).isoformat()}
            try:
                persisted = self.repo.approve_screen_code(relationship, row["expires"])
            except RepositoryDenied as exc:
                raise Refused("screen-code approval unavailable") from exc
            row.update(state="approved", relationship_id=persisted["id"], persistent=persisted["persistent"],
                       authorization_expires_at=persisted["expires_at"], generation=persisted["generation"],
                       revision=row["revision"]+1)
            self._sync_display()
            return self._view(request_id, row)

    def cancel(self, request_id, secret, source="unknown"):
        with self._lock:
            self._prune()
            self._admit_source(source)
            row = self._row(request_id, secret)
            if row["state"] != "pending":
                raise Refused("request changed")
            row["state"] = "cancelled"
            row["revision"] += 1
            self._sync_display()
            return self._view(request_id, row)

    def _grant(self, grant_id):
        grant = self.repo.grants().get(grant_id)
        if (not grant or grant["revoked"] or
                (grant["expires_at"] is not None and datetime.fromisoformat(grant["expires_at"]) <= self.clock())
                or grant["receiver_key_sha256"] != self._identity.fingerprint or grant["receiver_id"] != self.receiver_id):
            raise Refused("relationship unavailable")
        if grant["issuer_source"] == SCREEN_CODE_ISSUER:
            if not screen_code_dated(grant, self.clock()):
                raise Refused("relationship unavailable")
            return grant  # D-483 5: no issuer token; expiry, revocation and receiver key are checked above.
        try:
            issuer = self.repo.owner(grant["issuer_id"])
            if issuer["digest"] != grant["issuer_digest"] or issuer["source"] != grant["issuer_source"]:
                raise RepositoryDenied("issuer identity changed")
        except RepositoryDenied as exc:
            raise Refused("issuer unavailable") from exc
        return grant

    def challenge(self, grant_id):
        with self._lock:
            self._prune()
            grant = self._grant(grant_id)
            if len(self._challenges) >= 64:
                raise Refused("challenge limit reached")
            challenge_id = secrets.token_urlsafe(24)
            fields = {"relationship_id": grant_id, "challenge_id": challenge_id, "nonce": secrets.token_hex(32),
                      "receiver_id": self.receiver_id, "receiver_key_sha256": self._identity.fingerprint,
                      "client_id": grant["client_id"], "client_key_sha256": fingerprint(grant["client_public_key"]),
                      "role": grant["role"], "generation": grant["generation"],
                      "expires_at": (self.clock()+timedelta(seconds=60)).isoformat()}
            self._challenges[challenge_id] = {"fields": fields, "expires": self.clock()+timedelta(seconds=60)}
            return {"fields": copy.deepcopy(fields), "receiver_signature": self._identity.sign("receiver-challenge", fields)}

    def session(self, grant_id, fields, signature):
        with self._lock:
            self._prune()
            challenge = self._challenges.get(fields.get("challenge_id"))
            if not challenge or challenge["fields"] != fields or fields["relationship_id"] != grant_id:
                raise Refused("challenge unavailable")
            grant = self._grant(grant_id)
            try:
                verify(grant["client_public_key"], signature, "session-request", fields)
                result = self.repo.issue(grant_id, fields["challenge_id"], self._identity.fingerprint, grant)
            except (RepositoryDenied, ProofDenied) as exc:
                raise Refused("session rejected") from exc
            del self._challenges[fields["challenge_id"]]
            return result

    def revoke(self, token_id, grant_id):
        with self._lock:
            try:
                return self.repo.revoke(token_id, grant_id)
            except RepositoryDenied as exc:
                raise Refused("relationship revoke unavailable") from exc
