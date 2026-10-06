"""D-473 개발 연결 모드 — 같은 망 브라우저에 1시간 운용자 세션을 메모리에만 준다.

D-432 CORE `POST /api/v1/auth/development-session` 의 Fleet 짝이다. 켜는 조건
(`ROSY_DEPLOYMENT=development` + `--connection-mode development`)은 `cli.run_console` 이 본다.
이 모듈은 켜졌을 때의 발급·검증만 한다. 세션은 디스크에 쓰지 않는다 — 재시작하면 사라진다.
"""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from fleet.server.site_auth import SitePrincipal

SESSION_TTL_S = 3600.0
MAX_SESSIONS = 8
PER_ADDRESS_PER_MINUTE = 6
_RATE_WINDOW_S = 60.0
_MAX_TRACKED_ADDRESSES = 1024
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

#: D-473 2: loopback, RFC1918, link-local, and the Tailscale tailnet 100.64/10 (user decision 2026-10-06).
_LAN_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "100.64.0.0/10",
    "::1/128", "fe80::/10",
))


def lan_address(host: Optional[str]) -> bool:
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in _LAN_NETWORKS)


def console_authority(host_header: Optional[str], origin: Optional[str]) -> bool:
    """Host must name this console (LAN IP, localhost, .local, this host); a present Origin must equal it.

    DNS rebinding: a foreign name that resolves to a LAN address still arrives with that name as Host.
    """
    if not host_header or "@" in host_header:
        return False
    try:
        name = (urlsplit("//" + host_header).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not name or not (lan_address(name) or name == "localhost" or name.endswith(".local")
                        or name == socket.gethostname().rstrip(".").lower()):
        return False
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host_header.lower()


def client_address(request: Request, *, trust_forwarded: bool) -> str:
    """The browser's address. Behind the site Caddy (`--lan-camera-proxy`) Fleet sees the proxy, and
    Caddy writes the real peer as the last X-Forwarded-For entry; Fleet is not published otherwise."""
    forwarded = request.headers.get("x-forwarded-for")
    if trust_forwarded and forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


class DevelopmentSessions:
    """Live development sessions keyed by token digest. Plaintext tokens exist only in `issue`'s return."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, tuple[SitePrincipal, float]] = OrderedDict()
        self._hits: dict[str, deque[float]] = {}

    def admit(self, address: str) -> bool:
        """D-473 2: six issue requests per address per minute."""
        now = self._clock()
        with self._lock:
            if len(self._hits) > _MAX_TRACKED_ADDRESSES:
                # ponytail: drop idle addresses only; a LAN has far fewer than 1024 browsers.
                for key in [key for key, hits in self._hits.items()
                            if not hits or now - hits[-1] >= _RATE_WINDOW_S]:
                    del self._hits[key]
            hits = self._hits.setdefault(address, deque())
            while hits and now - hits[0] >= _RATE_WINDOW_S:
                hits.popleft()
            if len(hits) >= PER_ADDRESS_PER_MINUTE:
                return False
            hits.append(now)
            return True

    def issue(self) -> tuple[str, SitePrincipal, str]:
        """New token, its principal, and the UTC ISO expiry."""
        token = secrets.token_urlsafe(32)
        principal = SitePrincipal(f"development-{secrets.token_hex(4)}", "operator")
        now = self._clock()
        expires = now + SESSION_TTL_S
        with self._lock:
            self._prune(now)
            while len(self._sessions) >= MAX_SESSIONS:
                self._sessions.popitem(last=False)  # D-473 2: the oldest goes first
            self._sessions[_digest(token)] = (principal, expires)
        return token, principal, datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds")

    def principal(self, token: str) -> Optional[SitePrincipal]:
        digest = _digest(token)
        with self._lock:
            self._prune(self._clock())
            matched = None
            for stored, (principal, _expires) in self._sessions.items():
                if hmac.compare_digest(stored, digest):
                    matched = principal
            return matched

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(_digest(token), None)

    def _prune(self, now: float) -> None:
        for digest in [digest for digest, (_p, expires) in self._sessions.items() if expires <= now]:
            del self._sessions[digest]


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def install_development_routes(app, *, sessions: Optional[DevelopmentSessions], task_service,
                               trust_forwarded: bool) -> None:
    @app.get("/api/fleet/auth/connection", tags=["fleet-auth"])
    def fleet_connection() -> JSONResponse:
        return JSONResponse(headers=NO_STORE,
                            content={"mode": "development" if sessions is not None else "paired"})

    @app.post("/api/fleet/auth/development-session", status_code=201, tags=["fleet-auth"])
    def fleet_development_session(request: Request) -> JSONResponse:
        address = client_address(request, trust_forwarded=trust_forwarded)
        if (sessions is None or not lan_address(address)
                or not console_authority(request.headers.get("host"), request.headers.get("origin"))):
            raise HTTPException(status_code=403, detail={
                "code": "FORBIDDEN", "message": "this console requires a site credential"})
        if not sessions.admit(address):
            raise HTTPException(status_code=429, headers={"Retry-After": "60"}, detail={
                "code": "RATE_LIMITED", "message": "too many development session requests"})
        token, principal, expires_at = sessions.issue()
        try:
            # D-473 3: the issue itself is audited under the new principal; the middleware closes it.
            request.state.site_api_audit_id = task_service.store.begin_api_audit(
                principal_id=principal.principal_id, role=principal.role,
                method=request.method, path=request.url.path)
        except (OSError, sqlite3.Error, ValueError):
            sessions.revoke(token)
            raise HTTPException(status_code=503, detail={
                "code": "AUDIT_STORAGE_UNAVAILABLE", "message": "site command audit is unavailable",
            }) from None
        return JSONResponse(status_code=201, headers=NO_STORE, content={
            "token": token, "principal_id": principal.principal_id,
            "role": principal.role, "expires_at": expires_at,
        })
