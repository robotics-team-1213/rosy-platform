"""Fleet 서버의 HTTP 표면 — 관제 UI 와 그 UI 가 쓰는 사이트 API.

경로는 로봇 계약(`/api/v1/...`)과 일부러 다르다. 관제 API 는 사이트 것이고, 로봇 것을
흉내 내면 둘 중 어느 쪽에 말하고 있는지 화면에서도 코드에서도 흐려진다.

인증: 이 서버는 robots.yaml 의 운영자 토큰을 들고 있다. 즉 이 포트에 닿는 사람은 현장의
모든 로봇을 움직일 수 있다. 그래서 기본은 루프백이고, 루프백 밖으로 열려면 콘솔 토큰을
반드시 받는다(`serve()` 가 강제한다).
"""

from __future__ import annotations

import asyncio
import hmac
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from core_common.protocol.sightings import SiteSightingPayload
from core_common.protocol.schemas import DiscoveryScanPayload
from core_common.intent import IntentError, interpret
from fleet.hub.hub import HubError
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingError
from fleet.server.signals import SignalApiError
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import IdempotencyConflict, InvalidTaskTransition
from fleet.swarm.transport import RobotApiError

WEB_ROOT = Path(__file__).resolve().parent / "web"


async def _site_call(console: FleetConsole, call) -> dict:
    if call.verb == "formation_start":
        return await console.formation_start(
            call.body["leader"], call.body.get("formation", "COLUMN"),
            call.body.get("spacing"), call.body.get("max_speed"),
            members=call.body.get("members"))
    if call.verb == "formation_stop":
        return await console.formation_stop()
    if call.verb == "formation_resume":
        return await console.formation_resume()
    if call.verb == "estop":
        return await console.estop_all()
    raise HubError("UNKNOWN_VERB", call.verb)


async def _robot_call(console: FleetConsole, call) -> dict:
    robot = call.robot
    if call.verb == "navigate":
        if call.body.get("x") is None or call.body.get("y") is None:
            raise HubError("WAYPOINT_STAYS_ON_ROBOT", "name a point, or tell the robot itself")
        return await console.goal(robot, float(call.body["x"]), float(call.body["y"]),
                                  float(call.body.get("yaw") or 0.0))
    if call.verb == "cancel":
        return await console.cancel(robot)
    if call.verb == "stop":
        return await console._client(robot).estop()
    if call.verb == "follow":
        from core_common.protocol.schemas import SwarmFollowParams
        return await console._client(robot).follow(SwarmFollowParams(**call.body))
    return await console._client(robot)._post(call.path, call.body or None)

#: 경로 순회를 막는 유일한 방어다 — 디렉터리 스캔으로 바꾸지 않는다 (core 와 같은 규칙).
#: 공용 L1 자산은 여기 없다. 서버는 설정받은 web_common 디렉터리에서 명시된
#: 파일만 /common 아래로 서빙한다(D-129, D-1005).
CONSOLE_ASSETS = {
    "styles.css": "text/css",
    "console.js": "application/javascript",
    "authorization.js": "application/javascript",
    "formation.js": "application/javascript",
    "map-view.js": "application/javascript",
    "roster.js": "application/javascript",
    "signals.js": "application/javascript",
}

CONSOLE_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


@dataclass(frozen=True)
class SitePrincipal:
    principal_id: str
    role: str


class GoalRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0


class FormationRequest(BaseModel):
    leader: str
    formation: str = "COLUMN"
    spacing: Optional[float] = None
    max_speed: Optional[float] = None
    members: Optional[list[str]] = None  # FOR-001 Robot Selection — None 은 전원이다


class ReformRequest(BaseModel):
    formation: str
    spacing: Optional[float] = None
    max_speed: Optional[float] = None


class SignalCommandRequest(BaseModel):
    """ROSY-SIGNAL-001 의 `POST /command` 본문. `seq` 는 콘솔이 채운다 — 화면이
    붙이기 시작하면 두 명령이 같은 seq 로 싸운다."""
    mode: str
    lamps: Optional[dict[str, bool]] = None
    cycle: Optional[dict[str, int]] = None


