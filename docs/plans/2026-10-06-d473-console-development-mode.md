# D-473 Console Development Connection Mode — Implementation Plan

> **For agentic workers:** use superpowers:subagent-driven-development (or superpowers:executing-plans) to carry out this plan task by task. Each task is TDD: write the failing test, run it red, implement, run it green, compare against known failures, then commit only the listed paths.

**Goal:** Fleet console browsers on the same LAN get a 1-hour in-memory named operator session without a token. This works only when both `ROSY_DEPLOYMENT=development` and `fleet console --connection-mode development` are set (D-473). In every other case Fleet keeps today's `paired` behaviour.

**Architecture:** A new module `operations/fleet/fleet/server/development_session.py` holds the session store, the LAN-address and Host/Origin checks, and the two routes. `site_auth.build_authorize` checks a live development session first and then falls back to its unchanged logic. `require_named_operator` accepts `development-*` principals. `cli.run_console` turns the mode on only when both settings are present, and `create_app` wires it in. `console.js` asks `GET /api/fleet/auth/connection` at start-up and on the first 401. In development mode it requests a session and shows a persistent "개발 연결 모드" badge. The site stack passes both settings through `site.env`, and both are empty by default. This mirrors CORE's D-432 `core_api_web/api/v1/connection.py`. The differences: sessions live in memory and are never persisted (D-473 Alternatives), and a ninth session evicts the oldest instead of refusing (D-473 2).

**Tech Stack:** Python 3.12, FastAPI/Starlette TestClient, stdlib `ipaddress`/`secrets`/`hmac`, vanilla ES modules, Playwright (opt-in browser tests), Docker Compose, Caddy 2.10.

**Spec:** `docs/adr/D-473-fleet-console-development-connection-mode.md` (Accepted). Related: D-432, D-471, D-361, D-18 (a wire change needs its API Reference rows and tests in the same commit).

---

## Ground rules for every task

- Work only in `F:\Dev\Control\Robot\Rosy\rosy-platform\.worktrees\zone-grant` (branch `docs/zone-grant-and-console-dev`). Check `git status --short --branch` before each task.
- Stage only the paths a task lists, with explicit `git add <path> ...`. Never use `git add -A`, `git add .` or a directory add. Check the exit code before committing, and make sure `git diff --cached --name-only` equals the task's list.
- Existing files use CRLF line endings. `docs/reference/ROSY API & Protocol Reference.md` is also UTF-8 with BOM. Keep both. New files follow their neighbours (CRLF). Check with `file <path>` before committing.
- Test log directory: run `mkdir -p X:/DevTemp/zone-grant` once.
- Test pattern (repo root of the worktree):
  ```bash
  python -m pytest <paths> -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
  python test/known_failures.py X:/DevTemp/zone-grant/run.txt
  ```
  If `known_failures.py` exits 1 with `NEW`, the failure belongs to this branch until a clean `main` worktree shows otherwise.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not land or push. The user decides that.

## File map

| Path | Change |
|---|---|
| `operations/fleet/fleet/server/development_session.py` | **new**: `DevelopmentSessions`, `lan_address`, `console_authority`, `client_address`, `install_development_routes` |
| `operations/fleet/fleet/server/site_auth.py` | `build_authorize(..., development=None)`; `require_named_operator` accepts `development-*` |
| `operations/fleet/fleet/server/app.py` | `create_app(..., development_sessions=None)`; audit precondition; route install |
| `operations/fleet/fleet/cli.py` | `--connection-mode {paired,development}`; both-settings gate; `--tasks-db` requirement |
| `operations/fleet/fleet/server/web/console.js` | `connectionMode()`, `renewDevelopmentSession()`, `useToken()`; first-401 hook |
| `operations/fleet/fleet/server/web/index.html` | `#development-badge` in the top bar |
| `deploy/site/compose.yaml` | `--connection-mode ${ROSY_FLEET_CONNECTION_MODE:-paired}`, `ROSY_DEPLOYMENT` env |
| `deploy/site/.env.example` | two empty keys with a warning |
| `deploy/site/README.md` | new section "Development connection mode (D-473)" |
| `docs/reference/ROSY API & Protocol Reference.md` | two Fleet rows, version v1.108, change-log row |
| version pins | `middleware/core/api_web/core_api_web/api/app.py`, `operations/fleet/test/test_lane_route.py`, `operations/fleet/test/test_mission_progress.py`, `operations/fleet/test/test_task_contract_docs.py`, `test/test_line_follow_contract_docs.py` |
| `operations/fleet/test/test_development_session.py` | **new**: unit + route tests |
| `operations/fleet/test/test_cli.py` | four-combination gate tests |
| `test/test_fleet_console_browser.py` | two browser tests |
| `test/test_site_development_connection.py` | **new**: compose/env/README wiring |
| `docs/logs.md`, `operations/fleet/logs.md` | journal entries |
| generated `index.md` files | from `python tools/harness/rosy_harness.py generate` |

Task flow: 1 → 2 → 3 → 4 → 5 → 6 → 7. Tasks 5 and 6 depend only on task 4 and could run in parallel, but they share `docs/logs.md` in task 7, so run them in sequence.

---

## Task 1: Session store and request checks (no wire change)

**Files:**
- Create: `operations/fleet/fleet/server/development_session.py`
- Create: `operations/fleet/test/test_development_session.py`

- [ ] **Step 1: Write the failing test.** Create `operations/fleet/test/test_development_session.py`:

