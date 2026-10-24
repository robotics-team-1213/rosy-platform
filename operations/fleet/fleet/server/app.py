"""Fleet 서버의 HTTP 표면 — 조합 뿌리.

경로는 로봇 계약(`/api/v1/...`)과 일부러 다르다. 관제 API 는 사이트 것이고, 로봇 것을
흉내 내면 둘 중 어느 쪽에 말하고 있는지 화면에서도 코드에서도 흐려진다.

인증: 기본 바인드는 루프백이며 외부 접속은 설정된 Fleet 자격과 역할 검사를 거친다.
등록 자격·기명 운영자·장치 자격은 서로 다른 권한이다.

구조 (D-362 P0-1): 이 파일은 구성 검증·lifespan·감사 미들웨어·비전 임대만 남고, 경로는
소유자 모듈이 단다 — mission_routes, task_dispatch_routes, intent_routes, console_routes,
ingest_routes, static_routes, enrollment_routes(D-361). 각 모듈은 자기 저장소·서비스의
생애를 가진다(app.py 1556줄 split 판정의 실행).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hmac
import logging
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, HTTPException, Request

from core_common.protocol.vision_preview import VisionLeaseSigner
from fleet.server.cancel_all import DriveCancelFence
from fleet.server.cell_job_store import CellJobStore
from fleet.server.console import FleetConsole
from fleet.server.goal_evidence_service import GoalEvidenceService
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.local_action_transport import UnixLocalActionTransport
from fleet.server.arm_transfer_preflight_routes import install_arm_transfer_preflight_routes
from fleet.server.arm_transfer_job_routes import install_arm_transfer_job_routes
from fleet.server.mission_storage import configure_mission_storage
from fleet.server.simulation_pose_binding import validate_simulation_pose_binding
from fleet.server.physical_transfer_stop_targets import configure_omx_stops
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_model_turn_scheduler import MissionModelTurnScheduler
from fleet.server.mission_model_turn_store import MissionModelTurnStore
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_service import MissionService
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.step_action_kinds import dispatch_open
from fleet.server.cell_arm_dispatcher import CellJobDispatcher  # D-779: single-arm + multi-arm Cell Jobs
from fleet.stuck.resolver import ResolverConfig, StuckResolver
from fleet.stuck.loop import StuckResolverLoop
from fleet.incidents.automation.runtime import install_incident_runtime
from fleet.server.task_service import FleetTaskService

from fleet.server.console_routes import install_console_routes
from fleet.server.background_workers import proposal_expiry_loop as _proposal_expiry_loop
from fleet.server.background_workers import goal_evidence_expiry_loop
from fleet.server.background_workers import lane_compliance_loop
from fleet.server.background_workers import attempt_open, goal_lease_renew_loop
from fleet.server.background_workers import _task_dispatch_loop, _mission_model_turn_worker_loop
from fleet.server.background_workers import control_unit_loop, start_notification_worker
from fleet.server.control_unit_runtime import install_control_unit
from fleet.server.dispatch_workers import mission_feedback_schedule_loop, mission_dispatch_loop
from fleet.server.lane_compliance_service import PERIOD_S as LANE_COMPLIANCE_PERIOD_S
from fleet.server.signal_routes import install_signal_routes
from fleet.server.ingest_routes import address_reasons, install_discovery_routes, install_ingest_routes
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
from fleet.server.development_session import install_development_routes
from fleet.server.password_session import PasswordSessions, install_password_routes
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
_mission_feedback_schedule_loop = partial(mission_feedback_schedule_loop, logger=_LOG)
_mission_dispatch_loop = partial(mission_dispatch_loop, logger=_LOG)
DEPLOYMENT_PROFILES = frozenset({"production", "simulation"})


def create_app(console: FleetConsole, *, console_token: Optional[str] = None,
               web_common: Optional[Path] = None, hub=None, sightings=None,
               task_service: Optional[FleetTaskService] = None,
               control_unit_config: Optional[Path] = None,
               mission_service: Optional[MissionService] = None,
               proposal_store: Optional[ProposalStore] = None,
               cell_job_compiler=None,
               goal_evidence_service: Optional[GoalEvidenceService] = None,
               candidate_resolver=None,
               policy_evidence: Optional[PolicyEvidenceStore] = None,
               start_task_dispatcher: bool = True,
               site_users: Optional[Mapping[str, Mapping[str, str]]] = None,
               site_logins: Optional[Mapping[str, Mapping[str, str]]] = None,
               accounts_bootstrap: Optional[tuple[str, str]] = None,
               account_config: Optional[Path] = None,
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
               stuck_resolver_enrolled: frozenset = frozenset(),
               realign_config=None,
               ai_facts_acting: frozenset = frozenset(),
               autonomous_robots: frozenset = frozenset(),
               ai_first=None,   # D-610 3: fleet.stuck.ai_first.AiFirst (site config fleet.ai_first), None = empty list
               pairing=None, pairing_sync_token: Optional[str] = None,
               localization_service=None, deployment_profile: str = "production",
               central_registry=None, tracking=None,
               calibration_drift_watch=None,
               omx_cell_grant_revisions: Optional[Mapping[str, Mapping[str, str]]] = None,
               cell_item_pose_tolerance=None, cell_goal_registry=None,
               cell_app_service_id: str | None = None,
               development_sessions=None,
               site_maps=None, routing_config=None, map_pose_config=None,
               trip_caps_port=None, map_pose_port=None, simulation_pose_binding=None,
               lane_junction=None, trip_config=None, traffic_zones=None, traffic_authority=False, traffic_signals=(),
               traffic_signal_advice=False, trip_lease=None,
               identity_config=None, lane_compliance_config=None,
               notification_config=None, incident_model_config=None, channel_config=None,channel_model_config=None,
               conversation_config=None, assistant_config=None, station_ingress=None,
               charge_runtime_factory=None, arm_transfer_installation=None, arm_transfer_observer=None) -> FastAPI:
    if autonomous_robots and (task_service is None or stuck_resolver_clients is None):
        raise ValueError("autonomous Fleet requires the durable journal and background stuck resolver")
    if notification_config is not None and task_service is None:
        raise ValueError('team notifications require the durable Fleet journal (task_service)')
    if deployment_profile not in DEPLOYMENT_PROFILES:
        raise ValueError(f"unsupported deployment_profile {deployment_profile!r}")
    simulation_pose = validate_simulation_pose_binding(map_pose_port, deployment_profile, simulation_pose_binding)
    if development_sessions is not None and task_service is None:
        # D-473 3: every development session issue and POST is in the durable API audit.
        raise ValueError("development connection mode requires the durable API audit (task_service)")
    mission_configured = configure_mission_storage(task_service, mission_service, proposal_store,
        goal_evidence_service, candidate_resolver, cell_job_compiler)
    cell_job_store = CellJobStore(mission_service.store.path) if mission_configured else None
    if cell_job_store is not None:
        cell_job_store.recover_after_startup()
    cell_job_resolver = None
    if cell_job_compiler is not None:
        from fleet.server.cell_goal_evidence import make_cell_job_resolver
        cell_job_resolver = make_cell_job_resolver(cell_job_compiler, cell_item_pose_tolerance)
    if (site_users is not None or site_logins or accounts_bootstrap is not None
            or account_config is not None) and task_service is None:
        raise ValueError("per-user site authorization requires persistent task/audit storage")
    if bool(discovery) != bool(discovery_token):
        raise ValueError("discovery and its dedicated credential must be configured together")
    if discovery_token is not None and (discovery_token == console_token
                                        or console.uses_rest_token(discovery_token)
                                        or console.uses_agent_pairing_token(discovery_token)):
        raise ValueError("discovery credential must differ from Fleet and robot credentials")
    configured_omx = dict(omx_instances or {})
    stop_targets, stop_transport = configure_omx_stops(
        configured_omx, arm_transfer_installation, omx_stop_transport, omx_socket_root)
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

    def on_step_action_succeeded(job, index):
        if cell_goal_evidence_service is None:
            return None
        try:  # a goal-processing failure never rewrites the recorded device success
            return cell_goal_evidence_service.on_action_terminal(job["mission_id"], index)
        except Exception:
            _LOG.exception("stored Cell goal evidence could not be applied for %s", job["mission_id"])
            return None

    cell_job_dispatcher = (
        CellJobDispatcher(cell_job_store, task_service.store, action_transport, configured_omx,
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

    # The drift watch's verdicts ride the tracking snapshot's source rows, so it is a
    # misconfiguration to start one without the tracking service it is meant to inform.
    if calibration_drift_watch is not None and tracking is None:
        raise ValueError("calibration drift watch requires the tracking service")

    if localization_service is not None:
        # D-395 P2-6: the console badge reads the service's ladder (needs_human).
        console.set_localization_view(localization_service.view)

    if pairing_sync_token is not None and pairing is None:
        raise ValueError("pairing sync credential requires D-341 pairing (--pairing-ca with --tls-cert)")

    # D-421: one fence shared by cancel-all and the dispatcher closes the overlap window.
    drive_cancel = DriveCancelFence()
    if site_maps is None:  # D-488: no --tasks-db -> the site map lives in memory only
        from fleet.server.site_map_store import SiteMapStore
        from fleet.routing.cost import RoutingConfig
        site_maps = SiteMapStore(routing_config=routing_config or RoutingConfig())

    # D-472: LED identity binding; observation only (never map pose, trips or commands).
    from fleet.server.identity import IdentityConfig, IdentityService
    identity = IdentityService(console.clients, tracking=tracking,
                               config=identity_config or IdentityConfig())
    if tracking is not None:
        tracking.identity = identity

    @asynccontextmanager
    async def lifespan(app):
        control_task = (asyncio.create_task(control_unit_loop(app.state.control_unit))
                        if app.state.control_unit is not None else None)
        dispatcher = None
        mission_worker = None
        cell_job_worker = None
        proposal_expiry = None
        goal_evidence_worker = None
        mission_feedback_scheduler = None
        mission_model_turn_worker_task = None
        localization_task = None
        signal_task = None
        calibration_drift_task = None
        notification_http, notification_task = start_notification_worker(app, notification_config)
        physical_worker = (asyncio.create_task(app.state.arm_transfer_dispatcher.run())
                           if app.state.arm_transfer_dispatcher is not None else None)
        if console._signals is not None:
            signal_task = asyncio.create_task(console._signals.run())
        app.state.signal_supervision = signal_task
        resolver_task = None
        if getattr(app.state, "stuck_resolver", None) is not None:
            resolver_task = asyncio.create_task(app.state.stuck_resolver.run())
        if localization_service is not None:
            localization_task = asyncio.create_task(localization_service.run())
        if calibration_drift_watch is not None:
            calibration_drift_task = asyncio.create_task(calibration_drift_watch.run())
        trip_task = asyncio.create_task(app.state.trip_runner.run())  # D-494 5
        charge_task = (asyncio.create_task(app.state.charge_runtime.run())
                       if app.state.charge_runtime is not None else None)
        lease_task = (asyncio.create_task(goal_lease_renew_loop(console, _LOG))  # D-550 10
                      if getattr(getattr(console, "goal_leases", None), "ttl_s", 0) > 0 else None)
        identity_task = asyncio.create_task(identity.run())  # also polls CORE's blink answers (D-596)
        lane_task = asyncio.create_task(lane_compliance_loop(  # D-511 M0
            app.state.lane_compliance, _LOG, LANE_COMPLIANCE_PERIOD_S))
        tether_task = app.state.tether_watch.start()  # D-526
        path_task = asyncio.create_task(app.state.paths.run())  # D-594
        job_task = asyncio.create_task(app.state.job_trips.run()) if getattr(app.state, "job_trips", None) else None
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
            async with AsyncExitStack() as cleanup:
                for resource in (getattr(app.state, "power_health_display", None), notification_http,
                                 app.state.control_unit_http,
                                 calibration_drift_watch, post_action_observation_source, app.state.charge_runtime):
                    close = getattr(resource, "aclose", None)
                    if callable(close):
                        cleanup.push_async_callback(close)
                start_points = getattr(app.state, "start_points", None)
                if start_points is not None:
                    cleanup.callback(start_points.close)
                backgrounds = [background for background in (dispatcher, mission_worker, cell_job_worker, proposal_expiry,
                                   goal_evidence_worker, mission_feedback_scheduler,
                                   mission_model_turn_worker_task, localization_task,
                                   signal_task, resolver_task, trip_task, identity_task, lane_task, tether_task,
                                   lease_task, path_task, calibration_drift_task, notification_task, job_task, charge_task,
                                   control_task, physical_worker)
                               if background is not None]
                for background in backgrounds:
                    background.cancel()
                for result in await asyncio.gather(*backgrounds, return_exceptions=True):
                    if isinstance(result, Exception):
                        _LOG.error("Fleet background worker failed before shutdown",
                                   exc_info=(type(result), result, result.__traceback__))

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
    app.state.omx_instances, app.state.omx_stop_transport = configured_omx, stop_transport
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
    # D-519 1: a site-users file may hold only login accounts, leaving no token principals.
    authority = None
    if account_config is not None:
        from fleet.server.account_config import load_account_config
        from fleet.server.account_authority import AccountAuthority
        settings = load_account_config(account_config)
        admin = settings.pop("bootstrap_admin_login", None)
        site_id = settings.pop("site_id")
        if accounts_bootstrap is not None:
            raise ValueError("use one explicit Account bootstrap configuration")
        if admin is not None:
            accounts_bootstrap = (admin, site_id)
        if accounts_bootstrap is None and not PasswordSessions.accounts_active(task_service.store.path):
            raise ValueError("Account first activation requires an explicit existing administrator login")
        authority = AccountAuthority(task_service.store.path, **settings,
            resolve_family=lambda db, family: password_sessions.context_by_family(family, db=db),
            revoke_family=lambda db, family: password_sessions.revoke_family(family, db=db))
    account_login = bool(site_logins) or accounts_bootstrap is not None or (
        task_service is not None and PasswordSessions.accounts_active(task_service.store.path))
    principals = {} if account_login and not site_users else parse_site_principals(site_users, console)
    password_sessions = None
    if account_login:
        password_sessions = PasswordSessions(task_service.store.path, site_logins or {}, accounts_bootstrap=accounts_bootstrap)
    app.state.password_sessions = password_sessions
    app.state.account_authority = authority
    if authority is not None:
        if password_sessions._ledger.site_id != site_id:
            raise ValueError("Account configured site does not match the activated authority")
        from fleet.server.account_authority_routes import install_account_authority_routes
        install_account_authority_routes(app, sessions=password_sessions, authority=authority)
    other_tokens = (console_token, discovery_token, vision_lease_secret, robot_credential_key, pairing_sync_token)
    if cell_goal_evidence_service is not None:
        from fleet.server.cell_goal_evidence_routes import (
            assert_cell_producer_credentials_isolated, install_cell_goal_evidence_routes)
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
    authorize = build_authorize(console_token, principals, task_service, development=development_sessions,
                                password_sessions=password_sessions)
    require_viewer, require_operator, require_named_operator, require_proposer = build_role_guards(
        authorize, principals, named_logins=password_sessions is not None)
    install_control_unit(app, control_unit_config, tasks=task_service, console=console,
                         principals=principals, named_logins=password_sessions is not None,
                         console_token=console_token, authorize=authorize, require_viewer=require_viewer,
                         require_named_operator=require_named_operator)
    # D-473: `--lan-camera-proxy` already means "Fleet sits behind the site Caddy", whose
    # X-Forwarded-For carries the browser address the development session checks.
    install_development_routes(app, sessions=development_sessions, task_service=task_service,
                               trust_forwarded=lan_camera_proxy, account_login=password_sessions is not None)
    install_password_routes(app, sessions=password_sessions, authorize=authorize, task_service=task_service,
                            trust_forwarded=lan_camera_proxy)
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
    install_arm_transfer_preflight_routes(
        app, instances=configured_omx, deployment_profile=deployment_profile,
        transport=action_transport, socket_root=omx_socket_root, require_proposer=require_proposer)
    install_arm_transfer_job_routes(
        app, installation=arm_transfer_installation, deployment_profile=deployment_profile,
        task_store=task_service.store if mission_configured else None, transport=action_transport,
        socket_root=omx_socket_root, require_proposer=require_proposer, require_viewer=require_viewer,
        require_named_operator=require_named_operator, observer=arm_transfer_observer, console=console,
        principals=principals, other_tokens=other_tokens, other_services=(sightings, policy_evidence),
        registries=(cell_goal_registry, goal_evidence_service.registry if goal_evidence_service is not None else None))

    from fleet.server.peer_routes import install_peer_catalogue
    catalogue = install_peer_catalogue(app, console=console, enrollment=enrollment,
                                       pairing=pairing, read_guard=read_guard,
                                       directory_file=approved_peer_directory_file)
    if discovery is not None:
        install_discovery_routes(app, console=console, hub=hub, discovery=discovery,
                                 discovery_token=discovery_token, enrollment=enrollment,
                                 principals=principals, require_viewer=require_viewer,
                                 read_guard=read_guard, catalogue=catalogue)

        def _link_addresses():
            reasons = address_reasons(console=console, hub=hub, discovery=discovery,
                                     enrollment=enrollment)
            return {entry["robot_id"]: entry["status"] for entry in reasons["robots"]}

        console.set_link_address_status(_link_addresses)

    from fleet.server.central_registry_routes import install_registry_routes
    install_registry_routes(app, registry=central_registry, enrollment=enrollment, pairing=pairing,
                            sync_token=pairing_sync_token, require_viewer=require_viewer,
                            require_operator=require_operator,
                            named_identity=bool(principals) or password_sessions is not None)
    from fleet.server.camera_peer_adapter import install_camera_peer
    app.state.camera_peer = install_camera_peer(app, pairing=pairing,
        current_users=lambda:site_users or {}, require_named_operator=require_named_operator)

    # D-494 3: trip-only map pose from accepted sightings and robot odom_pose.
    from rosy.world.state.projections.map_pose import MapPoseConfig
    from fleet.server.map_pose_service import MapPoseService, install_map_pose_routes

    async def _gather_state(robot_id: str):
        return (await console._gather_state(robot_id))[0]

    async def _rest_state(robot_id: str):
        return await console._client(robot_id).state()

    map_pose_config = map_pose_config or MapPoseConfig()
    if sightings is not None and map_pose_config.sighting_lease_s > sightings.lease_s:
        raise ValueError("fleet.map_pose.sighting_lease_s must not exceed the sighting ingest lease")

    def _active_map_id():
        active = site_maps.active()
        return active[1].map_id if active is not None else None

    map_pose = MapPoseService(lambda: console.robot_ids, config=map_pose_config,
                              map_id=_active_map_id,
                              source_map_ids=[source.map_id for source in
                                              (sightings.sources if sightings is not None else ())],
                              gather=_gather_state, gather_rest=_rest_state, client_identity=console._client)
    map_pose.active_map_id()   # start-up warning when no sighting source reports the active map
    execution_pose = map_pose_port if simulation_pose else map_pose
    if simulation_pose:
        def _execution_active_map():
            active = site_maps.active()
            return (active[1].map_id, active[0]) if active is not None else (None, None)
        execution_pose.bind_active_map(_execution_active_map)
    app.state.execution_map_pose = execution_pose
    console.set_state_sink(map_pose.observe_state)
    console.read_state = map_pose.state   # D-760 8: one shared REST state read per robot for every loop
    identity.map_pose = map_pose.arbitrated_pose   # D-596 amendment: where to look, never an input
    from fleet.swarm.anchor import anchored_relay_factory
    console.formation_relay_factory = lambda enabled: anchored_relay_factory(map_pose, enabled)
    if localization_service is not None:
        localization_service.set_overhead_pose(map_pose.arbitrated_pose)   # D-546 6 (a)
    app.state.map_pose = map_pose
    if tracking is not None:
        tracking.map_pose = map_pose.arbitrated_pose   # D-600: robot regions Vision must not learn
    install_ingest_routes(app, console=console, console_token=console_token, hub=hub,
                          sightings=sightings, policy_evidence=policy_evidence,
                          principals=principals, require_viewer=require_viewer,
                          read_guard=read_guard, map_pose=map_pose, station_ingress=station_ingress)
    install_map_pose_routes(app, service=execution_pose, read_guard=read_guard)
    # D-511 M0: lane compliance from the same map pose; observe and notify only.
    from fleet.localization.lane_compliance import LaneComplianceConfig
    from fleet.server.lane_compliance_service import LaneComplianceMonitor, install_lane_compliance_routes
    app.state.lane_compliance = LaneComplianceMonitor(
        lambda: console.robot_ids, poses=execution_pose, site_maps=site_maps,
        config=lane_compliance_config or LaneComplianceConfig(), identity=identity,
        clients=console.clients,   # D-511 rev 1: the return cue
        # An open CORE stuck owns the robot (D-577 REALIGN); the board is built further down.
        stuck_open=lambda robot_id: (getattr(app.state, "line_stuck", None) is not None
                                     and app.state.line_stuck.view(robot_id) is not None))
    install_lane_compliance_routes(app, monitor=app.state.lane_compliance, read_guard=read_guard)

    install_console_routes(app, console=console, sightings=sightings,
                           require_viewer=require_viewer, read_guard=read_guard,
                           operator_guard=operator_guard, site_lanes=site_lanes,
                           require_operator=require_operator,
                           require_named_operator=require_named_operator,
                           answer_log_path=task_service.store.path if task_service else None,
                           tracking=tracking, identity=identity)
    if app.state.line_stuck._log is not None:
        app.state.line_stuck._log.notifications.config = notification_config
    from fleet.stuck.ai_facts import install_ai_routes   # D-577 4: AI PC facts, shadow only
    app.state.ai_facts = install_ai_routes(app, read_guard=read_guard, authorize=authorize,
                                           db_path=task_service.store.path if task_service else None,
                                           acting=ai_facts_acting)
    app.state.line_stuck.ai_view = app.state.ai_facts.robot_view
    from fleet.stuck.ai_first import AiFirst
    from fleet.stuck.episodes import ProblemLog
    app.state.ai_first = ai_first or AiFirst()
    app.state.ai_facts.first, app.state.ai_first.profiles = app.state.ai_first, app.state.ai_facts.profiles
    app.state.ai_episodes = ProblemLog(task_service.store.path if task_service else None)   # D-610 9
    app.state.ai_first.human_classes = app.state.ai_episodes.active
    if tracking is not None and tracking.enabled:
        from fleet.server.measured_calibration import active_map_revision
        from fleet.server.tracking_routes import install_tracking_routes
        install_tracking_routes(app, tracking=tracking, require_operator=require_operator,
                                read_guard=read_guard, operator_guard=operator_guard,
                                require_named_operator=require_named_operator,
                                map_revision=partial(active_map_revision, site_maps))
        from fleet.server.start_points import StartPointService
        from fleet.server.start_point_routes import install_start_point_routes
        install_start_point_routes(app, service=StartPointService(sources=tracking.sources,
                                                              calibrations=tracking.calibrations),
                                   read_guard=read_guard, require_named_operator=require_named_operator)
    install_signal_routes(app, signals=console._signals, require_viewer=require_viewer,
                          require_operator=require_operator, require_named_operator=require_named_operator,
                          # D-519: login accounts are configured named operators too.
                          auth_configured=bool(principals or console_token) or password_sessions is not None)

    if stuck_resolver_clients is not None:
        resolver_core = StuckResolver(ResolverConfig(), realign=realign_config,
                                      painted=lambda: (site_maps.active() or (None,) * 4)[3])
        resolver_core.autonomous_robots = frozenset(autonomous_robots)
        app.state.line_stuck.peer_config = resolver_core.config   # episodes judge peers as R1 does
        app.state.stuck_resolver = StuckResolverLoop(
            app.state.fleet_gather, app.state.line_stuck, resolver_core,
            # Enrolled robots the site config names answer with Fleet's own enrolled CORE credential
            # (operator, carries STUCK_DECIDE): D-503 6 by user go 2026-10-10, per robot id.
            clients=lambda: {**{rid: client for rid, client in console.clients().items()
                                if rid in stuck_resolver_enrolled}, **stuck_resolver_clients})
        app.state.stuck_resolver.map_pose = map_pose.stuck_pose   # D-577 1: R3 pose freshness
        app.state.stuck_resolver.events_since = console.hub.registry.events_since
        app.state.stuck_resolver.heading_review = app.state.lane_compliance.stuck_heading
        app.state.stuck_resolver.realign_evidence = app.state.lane_compliance.realign_evidence
        app.state.line_stuck.heading_review = app.state.lane_compliance.stuck_heading
        resolver_core.at_crosswalk = app.state.lane_compliance.at_crosswalk   # D-573 개정 2026-10-10
        app.state.stuck_resolver.ai_facts = app.state.ai_facts.acting_facts   # D-577 7, configured robots only
        app.state.stuck_resolver.ai_board = app.state.ai_facts   # D-577 개정: AI PC proposals, Fleet validates
        from fleet.stuck.problems import ProblemWatch
        resolver_core.ai_first = app.state.ai_first               # D-610: AI-first robots, closed loop, P2 kinds
        app.state.stuck_resolver.episodes, app.state.stuck_resolver.problems = app.state.ai_episodes, ProblemWatch()
    install_incident_runtime(app, incident_model_config)
    from fleet.stuck.ai_routes import install_ai_first_routes, rosy_cam_lease
    install_ai_first_routes(app, first=app.state.ai_first, line_stuck=app.state.line_stuck,
                            loop=getattr(app.state, "stuck_resolver", None), episodes=app.state.ai_episodes,
                            read_guard=read_guard, authorize=authorize, require_named_operator=require_named_operator,
                            clients=console.clients,
                            rosy_cam=lambda rid: rosy_cam_lease(rid, sightings, map_pose,
                                                                vision_signer, vision_sources),
                            pose=map_pose.stuck_pose,
                            deadlock_case=lambda: getattr(app.state.trip_runner.traffic.ai_replan, "case", None))

    def ai_chain() -> dict:   # D-577 supervision row: credential presence only, never a secret
        enrolled = console.clients() if stuck_resolver_enrolled else {}

        def credential(rid: str) -> str:
            if rid in (stuck_resolver_clients or {}):
                return "token"
            return "enrolled" if rid in stuck_resolver_enrolled and rid in enrolled else "none"
        return {"resolver": getattr(app.state, "stuck_resolver", None) is not None,
                "robots": [{"robot_id": rid, "credential": credential(rid), "ai_acting": rid in ai_facts_acting,
                            "last_answer": app.state.line_stuck.last_resolver_answer(rid)}
                           for rid in console.robot_ids]}
    app.state.ai_facts.chain = ai_chain
    if hub is not None and (task_service is not None or stuck_resolver_clients is not None):
        resolver = getattr(app.state, "stuck_resolver", None)
        hub.set_event_callback(_fan_out_events(
            task_service.project_core_event if task_service is not None else None,
            resolver.wake if resolver is not None else None))

    install_task_dispatch_routes(app, console=console, task_service=task_service,
                                 configured_omx=configured_omx,
                                 stop_transport=stop_transport, stop_targets=stop_targets,
                                 require_viewer=require_viewer,
                                 require_operator=require_operator, require_named_operator=require_named_operator,
                                 read_guard=read_guard, operator_guard=operator_guard,
                                 drive_cancel=drive_cancel)
    # D-488: the site map store (in memory without one) and the D-490 trip planner.
    from fleet.routing.cost import RoutingConfig
    from fleet.server.site_map_routes import install_site_map_routes
    from fleet.server.console_view import trip_caps
    from fleet.server.trip_routes import install_trip_routes
    from fleet.server.trip_ports import HttpLaneJunction
    from fleet.server.trip_guard import engaged, install_trip_guard, release_queue
    from fleet.server.trip_runner import TripConfig, TripRunner
    install_lane_route_routes(app, console=console, task_service=task_service,
                              site_maps=site_maps, require_named_operator=require_named_operator)

    async def _trip_caps(robot_id: str):
        """D-494 1: trip caps from the capability cache; None for an older image or no answer.
        D-604: a kept value older than two refreshes drops its line camera (front/status is asked)."""
        display = console._capability_display
        caps = trip_caps(await display.shown(robot_id, wait_s=2.0))
        age = display.age(robot_id)
        if caps is not None and (age is None or age > 2 * display.refresh_s):
            caps = dataclasses.replace(caps, line_camera=None)
        return caps

    if (trip_lease or {}).get("required") and console_token and console.uses_rest_token(console_token):
        # D-541 1: the lease owner is the robot REST token; browsers hold the console token
        raise ValueError("D-541: a robot REST token must be Fleet's own, not the console token")
    # D-494 5: the planner's caps closure, the trip map pose service, CORE's junction API.
    trip_runner = TripRunner(store=site_maps, routing_config=routing_config or site_maps.routing_config,
                             caps=trip_caps_port or _trip_caps, poses=map_pose_port or map_pose,
                             junction=lane_junction or HttpLaneJunction(console.clients, map_pose.state, map_pose.read_number),
                             goal=lambda *args, **kwargs: console.goal(*args, trip=True, **kwargs),
                             cancel_goal=console.cancel, config=trip_config or TripConfig(),
                             engaged=partial(engaged, console), release_queue=partial(release_queue, console),
                             roster=lambda: console.robot_ids, traffic_zones=traffic_zones, authority=traffic_authority,
                             traffic_signals=traffic_signals, signal_advice=traffic_signal_advice,
                             lease=trip_lease and {**trip_lease, "holder": console.fleet_name},
                             renew_lease=lambda robot_id: console.goal_leases.renew("trip", robot_id))
    install_trip_guard(console, trip_runner, claims=task_service.store.resource_claims if task_service else None)
    trip_runner.autonomous_robots = frozenset(autonomous_robots)
    trip_runner.traffic.autonomous_robots = frozenset(autonomous_robots)
    if hub is not None:
        from fleet.server.junction_signal import signal_for
        hub.junction_signal = partial(signal_for, traffic=trip_runner.traffic, poses=execution_pose,
                                      site_maps=site_maps)
    from fleet.stuck.deadlock import AiReplan   # D-610 7: the AI PC picks a wait cycle's replan, Fleet checks it
    trip_runner.traffic.ai_replan = AiReplan(app.state.ai_first, app.state.ai_facts, app.state.ai_episodes)
    from fleet.server.map_pose_service import install_map_pin_route  # D-593
    install_map_pin_route(app, service=map_pose, require_named_operator=require_named_operator,
                          record_event=site_maps.record_event, busy=trip_runner.robot_busy)
    if task_service is not None:  # D-550 10: a dispatch goal's lease lives as long as its attempt
        console.goal_leases.attempt_open = partial(attempt_open, task_service.store)
        console.goal_leases.admit_attempt = task_service.admit_attempt
        console.goal_leases.bind_native_receipt = task_service.bind_native_receipt
        console.goal_leases.native_required = task_service.native_required
        from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
        console.goal_leases.prepare_send = partial(prepare_send, console.goal_leases)
        task_service.core_events = hub.event_store if hub is not None else None

    @app.post("/api/fleet/goal-lease/presence", tags=["fleet"])
    def fleet_goal_lease_presence(principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """D-550 10: a named operator's console is open; operator goals are renewed while it keeps coming."""
        console.goal_leases.operator_present()
        return {"present": True}
    app.state.line_stuck.trip_busy = trip_runner.robot_busy   # stuck episode context (D-407)
    if getattr(app.state, "stuck_resolver", None) is not None:  # D-517 5: stopping answers only on a trip
        app.state.stuck_resolver.trip_busy = trip_runner.robot_busy
    install_site_map_routes(app, site_maps=site_maps, route_active=lambda: trip_runner.running() is not None
                            or console.formation_status()["active"] or app.state.teach.view()["recording"] is not None,
                            read_guard=read_guard, require_named_operator=require_named_operator)
    from fleet.server.teach_routes import TeachService, install_teach_routes  # D-494 6
    marker_sources = sightings is not None and any(s.place_markers for s in sightings.sources)  # D-564
    install_teach_routes(app, service=TeachService(poses=map_pose if simulation_pose else map_pose_port or map_pose, site_maps=site_maps,
                                                   roster=lambda: console.robot_ids,
                                                   place_markers=sightings.fresh_place_marker
                                                   if marker_sources else None),
                         read_guard=read_guard, require_named_operator=require_named_operator)
    from fleet.server.tether_routes import install_tether_routes  # D-512 map display half, D-526 watch
    install_tether_routes(app, console=console, trip_runner=trip_runner, read_guard=read_guard,
                          require_named_operator=require_named_operator)
    from fleet.server.path_history import PathRecorder, PathStore, install_path_routes  # D-594 display only
    app.state.paths = PathRecorder(
        PathStore(task_service.store.path if task_service is not None else None),
        roster=lambda: console.robot_ids, gather=_gather_state, map_pose=map_pose,
        tracking=tracking if tracking is not None and tracking.enabled else None,
        trips=trip_runner.open_trips, formation=console.formation_status)
    install_path_routes(app, paths=app.state.paths, read_guard=read_guard)
    install_trip_routes(app, console=console, site_maps=site_maps, caps_for=_trip_caps,
                        routing_config=routing_config or site_maps.routing_config,
                        require_operator=require_operator,
                        require_named_operator=require_named_operator, runner=trip_runner,
                        read_guard=read_guard)
    from fleet.server.guide_service import GuideService, install_guide_routes  # D-536
    app.state.guide = GuideService(gather=app.state.fleet_gather, poses=map_pose, site_maps=site_maps,
                                   tracking=tracking if tracking is not None and tracking.enabled else None,
                                   zones=trip_runner.traffic.zone_edges)
    install_guide_routes(app, service=app.state.guide, read_guard=read_guard)

    proposal_create = proposal_resolve = mission_admit = None
    if mission_service is not None:
        proposal_create, proposal_resolve, mission_admit = install_mission_routes(
            app, mission_service=mission_service, proposal_store=proposal_store,
            cell_job_store=cell_job_store, cell_job_resolver=cell_job_resolver,
            goal_evidence_service=goal_evidence_service, mission_progress=mission_progress,
            candidate_resolver=candidate_resolver, require_viewer=require_viewer,
            require_operator=require_operator, require_named_operator=require_named_operator,
            require_proposer=require_proposer, read_guard=read_guard, operator_guard=operator_guard)
        from fleet.server.cell_job_routes import install_cell_job_routes

        install_cell_job_routes(app, cell_job_store=cell_job_store, proposal_store=proposal_store,
                                require_viewer=require_viewer,
                                require_named_operator=require_named_operator,
                                operator_guard=operator_guard, read_guard=read_guard)

    from fleet.server.work_routes import install_work_routes
    from fleet.server.channel_requests import install_channel_feature
    install_work_routes(app, task_service=task_service, mission_service=mission_service, require_viewer=require_viewer,
                        require_named=(require_operator, require_named_operator), read_guard=read_guard)
    from fleet.server.trip_job_routes import install_trip_job_routes  # D-763 7: trip steps, SIM profile only
    install_trip_job_routes(app, store=cell_job_store, runner=trip_runner, console=console,
                            deployment_profile=deployment_profile, episodes=app.state.ai_episodes,
                            require_named_operator=require_named_operator, operator_guard=operator_guard,
                            require_viewer=require_viewer, read_guard=read_guard)
    from fleet.server.cell_app_routes import install_cell_app_routes
    cell_prepare = install_cell_app_routes(
        app, mission_service=mission_service, compiler=cell_job_compiler, service_id=cell_app_service_id,
        principals=principals, proposal_create=proposal_create, proposal_resolve=proposal_resolve,
        require_viewer=require_viewer, require_named_operator=require_named_operator)
    install_channel_feature(
        app, config=channel_config, task_service=task_service, principals=principals, site_logins=site_logins,
        require_operator=require_operator, require_named_operator=require_named_operator, read_guard=read_guard,
        existing_tokens=other_tokens + ((arm_transfer_observer.token,) if arm_transfer_observer else ()),
        console=console, secret_owners=(sightings, policy_evidence), proposals=proposal_store, proposal_create=proposal_create,
        proposal_resolve=proposal_resolve, cell_prepare=cell_prepare, mission_admit=mission_admit, cell_service_id=cell_app_service_id)
    install_intent_routes(app, console=console, task_service=task_service, require_operator=require_operator,
                          require_named_operator=require_named_operator,
                          operator_guard=operator_guard,
                          local_stop_fanout=partial(
                              fanout_local_omx_stops, configured_omx, stop_transport, targets=stop_targets),
                          cancel_pending=partial(
                              cancel_pending_task_queue, task_service, console))
    from .channel.conversation.runtime import install_conversation_routes
    install_conversation_routes(app, conversation_config, channel_model_config, site_maps,
                                task_service, require_operator, read_guard)

    from .assistant.runtime import install_assistant
    install_assistant(app, assistant_config, task_service=task_service,
                      require_named_operator=require_named_operator, authorize=authorize)

    from fleet.server.vision_preview_routes import install_vision_preview_routes
    install_vision_preview_routes(app, signer=vision_signer, sources=vision_sources,
                                  require_camera_viewer=require_camera_viewer,
                                  require_named_operator=require_named_operator)

    from fleet.host_control import UnavailableHostHelper, helper_from_config
    from fleet.server.host_control_routes import install_host_control_routes
    # D-524: without site-users or logins every caller is `site-console`, so no host control.
    install_host_control_routes(
        app, require_operator=require_operator, require_named_operator=require_named_operator,
        helper=(helper_from_config() if principals or password_sessions is not None
                else UnavailableHostHelper()))

    install_static_routes(app)
    from fleet.server.charge_bootstrap import install_charge_runtime
    install_charge_runtime(app, factory=charge_runtime_factory, runner=trip_runner, plans=site_maps,
        task_service=task_service, ingress=station_ingress, console=console)
    return app
