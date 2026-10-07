"""D-519 관제 콘솔 아이디·비밀번호 로그인 — HttpOnly 세션 쿠키, 세션은 tasks DB 에 해시로 둔다.

계정은 `site-users.yaml` 의 login 항목(`site_users.load_site_accounts`)이다. 쿠키 값은 응답에만
있고 DB 에는 SHA-256 만 남는다. 확인할 때마다 계정의 principal·role·비밀번호 지문을 다시 본다.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from collections import deque
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


class PasswordSessions:
    def __init__(self, path: Path | str, logins: Mapping[str, Mapping[str, str]], *,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._logins = dict(logins)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], deque[float]] = {}
        # Unknown logins still pay one scrypt so the 401 does not reveal which accounts exist.
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS fleet_console_sessions (
                session_sha256 TEXT PRIMARY KEY, login TEXT NOT NULL,
                principal_id TEXT NOT NULL, role TEXT NOT NULL, password_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL, last_used_at REAL NOT NULL, remember INTEGER NOT NULL)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
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

    def limited(self, address: str, login: str) -> bool:
        now = self._clock()
        with self._lock:
            return (len(self._hits(("address", address), now)) >= ADDRESS_FAILURES_PER_MINUTE
                    or len(self._hits(("login", login), now)) >= LOGIN_FAILURES_PER_MINUTE)

    def check(self, address: str, login: str, password: str) -> Optional[SitePrincipal]:
        account = self._logins.get(login)
        ok = verify_password(password, account["password_scrypt"] if account else self._dummy_hash)
        if ok and account is not None:
            return SitePrincipal(account["principal_id"], account["role"])
        now = self._clock()
        with self._lock:
            self._hits(("address", address), now).append(now)
            self._hits(("login", login), now).append(now)
        return None

    def issue(self, login: str, *, remember: bool) -> str:
        account = self._logins[login]
        value = secrets.token_urlsafe(32)
        now = self._clock()
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM fleet_console_sessions WHERE created_at <= ? "
                       "OR (remember = 0 AND last_used_at <= ?)", (now - ABSOLUTE_S, now - IDLE_S))
            db.execute("INSERT INTO fleet_console_sessions VALUES (?,?,?,?,?,?,?,?)", (
                _digest(value), login, account["principal_id"], account["role"],
                _digest(account["password_scrypt"]), now, now, int(remember)))
        return value

    def principal(self, value: str) -> Optional[tuple[SitePrincipal, str]]:
        """The live session's principal and UTC ISO expiry, sliding its idle window."""
        key = _digest(value)
        now = self._clock()
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT * FROM fleet_console_sessions WHERE session_sha256 = ?",
                             (key,)).fetchone()
            if row is None:
                return None
            account = self._logins.get(row["login"])
            window = REMEMBER_S if row["remember"] else IDLE_S
            cap = row["created_at"] + ABSOLUTE_S
            if (account is None or account["principal_id"] != row["principal_id"]
                    or account["role"] != row["role"]
                    or _digest(account["password_scrypt"]) != row["password_sha256"]
                    or now >= min(cap, row["last_used_at"] + window)):
                db.execute("DELETE FROM fleet_console_sessions WHERE session_sha256 = ?", (key,))
                return None
            if now - row["last_used_at"] >= _TOUCH_EVERY_S:
                db.execute("UPDATE fleet_console_sessions SET last_used_at = ? WHERE session_sha256 = ?",
                           (now, key))
                last_used = now
            else:
                last_used = row["last_used_at"]
        return SitePrincipal(row["principal_id"], row["role"]), _iso(min(cap, last_used + window))

    def revoke(self, value: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM fleet_console_sessions WHERE session_sha256 = ?", (_digest(value),))

    def authenticate(self, request: Request) -> Optional[SitePrincipal]:
        """Cookie authentication for `authorize`; Bearer has already been ruled out."""
        value = request.cookies.get(COOKIE)
        if not value:
            return None
        if request.method not in {"GET", "HEAD"} and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "cookie requests must come from this console"})
        found = self.principal(value)
        if found is None:
            return None
        request.state.site_auth_expires_at = found[1]
        return found[0]


def _set_cookie(response: Response, value: str, *, remember: bool) -> None:
    response.set_cookie(COOKIE, value, max_age=int(REMEMBER_S) if remember else None,
                        path="/", secure=True, httponly=True, samesite="strict")


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
        if sessions.limited(address, login):
            raise HTTPException(status_code=429, headers={"Retry-After": "60"}, detail={
                "code": "RATE_LIMITED", "message": "too many failed logins; wait a minute"})
        principal = sessions.check(address, login, password)
        audited = principal or SitePrincipal(
            f"login:{login if _LOGIN.fullmatch(login) else '?'}", "viewer")
        try:
            # D-519 2: success under the principal, failure as login:<name>; the middleware closes it.
            request.state.site_api_audit_id = task_service.store.begin_api_audit(
                principal_id=audited.principal_id, role=audited.role,
                method=request.method, path=request.url.path)
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(status_code=503, detail={
                "code": "AUDIT_STORAGE_UNAVAILABLE", "message": "site command audit is unavailable",
            }) from None
        if principal is None:
            raise HTTPException(status_code=401, detail={
                "code": "LOGIN_FAILED", "message": "login or password is incorrect"})
        response = Response(status_code=204, headers=NO_STORE)
        _set_cookie(response, sessions.issue(login, remember=remember), remember=remember)
        return response

    @app.post("/api/fleet/auth/logout", status_code=204, tags=["fleet-auth"])
    def fleet_auth_logout(request: Request) -> Response:
        value = request.cookies.get(COOKIE)
        if value and not same_origin(request):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_REJECTED", "message": "cookie requests must come from this console"})
        if value:
            sessions.revoke(value)
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response