```python
"""D-473 관제 콘솔 개발 연결 모드 — 세션 저장소, LAN 주소, Host/Origin, 상한, 만료."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from fleet.server.development_session import DevelopmentSessions, console_authority, lan_address


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("host", [
    "127.0.0.1", "10.1.2.3", "172.31.255.1", "192.168.0.9", "169.254.10.1",
    "::1", "fe80::1", "::ffff:192.168.1.5", "100.82.51.8", "100.64.0.1", "100.127.255.254",
])
def test_lan_address_accepts_loopback_rfc1918_and_link_local(host):
    assert lan_address(host)


@pytest.mark.parametrize("host", [
    "100.128.0.1", "172.32.0.1", "8.8.8.8", "2001:db8::1", "testclient", "", None,
])
def test_lan_address_refuses_everything_else(host):
    assert not lan_address(host)


@pytest.mark.parametrize(("host", "origin", "ok"), [
    ("192.168.1.10:8090", None, True),
    ("192.168.1.10:8090", "http://192.168.1.10:8090", True),
    ("rosy-site.local:8443", "https://rosy-site.local:8443", True),
    ("localhost:8090", "http://localhost:8090", True),
    ("[::1]:8090", "http://[::1]:8090", True),
    ("evil.example:8090", "http://evil.example:8090", False),  # DNS rebinding
    ("192.168.1.10:8090", "http://evil.example", False),
    ("192.168.1.10:8090", "http://192.168.1.10:9999", False),
    ("192.168.1.10:8090", "null", False),
    ("8.8.8.8", None, False),
    ("user@192.168.1.10:8090", None, False),
    (None, None, False),
])
def test_console_authority_requires_a_local_host_and_a_matching_origin(host, origin, ok):
    assert console_authority(host, origin) is ok


def test_session_is_a_named_operator_that_expires_after_one_hour():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)
    token, principal, expires_at = sessions.issue()

    assert re.fullmatch(r"development-[0-9a-f]{8}", principal.principal_id)
    assert principal.role == "operator"
    assert expires_at == datetime.fromtimestamp(clock.now + 3600, timezone.utc).isoformat(timespec="seconds")
    assert sessions.principal(token) == principal
    clock.now += 3599
    assert sessions.principal(token) == principal
    clock.now += 1
    assert sessions.principal(token) is None
    assert sessions.principal("not-a-session") is None


def test_ninth_session_evicts_the_oldest():
    sessions = DevelopmentSessions(clock=Clock())
    tokens = [sessions.issue()[0] for _ in range(9)]

    assert sessions.principal(tokens[0]) is None
    assert all(sessions.principal(token) is not None for token in tokens[1:])


def test_six_requests_per_address_per_minute():
    clock = Clock()
    sessions = DevelopmentSessions(clock=clock)

    assert all(sessions.admit("192.168.1.50") for _ in range(6))
    assert not sessions.admit("192.168.1.50")
    assert sessions.admit("192.168.1.51")
    clock.now += 60
    assert sessions.admit("192.168.1.50")


def test_revoked_session_no_longer_authenticates():
    sessions = DevelopmentSessions()
    token, _, _ = sessions.issue()
    sessions.revoke(token)

    assert sessions.principal(token) is None
```

- [ ] **Step 2: Run it red.**
```bash
mkdir -p X:/DevTemp/zone-grant
python -m pytest operations/fleet/test/test_development_session.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: collection error `ModuleNotFoundError: fleet.server.development_session`.

- [ ] **Step 3: Implement.** Create `operations/fleet/fleet/server/development_session.py`:

```python
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
```

- [ ] **Step 4: Run it green.** Same two commands as Step 2. Expected: all tests in the file pass and `known_failures.py` reports no `NEW`.

- [ ] **Step 5: Lint.** Run `python -m flake8 operations/fleet/fleet/server/development_session.py operations/fleet/test/test_development_session.py --max-line-length=120`. Expected: no output.

- [ ] **Step 6: Commit.**
```bash
git add operations/fleet/fleet/server/development_session.py operations/fleet/test/test_development_session.py
git diff --cached --name-only
git commit -m "feat(fleet): D-473 development session store and request checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Development sessions in `build_authorize` and the named-operator gate

**Files:**
- Modify: `operations/fleet/fleet/server/site_auth.py` (`build_authorize`, `build_role_guards.require_named_operator`)
- Modify: `operations/fleet/test/test_development_session.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `operations/fleet/test/test_development_session.py`. Put the imports at the top of the file, after the existing imports:

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
```

Append the test:

```python
def test_development_session_passes_the_named_operator_gate_without_site_users():
    sessions = DevelopmentSessions()
    token, principal, _ = sessions.issue()
    authorize = build_authorize("registry-secret", {}, None, development=sessions)
    _, _, named_operator, _ = build_role_guards(authorize, {})
    app = FastAPI()

    @app.post("/api/fleet/named")
    def named(caller: SitePrincipal = Depends(named_operator)) -> dict:
        return {"principal_id": caller.principal_id}

    client = TestClient(app)
    accepted = client.post("/api/fleet/named", headers={"Authorization": f"Bearer {token}"})
    assert accepted.json() == {"principal_id": principal.principal_id}
    shared = client.post("/api/fleet/named", headers={"Authorization": "Bearer registry-secret"})
    assert shared.status_code == 403
    assert shared.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"
    assert client.post("/api/fleet/named", headers={"Authorization": "Bearer wrong"}).status_code == 401
```

- [ ] **Step 2: Run it red.**
```bash
python -m pytest operations/fleet/test/test_development_session.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: `TypeError: build_authorize() got an unexpected keyword argument 'development'`.

- [ ] **Step 3: Implement.** In `operations/fleet/fleet/server/site_auth.py`, replace the head of `build_authorize`, from its signature to `principal = SitePrincipal("site-console", "operator")` after the console-token branch:

```python
def build_authorize(console_token: Optional[str],
                    principals: Mapping[str, SitePrincipal],
                    task_service, development=None):
    def authorize(request: Request,
                  authorization: Optional[str] = Header(default=None)) -> SitePrincipal:
        # D-473 3: a live development session is a named operator beside the configured credentials.
        principal = (development.principal(authorization[len("Bearer "):])
                     if development is not None and authorization and authorization.startswith("Bearer ")
                     else None)
        if principal is None and principals:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "valid site credential required"})
            supplied = authorization[len("Bearer "):]
            supplied_digest = sha256(supplied.encode("utf-8")).hexdigest()
            matched = None
            for token_digest, principal in principals.items():
                if hmac.compare_digest(supplied_digest, token_digest):
                    matched = principal
            if matched is None:
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "valid site credential required"})
            principal = matched
        elif principal is None and console_token is None:
            principal = SitePrincipal("site-console", "operator")
        elif principal is None:
            if authorization != f"Bearer {console_token}":
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "console token required"})
            principal = SitePrincipal("site-console", "operator")
