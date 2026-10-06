"""Fleet 서버의 HTTP 표면 — 조합 뿌리.

경로는 로봇 계약(`/api/v1/...`)과 일부러 다르다. 관제 API 는 사이트 것이고, 로봇 것을
흉내 내면 둘 중 어느 쪽에 말하고 있는지 화면에서도 코드에서도 흐려진다.

인증: 이 서버는 robots.yaml 의 운영자 토큰을 들고 있다. 즉 이 포트에 닿는 사람은 현장의
모든 로봇을 움직일 수 있다. 그래서 기본은 루프백이고, 루프백 밖으로 열려면 콘솔 토큰을
반드시 받는다(`serve()` 가 강제한다).

구조 (D-362 P0-1): 이 파일은 구성 검증·lifespan·감사 미들웨어·비전 임대만 남고, 경로는
소유자 모듈이 단다 — mission_routes, task_dispatch_routes, intent_routes, console_routes,
ingest_routes, static_routes, enrollment_routes(D-361). 각 모듈은 자기 저장소·서비스의
생애를 가진다(app.py 1556줄 split 판정의 실행).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import sqlite3
from contextlib import asynccontextmanager
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from core_common.protocol.vision_preview import VisionLeaseSigner
from fleet.server.cancel_all import DriveCancelFence
from fleet.server.cell_job_store import CellJobStore
from fleet.server.console import FleetConsole
from fleet.server.goal_evidence_service import GoalEvidenceService
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.local_action_transport import UnixLocalActionTransport
from fleet.server.local_stop_transport import UnixLocalStopTransport
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_model_turn_scheduler import MissionModelTurnScheduler
from fleet.server.mission_model_turn_store import MissionModelTurnStore
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_service import MissionService
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.step_action_kinds import dispatch_open
from fleet.server.step_dispatcher import StepJobDispatcher
from fleet.server.stuck_resolver import ResolverConfig, StuckResolver
from fleet.server.stuck_resolver_loop import StuckResolverLoop
from fleet.server.task_service import FleetTaskService

from fleet.server.console_routes import install_console_routes
from fleet.server.background_workers import proposal_expiry_loop as _proposal_expiry_loop
from fleet.server.background_workers import goal_evidence_expiry_loop
from fleet.server.signal_routes import install_signal_routes
from fleet.server.ingest_routes import install_discovery_routes, install_ingest_routes
from fleet.server.intent_routes import install_intent_routes
from fleet.server.mission_routes import install_mission_routes
from fleet.server.site_auth import (
    SitePrincipal,
    assert_registry_credential_isolated,
    assert_pairing_sync_token_isolated,
    assert_robot_credential_key_isolated,
    build_authorize,
    build_role_guards,
    install_mutation_audit,
    parse_site_principals,
)
from fleet.server.static_routes import install_static_routes
from fleet.hub.server import fan_out_events as _fan_out_events
from fleet.server.task_dispatch_routes import (  # noqa: F401 — GoalRequest 재수출: test_task_contract_docs 참조
    GoalRequest,
    cancel_pending_task_queue,
    fanout_local_omx_stops,
    install_task_dispatch_routes,
)
from fleet.server.lane_route_routes import (  # noqa: F401 — RouteRequest 재수출 (D-463)
    RouteRequest,
    install_lane_route_routes,
)

_LOG = logging.getLogger(__name__)
_goal_evidence_expiry_loop = partial(goal_evidence_expiry_loop, logger=_LOG)
DEPLOYMENT_PROFILES = frozenset({"production", "simulation"})


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


def create_app(console: FleetConsole, *, console_token: Optional[str] = None,
               web_common: Optional[Path] = None, hub=None, sightings=None,
               task_service: Optional[FleetTaskService] = None,
               mission_service: Optional[MissionService] = None,
               proposal_store: Optional[ProposalStore] = None,
               cell_job_compiler=None,
               goal_evidence_service: Optional[GoalEvidenceService] = None,
               candidate_resolver=None,
               policy_evidence: Optional[PolicyEvidenceStore] = None,
               start_task_dispatcher: bool = True,
               site_users: Optional[Mapping[str, Mapping[str, str]]] = None,
               discovery=None, discovery_token: Optional[str] = None,
               approved_peer_directory_file: Optional[Path] = None,
               vision_lease_secret: Optional[str] = None,
               vision_sources: tuple[str, ...] = (),
               lan_camera_proxy: bool = False,
               omx_instances: Optional[Mapping[str, str]] = None,
               omx_socket_root: Path | str = "/run/rosy/omx",
               omx_stop_transport=None,
               enable_mission_dispatcher: bool = False,
               omx_action_transport=None,
               enrollment=None,
               robot_credential_key: Optional[str] = None,
               mission_model_turn_max_rows: int = 10_000,
               mission_model_turn_worker=None,
               post_action_observation_source=None,
               site_lanes: Optional[Mapping] = None,
               stuck_resolver_clients: Optional[Mapping[str, object]] = None,
               pairing=None, pairing_sync_token: Optional[str] = None,
               localization_service=None, deployment_profile: str = "production",
               central_registry=None, tracking=None,
               omx_cell_grant_revisions: Optional[Mapping[str, Mapping[str, str]]] = None,
               cell_item_pose_tolerance=None, cell_goal_registry=None,
               cell_app_service_id: str | None = None) -> FastAPI:
    if deployment_profile not in DEPLOYMENT_PROFILES:
        raise ValueError(f"unsupported deployment_profile {deployment_profile!r}")
    mission_configured = mission_service is not None or proposal_store is not None
    if (mission_service is None) != (proposal_store is None):
        raise ValueError("Mission API requires both MissionService and ProposalStore")
    if candidate_resolver is not None and not mission_configured:
        raise ValueError("Mission candidate resolver requires MissionService and ProposalStore")
    if candidate_resolver is not None and not callable(candidate_resolver):
        raise ValueError("Mission candidate resolver must be callable")
    if cell_job_compiler is not None and not mission_configured:
        raise ValueError("Cell Job compiler requires the persistent Mission API")
    if cell_job_compiler is not None and not callable(getattr(cell_job_compiler, "compile", None)):
        raise ValueError("Cell Job compiler must implement compile(recipe, cell)")
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
    cell_job_store = CellJobStore(mission_service.store.path) if mission_configured else None
    if cell_job_store is not None:
        cell_job_store.recover_after_startup()
    cell_job_resolver = None
    if cell_job_compiler is not None:
        from fleet.server.cell_goal_evidence import make_cell_job_resolver
        cell_job_resolver = make_cell_job_resolver(cell_job_compiler, cell_item_pose_tolerance)
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
    if enable_mission_dispatcher and not mission_configured:
        raise ValueError("Mission dispatcher requires the complete Mission API")
    if enable_mission_dispatcher and not configured_omx:
        raise ValueError("Mission dispatcher requires configured OMX workcells")
    action_transport = omx_action_transport
    if enable_mission_dispatcher and action_transport is None:
        action_transport = UnixLocalActionTransport(omx_socket_root)
    # D-403 §7: dispatch opens per (deployment profile, Action kind). PICK_PLACE has no open
    # profile; CELL_TRANSFER opens only in `simulation`, where StepJobDispatcher refuses any
    # other profile and any OMX instance without declared simulation grant revisions.
    mission_dispatcher = (
        MissionDispatcher(
            mission_service, task_service.store, action_transport, configured_omx,
            on_action_terminal=(goal_evidence_service.on_action_terminal
                                if goal_evidence_service is not None else None),
        )
        if enable_mission_dispatcher and dispatch_open(deployment_profile, "PICK_PLACE") else None
    )
    # Public Cell goal ingress (ported from main 778f50294/3ef12ca3e): sim_model_pose evidence is
    # accepted only in the simulation profile (D-403 §5) and judged against the stored predicate.
    cell_goal_evidence_service = None
    if cell_goal_registry is not None:
        from fleet.server.cell_goal_evidence_registry import CellGoalRegistry
        from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
        if deployment_profile != "simulation":
            raise ValueError("Cell goal evidence (sim_model_pose) is accepted only in the simulation profile")
        if cell_job_compiler is None or cell_job_store is None or not isinstance(cell_goal_registry, CellGoalRegistry):
            raise ValueError("Cell goal registry requires the persistent Cell Job API and compiler")
        cell_goal_evidence_service = CellGoalEvidenceService(cell_job_store, cell_goal_registry, GoalEvidenceStore(
            mission_service.store.path))

    def on_step_action_succeeded(job, _index):
        if cell_goal_evidence_service is None:
            return None
        try:  # a goal-processing failure never rewrites the recorded device success
            return cell_goal_evidence_service.on_action_terminal(job["mission_id"])
        except Exception:
            _LOG.exception("stored Cell goal evidence could not be applied for %s", job["mission_id"])
            return None

    cell_job_dispatcher = (
        StepJobDispatcher(cell_job_store, task_service.store, action_transport, configured_omx,
                          omx_cell_grant_revisions or {}, deployment_profile=deployment_profile,
                          on_step_action_succeeded=on_step_action_succeeded)
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
    if mission_model_turn_worker is not None:
        worker_store = getattr(mission_model_turn_worker, "store", None)
        consume_next = getattr(mission_model_turn_worker, "consume_next", None)
        if mission_model_turn_scheduler is None:
            raise ValueError("Mission model-turn worker requires persistent Mission services")
        if (worker_store is None or not callable(consume_next)
                or Path(worker_store.path).resolve() != Path(mission_model_turn_store.path).resolve()):
            raise ValueError("Mission model-turn worker must consume the configured shared SQLite outbox")
    if post_action_observation_source is not None:
        if mission_model_turn_worker is None:
            raise ValueError("post-action observation source requires an injected Mission model-turn worker")
        tool_dispatcher = getattr(mission_model_turn_worker, "dispatcher", None)
        if not hasattr(tool_dispatcher, "post_action_observation_source"):
            raise ValueError("Mission model-turn worker must use the Fleet feedback tool dispatcher")
        configured_source = tool_dispatcher.post_action_observation_source
        if configured_source is not None and configured_source is not post_action_observation_source:
            raise ValueError("Mission worker and app must share one post-action observation source")
        tool_dispatcher.post_action_observation_source = post_action_observation_source
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

    if localization_service is not None:
        # D-395 P2-6: the console badge reads the service's ladder (needs_human).
        console.set_localization_view(localization_service.view)

    if pairing_sync_token is not None and pairing is None:
        raise ValueError("pairing sync credential requires D-341 pairing (--pairing-ca with --tls-cert)")

    # D-421: one fence shared by cancel-all and the dispatcher closes the overlap window.
    drive_cancel = DriveCancelFence()

    @asynccontextmanager
    async def lifespan(app):
        dispatcher = None
        mission_worker = None
        cell_job_worker = None
        proposal_expiry = None
        goal_evidence_worker = None
        mission_feedback_scheduler = None
        mission_model_turn_worker_task = None
        localization_task = None
        signal_task = None
        if console._signals is not None:
            signal_task = asyncio.create_task(console._signals.run())
        app.state.signal_supervision = signal_task
        resolver_task = None
        if getattr(app.state, "stuck_resolver", None) is not None:
            resolver_task = asyncio.create_task(app.state.stuck_resolver.run())
        if localization_service is not None:
            localization_task = asyncio.create_task(localization_service.run())
        if task_service is not None and start_task_dispatcher:
            dispatcher = asyncio.create_task(
                _task_dispatch_loop(console, task_service, drive_cancel))
        if proposal_store is not None:
            proposal_expiry = asyncio.create_task(_proposal_expiry_loop(proposal_store, _LOG))
        if mission_dispatcher is not None:
            mission_worker = asyncio.create_task(_mission_dispatch_loop(mission_dispatcher))
        if cell_job_dispatcher is not None:
            cell_job_worker = asyncio.create_task(_mission_dispatch_loop(cell_job_dispatcher))
        if goal_evidence_service is not None:
            goal_evidence_worker = asyncio.create_task(
                _goal_evidence_expiry_loop(goal_evidence_service)
            )
        if mission_model_turn_scheduler is not None:
            mission_feedback_scheduler = asyncio.create_task(
                _mission_feedback_schedule_loop(mission_model_turn_scheduler)
            )
        if mission_model_turn_worker is not None:
            mission_model_turn_worker_task = asyncio.create_task(
                _mission_model_turn_worker_loop(mission_model_turn_worker)
            )
        try:
            yield
        finally:
            for background in (dispatcher, mission_worker, cell_job_worker, proposal_expiry,
                               goal_evidence_worker, mission_feedback_scheduler,
                               mission_model_turn_worker_task, localization_task,
                               signal_task, resolver_task):
                if background is not None:
                    background.cancel()
                    try:
                        await background
                    except asyncio.CancelledError:
                        pass
            close_observation_source = getattr(post_action_observation_source, "aclose", None)
            if callable(close_observation_source):
                await close_observation_source()
            if getattr(app.state, "start_points", None) is not None:
                app.state.start_points.close()

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
    app.state.cell_job_store = cell_job_store
    app.state.cell_job_compiler = cell_job_compiler
    app.state.goal_evidence_service = goal_evidence_service
    app.state.mission_progress = mission_progress
    app.state.mission_model_turn_store = mission_model_turn_store
    app.state.mission_model_turn_scheduler = mission_model_turn_scheduler
    app.state.mission_model_turn_worker = mission_model_turn_worker
    app.state.post_action_observation_source = post_action_observation_source
    app.state.mission_dispatcher = mission_dispatcher
    app.state.cell_job_dispatcher = cell_job_dispatcher
    app.state.cell_goal_evidence_service = cell_goal_evidence_service
    app.state.deployment_profile = deployment_profile
    app.state.proposal_store = proposal_store
    app.state.omx_instances = configured_omx
    app.state.localization_service = localization_service
    if task_service is not None:

        async def release_traffic_task(mission: dict) -> None:
            task_service.traffic_queue_released(mission["task_id"])

        console.set_task_queue_release_callback(release_traffic_task)

    install_mutation_audit(app, task_service)

    if hub is not None:
        from fleet.hub.server import install_hub_routes

        install_hub_routes(app, hub, hub_token=console_token)

    if tracking is not None and (sightings is None
                                 or tuple(tracking.sources) != tuple(sightings.sources)):
        raise ValueError("overhead tracking must use the configured sighting sources")
    principals = parse_site_principals(site_users, console)
    if cell_goal_evidence_service is not None:
        from fleet.server.cell_goal_evidence_routes import (
            assert_cell_producer_credentials_isolated, install_cell_goal_evidence_routes)
        other_tokens = (console_token, discovery_token, vision_lease_secret, robot_credential_key, pairing_sync_token)
        if goal_evidence_service is not None:
            other_tokens += tuple(item.token for item in goal_evidence_service.registry.producers)
        assert_cell_producer_credentials_isolated(
            cell_goal_registry, console=console, principals=principals,
            other_tokens=other_tokens, other_services=(sightings, policy_evidence),
        )
        install_cell_goal_evidence_routes(app, cell_goal_evidence_service)
    if principals:
        assert_registry_credential_isolated(console_token, principals)
    if robot_credential_key is not None:
        assert_robot_credential_key_isolated(
            robot_credential_key, console_token=console_token,
            discovery_token=discovery_token, vision_lease_secret=vision_lease_secret,
            console=console, sightings=sightings, policy_evidence=policy_evidence,
            principals=principals)
    if pairing_sync_token is not None:
        assert_pairing_sync_token_isolated(
            pairing_sync_token, console_token=console_token, discovery_token=discovery_token,
            vision_lease_secret=vision_lease_secret, robot_credential_key=robot_credential_key,
            console=console, sightings=sightings, policy_evidence=policy_evidence,
            principals=principals)
    authorize = build_authorize(console_token, principals, task_service)
    require_viewer, require_operator, require_named_operator, require_proposer = build_role_guards(
        authorize, principals)
    read_guard = [Depends(require_viewer)]

    def require_camera_viewer(request: Request) -> SitePrincipal:
        # Enable only behind the site proxy; its other routes strip client copies.
        if (lan_camera_proxy and request.headers.get("X-Rosy-Lan-Camera") == "1"
                and not request.headers.get("Authorization")):
            principal = SitePrincipal("lan-camera", "viewer")
            request.state.site_principal = principal
            if task_service is not None and request.method == "POST":
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
        return authorize(request, request.headers.get("Authorization"))
    operator_guard = [Depends(require_operator)]

    from fleet.server.peer_routes import install_peer_catalogue
    catalogue = install_peer_catalogue(app, console=console, enrollment=enrollment,
                                       pairing=pairing, read_guard=read_guard,
                                       directory_file=approved_peer_directory_file)
    if discovery is not None:
        install_discovery_routes(app, console=console, hub=hub, discovery=discovery,
                                 discovery_token=discovery_token, enrollment=enrollment,
                                 principals=principals, require_viewer=require_viewer,
                                 read_guard=read_guard, catalogue=catalogue)

    from fleet.server.central_registry_routes import install_registry_routes
    install_registry_routes(app, registry=central_registry, enrollment=enrollment, pairing=pairing,
                            sync_token=pairing_sync_token, require_viewer=require_viewer,
                            require_operator=require_operator, named_identity=bool(principals))
    from fleet.server.camera_peer_adapter import install_camera_peer
    app.state.camera_peer = install_camera_peer(app, pairing=pairing,
        current_users=lambda:site_users or {}, require_named_operator=require_named_operator)

    install_ingest_routes(app, console=console, console_token=console_token, hub=hub,
                          sightings=sightings, policy_evidence=policy_evidence,
                          principals=principals, require_viewer=require_viewer,
                          read_guard=read_guard)

    install_console_routes(app, console=console, sightings=sightings,
                           require_viewer=require_viewer, read_guard=read_guard,
                           operator_guard=operator_guard, site_lanes=site_lanes,
                           require_operator=require_operator,
                           answer_log_path=task_service.store.path if task_service else None,
                           tracking=tracking)
    if tracking is not None and tracking.enabled:
        from fleet.server.tracking_routes import install_tracking_routes
        install_tracking_routes(app, tracking=tracking, require_operator=require_operator,
                                read_guard=read_guard, operator_guard=operator_guard)
        from fleet.server.start_points import StartPointService
        from fleet.server.start_point_routes import install_start_point_routes
        install_start_point_routes(app, service=StartPointService(sources=tracking.sources,
                                                              calibrations=tracking.calibrations),
                                   read_guard=read_guard, require_operator=require_operator)
    install_signal_routes(app, signals=console._signals, require_viewer=require_viewer,
                          require_operator=require_operator, auth_configured=bool(principals or console_token))

    if stuck_resolver_clients is not None:
        app.state.stuck_resolver = StuckResolverLoop(
            app.state.fleet_gather, app.state.line_stuck, StuckResolver(ResolverConfig()),
            clients=lambda: stuck_resolver_clients)
    if hub is not None and (task_service is not None or stuck_resolver_clients is not None):
        resolver = getattr(app.state, "stuck_resolver", None)
        hub.set_event_callback(_fan_out_events(
            task_service.project_core_event if task_service is not None else None,
            resolver.wake if resolver is not None else None))

    install_task_dispatch_routes(app, console=console, task_service=task_service,
                                 configured_omx=configured_omx,
                                 stop_transport=stop_transport,
                                 require_viewer=require_viewer,
                                 require_operator=require_operator, require_named_operator=require_named_operator,
                                 read_guard=read_guard, operator_guard=operator_guard,
                                 drive_cancel=drive_cancel)
    install_lane_route_routes(app, console=console, task_service=task_service,
                              require_operator=require_operator,
                              operator_guard=operator_guard)

    proposal_create = proposal_resolve = None
    if mission_service is not None:
        proposal_create, proposal_resolve = install_mission_routes(
            app, mission_service=mission_service, proposal_store=proposal_store,
            cell_job_store=cell_job_store, cell_job_resolver=cell_job_resolver,
            goal_evidence_service=goal_evidence_service, mission_progress=mission_progress,
            candidate_resolver=candidate_resolver, require_viewer=require_viewer,
            require_operator=require_operator, require_named_operator=require_named_operator,
            require_proposer=require_proposer, read_guard=read_guard, operator_guard=operator_guard)
        from fleet.server.cell_job_routes import install_cell_job_routes

        install_cell_job_routes(app, cell_job_store=cell_job_store,
                                require_named_operator=require_named_operator,
                                operator_guard=operator_guard, read_guard=read_guard)

    from fleet.server.cell_app_routes import install_cell_app_routes
    install_cell_app_routes(app, mission_service=mission_service, compiler=cell_job_compiler,
                            service_id=cell_app_service_id, principals=principals,
                            proposal_create=proposal_create, proposal_resolve=proposal_resolve,
                            require_viewer=require_viewer, require_named_operator=require_named_operator)

    install_intent_routes(app, console=console, task_service=task_service,
                          require_operator=require_operator,
                          operator_guard=operator_guard,
                          local_stop_fanout=partial(
                              fanout_local_omx_stops, configured_omx, stop_transport),
                          cancel_pending=partial(
                              cancel_pending_task_queue, task_service, console))

    @app.get("/api/fleet/vision/sources", tags=["vision-preview"])
    def vision_preview_sources(_principal: SitePrincipal = Depends(require_camera_viewer)) -> dict:
        if vision_signer is None:
            raise HTTPException(status_code=503, detail={"code": "VISION_PREVIEW_DISABLED"})
        return {"sources": list(vision_sources)}

    @app.post("/api/fleet/vision/lease", tags=["vision-preview"])
    def vision_preview_lease(body: VisionLeaseRequest,
                             principal: SitePrincipal = Depends(require_camera_viewer)) -> dict:
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

    install_static_routes(app)

    return app


async def _task_dispatch_loop(console: FleetConsole, task_service: FleetTaskService,
                              drive_cancel: DriveCancelFence) -> None:
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
                available, dispatch=lambda task: drive_cancel.fenced_goal(console, task))
        except asyncio.CancelledError:
            raise
        except Exception:
            # A status read failure cannot establish availability. Leave work queued.
            pass
        await asyncio.sleep(0.25)


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


async def _mission_model_turn_worker_loop(worker) -> None:
    """Consume durable ER 2 turns only when an approved worker is injected."""
    while True:
        try:
            await worker.consume_next(worker_id="fleet-feedback")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("Fleet Mission model-turn worker cycle failed")
        await asyncio.sleep(0.25)


async def _mission_dispatch_loop(dispatcher: MissionDispatcher | StepJobDispatcher) -> None:
    """Run the explicit, disabled-by-default Mission to OMX bridge off request handlers."""
    while True:
        try:
            await asyncio.to_thread(dispatcher.dispatch_next)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("Fleet Mission dispatcher cycle failed")
        await asyncio.sleep(0.25)
