"""D-519 관제 콘솔 아이디·비밀번호 로그인 — HttpOnly 세션 쿠키, 세션은 tasks DB 에 해시로 둔다.

계정은 `site-users.yaml` 의 login 항목(`site_users.load_site_accounts`)이다. 쿠키 값은 응답에만
있고 DB 에는 SHA-256 만 남는다. 확인할 때마다 계정의 principal·role·비밀번호 지문을 다시 본다.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from fleet.server.site_auth import SitePrincipal, legacy_grants
from fleet.server.site_users import _LOGIN, hash_password, verify_password

COOKIE = "rosy_fleet_session"
IDLE_S = 12 * 3600.0
REMEMBER_S = 30 * 86400.0
ABSOLUTE_S = 30 * 86400.0
ADDRESS_FAILURES_PER_MINUTE = 5
LOGIN_FAILURES_PER_MINUTE = 10
_RATE_WINDOW_S = 60.0
_TOUCH_EVERY_S = 60.0  # sliding-expiry writes at most once a minute per session, not per poll
_MAX_TRACKED = 1024
_AUTH_DB_TIMEOUT_S = 1.0  # an auth read never waits out a long writer
_CACHE_S = 60.0  # a cookie validated this recently authenticates from memory
_CACHE_MAX = 256
_SCRYPT_WAIT_S = 1.0
#: Each scrypt holds about 33 MiB; at most two run at once.
_SCRYPT_SLOTS = threading.BoundedSemaphore(2)


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def same_origin(request: Request) -> bool:
    """D-519 4: an `Origin` must be present and its authority must equal `Host`."""
    origin, host = request.headers.get("origin"), request.headers.get("host")
    if not origin or not host:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host.lower()


class SessionStorageUnavailable(Exception):
    """The sessions table could not be read or written."""


class LoginRateLimited(Exception):
    """Too many failed logins, or too many password checks already running."""


class StalePasswordCheck(Exception):
    """The credential changed after verification, or this is not an initial session."""


class CurrentPasswordIncorrect(Exception):
    """The valid session remains usable after an incorrect current password."""


class PasswordSessions:
    def __init__(self, path: Path | str, logins: Mapping[str, Mapping[str, str]], *,
                 clock: Callable[[], float] = time.time, accounts_bootstrap=None) -> None:
        self.path = Path(path)
        # D-519 3: the site-users snapshot loaded at startup; account changes apply on restart.
        self._logins = {login: dict(account) for login, account in logins.items()}
        self._sources = {login: _digest("\0".join(account[key] for key in
                         ("principal_id", "role", "password_scrypt"))) for login, account in logins.items()}
        self._clock = clock
        self._lock = threading.RLock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._limit_audited: dict[str, float] = {}
        # digest -> session row plus "validated_at": recent cookies authenticate without the DB.
        self._cache: OrderedDict[str, dict] = OrderedDict()
        # digest -> revoked_at: a request already past its snapshot cannot re-cache a logged-out cookie.
        self._revoked: dict[str, float] = {}
        # Unknown logins still pay one scrypt so the 401 does not reveal which accounts exist.
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))
        from fleet.server.account_ledger import AccountLedger
        self._ledger = AccountLedger(self)
        with closing(self._connect(timeout=10)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_sessions (
                session_sha256 TEXT PRIMARY KEY, login TEXT NOT NULL,
                principal_id TEXT NOT NULL, role TEXT NOT NULL, password_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL, last_used_at REAL NOT NULL, remember INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_passwords (
                login TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, password_scrypt TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_profiles (
                login TEXT PRIMARY KEY, principal_id TEXT NOT NULL, display_name TEXT NOT NULL)""")
            if accounts_bootstrap is not None and not self._ledger.active:
                self.bootstrap_accounts(*accounts_bootstrap)
            if self._ledger.active:
                self._required = {}
                return
            for row in db.execute("SELECT * FROM fleet_console_passwords").fetchall():
                if self._sources.get(row["login"]) == row["source_sha256"]:
                    self._logins[row["login"]]["password_scrypt"] = row["password_scrypt"]
                else:
                    # Source rotation invalidates sessions even if YAML now contains the effective hash.
                    db.execute("DELETE FROM fleet_console_sessions WHERE login = ?", (row["login"],))
                    db.execute("DELETE FROM fleet_console_passwords WHERE login = ?", (row["login"],))
        self._required = {login: (verify_password(login, account["password_scrypt"])
                                 or verify_password(login + "!", account["password_scrypt"]))
                          for login, account in self._logins.items()}

    def bootstrap_accounts(self, admin_login: str, site_id: str) -> None:
        self._ledger.bootstrap(admin_login, site_id)

    def account_context(self, value: str):
        self._refresh_authority()
        return self._ledger.context(value) if self._ledger.active else None

    def context_by_family(self, family: str, *, db=None):
        self._refresh_authority()
        return self._ledger.context(family=family, db=db) if self._ledger.active else None

    def _refresh_authority(self):
        if self._ledger.active or not self.path.is_file():
            return
        try:
            with closing(sqlite3.connect(self.path, timeout=_AUTH_DB_TIMEOUT_S)) as db:
                row = db.execute("SELECT site_id FROM rosy_account_authority WHERE singleton=1").fetchone()
            if row:
                self._ledger.site_id = row[0]
                self._cache.clear()
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None

    def revoke_family(self, family: str, *, db=None) -> None:
        self._ledger.revoke_family(family, db=db)

    @staticmethod
    def accounts_active(path) -> bool:
        if not Path(path).is_file():
            return False
        try:
            with closing(sqlite3.connect(path, timeout=_AUTH_DB_TIMEOUT_S)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='rosy_account_authority'").fetchone():
                    return False
                return db.execute("SELECT 1 FROM rosy_account_authority WHERE singleton=1").fetchone() is not None
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None

    def list_accounts(self, value: str):
        return self._ledger.list_accounts(value)

    def list_account_audit(self, value: str):
        return self._ledger.list_audit(value)

    def _authority_site(self, db):
        row = db.execute("SELECT site_id FROM rosy_account_authority WHERE singleton=1").fetchone()
        return row[0] if row else self._ledger.site_id

    def migrated_principal(self, principal_id: str, *, db=None) -> bool:
        if db is None:
            self._refresh_authority()
            with self._ledger.db() as current:
                return self.migrated_principal(principal_id, db=current)
        if self._authority_site(db) is not None:
            return db.execute("SELECT 1 FROM rosy_accounts WHERE principal_id=?", (principal_id,)).fetchone() is not None
        return False

    def principal_by_id(self, principal_id: str, *, db=None):
        if db is None:
            with self._ledger.db() as current:
                return self.principal_by_id(principal_id, db=current)
        site_id = self._authority_site(db)
        if site_id is not None:
            row = db.execute("SELECT * FROM rosy_accounts WHERE principal_id=? AND enabled=1",
                             (principal_id,)).fetchone()
            return self._ledger.principal_for(row, site_id=site_id) if row else None
        for login, account in self._logins.items():
            if account["principal_id"] == principal_id:
                return SitePrincipal(principal_id, account["role"], self._required[login], grants=legacy_grants(account))
        return None

    def create_account(self, value: str, **fields):
        return self._ledger.create(value, **fields)

    def update_account(self, value: str, account_id: str, *, revision: int, **changes):
        return self._ledger.mutate(value, account_id, revision, changes)

    def reset_account_password(self, value: str, account_id: str, *, revision: int, password: str):
        return self._ledger.reset_password(value, account_id, revision, password)

    def revoke_account_sessions(self, value: str, account_id: str, *, revision: int):
        return self._ledger.mutate(value, account_id, revision, {}, operation="revoke")

    def _connect(self, *, timeout: float = _AUTH_DB_TIMEOUT_S) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=timeout)
        db.row_factory = sqlite3.Row
        return db

    def _hits(self, key: tuple[str, str], now: float) -> deque[float]:
        if len(self._failures) > _MAX_TRACKED:
            # ponytail: drop idle keys only; a site has far fewer than 1024 browsers and accounts.
            for stale in [k for k, hits in self._failures.items()
                          if not hits or now - hits[-1] >= _RATE_WINDOW_S]:
                del self._failures[stale]
        hits = self._failures.setdefault(key, deque())
        while hits and now - hits[0] >= _RATE_WINDOW_S:
            hits.popleft()
        return hits

    def audit_limit(self, address: str) -> bool:
        """True at most once per address per window, so a 429 flood leaves one audit row."""
        now = self._clock()
        with self._lock:
            if len(self._limit_audited) > _MAX_TRACKED:
                self._limit_audited = {k: t for k, t in self._limit_audited.items()
                                       if now - t < _RATE_WINDOW_S}
            if now - self._limit_audited.get(address, now - _RATE_WINDOW_S) < _RATE_WINDOW_S:
                return False
            self._limit_audited[address] = now
            return True

    def check(self, address: str, login: str, password: str) -> Optional[SitePrincipal]:
        """The account for a correct password, else None; raises LoginRateLimited.

        The failure slot is reserved under the lock before scrypt runs and refunded on success,
        so concurrent attempts cannot all pass the count. A login outside the login pattern is
        refused like a wrong password and never becomes a per-login rate key.
        """
        self._refresh_authority()
        valid = bool(_LOGIN.fullmatch(login))
        keys = [("address", address)] + ([("login", login)] if valid else [])
        now = self._clock()
        with self._lock:
            if (len(self._hits(keys[0], now)) >= ADDRESS_FAILURES_PER_MINUTE
                    or (valid and len(self._hits(keys[1], now)) >= LOGIN_FAILURES_PER_MINUTE)):
                raise LoginRateLimited()
            for key in keys:
                self._hits(key, now).append(now)
        if not _SCRYPT_SLOTS.acquire(timeout=_SCRYPT_WAIT_S):
            self._refund(keys, now)
            raise LoginRateLimited()
        try:
            account = ((self._ledger.account(login) if self._ledger.active else self._logins.get(login))
                       if valid else None)
            ok = verify_password(password, account["password_scrypt"] if account else self._dummy_hash)
        finally:
            _SCRYPT_SLOTS.release()
        if ok and account is not None:
            self._refund(keys, now)
            if self._ledger.active:
                return self._ledger.principal_for(account, fingerprint=self._ledger.credential_revision(account))
            return SitePrincipal(account["principal_id"], account["role"],
                                 self._required[login], _digest(account["password_scrypt"]),
                                 grants=legacy_grants(account))
        return None

    def _refund(self, keys, stamp: float) -> None:
        with self._lock:
            for key in keys:
                hits = self._failures.get(key)
                if hits is not None and stamp in hits:
                    hits.remove(stamp)

    def issue(self, login: str, *, remember: bool, verified: Optional[SitePrincipal] = None,
              replacing: Optional[str] = None) -> str:
        self._refresh_authority()
        if self._ledger.active:
            return self._ledger.issue(login, remember, verified, replacing)
        with self._lock:
            if (verified is not None
                    and verified.password_fingerprint != _digest(self._logins[login]["password_scrypt"])):
                raise StalePasswordCheck()
            return self._issue(login, remember=remember)

    def _issue(self, login: str, *, remember: bool) -> str:
        account = self._logins[login]
        value = secrets.token_urlsafe(32)
        now = self._clock()
        row = {"login": login, "principal_id": account["principal_id"], "role": account["role"],
               "password_sha256": _digest(account["password_scrypt"]), "created_at": now,
               "last_used_at": now, "remember": int(remember)}
        try:
            with closing(self._connect()) as db, db:
                db.execute("DELETE FROM fleet_console_sessions WHERE created_at <= ? "
                           "OR (remember = 0 AND last_used_at <= ?)", (now - ABSOLUTE_S, now - IDLE_S))
                db.execute("INSERT INTO fleet_console_sessions VALUES (?,?,?,?,?,?,?,?)", (
                    _digest(value), row["login"], row["principal_id"], row["role"],
                    row["password_sha256"], now, now, row["remember"]))
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None
        self._remember(_digest(value), row, now)
        return value

    def change_password(self, value: str, password: str, *, current_password: Optional[str] = None) -> tuple[str, bool]:
        self._refresh_authority()
        if self._ledger.active:
            return self._ledger.change_password(value, password, current_password)
        with self._lock:
            cached = self._cache.get(_digest(value))
            checked_hash = self._logins[cached["login"]]["password_scrypt"] if cached else None
        # A cold cookie is validated before taking the current credential snapshot.
        if checked_hash is None:
            if self.principal(value) is None:
                raise StalePasswordCheck()
            with self._lock:
                cached = self._cache.get(_digest(value))
                if cached is None:
                    raise StalePasswordCheck()
                checked_hash = self._logins[cached["login"]]["password_scrypt"]
        if not _SCRYPT_SLOTS.acquire(timeout=_SCRYPT_WAIT_S):
            raise LoginRateLimited()
        try:
            current_ok = current_password is None or verify_password(current_password, checked_hash)
            same_password = verify_password(password, checked_hash)
            encoded = hash_password(password)
        finally:
            _SCRYPT_SLOTS.release()
        with self._lock:
            now, key = self._clock(), _digest(value)
            replacement = secrets.token_urlsafe(32)
            try:
                with closing(self._connect()) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?", (key,)).fetchone()
                    if (row is None or self._tombstoned(key) or self._expiry(row, now) is None
                            or row["password_sha256"] != _digest(checked_hash)):
                        raise StalePasswordCheck()
                    login = row["login"]
                    if not self._required[login] and current_password is None:
                        raise ValueError("current password required")
                    if not current_ok:
                        raise CurrentPasswordIncorrect()
                    if password in (login, login + "!") or same_password or not 8 <= len(password) <= 1024:
                        raise ValueError("invalid new password")
                    db.execute("INSERT OR REPLACE INTO fleet_console_passwords VALUES (?,?,?)",
                               (login, self._sources[login], encoded))
                    db.execute("DELETE FROM fleet_console_sessions WHERE login = ?", (login,))
                    fresh = {**dict(row), "password_sha256": _digest(encoded),
                             "created_at": now, "last_used_at": now}
                    db.execute("INSERT INTO fleet_console_sessions VALUES (?,?,?,?,?,?,?,?)", (
                        _digest(replacement), login, fresh["principal_id"], fresh["role"],
                        fresh["password_sha256"], now, now, fresh["remember"]))
            except sqlite3.Error:
                raise SessionStorageUnavailable() from None
            self._logins[login] = {**self._logins[login], "password_scrypt": encoded}
            self._required[login] = False
            for cached_key in [k for k, cached in self._cache.items() if cached["login"] == login]:
                self._forget(cached_key, revoked=True)
            self._forget(key, revoked=True)
            self._remember(_digest(replacement), fresh, now)
            return replacement, bool(fresh["remember"])

    def profile(self, value: str, display_name: Optional[str] = None) -> dict:
        self._refresh_authority()
        if self._ledger.active:
            return self._ledger.profile(value, display_name)
        with self._lock:
            now, key = self._clock(), _digest(value)
            try:
                with closing(self._connect()) as db, db:
                    if display_name is not None:
                        db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?", (key,)).fetchone()
                    if row is None or self._tombstoned(key) or self._expiry(row, now) is None:
                        raise StalePasswordCheck()
                    if self._required[row["login"]]:
                        raise StalePasswordCheck()
                    login, principal = row["login"], row["principal_id"]
                    if display_name is not None:
                        db.execute("INSERT OR REPLACE INTO fleet_console_profiles VALUES (?,?,?)",
                                   (login, principal, display_name))
                    profile = db.execute("SELECT display_name FROM fleet_console_profiles "
                                         "WHERE login = ? AND principal_id = ?", (login, principal)).fetchone()
                    return {"login": login, "principal_id": principal,
                            "email": principal if principal.count("@") == 1 and all(principal.split("@")) else None,
                            "role": row["role"], "display_name": profile[0] if profile else login}
            except sqlite3.Error:
                raise SessionStorageUnavailable() from None

    def _tombstoned(self, key: str) -> bool:
        # Caller holds the lock. Tombstones outlive any cache entry that could have been in flight.
        now = self._clock()
        for stale in [k for k, at in self._revoked.items() if now - at >= _CACHE_S]:
            del self._revoked[stale]
        return key in self._revoked

    def _remember(self, key: str, row: Mapping, validated_at: float) -> None:
        with self._lock:
            if self._tombstoned(key):
                return
            self._cache[key] = {**row, "validated_at": validated_at}
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)

    def _forget(self, key: str, *, revoked: bool = False) -> None:
        with self._lock:
            self._cache.pop(key, None)
            if revoked:
                self._revoked[key] = self._clock()

    def _expiry(self, row: Mapping, now: float) -> Optional[float]:
        """The row's expiry if the account snapshot still matches and it has not lapsed."""
        account = self._logins.get(row["login"])
        window = REMEMBER_S if row["remember"] else IDLE_S
        expires = min(row["created_at"] + ABSOLUTE_S, row["last_used_at"] + window)
        if (account is None or account["principal_id"] != row["principal_id"]
                or account["role"] != row["role"]
                or _digest(account["password_scrypt"]) != row["password_sha256"] or now >= expires):
            return None
        return expires

    def _best_effort(self, sql: str, params: tuple) -> bool:
        # The sliding touch and expiry cleanup never fail authentication.
        try:
            with closing(self._connect()) as db, db:
                db.execute(sql, params)
            return True
        except sqlite3.Error:
            return False

    def principal(self, value: str, *, allow_stale: bool = False) -> Optional[tuple[SitePrincipal, str]]:
        """The live session's principal and UTC ISO expiry, sliding its idle window.

        A cookie validated within `_CACHE_S` needs no DB. Otherwise the DB decides; a DB error
        raises SessionStorageUnavailable unless `allow_stale` (e-stop) and the cache knows the cookie.
        """
        try:
            self._refresh_authority()
        except SessionStorageUnavailable:
            if not allow_stale:
                raise
        if self._ledger.active:
            return self._ledger.principal(value, allow_stale)
        key = _digest(value)
        now = self._clock()
        with self._lock:
            cached = dict(self._cache[key]) if key in self._cache else None
            if self._tombstoned(key):
                return None
        if cached is None or now - cached["validated_at"] >= _CACHE_S:
            try:
                with closing(self._connect()) as db:
                    found = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?",
                                       (key,)).fetchone()
            except sqlite3.Error:
                if not (allow_stale and cached is not None):
                    raise SessionStorageUnavailable() from None
                found = None  # e-stop on the stale cache entry; it stays stale for everything else
            else:
                if found is None:
                    self._forget(key)
                    return None
                cached = {name: found[name] for name in (
                    "login", "principal_id", "role", "password_sha256", "created_at", "last_used_at",
                    "remember")}
                cached["validated_at"] = now
        if self._expiry(cached, now) is None:
            self._forget(key)
            self._best_effort("DELETE FROM fleet_console_sessions WHERE session_sha256 = ?", (key,))
            return None
        if now - cached["last_used_at"] >= _TOUCH_EVERY_S and self._best_effort(
                "UPDATE fleet_console_sessions SET last_used_at = ? WHERE session_sha256 = ?", (now, key)):
            cached["last_used_at"] = now
        self._remember(key, cached, cached["validated_at"])
        with self._lock:
            expiry = self._expiry(cached, now)
            if self._tombstoned(key) or expiry is None:
                return None  # logged out while this request was in flight
            return SitePrincipal(cached["principal_id"], cached["role"], self._required[cached["login"]],
                                 grants=legacy_grants(self._logins.get(cached["login"], {}))), _iso(expiry)

    def revoke(self, value: str) -> None:
        key = _digest(value)
        self._forget(key, revoked=True)
        try:
            with closing(self._connect()) as db, db:
                db.execute("DELETE FROM fleet_console_sessions WHERE session_sha256 = ?", (key,))
        except sqlite3.Error:
            raise SessionStorageUnavailable() from None

    def authenticate(self, request: Request) -> Optional[SitePrincipal]:
        """Cookie authentication for `authorize`; Bearer has already been ruled out."""
        value = request.cookies.get(COOKIE)
        if not value:
            return None
        if request.method not in {"GET", "HEAD"} and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "cookie requests must come from this console"})
        try:
            found = self.principal(value, allow_stale=request.url.path == "/api/fleet/estop")
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        if found is None:
            return None
        request.state.site_auth_expires_at = found[1]
        return found[0]


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "SESSION_STORAGE_UNAVAILABLE", "message": "console session storage is unavailable"})


def install_password_routes(app, *, sessions: Optional[PasswordSessions], authorize, task_service,
                            trust_forwarded: bool) -> None:
    """Preserve the session module entry point while HTTP routes live separately."""
    from fleet.server.password_routes import install_password_routes as install

    install(app, sessions=sessions, authorize=authorize, task_service=task_service,
            trust_forwarded=trust_forwarded)