```

The rest of `authorize` (from `request.state.site_principal = principal` down) stays as it is.

In `build_role_guards`, replace `require_named_operator`:

```python
    def require_named_operator(principal: SitePrincipal = Depends(require_operator)) -> SitePrincipal:
        # D-473 3: without site-users the only named operator is a development session.
        if not principals and not principal.principal_id.startswith("development-"):
            raise HTTPException(status_code=403, detail={
                "code": "OPERATOR_IDENTITY_REQUIRED",
                "message": "mission admission requires a configured named operator credential",
            })
        return principal
```

- [ ] **Step 4: Run it green, plus the existing auth users.**
```bash
python -m pytest operations/fleet/test/test_development_session.py operations/fleet/test/test_camera_peer_routes.py operations/fleet/test/test_start_points.py operations/fleet/test/test_server_app.py operations/fleet/test/test_site_users.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: no `NEW`.

- [ ] **Step 5: Commit.**
```bash
git add operations/fleet/fleet/server/site_auth.py operations/fleet/test/test_development_session.py
git diff --cached --name-only
git commit -m "feat(fleet): D-473 development sessions authorize as named operators

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Routes in `create_app`, plus the API Reference (wire change, D-18)

**Files:**
- Modify: `operations/fleet/fleet/server/app.py`
- Modify: `operations/fleet/test/test_development_session.py` (append)
- Modify: `docs/reference/ROSY API & Protocol Reference.md`
- Modify (version pin): `middleware/core/api_web/core_api_web/api/app.py`, `operations/fleet/test/test_lane_route.py`, `operations/fleet/test/test_mission_progress.py`, `operations/fleet/test/test_task_contract_docs.py`, `test/test_line_follow_contract_docs.py`

- [ ] **Step 1: Write the failing tests.** Add these imports at the top of `operations/fleet/test/test_development_session.py`:

```python
import sqlite3
from pathlib import Path

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
```

Append the module constants and tests:

```python
ROOT = Path(__file__).resolve().parents[3]
LAN = ("192.168.1.50", 50000)
BASE = "http://192.168.1.10:8090"
ORIGIN = {"Origin": BASE}
SESSION = "/api/fleet/auth/development-session"


def _app(tmp_path, *, sessions=None, lan_camera_proxy=False):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, console_token="registry-secret", task_service=tasks,
                     development_sessions=sessions, lan_camera_proxy=lan_camera_proxy)
    return app, tasks


def _client(app, client=LAN, base_url=BASE):
    return TestClient(app, client=client, base_url=base_url)


def test_paired_console_reports_paired_and_refuses_sessions(tmp_path):
    app, _ = _app(tmp_path)
    client = _client(app)

    response = client.get("/api/fleet/auth/connection")
    assert response.status_code == 200
    assert response.json() == {"mode": "paired"}
    assert response.headers["cache-control"] == "no-store"
    refused = client.post(SESSION, headers=ORIGIN)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "FORBIDDEN"


def test_development_session_is_a_named_operator_and_is_audited(tmp_path):
    app, tasks = _app(tmp_path, sessions=DevelopmentSessions())
    client = _client(app)

    assert client.get("/api/fleet/auth/connection").json() == {"mode": "development"}
    issued = client.post(SESSION, headers=ORIGIN)
    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    body = issued.json()
    assert set(body) == {"token", "principal_id", "role", "expires_at"}
    assert body["role"] == "operator"
    assert re.fullmatch(r"development-[0-9a-f]{8}", body["principal_id"])
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/api/fleet/session", headers=headers).json() == {
        "principal_id": body["principal_id"], "role": "operator"}
    assert client.get("/api/fleet/session").status_code == 401
    assert client.get("/api/fleet/session", headers={"Authorization": "Bearer registry-secret"}).json() == {
        "principal_id": "site-console", "role": "operator"}
    client.post("/api/fleet/estop", headers=headers)
    rows = tasks.store.api_audit(limit=20)
    intents = {(row["principal_id"], row["path"]) for row in rows if row["event_type"] == "INTENT"}
    assert {(body["principal_id"], SESSION), (body["principal_id"], "/api/fleet/estop")} <= intents
    assert any(row["event_type"] == "RESULT" and row["path"] == SESSION and row["status_code"] == 201
               for row in rows)


@pytest.mark.parametrize("peer", ["100.128.0.1", "8.8.8.8", "testclient"])
def test_session_is_refused_off_the_lan(tmp_path, peer):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())

    assert _client(app, client=(peer, 50000)).post(SESSION, headers=ORIGIN).status_code == 403


@pytest.mark.parametrize(("base_url", "origin", "status"), [
    ("http://evil.example:8090", "http://evil.example:8090", 403),
    (BASE, "http://evil.example", 403),
    (BASE, "http://192.168.1.10:9999", 403),
    ("https://rosy-site.local:8443", "https://rosy-site.local:8443", 201),
    (BASE, None, 201),
])
def test_session_requires_the_console_authority(tmp_path, base_url, origin, status):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())
    headers = {"Origin": origin} if origin is not None else {}

    assert _client(app, base_url=base_url).post(SESSION, headers=headers).status_code == status


@pytest.mark.parametrize(("trusted", "peer", "forwarded", "status"), [
    (True, "172.18.0.4", "8.8.8.8", 403),
    (True, "172.18.0.4", "192.168.1.50", 201),
    (False, "8.8.8.8", "192.168.1.50", 403),
])
def test_forwarded_address_counts_only_behind_the_site_proxy(tmp_path, trusted, peer, forwarded, status):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions(), lan_camera_proxy=trusted)
    headers = {**ORIGIN, "X-Forwarded-For": forwarded}

    assert _client(app, client=(peer, 50000)).post(SESSION, headers=headers).status_code == status


