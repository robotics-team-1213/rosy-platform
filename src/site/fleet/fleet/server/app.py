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
import json
import logging
import math
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from core_common.protocol.policy_evidence import PolicyEvidencePayload
from core_common.protocol.sightings import SiteSightingPayload
from core_common.protocol.vision_preview import VisionLeaseSigner
from core_common.protocol.schemas import (
    DiscoveryScanPayload,
    MissionCursorExpiredError,
    MissionCursorResetError,
    MissionProgressEventPage,
    MissionProgressReadResponse,
    ResolvedTargetEvidence,
)
from core_common.intent import IntentError, interpret, request_schema
from fleet.hub.hub import HubError
from fleet.server.console import FleetConsole
from fleet.server.policy_evidence import PolicyEvidenceError, PolicyEvidenceStore, status_code_for
from fleet.server.mission_service import MissionService
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_model_turn_store import MissionModelTurnStore
from fleet.server.mission_model_turn_scheduler import MissionModelTurnScheduler
from fleet.server.mission_store import MissionConflict
from fleet.server.goal_evidence_service import (
    GoalEvidenceService, GoalEvidenceSubmissionError,
)
from fleet.server.proposal_store import ProposalConflict, ProposalRejected, ProposalStore
from fleet.server.local_stop_transport import UnixLocalStopTransport
from fleet.server.local_action_transport import UnixLocalActionTransport
from fleet.server.sightings import SightingError
from fleet.server.signals import SignalApiError
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import IdempotencyConflict, InvalidTaskTransition
from fleet.swarm.transport import RobotApiError

WEB_ROOT = Path(__file__).resolve().parent / "web"
_LOG = logging.getLogger(__name__)


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


def _shared_assets(root: Optional[Path]) -> dict[str, str]:
    """The /common allowlist is web_common's manifest.json. A configured
    directory without one (a trimmed copy) uses the default web_common's."""
    manifest = root / "manifest.json" if root is not None else None
    if manifest is None or not manifest.is_file():
        from fleet.cli import default_web_common

        manifest = default_web_common() / "manifest.json"
    return dict(json.loads(manifest.read_text(encoding="utf-8"))["shared_assets"])


#: 경로 순회를 막는 유일한 방어다 — 디렉터리 스캔으로 바꾸지 않는다 (core 와 같은 규칙).
#: 공용 L1 자산은 여기 없다. 서버는 설정받은 web_common 디렉터리에서 명시된
#: 파일만 /common 아래로 서빙한다(D-129, D-157).
CONSOLE_ASSETS = {
    "styles.css": "text/css",
    "console.js": "application/javascript",
    "authorization.js": "application/javascript",
    "field-layers.js": "application/javascript",
    "field-view.js": "application/javascript",
    "formation.js": "application/javascript",
    "map-view.js": "application/javascript",
    "roster.js": "application/javascript",
    "enrollment.js": "application/javascript",
    "signals.js": "application/javascript",
    "site-layer.js": "application/javascript",
    "vision-view.js": "application/javascript",
}

CONSOLE_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