def _http_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, HubError):
        # 409 는 "지금 상태에서는 안 된다"(이미 대형이 열려 있음, 팔로워가 대형에 묶임)이고,
        # 400 은 "요청이 틀렸다"(없는 대형 이름)다. 화면이 둘을 다르게 안내해야 한다.
        conflict = {"FORMATION_ACTIVE", "NO_FORMATION", "REFORM_REFUSED",
                    "RESUME_REFUSED", "ARMING_FAILED", "NO_FOLLOWERS"}
        status = (404 if exc.code in ("UNKNOWN_ROBOT", "UNKNOWN_SIGNAL", "NO_SIGNALS")
                  else 409 if exc.code in conflict else 400)
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, SignalApiError):
        # 신호등이 거절한 것이다 — 400 conflict 같은 장치 코드를 그대로 화면에 옮긴다.
        return HTTPException(status_code=502,
                             detail={"code": exc.code, "message": str(exc),
                                     "signal_id": exc.signal_id})
    if isinstance(exc, RobotApiError):
        # 로봇이 거절한 것이지 관제가 잘못 만든 요청이 아니다 — 502 로 그 사실을 남긴다.
        return HTTPException(status_code=502,
                             detail={"code": exc.code, "message": str(exc),
                                     "robot_id": exc.robot_id})
    return HTTPException(status_code=502,
                         detail={"code": type(exc).__name__, "message": str(exc)})