def test_route_rate_limits_per_address(tmp_path):
    app, _ = _app(tmp_path, sessions=DevelopmentSessions())
    client = _client(app)

    for _ in range(6):
        assert client.post(SESSION, headers=ORIGIN).status_code == 201
    limited = client.post(SESSION, headers=ORIGIN)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "RATE_LIMITED"
    assert _client(app, client=("192.168.1.51", 50000)).post(SESSION, headers=ORIGIN).status_code == 201


def test_expired_session_is_401(tmp_path):
    clock = Clock()
    app, _ = _app(tmp_path, sessions=DevelopmentSessions(clock=clock))
    client = _client(app)
    token = client.post(SESSION, headers=ORIGIN).json()["token"]

    clock.now += 3600
    assert client.get("/api/fleet/session", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_issue_fails_closed_when_the_audit_is_unavailable(tmp_path, monkeypatch):
    sessions = DevelopmentSessions()
    app, tasks = _app(tmp_path, sessions=sessions)

    def broken(**_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(tasks.store, "begin_api_audit", broken)
    response = _client(app).post(SESSION, headers=ORIGIN)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUDIT_STORAGE_UNAVAILABLE"
    assert "token" not in response.json()
    assert sessions._sessions == {}


def test_development_mode_requires_the_durable_api_audit():
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8081", "t")], [FakeRobot("rosy_01")])

    with pytest.raises(ValueError, match="audit"):
        create_app(console, development_sessions=DevelopmentSessions())


def test_api_reference_documents_the_development_session_routes():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")

    assert "**Version:** v1.108" in reference
    assert "| GET | `/api/fleet/auth/connection` |" in reference
    assert "| POST | `/api/fleet/auth/development-session` |" in reference
    assert "| v1.108 | 2026-10-06 | Additive (D-473)" in reference
```

- [ ] **Step 2: Run it red.**
```bash
python -m pytest operations/fleet/test/test_development_session.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: `TypeError: create_app() got an unexpected keyword argument 'development_sessions'` and an assertion failure on the API reference test.

- [ ] **Step 3: Implement `create_app`.** In `operations/fleet/fleet/server/app.py`:

1. After `from fleet.server.static_routes import install_static_routes`, add
   ```python
   from fleet.server.development_session import install_development_routes
   ```
2. Replace the last signature line `               cell_app_service_id: str | None = None) -> FastAPI:` with
   ```python
                  cell_app_service_id: str | None = None,
                  development_sessions=None) -> FastAPI:
   ```
3. Right after
   ```python
       if deployment_profile not in DEPLOYMENT_PROFILES:
           raise ValueError(f"unsupported deployment_profile {deployment_profile!r}")
   ```
   add
   ```python
       if development_sessions is not None and task_service is None:
           # D-473 3: every development session issue and POST is in the durable API audit.
           raise ValueError("development connection mode requires the durable API audit (task_service)")
   ```
4. Replace
   ```python
       authorize = build_authorize(console_token, principals, task_service)
       require_viewer, require_operator, require_named_operator, require_proposer = build_role_guards(
           authorize, principals)
       read_guard = [Depends(require_viewer)]
   ```
   with
   ```python
       authorize = build_authorize(console_token, principals, task_service, development=development_sessions)
       require_viewer, require_operator, require_named_operator, require_proposer = build_role_guards(
           authorize, principals)
       # D-473: `--lan-camera-proxy` already means "Fleet sits behind the site Caddy", whose
       # X-Forwarded-For carries the browser address the development session checks.
       install_development_routes(app, sessions=development_sessions, task_service=task_service,
                                  trust_forwarded=lan_camera_proxy)
       read_guard = [Depends(require_viewer)]
   ```
   Before editing, confirm that nothing else registers `/api/fleet/auth/`: `grep -rn "/api/fleet/auth" operations/fleet/fleet` must show only `development_session.py`.

- [ ] **Step 4: Update the API Reference.** In `docs/reference/ROSY API & Protocol Reference.md` (UTF-8 BOM + CRLF, keep both):
   1. Re-read the header and the `# 11. 변경 이력` table first. If a peer has taken v1.108, use the next free minor here, in the test above, and in every pin below.
   2. Change `**Version:** v1.107` to `**Version:** v1.108`.
   3. Directly under the row `| GET | \`/api/fleet/session\` | any configured site-user bearer | ... |`, insert:
   ```markdown
   | GET | `/api/fleet/auth/connection` | none | D-473 (v1.108): `{mode: "development"\|"paired"}` with `Cache-Control: no-store`. `development` only when Fleet started with both `ROSY_DEPLOYMENT=development` and `--connection-mode development`; any other combination, or a missing setting, is `paired`. |
   | POST | `/api/fleet/auth/development-session` | none (development mode only) | D-473 (v1.108): 201 `{token, principal_id, role: "operator", expires_at}` with `Cache-Control: no-store`. `principal_id` is `development-<8 hex>`; the token is returned once and lives 1 h in Fleet memory only (gone on restart). The caller address (the last `X-Forwarded-For` entry when Fleet runs with `--lan-camera-proxy` behind the site proxy, otherwise the TCP peer) must be loopback, RFC1918 or link-local; `Host` must be a LAN IP literal, `localhost`, a `.local` name or the host name, and a present `Origin` must equal `Host`; otherwise, and always in paired mode, 403 `FORBIDDEN`. More than 6 requests per address per minute is 429 `RATE_LIMITED` with `Retry-After: 60`. At most 8 sessions are live; a ninth evicts the oldest. The session is a named operator: it passes the named-operator gate (missions included), and the issue and every later POST are written to the API audit under that principal; an unavailable audit is 503 `AUDIT_STORAGE_UNAVAILABLE` and no session. Robot credentials (`robots.yaml`, D-361 enrollment) and stop paths are unchanged. |
   ```
   4. In the `# 11. 변경 이력` table, insert above the `| v1.107 | ...` row:
   ```markdown
   | v1.108 | 2026-10-06 | Additive (D-473): Fleet `GET /api/fleet/auth/connection` and `POST /api/fleet/auth/development-session`. Development connection mode (both `ROSY_DEPLOYMENT=development` and `--connection-mode development`) gives same-LAN console browsers a 1 h in-memory named operator session; paired mode unchanged. Robot API and envelope 1.0 unchanged |
   ```

- [ ] **Step 5: Move the version pins.** Run `grep -rn "v1\.107" --include=*.py .` (ignore `.worktrees`). Change exactly these pins to `v1.108`:
   - `middleware/core/api_web/core_api_web/api/app.py` line 1 (`ROSY-API-REF-001 v1.107`) and the `description=` line (`(v1.107)`)
   - `operations/fleet/test/test_lane_route.py`: `assert "**Version:** v1.107" in reference`
   - `operations/fleet/test/test_mission_progress.py`: `assert "**Version:** v1.107" in reference`
   - `operations/fleet/test/test_task_contract_docs.py`: both `assert "**Version:** v1.107" in reference`
   - `test/test_line_follow_contract_docs.py`: `assert header and "v1.107" in header[0], (`
   Run the grep again afterwards. Expected: no `v1.107` hits in any of these files.

- [ ] **Step 6: Run it green.**
```bash
python -m pytest operations/fleet/test/test_development_session.py operations/fleet/test/test_server_app.py operations/fleet/test/test_lane_route.py operations/fleet/test/test_mission_progress.py operations/fleet/test/test_task_contract_docs.py operations/fleet/test/test_pairing_api.py test/test_line_follow_contract_docs.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: no `NEW`. Also run `file "docs/reference/ROSY API & Protocol Reference.md"`. It must still say `UTF-8 (with BOM) ... CRLF`.

- [ ] **Step 7: Commit (one commit for the wire change, its docs and its tests, per D-18).**
```bash
git add operations/fleet/fleet/server/app.py operations/fleet/test/test_development_session.py "docs/reference/ROSY API & Protocol Reference.md" middleware/core/api_web/core_api_web/api/app.py operations/fleet/test/test_lane_route.py operations/fleet/test/test_mission_progress.py operations/fleet/test/test_task_contract_docs.py test/test_line_follow_contract_docs.py
git diff --cached --name-only
git commit -m "feat(fleet): D-473 connection and development-session routes (API v1.108)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: CLI flag and the both-settings gate

**Files:**
- Modify: `operations/fleet/fleet/cli.py` (`parse_args` console parser, `run_console`)
- Modify: `operations/fleet/test/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests.** Append to `operations/fleet/test/test_cli.py`:

```python
@pytest.mark.parametrize(("deployment", "mode", "expected"), [
    ("", "paired", "paired"),
    ("development", "paired", "paired"),
    ("", "development", "paired"),
    ("development", "development", "development"),
])
def test_console_development_mode_needs_both_the_flag_and_the_deployment(
        tmp_path, monkeypatch, deployment, mode, expected):
    # D-473 1: a missing or mismatched setting never falls back to development mode.
    monkeypatch.setenv("ROSY_DEPLOYMENT", deployment)
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--tasks-db", str(tmp_path / "fleet.sqlite3"),
                           "--token", "operator-test", "--connection-mode", mode])

    cli.run_console(args)

    client = TestClient(captured["app"], client=("192.168.1.50", 50000),
                        base_url="http://192.168.1.10:8090")
    assert client.get("/api/fleet/auth/connection").json() == {"mode": expected}
    issued = client.post("/api/fleet/auth/development-session")
    assert issued.status_code == (201 if expected == "development" else 403)