@dataclass(frozen=True)
class SitePrincipal:
    principal_id: str
    role: str


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float
    yaw: float = 0.0

    @field_validator("x", "y", "yaw", mode="before")
    @classmethod
    def _finite_numeric_goal(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("goal coordinates must be finite numbers")
        return value


class DispatchRearmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_generation: int

    @field_validator("expected_generation", mode="before")
    @classmethod
    def _non_negative_generation(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        return value


class MissionCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_key: str
    workcell_id: str
    instance_id: str
    candidate: dict[str, object]


class MissionAdmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_generation: int

    @field_validator("expected_generation", mode="before")
    @classmethod
    def _non_negative_generation(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        return value


class LineFollowModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str


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


class VisionLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    rectification: Optional[dict[str, object]] = None

    @field_validator("rectification")
    @classmethod
    def _valid_rectification(cls, value):
        if value is None:
            return None
        from core_common.protocol.vision_preview import PreviewRectification
        return PreviewRectification.from_mapping(value).as_dict()


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
               mission_service: Optional[MissionService] = None,
               proposal_store: Optional[ProposalStore] = None,
               goal_evidence_service: Optional[GoalEvidenceService] = None,
               candidate_resolver=None,
               policy_evidence: Optional[PolicyEvidenceStore] = None,
               start_task_dispatcher: bool = True,
               site_users: Optional[Mapping[str, Mapping[str, str]]] = None,
               discovery=None, discovery_token: Optional[str] = None,
               vision_lease_secret: Optional[str] = None,
               vision_sources: tuple[str, ...] = (),
               omx_instances: Optional[Mapping[str, str]] = None,
               omx_socket_root: Path | str = "/run/rosy/omx",
               omx_stop_transport=None,
               enable_mission_dispatcher: bool = False,
               omx_action_transport=None,
               enrollment=None,
               robot_credential_key: Optional[str] = None,
               mission_model_turn_max_rows: int = 10_000) -> FastAPI:
    mission_configured = mission_service is not None or proposal_store is not None
    if (mission_service is None) != (proposal_store is None):
        raise ValueError("Mission API requires both MissionService and ProposalStore")
    if candidate_resolver is not None and not mission_configured:
        raise ValueError("Mission candidate resolver requires MissionService and ProposalStore")
    if candidate_resolver is not None and not callable(candidate_resolver):
        raise ValueError("Mission candidate resolver must be callable")
    if goal_evidence_service is not None and not mission_configured:
        raise ValueError("goal evidence requires the persistent Mission API")
    if goal_evidence_service is not None and goal_evidence_service.missions is not mission_service:
        raise ValueError("goal evidence service must use the configured MissionService")
    if mission_configured and task_service is None:
        raise ValueError("Mission API requires persistent API audit and dispatch-control storage")
    if mission_configured:
        database_paths = {
            task_service.store.path.resolve(), mission_service.store.path.resolve(),
            proposal_store.path.resolve(),
        }
        if goal_evidence_service is not None:
            database_paths.add(goal_evidence_service.store.path.resolve())
        if len(database_paths) != 1:
            raise ValueError("Mission, proposal, audit, and resource claims must share one SQLite database")
    if site_users is not None and task_service is None:
        raise ValueError("per-user site authorization requires persistent task/audit storage")
    if bool(discovery) != bool(discovery_token):
        raise ValueError("discovery and its dedicated credential must be configured together")
    if discovery_token is not None and (discovery_token == console_token
                                        or console.uses_rest_token(discovery_token)
                                        or console.uses_agent_pairing_token(discovery_token)):
        raise ValueError("discovery credential must differ from Fleet and robot credentials")
    configured_omx = dict(omx_instances or {})
    if len(set(configured_omx.values())) != len(configured_omx):
        raise ValueError("each OMX instance may be configured only once")
    stop_transport = omx_stop_transport
    if configured_omx and stop_transport is None:
        stop_transport = UnixLocalStopTransport(omx_socket_root)
    if enable_mission_dispatcher and (not mission_configured or candidate_resolver is None):
        raise ValueError("Mission dispatcher requires the complete Mission API and candidate resolver")
    if enable_mission_dispatcher and not configured_omx:
        raise ValueError("Mission dispatcher requires configured OMX workcells")
    action_transport = omx_action_transport
    if enable_mission_dispatcher and action_transport is None:
        action_transport = UnixLocalActionTransport(omx_socket_root)
    mission_dispatcher = (
        MissionDispatcher(
            mission_service, task_service.store, action_transport, configured_omx,
            on_action_terminal=(goal_evidence_service.on_action_terminal
                                if goal_evidence_service is not None else None),
        )
        if enable_mission_dispatcher else None
    )
    mission_progress = (
        MissionProgressService(mission_service.store) if mission_configured else None
    )
    mission_model_turn_store = (
        MissionModelTurnStore(
            mission_service.store.path, max_rows=mission_model_turn_max_rows,
        ) if mission_configured else None
    )
    mission_model_turn_scheduler = (
        MissionModelTurnScheduler(
            mission_service=mission_service, progress_service=mission_progress,
            turn_store=mission_model_turn_store, policy_revision="er2-feedback-v1",
        ) if mission_configured else None
    )
    vision_signer = VisionLeaseSigner(vision_lease_secret) if vision_lease_secret else None
    if vision_signer is not None:
        if console_token is not None and hmac.compare_digest(vision_lease_secret, console_token):
            raise ValueError("vision preview secret must differ from Fleet credentials")
        if (console.uses_rest_token(vision_lease_secret)
                or console.uses_agent_pairing_token(vision_lease_secret)):
            raise ValueError("vision preview secret must differ from robot credentials")
        if discovery_token is not None and hmac.compare_digest(vision_lease_secret, discovery_token):
            raise ValueError("vision preview secret must differ from discovery credentials")
        if sightings is not None and sightings.uses_token(vision_lease_secret):
            raise ValueError("vision preview secret must differ from sighting credentials")
        vision_secret_digest = sha256(vision_lease_secret.encode("utf-8")).hexdigest()
        if site_users is not None and any(
                hmac.compare_digest(vision_secret_digest, digest) for digest in site_users):
            raise ValueError("vision preview secret must differ from site user credentials")
        if len(set(vision_sources)) != len(vision_sources) or any(
                not isinstance(source, str) or not source for source in vision_sources):
            raise ValueError("vision preview sources must be unique non-empty ids")

    @asynccontextmanager
    async def lifespan(app):
        dispatcher = None
        mission_worker = None
        proposal_expiry = None
        goal_evidence_worker = None
        mission_feedback_scheduler = None
        if task_service is not None and start_task_dispatcher:
            dispatcher = asyncio.create_task(_task_dispatch_loop(console, task_service))
        if proposal_store is not None:
            proposal_expiry = asyncio.create_task(_proposal_expiry_loop(proposal_store))
        if mission_dispatcher is not None:
            mission_worker = asyncio.create_task(_mission_dispatch_loop(mission_dispatcher))
        if goal_evidence_service is not None:
            goal_evidence_worker = asyncio.create_task(
                _goal_evidence_expiry_loop(goal_evidence_service)
            )
        if mission_model_turn_scheduler is not None:
            mission_feedback_scheduler = asyncio.create_task(
                _mission_feedback_schedule_loop(mission_model_turn_scheduler)
            )
        try:
            yield
        finally:
            for background in (dispatcher, mission_worker, proposal_expiry,
                               goal_evidence_worker, mission_feedback_scheduler):
                if background is not None:
                    background.cancel()
                    try:
                        await background
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
    app.state.mission_service = mission_service
    app.state.goal_evidence_service = goal_evidence_service
    app.state.mission_progress = mission_progress
    app.state.mission_model_turn_store = mission_model_turn_store
    app.state.mission_model_turn_scheduler = mission_model_turn_scheduler
    app.state.mission_dispatcher = mission_dispatcher
    app.state.proposal_store = proposal_store
    app.state.omx_instances = configured_omx
    if task_service is not None:
        if hub is not None:
            hub.set_event_callback(task_service.project_core_event)

        async def release_traffic_task(mission: dict) -> None:
            task_service.traffic_queue_released(mission["task_id"])

        console.set_task_queue_release_callback(release_traffic_task)

    def dispatch_local_omx_stops(control: Mapping | None, *, reason: str) -> dict:
        if not configured_omx:
            return {"state": "NOT_CONFIGURED", "instances": []}
        if stop_transport is None or control is None:
            return {"state": "UNKNOWN", "instances": [
                {"workcell_id": workcell_id, "instance_id": instance_id,
                 "state": "UNKNOWN", "reason": "FLEET_DISPATCH_CONTROL_UNAVAILABLE"}
                for workcell_id, instance_id in configured_omx.items()
            ]}
        results = []
        for workcell_id, instance_id in configured_omx.items():
            try:
                outcome = stop_transport.stop(
                    workcell_id=workcell_id, instance_id=instance_id,
                    authority_epoch=control["authority_epoch"],
                    dispatch_generation=control["generation"], reason=reason,
                )
                if not isinstance(outcome, Mapping):
                    outcome = {"state": "UNKNOWN", "reason": "INVALID_STOP_RECEIPT"}
            except Exception as exc:
                _LOG.exception("OMX StopLocal fanout failed instance=%s", instance_id)
                outcome = {"state": "UNKNOWN", "reason": type(exc).__name__}
            results.append({"workcell_id": workcell_id, "instance_id": instance_id,
                            **dict(outcome)})
        states = {row["state"] for row in results}
        overall = "LOCAL_LATCHED" if states == {"LOCAL_LATCHED"} else (
            "REQUESTED" if states and states <= {"LOCAL_LATCHED", "REQUESTED"}
            else "UNKNOWN"
        )
        return {"state": overall, "instances": results}

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

    if robot_credential_key is not None:
        # D-361 4: the register key is its own secret, never another site credential.
        key = robot_credential_key.strip()
        key_digest = sha256(key.encode("utf-8")).hexdigest()
        same = lambda other: other is not None and hmac.compare_digest(key, other.strip())  # noqa: E731
        if (same(console_token) or same(discovery_token) or same(vision_lease_secret)
                or console.uses_rest_token(key) or console.uses_agent_pairing_token(key)
                or (sightings is not None and sightings.uses_token(key))
                or (policy_evidence is not None and policy_evidence.uses_token(key))
                or any(hmac.compare_digest(key_digest, digest) for digest in principals)):
            raise ValueError("robot credential key must differ from every other site secret")

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
                and request.url.path != "/api/fleet/sightings"
                and request.url.path != "/api/fleet/policy-evidence"):
            try:
                request.state.site_api_audit_id = task_service.store.begin_api_audit(
                    principal_id=principal.principal_id, role=principal.role,
                    method=request.method, path=request.url.path,
                )
            except (OSError, sqlite3.Error, ValueError):
                if request.url.path == "/api/fleet/estop":
                    _LOG.exception(
                        "emergency stop audit unavailable; continuing stop request principal=%s",
                        principal.principal_id,
                    )
                    return principal
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

    def require_named_operator(principal: SitePrincipal = Depends(require_operator)) -> SitePrincipal:
        if not principals:
            raise HTTPException(status_code=403, detail={
                "code": "OPERATOR_IDENTITY_REQUIRED",
                "message": "mission admission requires a configured named operator credential",
            })
        return principal

    read_guard = [Depends(require_viewer)]
    operator_guard = [Depends(require_operator)]

    if discovery is not None:
        if principals and any(hmac.compare_digest(
                sha256(discovery_token.encode("utf-8")).hexdigest(), digest)
                for digest in principals):
            raise ValueError("discovery credential must differ from site user credentials")

        @app.post("/api/fleet/discovery/scan", tags=["fleet-discovery"])
        async def discovery_scan(body: DiscoveryScanPayload,
                                 authorization: Optional[str] = Header(default=None)) -> dict:
            expected = f"Bearer {discovery_token}"
            if not authorization or not hmac.compare_digest(authorization, expected):
                raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})
            try:
                discovery.replace_scan(body.devices)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_SCAN",
                                                             "message": str(exc)}) from exc
            if enrollment is not None and enrollment.available:
                await enrollment.on_discovery(discovery.rows())
                await enrollment.settle_holds()
            return {"accepted": True}

        @app.get("/api/fleet/discovery", dependencies=read_guard,
                 tags=["fleet-discovery"])
        def discovery_readback() -> dict:
            identities = hub.registry.identity_snapshot() if hub is not None else {}
            enrolled = enrollment.enrolled_names() if enrollment is not None else {}
            return discovery.snapshot(console.registered_endpoints, identities, enrolled)

    if enrollment is not None:
        from fleet.server.enrollment_routes import install_enrollment_routes

        install_enrollment_routes(app, enrollment, require_viewer=require_viewer,
                                  require_operator=require_operator,
                                  named_identity=bool(principals))

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

    if policy_evidence is not None:
        if console_token is not None and policy_evidence.uses_token(console_token):
            raise ValueError("policy evidence credentials must differ from the console token")
        if principals and policy_evidence.reuses_any(
                lambda candidate: any(
                    hmac.compare_digest(sha256(candidate.encode("utf-8")).hexdigest(), digest)
                    for digest in principals)):
            raise ValueError("site user and policy evidence credentials must differ")
        if policy_evidence.reuses_any(console.uses_rest_token):
            raise ValueError("policy evidence credentials must differ from robot REST tokens")
        if policy_evidence.reuses_any(console.uses_agent_pairing_token):
            raise ValueError("policy evidence credentials must differ from CORE Agent pairing tokens")

        @app.post("/api/fleet/policy-evidence", tags=["policy-evidence"])
        async def submit_policy_evidence(body: PolicyEvidencePayload,
                                         authorization: Optional[str] = Header(default=None)) -> dict:
            try:
                return policy_evidence.accept(authorization, body)
            except PolicyEvidenceError as exc:
                reason = str(exc).split(":", 1)[0].strip()
                raise HTTPException(status_code=status_code_for(reason),
                                    detail={"code": reason,
                                            "message": "policy evidence was not accepted"}) from exc

        @app.get("/api/fleet/policy-evidence/latest", dependencies=read_guard,
                 tags=["policy-evidence"])
        async def policy_evidence_readback() -> dict:
            return {"evidence": policy_evidence.latest()}

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

    if task_service is not None:
        @app.get("/api/fleet/dispatch-control", dependencies=read_guard,
                 tags=["fleet-control"])
        def dispatch_control_readback() -> dict:
            return task_service.store.dispatch_control()

        @app.post("/api/fleet/dispatch/rearm", dependencies=operator_guard,
                  tags=["fleet-control"])
        async def dispatch_rearm(
            body: DispatchRearmRequest,
            principal: SitePrincipal = Depends(require_operator),
        ) -> dict:
            try:
                control = task_service.store.rearm_dispatch(
                    expected_generation=body.expected_generation,
                    actor_id=principal.principal_id,
                )
            except InvalidTaskTransition as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "DISPATCH_REARM_REFUSED", "message": str(exc),
                }) from exc
            if configured_omx:
                local_rearm = []
                for workcell_id, instance_id in configured_omx.items():
                    try:
                        result = stop_transport.rearm(
                            workcell_id=workcell_id, instance_id=instance_id,
                            authority_epoch=control["authority_epoch"],
                            dispatch_generation=control["generation"],
                        )
                        if not isinstance(result, Mapping):
                            result = {"state": "UNKNOWN", "reason": "INVALID_REARM_RECEIPT"}
                    except Exception as exc:
                        _LOG.exception("OMX local rearm failed instance=%s", instance_id)
                        result = {"state": "UNKNOWN", "reason": type(exc).__name__}
                    local_rearm.append({"workcell_id": workcell_id,
                                        "instance_id": instance_id, **dict(result)})
                if any(item["state"] != "OPEN" for item in local_rearm):
                    try:
                        stopped = task_service.store.trip_stop_latch(
                            actor_id=principal.principal_id,
                            reason="OMX_LOCAL_REARM_FAILED",
                        )
                    except Exception:
                        _LOG.exception("failed to close Fleet dispatch after OMX rearm refusal")
                        try:
                            stopped = task_service.store.dispatch_control()
                        except Exception:
                            stopped = None
                    await asyncio.to_thread(
                        dispatch_local_omx_stops, stopped, reason="OMX_REARM_ROLLBACK",
                    )
                    raise HTTPException(status_code=409, detail={
                        "code": "LOCAL_WORKCELL_REARM_FAILED",
                        "fleet_dispatch": stopped,
                        "omx_local_rearm": local_rearm,
                    })
                control["omx_local_rearm"] = local_rearm
            return control

    if mission_service is not None:
        if goal_evidence_service is not None:
            @app.post("/api/fleet/goal-evidence", tags=["fleet-goal-evidence"])
            def fleet_goal_evidence(
                body: dict,
                x_goal_evidence_token: Optional[str] = Header(default=None),
            ) -> dict:
                if not isinstance(body, dict) or set(body) != {"mission_id", "evidence"}:
                    raise HTTPException(status_code=422, detail={
                        "code": "INVALID_GOAL_EVIDENCE_ENVELOPE",
                        "message": "body requires mission_id and evidence",
                    })
                if not isinstance(body["mission_id"], str) or not isinstance(body["evidence"], dict):
                    raise HTTPException(status_code=422, detail={
                        "code": "INVALID_GOAL_EVIDENCE_ENVELOPE",
                    })
                if not x_goal_evidence_token:
                    raise HTTPException(status_code=401, detail={"code": "PRODUCER_UNAUTHORIZED"})
                try:
                    return goal_evidence_service.submit(
                        token=x_goal_evidence_token, mission_id=body["mission_id"],
                        raw_evidence=body["evidence"],
                    )
                except GoalEvidenceSubmissionError as exc:
                    raise HTTPException(status_code=exc.status_code, detail={
                        "code": exc.code, "message": str(exc),
                    }) from exc

        def _mission_candidate_result(proposal: dict, mission: dict | None) -> dict:
            return {
                "proposal": {
                    "proposal_id": proposal["proposal_id"],
                    "request_key": proposal["request_key"],
                    "state": proposal["state"],
                    "candidate": proposal["candidate"],
                    "source_mission_id": proposal.get("source_mission_id"),
                    "source_action_id": proposal.get("source_action_id"),
                    "source_attempt_id": proposal.get("source_attempt_id"),
                    "source_dispatch_generation": proposal.get("source_dispatch_generation"),
                    "source_event_watermark": proposal.get("source_event_watermark"),
                    "source_observation_id": proposal.get("source_observation_id"),
                    "supersedes_mission_id": proposal.get("supersedes_mission_id"),
                    "reason": proposal["reason"],
                    "expires_at": proposal["expires_at"],
                },
                "mission": mission,
            }

        def _mission_snapshot_response(proposal: dict, snapshot: dict) -> dict:
            return {
                **_mission_candidate_result(proposal, snapshot["mission"]),
                "history": snapshot["history"],
                "history_truncated": snapshot["history_truncated"],
                "progress": snapshot["progress"],
            }

        def _resolve_candidate(candidate: Mapping, *, workcell_id: str,
                               instance_id: str, now: float) -> dict:
            try:
                resolution = candidate_resolver(
                    candidate, workcell_id=workcell_id, instance_id=instance_id, now=now,
                )
            except ProposalRejected:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                raise ProposalRejected("CANDIDATE_UNRESOLVED") from exc
            if not isinstance(resolution, Mapping):
                raise ProposalRejected("CANDIDATE_UNRESOLVED")
            if set(resolution) != {"plan", "goal_predicate", "resources"}:
                raise ProposalRejected("CANDIDATE_UNRESOLVED")
            if not isinstance(resolution["plan"], Mapping) or not isinstance(
                    resolution["goal_predicate"], Mapping):
                raise ProposalRejected("CANDIDATE_UNRESOLVED")
            try:
                encoded = json.dumps(dict(resolution), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ProposalRejected("INVALID_RESOLUTION_METADATA") from exc
            if len(encoded) > 64 * 1024:
                raise ProposalRejected("RESOLUTION_METADATA_TOO_LARGE")

            def reject_sensitive_fields(item):
                if isinstance(item, Mapping):
                    for key, nested in item.items():
                        if not isinstance(key, str):
                            raise ProposalRejected("INVALID_RESOLUTION_METADATA")
                        if key.casefold() in {
                                "principal_id", "actor_id", "image_bytes", "image_data",
                                "raw_image", "frame_bytes", "api_key", "authorization",
                                "access_token", "bearer_token"}:
                            raise ProposalRejected("RESOLUTION_CONTAINS_FORBIDDEN_DATA")
                        reject_sensitive_fields(nested)
                elif isinstance(item, list):
                    for nested in item:
                        reject_sensitive_fields(nested)

            reject_sensitive_fields(resolution)
            source_raw = resolution["plan"].get("source_evidence")
            destination_raw = resolution["plan"].get("destination_evidence")
            try:
                source_evidence = ResolvedTargetEvidence.model_validate(source_raw)
                destination_evidence = ResolvedTargetEvidence.model_validate(destination_raw)
            except (ValidationError, TypeError) as exc:
                raise ProposalRejected("TARGET_EVIDENCE_INVALID") from exc
            candidate_observation = candidate.get("source_observation")
            if not isinstance(candidate_observation, Mapping):
                raise ProposalRejected("OBSERVATION_PROVENANCE_INVALID")
            try:
                observed = datetime.fromisoformat(
                    str(candidate_observation["observed_at"]).replace("Z", "+00:00"))
                if observed.tzinfo is None or observed.utcoffset() is None:
                    raise ValueError("timezone required")
                elapsed = observed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                capture_time_ns = ((elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000
                                   + elapsed.microseconds * 1_000)
                expected_identity = (
                    candidate_observation["observation_id"],
                    candidate_observation["image_sha256"],
                    candidate_observation["camera_id"],
                    candidate_observation["frame_id"],
                    candidate_observation["calibration_revision"],
                    candidate_observation["transform_revision"],
                    capture_time_ns,
                )
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ProposalRejected("OBSERVATION_PROVENANCE_INVALID") from exc
            for evidence in (source_evidence, destination_evidence):
                actual_identity = (
                    evidence.observation_id, evidence.frame_sha256,
                    evidence.camera_identity, evidence.optical_frame_id,
                    evidence.calibration_revision, evidence.transform_revision,
                    evidence.capture_time_ns,
                )
                if actual_identity != expected_identity:
                    raise ProposalRejected("OBSERVATION_PROVENANCE_MISMATCH")
            resources = resolution["resources"]
            if (not isinstance(resources, list) or not resources
                    or any(not isinstance(item, (tuple, list)) or len(item) != 2
                           or any(not isinstance(part, str) or not part.strip() for part in item)
                           for item in resources)):
                raise ProposalRejected("CANDIDATE_UNRESOLVED")
            goal = resolution["goal_predicate"]
            object_id, destination_id = goal.get("object_id"), goal.get("destination_id")
            if (source_evidence.object_id != object_id
                    or destination_evidence.object_id != destination_id
                    or source_evidence.object_id == destination_evidence.object_id):
                raise ProposalRejected("TARGET_GOAL_MISMATCH")
            required_claims = {
                ("workcell", workcell_id), ("object", object_id),
                ("object", destination_id),
            }
            if (not all(isinstance(value, str) and value.strip()
                        for value in (object_id, destination_id))
                    or not required_claims.issubset({tuple(item) for item in resources})):
                raise ProposalRejected("CANDIDATE_RESOURCES_INCOMPLETE")
            plan = dict(resolution["plan"])
            plan["source_evidence"] = source_evidence.model_dump(mode="json")
            plan["destination_evidence"] = destination_evidence.model_dump(mode="json")
            plan["observation_revision"] = plan.get(
                "observation_revision", source_evidence.observation_id,
            )
            for revision_name in ("capability_revision", "config_revision",
                                  "observation_revision"):
                revision = plan.get(revision_name)
                if (not isinstance(revision, str) or not revision.strip()
                        or revision != revision.strip() or len(revision) > 128):
                    raise ProposalRejected(f"{revision_name.upper()}_MISSING")
            if plan["observation_revision"] != source_evidence.observation_id:
                raise ProposalRejected("OBSERVATION_REVISION_MISMATCH")
            return {"plan": plan,
                    "goal_predicate": dict(resolution["goal_predicate"]),
                    "resources": [list(item) for item in resources]}

        def _stable_resolution(value: Mapping) -> str:
            def strip_transient(item):
                if isinstance(item, Mapping):
                    return {key: strip_transient(nested) for key, nested in item.items()
                            if key not in {"resolved_at", "validated_at", "age_ms"}}
                if isinstance(item, list):
                    return [strip_transient(nested) for nested in item]
                return item
            return json.dumps(strip_transient(value), sort_keys=True, separators=(",", ":"),
                              allow_nan=False)

        @app.post("/api/fleet/proposals", dependencies=operator_guard, tags=["fleet-missions"])
        def fleet_proposal_create(body: MissionCandidateRequest,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
            try:
                saved = proposal_store.create(
                    principal_id=principal.principal_id, request_key=body.request_key,
                    workcell_id=body.workcell_id, instance_id=body.instance_id,
                    candidate=body.candidate,
                )
            except ProposalConflict as exc:
                raise HTTPException(status_code=409, detail={"code": "REQUEST_CONFLICT",
                                                             "message": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={"code": "INVALID_CANDIDATE",
                                                             "message": str(exc)}) from exc
            proposal = saved["proposal"]
            return {"created": saved["created"], "proposal": {
                "proposal_id": proposal["proposal_id"], "request_key": proposal["request_key"],
                "state": proposal["state"], "candidate": proposal["candidate"],
                "reason": proposal["reason"], "expires_at": proposal["expires_at"],
            }, "physical_submission": "NOT_CONNECTED"}

        @app.get("/api/fleet/proposals/{proposal_id}", dependencies=read_guard,
                 tags=["fleet-missions"])
        def fleet_proposal_read(proposal_id: str,
                                principal: SitePrincipal = Depends(require_viewer)) -> dict:
            proposal = proposal_store.get(proposal_id, principal_id=principal.principal_id)
            if proposal is None:
                raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})
            mission = mission_service.get(proposal_id)
            return _mission_candidate_result(proposal, mission)

        @app.post("/api/fleet/proposals/{proposal_id}/resolve", dependencies=operator_guard,
                  tags=["fleet-missions"])
        def fleet_proposal_resolve(proposal_id: str,
                                   principal: SitePrincipal = Depends(require_operator)) -> dict:
            if candidate_resolver is None:
                raise HTTPException(status_code=503, detail={"code": "MISSION_RESOLVER_UNAVAILABLE"})
            proposal = proposal_store.get(proposal_id, principal_id=principal.principal_id)
            if proposal is None:
                raise HTTPException(status_code=404, detail={"code": "PROPOSAL_NOT_FOUND"})
            if proposal["state"] == "RESOLVED":
                return {"created": False,
                        **_mission_candidate_result(proposal, mission_service.get(proposal_id))}
            if proposal["state"] != "PROPOSED":
                raise HTTPException(status_code=409, detail={
                    "code": proposal["reason"] or "PROPOSAL_RESOLUTION_NOT_AVAILABLE",
                })
            try:
                resolution = _resolve_candidate(
                    proposal["candidate"], workcell_id=proposal["workcell_id"],
                    instance_id=proposal["instance_id"], now=time.time(),
                )
                resolved, mission, created = proposal_store.finalize_resolution(
                    mission_service.store, proposal_id=proposal["proposal_id"],
                    principal_id=principal.principal_id, resolution=resolution,
                    mission_request=resolution,
                )
            except ProposalRejected as exc:
                rejected = proposal_store.set_resolution(
                    proposal["proposal_id"], state="REJECTED", reason=exc.code,
                )
                raise HTTPException(status_code=409, detail={
                    "code": exc.code, "proposal_id": rejected["proposal_id"],
                }) from exc
            except (MissionConflict, ProposalConflict) as exc:
                raise HTTPException(status_code=409, detail={"code": "MISSION_CONFLICT",
                                                             "message": str(exc)}) from exc
            return {"created": created, **_mission_candidate_result(resolved, mission)}

        @app.get("/api/fleet/missions/{mission_id}", dependencies=read_guard,
                 response_model=MissionProgressReadResponse,
                 tags=["fleet-missions"])
        def fleet_mission_read(mission_id: str,
                               principal: SitePrincipal = Depends(require_viewer)) -> dict:
            proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
            if proposal is None or proposal["state"] != "RESOLVED":
                raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
            snapshot = mission_progress.snapshot(mission_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
            return _mission_snapshot_response(proposal, snapshot)

        @app.get("/api/fleet/missions/{mission_id}/events", dependencies=read_guard,
                 response_model=MissionProgressEventPage,
                 responses={
                     409: {"model": MissionCursorResetError},
                     410: {"model": MissionCursorExpiredError},
                 }, tags=["fleet-missions"])
        def fleet_mission_events(
            mission_id: str,
            after_event_id: int = Query(default=0, ge=0),
            limit: int = Query(default=50, ge=1, le=200),
            principal: SitePrincipal = Depends(require_viewer),
        ) -> dict:
            proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
            if proposal is None or proposal["state"] != "RESOLVED":
                raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
            page = mission_progress.events(
                mission_id, after_event_id=after_event_id, limit=limit,
            )
            if page is None:
                raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
            if page["cursor_state"] != "OK":
                snapshot = mission_progress.snapshot(mission_id)
                status = 410 if page["cursor_state"] == "EXPIRED" else 409
                code = ("MISSION_CURSOR_EXPIRED" if status == 410 else
                        "MISSION_CURSOR_RESET_REQUIRED")
                raise HTTPException(status_code=status, detail={
                    "code": code, "snapshot_restart_required": True,
                    "cursor_floor": page["cursor_floor"],
                    "snapshot": _mission_snapshot_response(proposal, snapshot),
                })
            contract_page = {key: value for key, value in page.items()
                             if key != "cursor_state"}
            return MissionProgressEventPage.model_validate(contract_page).model_dump(mode="json")

        @app.post("/api/fleet/missions/{mission_id}/admit", dependencies=operator_guard,
                  tags=["fleet-missions"])
        def fleet_mission_admit(mission_id: str, body: MissionAdmitRequest,
                                principal: SitePrincipal = Depends(require_named_operator)) -> dict:
            proposal = proposal_store.get(mission_id, principal_id=principal.principal_id)
            if proposal is None:
                raise HTTPException(status_code=404, detail={"code": "MISSION_NOT_FOUND"})
            mission = mission_service.get(mission_id)
            if mission is None or proposal["state"] != "RESOLVED":
                raise HTTPException(status_code=409, detail={"code": "PROPOSAL_NOT_RESOLVED"})
            try:
                current = _resolve_candidate(
                    proposal["candidate"], workcell_id=mission["workcell_id"],
                    instance_id=mission["instance_id"], now=time.time(),
                )
                if _stable_resolution(current) != _stable_resolution(proposal["resolution"]):
                    raise ProposalRejected("EVIDENCE_OR_CAPABILITY_CHANGED")
                admitted = mission_service.admit(
                    mission_id, actor_id=principal.principal_id,
                    expected_generation=body.expected_generation,
                    resources=[tuple(item) for item in proposal["resolution"]["resources"]],
                )
            except ProposalRejected as exc:
                raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
            except (MissionConflict, ValueError) as exc:
                raise HTTPException(status_code=409, detail={"code": "MISSION_ADMISSION_REFUSED",
                                                             "message": str(exc)}) from exc
            return {"proposal": _mission_candidate_result(proposal, admitted)["proposal"],
                    "mission": admitted, "physical_submission": "NOT_CONNECTED"}

    @app.get("/api/fleet/session", dependencies=read_guard, tags=["fleet-auth"])
    def fleet_session(request: Request) -> dict:
        principal: SitePrincipal = request.state.site_principal
        return {"principal_id": principal.principal_id, "role": principal.role}

    @app.get("/api/fleet/vision/sources", dependencies=read_guard, tags=["vision-preview"])
    def vision_preview_sources() -> dict:
        if vision_signer is None:
            raise HTTPException(status_code=503, detail={"code": "VISION_PREVIEW_DISABLED"})
        return {"sources": list(vision_sources)}

    @app.post("/api/fleet/vision/lease", dependencies=read_guard, tags=["vision-preview"])
    def vision_preview_lease(body: VisionLeaseRequest,
                             principal: SitePrincipal = Depends(require_viewer)) -> dict:
        if vision_signer is None:
            raise HTTPException(status_code=503, detail={"code": "VISION_PREVIEW_DISABLED"})
        if body.source_id not in vision_sources:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_VISION_SOURCE"})
        token = vision_signer.issue(principal_id=principal.principal_id,
                                    source_id=body.source_id, ttl_s=60,
                                    rectification=body.rectification)
        return {"source_id": body.source_id, "lease": token,
                "frame_path": f"/api/vision/sources/{body.source_id}/frame",
                "expires_in_s": 60}

    @app.get("/api/fleet/site-map", dependencies=read_guard, tags=["sightings"])
    async def fleet_site_map() -> dict:
        # D-257: the overhead-covered rectangle is display geometry, not a motion input.
        site_map = sightings.site_map() if sightings is not None and sightings.enabled else None
        if site_map is None:
            raise HTTPException(status_code=404, detail={"code": "NO_SITE_MAP",
                                                         "message": "no site camera geometry configured"})
        return site_map

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

    @app.post("/api/fleet/robots/{robot_id}/line-follow", dependencies=operator_guard,
              tags=["fleet"])
    async def fleet_line_follow_mode(
        robot_id: str, body: LineFollowModeRequest,
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        try:
            result = await console.line_follow_mode(robot_id, body.mode)
            return {"robot_id": robot_id, "actor_id": principal.principal_id, "result": result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_MODE"}) from exc
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

    @app.post(
        "/api/fleet/do",
        dependencies=operator_guard,
        tags=["fleet"],
        openapi_extra={
            "requestBody": {
                "content": {"application/json": {"schema": request_schema()}},
            },
        },
    )
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
                    stop_control = None
                    if call.verb == "estop":
                        if task_service is not None:
                            try:
                                stop_control = task_service.store.trip_stop_latch(
                                    actor_id=principal.principal_id,
                                )
                            except Exception:
                                _LOG.exception("dispatch latch unavailable for site E-stop")
                                try:
                                    stop_control = task_service.store.dispatch_control()
                                except Exception:
                                    _LOG.exception("dispatch readback unavailable for site E-stop")
                        cancel_pending_task_queue(actor_id=principal.principal_id)
                    result = await _site_call(console, call)
                    if call.verb == "estop":
                        result["omx_local_stop"] = await asyncio.to_thread(
                            dispatch_local_omx_stops, stop_control,
                            reason="FLEET_ESTOP",
                        )
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
        stop_control = None
        if task_service is not None:
            try:
                stop_control = task_service.store.trip_stop_latch(
                    actor_id=principal.principal_id,
                )
            except Exception:
                _LOG.exception(
                    "emergency stop dispatch latch unavailable; continuing stop fanout principal=%s",
                    principal.principal_id,
                )
                try:
                    stop_control = task_service.store.dispatch_control()
                except Exception:
                    _LOG.exception("emergency stop dispatch readback unavailable")
        local_stop_task = asyncio.to_thread(
            dispatch_local_omx_stops, stop_control, reason="FLEET_ESTOP",
        )
        result, local_stop = await asyncio.gather(console.estop_all(), local_stop_task)
        try:
            cancel_pending_task_queue(actor_id=principal.principal_id)
        except Exception:
            _LOG.exception(
                "emergency stop queue cleanup unavailable principal=%s",
                principal.principal_id,
            )
        result = dict(result)
        result["omx_local_stop"] = local_stop
        if stop_control is not None:
            result["fleet_dispatch_control"] = stop_control
        return result

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

    common_assets = _shared_assets(app.state.web_common)

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
                and row["state"].get("safety", {}).get("estop") is False
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


async def _proposal_expiry_loop(proposal_store: ProposalStore) -> None:
    while True:
        try:
            proposal_store.purge_expired()
        except (OSError, sqlite3.Error):
            _LOG.exception("expired Fleet proposal cleanup failed")
        await asyncio.sleep(3600)


async def _goal_evidence_expiry_loop(service: GoalEvidenceService) -> None:
    """Apply registered grace deadlines without enabling Action dispatch."""
    while True:
        try:
            service.hold_expired_without_evidence()
        except (OSError, sqlite3.Error, ValueError):
            _LOG.exception("goal evidence grace reconciliation failed")
        await asyncio.sleep(1.0)


async def _mission_feedback_schedule_loop(scheduler: MissionModelTurnScheduler) -> None:
    """Populate the durable outbox only; this loop never invokes a provider."""
    while True:
        try:
            before = scheduler.turn_store.capacity_dropped_count()
            await asyncio.to_thread(scheduler.poll_once)
            dropped = scheduler.turn_store.capacity_dropped_count()
            if dropped > before:
                _LOG.error(
                    "Mission feedback outbox is at capacity; dropped enqueue attempts=%d",
                    dropped,
                )
        except Exception:
            _LOG.exception("Mission feedback outbox scan failed")
        await asyncio.sleep(1.0)


async def _mission_dispatch_loop(dispatcher: MissionDispatcher) -> None:
    """Run the explicit, disabled-by-default Mission to OMX bridge off request handlers."""
    while True:
        try:
            await asyncio.to_thread(dispatcher.dispatch_next)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("Fleet Mission dispatcher cycle failed")
        await asyncio.sleep(0.25)
