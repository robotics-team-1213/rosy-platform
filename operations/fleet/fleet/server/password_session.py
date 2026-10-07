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

from fastapi import Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from fleet.server.development_session import NO_STORE, client_address
from fleet.server.site_auth import SitePrincipal
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
_SCRYPT_WAIT_S = 5.0
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


class PasswordSessions:
    def __init__(self, path: Path | str, logins: Mapping[str, Mapping[str, str]], *,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        # D-519 3: the site-users snapshot loaded at startup; account changes apply on restart.
        self._logins = dict(logins)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._limit_audited: dict[str, float] = {}
        # digest -> session row plus "validated_at": recent cookies authenticate without the DB.
        self._cache: OrderedDict[str, dict] = OrderedDict()
        # Unknown logins still pay one scrypt so the 401 does not reveal which accounts exist.
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))
        with closing(self._connect(timeout=10)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_sessions (
                session_sha256 TEXT PRIMARY KEY, login TEXT NOT NULL,
                principal_id TEXT NOT NULL, role TEXT NOT NULL, password_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL, last_used_at REAL NOT NULL, remember INTEGER NOT NULL)""")

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
            account = self._logins.get(login) if valid else None
            ok = verify_password(password, account["password_scrypt"] if account else self._dummy_hash)
        finally:
            _SCRYPT_SLOTS.release()
        if ok and account is not None:
            self._refund(keys, now)
            return SitePrincipal(account["principal_id"], account["role"])
        return None

    def _refund(self, keys, stamp: float) -> None:
        with self._lock:
            for key in keys:
                hits = self._failures.get(key)
                if hits is not None and stamp in hits:
                    hits.remove(stamp)

    def issue(self, login: str, *, remember: bool) -> str:
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

    def _remember(self, key: str, row: Mapping, validated_at: float) -> None:
        with self._lock:
            self._cache[key] = {**row, "validated_at": validated_at}
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)

    def _forget(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

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
        key = _digest(value)
        now = self._clock()
        with self._lock:
            cached = dict(self._cache[key]) if key in self._cache else None
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
        return SitePrincipal(cached["principal_id"], cached["role"]), _iso(self._expiry(cached, now))

    def revoke(self, value: str) -> None:
        key = _digest(value)
        self._forget(key)
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


def _set_cookie(response: Response, value: str, *, remember: bool) -> None:
    response.set_cookie(COOKIE, value, max_age=int(REMEMBER_S) if remember else None,
                        path="/", secure=True, httponly=True, samesite="strict")


def _begin_audit(request: Request, task_service, principal: SitePrincipal) -> None:
    request.state.site_api_audit_id = task_service.store.begin_api_audit(
        principal_id=principal.principal_id, role=principal.role,
        method=request.method, path=request.url.path)


def install_password_routes(app, *, sessions: Optional[PasswordSessions], authorize, task_service,
                            trust_forwarded: bool) -> None:
    @app.get("/api/fleet/auth/session", tags=["fleet-auth"])
    def fleet_auth_session(request: Request, principal: SitePrincipal = Depends(authorize)) -> JSONResponse:
        return JSONResponse(headers=NO_STORE, content={
            "principal_id": principal.principal_id, "role": principal.role,
            "via": getattr(request.state, "site_auth_via", "bearer"),
            "expires_at": getattr(request.state, "site_auth_expires_at", None),
        })

    if sessions is None:
        return  # D-519: no login entries -> no login/logout routes, so both are 404

    @app.post("/api/fleet/auth/login", status_code=204, tags=["fleet-auth"])
    def fleet_auth_login(request: Request, payload: dict = Body(...)) -> Response:
        login, password, remember = payload.get("login"), payload.get("password"), payload.get("remember", False)
        if (not isinstance(login, str) or not isinstance(password, str) or len(password) > 1024
                or not isinstance(remember, bool)):
            raise HTTPException(status_code=422, detail={
                "code": "INVALID_REQUEST", "message": "login, password and remember are required"})
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "login must come from this console"})
        address = client_address(request, trust_forwarded=trust_forwarded)
        attempted = SitePrincipal(f"login:{login if _LOGIN.fullmatch(login) else '?'}", "viewer")
        try:
            principal = sessions.check(address, login, password)
        except LoginRateLimited:
            if sessions.audit_limit(address):
                try:
                    _begin_audit(request, task_service, attempted)
                except (OSError, sqlite3.Error, ValueError):
                    pass  # the 429 stands either way
            raise HTTPException(status_code=429, headers={"Retry-After": "60"}, detail={
                "code": "RATE_LIMITED", "message": "too many failed logins; wait a minute"}) from None
        try:
            # D-519 2: success under the principal, failure as login:<name>; the middleware closes it.
            _begin_audit(request, task_service, principal or attempted)
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(status_code=503, detail={
                "code": "AUDIT_STORAGE_UNAVAILABLE", "message": "site command audit is unavailable",
            }) from None
        if principal is None:
            raise HTTPException(status_code=401, detail={
                "code": "LOGIN_FAILED", "message": "login or password is incorrect"})
        try:
            value = sessions.issue(login, remember=remember)
        except SessionStorageUnavailable:
            raise _storage_unavailable() from None
        response = Response(status_code=204, headers=NO_STORE)
        _set_cookie(response, value, remember=remember)
        return response

    @app.post("/api/fleet/auth/logout", status_code=204, tags=["fleet-auth"])
    def fleet_auth_logout(request: Request) -> Response:
        value = request.cookies.get(COOKIE)
        if value and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "cookie requests must come from this console"})
        if value:
            try:
                sessions.revoke(value)
            except SessionStorageUnavailable:
                raise _storage_unavailable() from None
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