def test_console_connection_mode_defaults_to_paired(tmp_path):
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path))])

    assert args.connection_mode == "paired"


def test_console_refuses_an_unknown_connection_mode(tmp_path):
    with pytest.raises(SystemExit):
        cli.parse_args(["console", "--robots", str(_write(tmp_path)), "--connection-mode", "open"])


def test_console_development_mode_requires_the_task_database(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_DEPLOYMENT", "development")
    args = cli.parse_args(["console", "--robots", str(_write(tmp_path)),
                           "--connection-mode", "development"])

    with pytest.raises(SystemExit, match="--tasks-db is required with --connection-mode development"):
        cli.run_console(args)
```

- [ ] **Step 2: Run it red.**
```bash
python -m pytest operations/fleet/test/test_cli.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: the new tests fail with argparse `unrecognized arguments: --connection-mode` (SystemExit 2) or `AttributeError: connection_mode`.

- [ ] **Step 3: Implement.** In `operations/fleet/fleet/cli.py`:

1. In `parse_args`, directly before `return parser.parse_args(argv)`, add:
   ```python
       console.add_argument("--connection-mode", choices=("paired", "development"), default="paired",
                            help=("D-473: development gives same-LAN browsers a 1 h operator session "
                                  "without a token; also needs ROSY_DEPLOYMENT=development"))
   ```
2. In `run_console`, directly after
   ```python
       if mission_api and site_users is None:
           sys.exit("--users-file is required with --mission-api for named operator authorization")
   ```
   add:
   ```python
       development_sessions = None
       if args.connection_mode == "development":
           # D-473 1: both settings or nothing; a missing one keeps paired, never the other way round.
           if os.environ.get("ROSY_DEPLOYMENT", "").strip() != "development":
               print("warning: --connection-mode development ignored: ROSY_DEPLOYMENT is not development",
                     file=sys.stderr)
           elif tasks_db is None:
               sys.exit("--tasks-db is required with --connection-mode development for the session audit")
           else:
               from fleet.server.development_session import DevelopmentSessions

               development_sessions = DevelopmentSessions()
               print("warning: development connection mode: same-LAN browsers get 1 h operator sessions",
                     file=sys.stderr)
   ```
3. In the `create_app(...)` call, change the last argument line `                     central_registry=central_registry)` to
   ```python
                        central_registry=central_registry,
                        development_sessions=development_sessions)
   ```

The off-loopback guard (`--token or --users-file 없이 루프백 밖으로 열 수 없다`) stays unchanged. Development mode adds sessions beside the paired credentials and never replaces them.

- [ ] **Step 4: Run it green.** Same commands as Step 2, plus `operations/fleet/test/test_development_session.py`:
```bash
python -m pytest operations/fleet/test/test_cli.py operations/fleet/test/test_development_session.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: no `NEW`.

- [ ] **Step 5: Commit.**
```bash
git add operations/fleet/fleet/cli.py operations/fleet/test/test_cli.py
git diff --cached --name-only
git commit -m "feat(fleet): D-473 --connection-mode gated by ROSY_DEPLOYMENT=development

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Console auto-session and the persistent badge

**Files:**
- Modify: `operations/fleet/fleet/server/web/index.html`
- Modify: `operations/fleet/fleet/server/web/console.js`
- Modify: `test/test_fleet_console_browser.py` (append)

- [ ] **Step 1: Write the failing browser tests.** Append to `test/test_fleet_console_browser.py`:

```python
def test_development_mode_console_gets_a_session_and_shows_the_badge(console_url):
    # D-473 4: no stored token -> 401 -> connection says development -> one session, badge stays up.
    from playwright.sync_api import sync_playwright

    issued: list[str] = []

    def serve_api(route):
        path = urlparse(route.request.url).path
        authorization = route.request.headers.get("authorization", "")
        if path == "/api/fleet/auth/connection":
            route.fulfill(status=200, json={"mode": "development"})
        elif path == "/api/fleet/auth/development-session" and route.request.method == "POST":
            issued.append(f"dev-token-{len(issued) + 1}")
            route.fulfill(status=201, json={"token": issued[-1], "principal_id": "development-0a1b2c3d",
                                            "role": "operator", "expires_at": "2026-10-06T12:00:00+00:00"})
        elif not authorization.startswith("Bearer dev-token-"):
            route.fulfill(status=401, json={"detail": {"code": "UNAUTHORIZED"}})
        elif path == "/api/fleet/session":
            route.fulfill(status=200, json={"principal_id": "development-0a1b2c3d", "role": "operator"})
        elif path in API:
            route.fulfill(status=200, json=API[path])
        else:
            route.fulfill(status=404, json={"detail": "no such api"})

    with sync_playwright() as p:
        browser, page, errors = open_page(p, 1920, 1080)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.getElementById('user-role').textContent.includes('development-0a1b2c3d')",
            timeout=8000)

        assert page.is_visible("#development-badge")
        assert page.inner_text("#development-badge").strip() == "개발 연결 모드"
        assert page.evaluate("() => sessionStorage.getItem('rosy-console-token')") == "dev-token-1"
        assert issued == ["dev-token-1"], "one 401 must ask for one session, not loop"
        assert not errors, f"페이지 오류: {errors}"
        save_temp_screenshot(page, "fleet_console_development_mode.png")
        browser.close()


def test_paired_console_keeps_the_token_field_and_never_asks_for_a_session(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[str] = []

    def serve_api(route):
        path = urlparse(route.request.url).path
        if route.request.method == "POST":
            posts.append(path)
        if path == "/api/fleet/auth/connection":
            route.fulfill(status=200, json={"mode": "paired"})
        else:
            route.fulfill(status=401, json={"detail": {"code": "UNAUTHORIZED"}})

    with sync_playwright() as p:
        browser, page, errors = open_page(p, 1920, 1080)
        page.route("**/api/**", serve_api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.getElementById('online-pill').textContent === '토큰 필요'",
                               timeout=8000)

        assert page.is_hidden("#development-badge")
        assert page.is_visible("#console-token")
        assert posts == []
        assert not errors, f"페이지 오류: {errors}"
        browser.close()
```

- [ ] **Step 2: Run it red.** In PowerShell set `$env:ROSY_RUN_BROWSER_TESTS='1'`; in bash prefix the command with `ROSY_RUN_BROWSER_TESTS=1`.
```bash
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -k "development_mode or paired_console" -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: both tests fail because `#development-badge` is not found or the wait times out.

- [ ] **Step 3: Add the badge.** In `operations/fleet/fleet/server/web/index.html`, replace
```html
    <ui-tag id="online-pill" status="neutral">연결 대기</ui-tag>
```
with
```html
    <!-- D-473 — 개발 연결 모드면 항상 보인다. 접힌 설정 칸(#topbar-extra) 밖에 둔다. -->
    <ui-tag id="development-badge" status="warn" hidden title="같은 망 PC 누구나 1시간 운용자 세션을 받는다 (D-473)">개발 연결 모드</ui-tag>
    <ui-tag id="online-pill" status="neutral">연결 대기</ui-tag>
```
(`ui-tag[hidden] { display: none; }` already exists in `shared/web/components.css`.)

- [ ] **Step 4: Wire `console.js`.** In `operations/fleet/fleet/server/web/console.js`:

1. In `markLocked`, replace
   ```js
       visionView.reset(); visionView.refreshSources(); trackingView.reset(); startPointView.reset();
     }
     render();
   }
   ```
   with
   ```js
       visionView.reset(); visionView.refreshSources(); trackingView.reset(); startPointView.reset();
     }
     render();
     // D-473 4 — the first 401 of a lock asks once whether this console is in development mode.
     if (firstLock && reason === "auth") renewDevelopmentSession();
   }
   ```
2. Replace
   ```js
   function saveToken() {
     pageScope.invalidate();
     auth.token = el("console-token").value.trim();
   ```
   with
   ```js
   function saveToken() {
     useToken(el("console-token").value.trim());
   }

   function useToken(token) {
     pageScope.invalidate();
     auth.token = token;
   ```
   The rest of the old `saveToken` body becomes the body of `useToken`, unchanged.
3. Replace
   ```js
   pageScope.listen(el("console-token"), "keydown", (event) => {
     if (event.key === "Enter") saveToken();
   });
   ```
   with
   ```js
   pageScope.listen(el("console-token"), "keydown", (event) => {
     if (event.key === "Enter") saveToken();
   });

   // D-473 — development connection mode. The badge is on only while the server says development;
   // paired, 404 (an older Fleet) or an error leaves the token field as the way in.
   async function connectionMode() {
     try {
       const info = await fleetClient("/api/fleet/auth/connection");
       el("development-badge").hidden = info?.mode !== "development";
       return info?.mode === "development";
     } catch (_err) {
       return false;
     }
   }

   // Called on the first 401 of a lock only, so a refused or rate-limited issue (403/429) is one
   // request, not a loop. useToken() invalidates in-flight polls so their stale 401s are dropped.
   async function renewDevelopmentSession() {
     if (!(await connectionMode())) return;
     let session;
     try {
       session = await fleetClient("/api/fleet/auth/development-session", { method: "POST" });
     } catch (_err) {
       return;
     }
     useToken(session.token);
   }
   ```
4. In the start-up block, replace
   ```js
   applyRoleToControls(null, operatorControls());
   render();
   refreshAuthorization();
   ```
   with
   ```js
   applyRoleToControls(null, operatorControls());
   render();
   connectionMode();
   refreshAuthorization();
   ```

- [ ] **Step 5: Run it green, plus the existing console browser suite and web unit tests.**
```bash
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py test/test_fleet_workflows_browser.py operations/fleet/test/test_console_disabled_features.py operations/fleet/test/test_document_imports.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: no `NEW`. Existing tests stub unknown paths with 404, so `connectionMode()` returns false and their behaviour does not change. If `operations/fleet/test/web/` has a Node runner (`ls operations/fleet/test/web`), run it as its README says and record the result in the commit body.

- [ ] **Step 6: Commit.**
```bash
git add operations/fleet/fleet/server/web/index.html operations/fleet/fleet/server/web/console.js test/test_fleet_console_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): D-473 console auto development session and badge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Site stack wiring and the README section