def create_app(console: FleetConsole, *, console_token: Optional[str] = None,
               web_common: Optional[Path] = None, hub=None, sightings=None,
               task_service: Optional[FleetTaskService] = None,
               start_task_dispatcher: bool = True,
               site_users: Optional[Mapping[str, Mapping[str, str]]] = None,
               discovery=None, discovery_token: Optional[str] = None) -> FastAPI:
    if site_users is not None and task_service is None:
        raise ValueError("per-user site authorization requires persistent task/audit storage")
    if bool(discovery) != bool(discovery_token):
        raise ValueError("discovery and its dedicated credential must be configured together")
    if discovery_token is not None and (discovery_token == console_token
                                        or console.uses_rest_token(discovery_token)
                                        or console.uses_agent_pairing_token(discovery_token)):
        raise ValueError("discovery credential must differ from Fleet and robot credentials")

    @asynccontextmanager
    async def lifespan(app):
        dispatcher = None
        if task_service is not None and start_task_dispatcher:
            dispatcher = asyncio.create_task(_task_dispatch_loop(console, task_service))
        try:
            yield
        finally:
            if dispatcher is not None:
                dispatcher.cancel()
                try:
                    await dispatcher
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="ROSY Fleet",
        version="0.1.0",
        lifespan=lifespan,
        description="사이트 오케스트레이터 — 모음과 원자 액션 흩뿌림 (D-59)",
    )
    app.state.console = console
    app.state.web_common = Path(web_common) if web_common is not None else None
    app.state.task_service = task_service
    if task_service is not None:
        async def release_traffic_task(mission: dict) -> None:
            task_service.traffic_queue_released(mission["task_id"])

        console.set_task_queue_release_callback(release_traffic_task)

    @app.middleware("http")
    async def finish_mutation_audit(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            audit_id = getattr(request.state, "site_api_audit_id", None)
            if audit_id is not None:
                task_service.store.finish_api_audit(audit_id, status_code=500)
            raise
        audit_id = getattr(request.state, "site_api_audit_id", None)
        if audit_id is not None:
            task_service.store.finish_api_audit(audit_id, status_code=response.status_code)
        return response

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        """Minimal process liveness for local container supervision."""
        return {"status": "ok"}

    if hub is not None:
        from fleet.hub.server import install_hub_routes

        install_hub_routes(app, hub, hub_token=console_token)

    principals = {}
    if site_users is not None:
        seen_principal_ids = set()
        for token, details in site_users.items():
            if not isinstance(token, str) or not isinstance(details, Mapping):
                raise ValueError("site user credential entries must be strings and mappings")
            principal_id = details.get("principal_id", "")
            role = details.get("role", "")
            if not isinstance(principal_id, str) or not isinstance(role, str):
                raise ValueError("site principal_id and role must be strings")
            principal_id = principal_id.strip()
            role = role.strip()
            if (len(token) != 64 or any(char not in "0123456789abcdef" for char in token)
                    or not principal_id or len(principal_id) > 96
                    or any(ord(char) < 32 for char in principal_id)
                    or principal_id in seen_principal_ids
                    or role not in {"viewer", "operator", "policy-admin"}):
                raise ValueError("site user credentials require a token, principal_id, and known role")
            principals[token] = SitePrincipal(principal_id, role)
            seen_principal_ids.add(principal_id)
        if not principals:
            raise ValueError("site user credentials cannot be empty")
        if console.user_credential_overlaps_robot_secret(tuple(principals)):
            raise ValueError("site user credentials must differ from robot credentials")
        registry_digest = (sha256(console_token.encode("utf-8")).hexdigest()
                           if console_token is not None else None)
        if (registry_digest is not None
                and any(hmac.compare_digest(registry_digest, digest) for digest in principals)):
            raise ValueError("site user credentials must differ from the CORE registry credential")

    def authorize(request: Request,
                  authorization: Optional[str] = Header(default=None)) -> SitePrincipal:
        if principals:
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
        elif console_token is None:
            principal = SitePrincipal("site-console", "operator")
        else:
            if authorization != f"Bearer {console_token}":
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED",
                                                             "message": "console token required"})
            principal = SitePrincipal("site-console", "operator")
        request.state.site_principal = principal
        if (task_service is not None and request.method == "POST"
                and request.url.path.startswith("/api/fleet/")
                and request.url.path != "/api/fleet/sightings"):
            try:
                request.state.site_api_audit_id = task_service.store.begin_api_audit(
                    principal_id=principal.principal_id, role=principal.role,
                    method=request.method, path=request.url.path,
                )
            except (OSError, sqlite3.Error, ValueError):
                raise HTTPException(status_code=503, detail={
                    "code": "AUDIT_STORAGE_UNAVAILABLE",
                    "message": "site command audit is unavailable",
                }) from None
        return principal

    def require_viewer(principal: SitePrincipal = Depends(authorize)) -> SitePrincipal:
        return principal

    def require_operator(principal: SitePrincipal = Depends(authorize)) -> SitePrincipal:
        if principal.role != "operator":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN",
                                                         "message": "operator role required"})
        return principal

    read_guard = [Depends(require_viewer)]
    operator_guard = [Depends(require_operator)]

    if discovery is not None:
        if principals and any(hmac.compare_digest(
                sha256(discovery_token.encode("utf-8")).hexdigest(), digest)
                for digest in principals):
            raise ValueError("discovery credential must differ from site user credentials")

        @app.post("/api/fleet/discovery/scan", tags=["fleet-discovery"])
        def discovery_scan(body: DiscoveryScanPayload,
                           authorization: Optional[str] = Header(default=None)) -> dict:
            expected = f"Bearer {discovery_token}"
            if not authorization or not hmac.compare_digest(authorization, expected):
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
            try:
                discovery.replace_scan(body.devices)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_SCAN",
                                                             "message": str(exc)}) from exc
            return {"accepted": True}

        @app.get("/api/fleet/discovery", dependencies=read_guard,
                 tags=["fleet-discovery"])
        def discovery_readback() -> dict:
            identities = hub.registry.identity_snapshot() if hub is not None else {}
            return discovery.snapshot(console.registered_endpoints, identities)

    def cancel_pending_task_queue(robot_id: Optional[str] = None, *,
                                  actor_id: str = "site-console") -> None:
        if task_service is None:
            return
        canceled = (task_service.cancel_all_queued(actor_id=actor_id) if robot_id is None else
                    task_service.cancel_queued_for_robot(robot_id, actor_id=actor_id))
        console.discard_task_queue_entries(set(canceled))

    if sightings is not None and sightings.enabled:
        if console_token is not None and sightings.uses_token(console_token):
            raise ValueError("sighting source credentials must differ from the console token")
        if principals and sightings.reuses_any(
                lambda candidate: any(
                    hmac.compare_digest(sha256(candidate.encode("utf-8")).hexdigest(), digest)
                    for digest in principals)):
            raise ValueError("site user and sighting credentials must differ")
        if sightings.reuses_any(console.uses_rest_token):
            raise ValueError("sighting source credentials must differ from robot REST tokens")
        if sightings.reuses_any(console.uses_agent_pairing_token):
            raise ValueError("sighting source credentials must differ from CORE Agent pairing tokens")

        @app.post("/api/fleet/sightings", tags=["sightings"])
        async def submit_sighting(body: SiteSightingPayload,
                                  authorization: Optional[str] = Header(default=None)) -> dict:
            try:
                return sightings.accept(authorization, body)
            except SightingError as exc:
                raise HTTPException(status_code=exc.status_code,
                                    detail={"code": exc.code, "message": str(exc)}) from exc

        @app.get("/api/fleet/sightings", dependencies=read_guard, tags=["sightings"])
        async def sighting_readback() -> dict:
            return sightings.snapshot()

    if hub is not None and hub.event_store is not None:
        @app.get("/api/fleet/events", dependencies=read_guard, tags=["fleet-events"])
        def core_event_history(
            after_id: int = Query(default=0, ge=0),
            limit: int = Query(default=100, ge=1, le=200),
            robot_id: Optional[str] = Query(default=None, min_length=1, max_length=96),
        ) -> dict:
            try:
                rows = hub.event_store.read_events(after_id=after_id, limit=limit,
                                                   robot_id=robot_id)
            except (OSError, sqlite3.Error):
                raise HTTPException(status_code=503, detail={
                    "code": "EVENT_STORAGE_UNAVAILABLE",
                    "message": "CORE event history is temporarily unavailable",
                }) from None
            page = rows[:limit]
            return {
                "events": page,
                "next_cursor": page[-1]["audit_id"] if page else after_id,
                "has_more": len(rows) > limit,
            }

    @app.get("/api/fleet/state", dependencies=read_guard, tags=["fleet"])
    async def fleet_state() -> dict:
        return await console.snapshot()

    @app.get("/api/fleet/session", dependencies=read_guard, tags=["fleet-auth"])
    def fleet_session(request: Request) -> dict:
        principal: SitePrincipal = request.state.site_principal
        return {"principal_id": principal.principal_id, "role": principal.role}

    @app.get("/api/fleet/map", dependencies=read_guard, tags=["fleet"])
    async def fleet_map() -> dict:
        grid = await console.map()
        if grid is None:
            raise HTTPException(status_code=404, detail={"code": "NO_MAP",
                                                         "message": "no robot served a map"})
        return grid

    @app.post("/api/fleet/robots/{robot_id}/goal", dependencies=operator_guard, tags=["fleet"])
    async def fleet_goal(
        robot_id: str, body: GoalRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        try:
            if task_service is not None:
                if not idempotency_key:
                    raise HTTPException(status_code=400, detail={
                        "code": "IDEMPOTENCY_KEY_REQUIRED",
                        "message": "Idempotency-Key is required for navigation requests",
                    })
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=body.x, y=body.y, yaw=body.yaw,
                    source="operator", actor_id=principal.principal_id, request_key=idempotency_key,
                )
                return {"accepted": task["status"] == "ACCEPTED",
                        "queued": task["status"] == "QUEUED", "task": task}
            return await console.goal(robot_id, body.x, body.y, body.yaw)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail={
                "code": "IDEMPOTENCY_CONFLICT", "message": str(exc),
            }) from exc
        except ValueError as exc:
            code = str(exc)
            status = 404 if code == "UNKNOWN_ROBOT" else 400
            raise HTTPException(status_code=status, detail={"code": code}) from exc
        except (HubError, RobotApiError, OSError) as exc:
            raise _http_error(exc) from exc

    if task_service is not None:
        @app.get("/api/fleet/tasks/{task_id}", dependencies=read_guard, tags=["fleet-tasks"])
        def fleet_task_readback(task_id: str) -> dict:
            task = task_service.store.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
            return {"task": task, "history": task_service.store.history(task_id)}

        @app.post("/api/fleet/tasks/{task_id}/cancel", dependencies=operator_guard,
                  tags=["fleet-tasks"])
        def fleet_task_cancel(task_id: str,
                              principal: SitePrincipal = Depends(require_operator)) -> dict:
            try:
                task = task_service.cancel_queued_task(task_id, actor_id=principal.principal_id)
            except KeyError:
                raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None
            except InvalidTaskTransition:
                raise HTTPException(status_code=409, detail={
                    "code": "TASK_ALREADY_DISPATCHED",
                    "message": "only a task not yet dispatched can be canceled here",
                }) from None
            console.discard_task_queue_entries({task_id})
            return {"task": task}

    @app.post("/api/fleet/robots/{robot_id}/cancel", dependencies=operator_guard, tags=["fleet"])
    async def fleet_cancel(robot_id: str,
                           principal: SitePrincipal = Depends(require_operator)) -> dict:
        cancel_pending_task_queue(robot_id, actor_id=principal.principal_id)
        try:
            result = await console.cancel(robot_id)
        except (HubError, RobotApiError, OSError) as exc:
            raise _http_error(exc) from exc
        return result

    @app.get("/api/fleet/formation", dependencies=read_guard, tags=["formation"])
    async def formation_state() -> dict:
        return console.formation_status()

    @app.post("/api/fleet/formation/start", dependencies=operator_guard, tags=["formation"])
    async def formation_start(body: FormationRequest) -> dict:
        try:
            return await console.formation_start(body.leader, body.formation,
                                                 body.spacing, body.max_speed,
                                                 members=body.members)
        except (HubError, RobotApiError, OSError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/fleet/formation/reform", dependencies=operator_guard, tags=["formation"])
    async def formation_reform(body: ReformRequest) -> dict:
        try:
            return await console.formation_reform(body.formation, body.spacing, body.max_speed)
        except (HubError, RobotApiError, OSError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/fleet/formation/resume", dependencies=operator_guard, tags=["formation"])
    async def formation_resume() -> dict:
        try:
            return await console.formation_resume()
        except (HubError, RobotApiError, OSError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/fleet/formation/stop", dependencies=operator_guard, tags=["formation"])
    async def formation_stop() -> dict:
        # 해제는 거절하지 않는다. 대형을 못 푸는 화면은 대형을 여는 화면보다 나쁘다.
        return await console.formation_stop()

    @app.get("/api/fleet/signals", dependencies=read_guard, tags=["signals"])
    async def fleet_signals() -> dict:
        try:
            return await console.signals_detail()
        except (HubError, OSError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/fleet/signals/{signal_id}/command", dependencies=operator_guard, tags=["signals"])
    async def fleet_signal_command(signal_id: str, body: SignalCommandRequest) -> dict:
        try:
            return await console.signal_command(signal_id, body.model_dump(exclude_none=True))
        except (HubError, SignalApiError, OSError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/fleet/do", dependencies=operator_guard, tags=["fleet"])
    async def fleet_do(
        body: dict,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        """같은 통역기. 로봇 일은 그 로봇 API로, 현장 말은 이 서버가 실행한다."""
        try:
            calls = interpret(body)
        except IntentError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
        steps = []
        for call in calls:
            try:
                if call.scope == "site":
                    if call.verb == "estop":
                        cancel_pending_task_queue(actor_id=principal.principal_id)
                    result = await _site_call(console, call)
                else:
                    if not call.robot:
                        raise HubError("ROBOT_REQUIRED", call.verb)
                    if call.verb in {"cancel", "stop"}:
                        cancel_pending_task_queue(call.robot, actor_id=principal.principal_id)
                    if task_service is not None and call.verb == "navigate":
                        if not idempotency_key:
                            raise HTTPException(status_code=400, detail={
                                "code": "IDEMPOTENCY_KEY_REQUIRED",
                                "message": "Idempotency-Key is required for navigation requests",
                            })
                        if call.body.get("x") is None or call.body.get("y") is None:
                            raise HubError("WAYPOINT_STAYS_ON_ROBOT",
                                           "name a point, or tell the robot itself")
                        child_key = sha256(f"{idempotency_key}:{len(steps)}".encode()).hexdigest()
                        task = await task_service.submit_navigation(
                            robot_id=call.robot, x=float(call.body["x"]),
                            y=float(call.body["y"]), yaw=float(call.body.get("yaw") or 0.0),
                            source="operator", actor_id=principal.principal_id, request_key=child_key,
                        )
                        result = {"accepted": task["status"] == "ACCEPTED",
                                  "queued": task["status"] == "QUEUED", "task": task}
                    else:
                        result = await _robot_call(console, call)
            except IdempotencyConflict as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "IDEMPOTENCY_CONFLICT", "message": str(exc),
                }) from exc
            except ValueError as exc:
                code = str(exc)
                status = 404 if code == "UNKNOWN_ROBOT" else 400
                raise HTTPException(status_code=status, detail={"code": code}) from exc
            except (HubError, RobotApiError, OSError) as exc:
                raise _http_error(exc) from exc
            steps.append({"do": call.verb, "robot": call.robot, "path": call.path, "result": result})
        return {
            "accepted": all(step["result"].get("accepted", True) for step in steps),
            "queued": any(step["result"].get("queued", False) for step in steps),
            "steps": steps,
        }

    @app.post("/api/fleet/estop", dependencies=operator_guard, tags=["fleet"])
    async def fleet_estop(principal: SitePrincipal = Depends(require_operator)) -> dict:
        # 이쪽은 한 대가 거절해도 200 이다 — 어느 대가 섰고 어느 대가 못 섰는지는 본문에
        # 다 들어 있고, 화면은 그 목록을 보여 줘야 한다.
        cancel_pending_task_queue(actor_id=principal.principal_id)
        return await console.estop_all()

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/console")

    @app.get("/console", include_in_schema=False)
    def console_page():
        return FileResponse(
            WEB_ROOT / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": CONSOLE_CSP},
        )

    common_assets = {
        "tokens.css": "text/css",
        "components.css": "text/css",
        "template.html": "text/html",
        "core_ui_logic.js": "application/javascript",
        "ui.js": "application/javascript",
    }

    @app.get("/common/{asset_name:path}", include_in_schema=False)
    def common_asset(asset_name: str):
        media_type = common_assets.get(asset_name)
        root = app.state.web_common
        if media_type is None:
            raise HTTPException(status_code=404, detail="common asset not found")
        if root is None or not root.is_dir():
            raise HTTPException(
                status_code=404,
                detail={"code": "WEB_COMMON_UNCONFIGURED",
                        "message": "--web-common 가 설정되지 않았다"},
            )
        path = root / asset_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="common asset not found")
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})

    @app.get("/ui/tokens.css", include_in_schema=False)
    def legacy_ui_tokens_asset():
        return common_asset("tokens.css")

    @app.get("/console/assets/{asset_name:path}", include_in_schema=False)
    def console_asset(asset_name: str):
        media_type = CONSOLE_ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="console asset not found")
        return FileResponse(WEB_ROOT / asset_name, media_type=media_type,
                            headers={"Cache-Control": "no-cache"})

    return app


async def _task_dispatch_loop(console: FleetConsole, task_service: FleetTaskService) -> None:
    """Dispatch one eligible task at a time from the app-owned background worker."""
    while True:
        try:
            task_service.scheduler.expire_queued()
            snapshot = await console.snapshot()
            console.prune_task_queue_entries(task_service.store.queued_task_ids())
            available = {
                row["robot_id"] for row in snapshot["robots"]
                if row["online"] and row["queued"] is None and row["goal"] is None
                and row["state"] is not None
                and row["state"].get("navigation") in {"IDLE", "ARRIVED", "CANCELED", "FAILED"}
                and row["state"].get("mode") in {"IDLE", "NAVIGATION"}
                and not row["state"].get("capabilities_degraded")
                and not row["state"].get("safety", {}).get("estop")
            }
            await task_service.dispatch_next(
                available,
                dispatch=lambda task: console.goal(
                    task["robot_id"], task["request"]["goal"]["x"],
                    task["request"]["goal"]["y"], task["request"]["goal"]["yaw"],
                    task_id=task["task_id"], attempt_id=task["attempt_id"],
                    attempt_seq=task["attempt_seq"],
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A status read failure cannot establish availability. Leave work queued.
            pass
        await asyncio.sleep(0.25)
