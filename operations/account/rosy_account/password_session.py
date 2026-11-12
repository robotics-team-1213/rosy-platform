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

from fastapi import HTTPException, Request

from core_common.protocol.account_access import same_origin
from rosy_account.db_policy import configure_connection, enable_wal
from rosy_account.password_session_helpers import (
    ABSOLUTE_S,
    ADDRESS_FAILURES_PER_MINUTE,
    COOKIE,
    IDLE_S,
    LOGIN_FAILURES_PER_MINUTE,
    REMEMBER_S,
    CurrentPasswordIncorrect,
    LoginRateLimited,
    SessionStorageUnavailable,
    StalePasswordCheck,
    _AUTH_DB_TIMEOUT_S,
    _CACHE_MAX,
    _CACHE_S,
    _MAX_TRACKED,
    _RATE_WINDOW_S,
    _SCRYPT_SLOTS,
    _SCRYPT_WAIT_S,
    _TOUCH_EVERY_S,
    _digest,
    _storage_unavailable,
    accounts_active_on_disk,
    init_legacy_session_tables,
    install_password_routes,
    resolve_legacy_principal,
    rotate_legacy_password,
)
from rosy_account.principal import SitePrincipal, legacy_grants
from rosy_account.site_users import _LOGIN, hash_password, verify_password


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


class PasswordSessions:
    def __init__(self, path: Path | str, logins: Mapping[str, Mapping[str, str]], *,
                 clock: Callable[[], float] = time.time, accounts_bootstrap=None) -> None:
        self.path = Path(path)
        self._logins = {login: dict(account) for login, account in logins.items()}
        self._sources = {login: _digest("\0".join(account[key] for key in ("principal_id", "role", "password_scrypt")))
                         for login, account in logins.items()}
        self._clock, self._lock = clock, threading.RLock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._limit_audited: dict[str, float] = {}
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._revoked: dict[str, float] = {}
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))
        from rosy_account.account_ledger import AccountLedger
        self._ledger = AccountLedger(self)
        init_legacy_session_tables(self, accounts_bootstrap, verify_password)

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
        return accounts_active_on_disk(path)

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
        return configure_connection(db)

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
        return rotate_legacy_password(self, value, password, current_password, verify_password_fn=verify_password)

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
        return resolve_legacy_principal(self, value, allow_stale, iso_fn=_iso)

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