**Files:**
- Modify: `deploy/site/compose.yaml`
- Modify: `deploy/site/.env.example`
- Modify: `deploy/site/README.md`
- Create: `test/test_site_development_connection.py`

- [ ] **Step 1: Write the failing test.** Create `test/test_site_development_connection.py`:

```python
"""D-473 site wiring — development connection mode is off unless site.env sets both keys."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_site_compose_passes_both_development_settings_off_by_default():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")

    assert '--connection-mode\n      - "${ROSY_FLEET_CONNECTION_MODE:-paired}"' in compose
    assert 'ROSY_DEPLOYMENT: "${ROSY_DEPLOYMENT:-}"' in compose


def test_site_env_example_leaves_development_mode_empty():
    env = (ROOT / "deploy/site/.env.example").read_text(encoding="utf-8")

    assert "\nROSY_DEPLOYMENT=\n" in env
    assert "\nROSY_FLEET_CONNECTION_MODE=\n" in env


def test_site_readme_explains_how_to_turn_development_mode_on_and_its_risk():
    readme = (ROOT / "deploy/site/README.md").read_text(encoding="utf-8")

    assert "## Development connection mode (D-473)" in readme
    assert "ROSY_DEPLOYMENT=development" in readme
    assert "ROSY_FLEET_CONNECTION_MODE=development" in readme
    assert "/api/fleet/auth/connection" in readme
    assert "trust" in readme
```

- [ ] **Step 2: Run it red.**
```bash
python -m pytest test/test_site_development_connection.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: 3 failures.

- [ ] **Step 3: Implement.**

`deploy/site/compose.yaml`: replace
```yaml
      - --site-lane-paint
      - /opt/rosy/maps/map_v2_fleet/road_lines.stl
    environment:
```
with
```yaml
      - --site-lane-paint
      - /opt/rosy/maps/map_v2_fleet/road_lines.stl
      - --connection-mode
      - "${ROSY_FLEET_CONNECTION_MODE:-paired}"
    environment:
```
and replace
```yaml
      ROSY_ENROLLED_TLS_BINDINGS_FILE: "${ROSY_SITE_ENROLLED_TLS_BINDINGS_FILE:-}"
```
with
```yaml
      ROSY_ENROLLED_TLS_BINDINGS_FILE: "${ROSY_SITE_ENROLLED_TLS_BINDINGS_FILE:-}"
      ROSY_DEPLOYMENT: "${ROSY_DEPLOYMENT:-}"
```

`deploy/site/.env.example`: append at the end (CRLF):
```bash

# D-473 console development connection mode (README "Development connection mode (D-473)").
# Same-LAN browsers get a 1 h operator session without a token. Both must be "development";
# leave either empty for the normal site user token. Only on a trusted development LAN.
ROSY_DEPLOYMENT=
ROSY_FLEET_CONNECTION_MODE=
```

`deploy/site/README.md`: insert this section directly before `## Contract path`:
````markdown
## Development connection mode (D-473)

On a trusted development LAN the console can skip the site user token. Set
both lines in the private `/etc/rosy/site/site.env` and restart the site stack:

```
ROSY_DEPLOYMENT=development
ROSY_FLEET_CONNECTION_MODE=development
```

With both set, a browser on a loopback, RFC1918 or link-local address that
opens `/console` through the site proxy receives a 1-hour operator session
automatically. The top bar shows "개발 연결 모드" while the mode is on. Each
session is a named principal `development-<8 hex>`. It may dispatch missions,
and the session issue and every POST it makes are recorded in the API audit
under that name. Sessions live in Fleet memory only, so a restart or the end
of the hour issues a new one. At most 8 sessions are live at once (the oldest
is dropped first), and one address may request 6 sessions a minute.

Anyone on the same LAN gets that operator session, so turn this on only on a
network you trust. Leave either line empty (the `.env.example` default) and
the console asks for a site user token as before. A missing or mistyped
setting never falls back to development mode. Robot credentials
(`robots.yaml`, console enrollment) and the stop paths do not change.

Check from any LAN PC:
`curl -sk https://<site-host>.local:$ROSY_SITE_HTTPS_PORT/api/fleet/auth/connection`
prints `{"mode":"development"}`.

````

- [ ] **Step 4: Run it green, plus the existing site wiring tests.**
```bash
python -m pytest test/test_site_development_connection.py test/test_site_task_queue_deploy.py test/test_site_firewall.py test/test_site_preflight.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
```
Expected: no `NEW`. If Docker is available, `docker compose --env-file deploy/site/.env.example -f deploy/site/compose.yaml config --quiet` must exit 0 (`:?` variables come from the example file). Otherwise note "compose config not run (no docker on host)" in the commit body.

- [ ] **Step 5: Commit.**
```bash
git add deploy/site/compose.yaml deploy/site/.env.example deploy/site/README.md test/test_site_development_connection.py
git diff --cached --name-only
git commit -m "feat(site): D-473 pass development connection mode through site.env

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Journal entries, harness generate + lint, change-scoped run

**Files:**
- Modify: `docs/logs.md`, `operations/fleet/logs.md` (append, CRLF)
- Modify: generated files that `python tools/harness/rosy_harness.py generate` changes (typically `docs/index.md`, `operations/fleet/index.md`, `middleware/core/api_web/index.md`)

- [ ] **Step 1: Append the journal entries.**

`docs/logs.md`, at the end:
```markdown

## 2026-10-06 · uncommitted · feat(fleet): D-473 관제 콘솔 개발 연결 모드

- 변경: Fleet `GET /api/fleet/auth/connection`·`POST /api/fleet/auth/development-session`(API Reference v1.108). `ROSY_DEPLOYMENT=development`와 `--connection-mode development`가 함께 있을 때만 같은 망(loopback·RFC1918·link-local) 브라우저에 1시간 메모리 운용자 세션(`development-<8hex>`, 이름 있는 운용자, 감사 기록)을 준다. 콘솔은 첫 401에서 자동 발급하고 "개발 연결 모드" 배지를 띄운다. site.env 두 키(기본 비움), README 절 추가.
- 증거: 관련 호스트 pytest(`operations/fleet/test/test_development_session.py`, `test_cli.py`, 버전 고정 시험, `test/test_site_development_connection.py`)와 콘솔 브라우저 시험. 관제 PC에서 다른 PC 브라우저로 접속하는 FIELD 확인은 아직 하지 않았다.
- gate 변화: SOURCE/LOCAL 검증만 추가. SITE/FIELD 상태는 그대로 둔다.
```

`operations/fleet/logs.md`, at the end:
```markdown

## 2026-10-06 · uncommitted · D-473 관제 콘솔 개발 연결 모드

- 변경: `fleet/server/development_session.py`(세션 저장소·LAN 주소·Host/Origin·분당 6회·상한 8·1시간 만료·발급 감사), `site_auth.build_authorize`의 개발 세션 우선 확인, `require_named_operator`의 `development-*` 허용, `--connection-mode`와 `ROSY_DEPLOYMENT` 이중 조건, 콘솔 자동 발급·배지.
- 증거: 위 호스트 pytest와 브라우저 시험. 사이트 Caddy 뒤 `X-Forwarded-For`·`Host` 전달은 실사이트 확인이 필요하다.
- gate 변화: LOCAL 검증만 추가. SITE/FIELD 상태는 그대로 둔다.
```

- [ ] **Step 2: Harness generate and lint.**
```bash
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```
Expected: `lint` reports 0 errors. Warnings that already existed on `main` are not this branch's. Then run `git status --short` and note each path that `generate` changed.

- [ ] **Step 3: Change-scoped run (affected tests and guards).**
```bash
python -m pytest operations/fleet/test/ test/test_site_development_connection.py test/test_site_task_queue_deploy.py test/test_line_follow_contract_docs.py test/test_harness_contracts.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run.txt
python test/known_failures.py X:/DevTemp/zone-grant/run.txt
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -q -rfE -p no:cacheprovider > X:/DevTemp/zone-grant/run-browser.txt
python test/known_failures.py X:/DevTemp/zone-grant/run-browser.txt
python -m flake8 operations/fleet --max-line-length=120
```
Expected: no `NEW` in either run, and flake8 prints nothing for the files this branch changed.

- [ ] **Step 4: Commit.** List the generated paths by name, exactly as `git status --short` showed them. Do not add any path this branch did not produce.
```bash
git add docs/logs.md operations/fleet/logs.md docs/index.md operations/fleet/index.md
git diff --cached --name-only
git commit -m "docs(fleet): D-473 journal entries and generated harness indexes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
If `generate` also changed `middleware/core/api_web/index.md`, because of the app.py version pin, add it to the same `git add` line. If `generate` did not change one of the listed index files, remove it from the line.

---

## Acceptance (from D-473 Consequences)

| Check | Where |
|---|---|
| The four combinations of the two settings | Task 4 `test_console_development_mode_needs_both_the_flag_and_the_deployment` |
| Address and Origin refusal | Task 1 unit tests and Task 3 route tests (off-LAN peer, DNS rebinding Host, Origin mismatch, untrusted `X-Forwarded-For`) |
| Cap and expiry | Task 1 (9th evicts the oldest, 3600 s expiry, 6/min) and Task 3 (429 + `Retry-After`, 401 after expiry) |
| Named operator and audit | Tasks 2 and 3 (`OPERATOR_IDENTITY_REQUIRED` stays for the shared token; INTENT/RESULT rows) |
| Console auto-issue and badge | Task 5 browser tests |
| **Not covered here (FIELD, user-run)** | On the site PC with both keys set, open `/console` from another LAN PC's browser. Confirm the badge appears, the session works with no token, and an `/api/fleet/estop` POST lands in `fleet_api_audit` under `development-*`. This also proves that Caddy keeps `Host` and writes `X-Forwarded-For` as assumed. |

## Open questions

- [ ] The development session address check trusts the last `X-Forwarded-For` entry only when `--lan-camera-proxy` is set, because that flag already marks "behind the site Caddy". If the user would rather have a dedicated `--trust-proxy` flag, it is a 3-line change in `cli.py`/`app.py`. The FIELD check above confirms the Caddy assumption either way.
- [ ] API Reference minor v1.108 is assumed free as of 2026-10-06. Re-check it right before Task 3 Step 4, because peers bump this file often.
