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
import logging
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, HTTPException, Request

from fleet.server.account_runtime import configure_account_sessions, install_account_login_routes
from fleet.server.arm_transfer_job_routes import install_arm_transfer_job_routes
from fleet.server.arm_transfer_preflight_routes import install_arm_transfer_preflight_routes
from fleet.server.cancel_all import DriveCancelFence
from fleet.server.console import FleetConsole
from fleet.server.control_unit_runtime import install_control_unit
from fleet.server.credential_isolation import assert_credentials_isolated
from fleet.server.execution_profile_routes import install_execution_profile_routes
from fleet.server.goal_evidence_service import GoalEvidenceService
from fleet.server.ingest_routes import address_reasons, install_discovery_routes
from fleet.server.lane_compliance_service import PERIOD_S as LANE_COMPLIANCE_PERIOD_S
from fleet.server.lane_route_routes import RouteRequest  # noqa: F401 — RouteRequest 재수출 (D-463)
from fleet.server.loop_supervision import FLEET_LOOP_NAMES, LoopSupervisor, start_fleet_loops
from fleet.server.mission_service import MissionService
from fleet.server.physical_transfer_stop_targets import configure_omx_stops
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.simulation_pose_binding import validate_simulation_pose_binding
from fleet.server.site_auth import (
    SitePrincipal,
    build_authorize,
    build_role_guards,
    install_mutation_audit,
)
from fleet.server.static_routes import install_static_routes
from fleet.server.berth_parking_routes import install_berth_parking_routes
from fleet.server.task_dispatch_routes import (  # noqa: F401 — GoalRequest 재수출: test_task_contract_docs 참조
    GoalRequest,
    cancel_pending_task_queue,
    fanout_local_omx_stops,
    install_task_dispatch_routes,
)
from fleet.server.task_service import FleetTaskService
from fleet.server.vision_preview_routes import VisionLeaseRequest, configure_vision_previews  # noqa: F401
from .bootstrap.role_builders import (
    build_mission_and_cell_runtime,
    install_mission_and_channel_surfaces,
    install_pose_and_stuck_runtime,
    install_trip_and_map_surfaces,
)

_LOG = logging.getLogger(__name__)
DEPLOYMENT_PROFILES = frozenset({"production", "simulation", "device_trial"})  # D-797 2


def create_app(console: FleetConsole, *, console_token: Optional[str] = None,
               web_common: Optional[Path] = None, hub=None, sightings=None,
               task_service: Optional[FleetTaskService] = None,
               control_unit_config: Optional[Path] = None,
               mission_service: Optional[MissionService] = None,
               proposal_store: Optional[ProposalStore] = None,
               cell_job_compiler=None, intake_supply=None,
               goal_evidence_service: Optional[GoalEvidenceService] = None,
               candidate_resolver=None,
               policy_evidence: Optional[PolicyEvidenceStore] = None,
               start_task_dispatcher: bool = True,
               site_users: Optional[Mapping[str, Mapping[str, str]]] = None,
               site_logins: Optional[Mapping[str, Mapping[str, str]]] = None,
               accounts_bootstrap: Optional[tuple[str, str]] = None,
               account_config: Optional[Path] = None,
               account_client_config: Optional[Path] = None,
               discovery=None, discovery_token: Optional[str] = None,
               approved_peer_directory_file: Optional[Path] = None,
               vision_lease_secret: Optional[str] = None,
               vision_sources: tuple[str, ...] = (),
               workcell_observations=None,
               lan_camera_proxy: bool = False,
               omx_instances: Optional[Mapping[str, str]] = None,
               omx_socket_root: Path | str = "/run/rosy/omx",
               omx_stop_transport=None,
               enable_mission_dispatcher: bool = False, policy_admission_core=None,
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
               traffic_signal_advice=False, trip_lease=None, station_recovery=False,
               identity_config=None, lane_compliance_config=None,
               notification_config=None, incident_model_config=None, channel_config=None, channel_model_config=None,
               conversation_config=None, assistant_config=None, station_ingress=None,
               charge_runtime_factory=None, arm_transfer_installation=None, arm_transfer_observer=None) -> FastAPI:
    if autonomous_robots and (task_service is None or stuck_resolver_clients is None):
        raise ValueError("autonomous Fleet requires the durable journal and background stuck resolver")
    if notification_config is not None and task_service is None:
        raise ValueError("team notifications require the durable Fleet journal (task_service)")
    if deployment_profile not in DEPLOYMENT_PROFILES:
        raise ValueError(f"unsupported deployment_profile {deployment_profile!r}")
    simulation_pose = validate_simulation_pose_binding(map_pose_port, deployment_profile, simulation_pose_binding)
    if development_sessions is not None and task_service is None:
        raise ValueError("development connection mode requires the durable API audit (task_service)")
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
    mission_rt = build_mission_and_cell_runtime(
        task_service=task_service, mission_service=mission_service, proposal_store=proposal_store,
        goal_evidence_service=goal_evidence_service, candidate_resolver=candidate_resolver,
        cell_job_compiler=cell_job_compiler, cell_item_pose_tolerance=cell_item_pose_tolerance,
        enable_mission_dispatcher=enable_mission_dispatcher, configured_omx=configured_omx,
        omx_action_transport=omx_action_transport, omx_socket_root=omx_socket_root,
        deployment_profile=deployment_profile, cell_goal_registry=cell_goal_registry,
        omx_cell_grant_revisions=omx_cell_grant_revisions,
        mission_model_turn_max_rows=mission_model_turn_max_rows,
        mission_model_turn_worker=mission_model_turn_worker,
        post_action_observation_source=post_action_observation_source, log=_LOG)
    mission_configured = mission_rt.mission_configured
    cell_job_store = mission_rt.cell_job_store
    cell_job_resolver = mission_rt.cell_job_resolver
    action_transport = mission_rt.action_transport
    mission_dispatcher = mission_rt.mission_dispatcher
    cell_goal_evidence_service = mission_rt.cell_goal_evidence_service
    cell_job_dispatcher = mission_rt.cell_job_dispatcher
    mission_progress = mission_rt.mission_progress
    mission_model_turn_store = mission_rt.mission_model_turn_store
    mission_model_turn_scheduler = mission_rt.mission_model_turn_scheduler
    vision_signer, vision_sources = configure_vision_previews(
        console, console_token=console_token, vision_lease_secret=vision_lease_secret,
        vision_sources=vision_sources, discovery_token=discovery_token, sightings=sightings,
        site_users=site_users, workcell_observations=workcell_observations)

    if calibration_drift_watch is not None and tracking is None:
        raise ValueError("calibration drift watch requires the tracking service")
    if localization_service is not None:
        console.set_localization_view(localization_service.view)
    if pairing_sync_token is not None and pairing is None:
        raise ValueError("pairing sync credential requires D-341 pairing (--pairing-ca with --tls-cert)")

    drive_cancel = DriveCancelFence()
    if site_maps is None:  # D-488: no --tasks-db -> the site map lives in memory only
        from fleet.routing.cost import RoutingConfig
        from fleet.server.site_map_store import SiteMapStore
        site_maps = SiteMapStore(routing_config=routing_config or RoutingConfig())

    from fleet.server.identity import IdentityConfig, IdentityService
    identity = IdentityService(console.clients, tracking=tracking, config=identity_config or IdentityConfig())
    if tracking is not None:
        tracking.identity = identity

    loop_supervision = LoopSupervisor()
    loop_supervision.declare(*FLEET_LOOP_NAMES)

    @asynccontextmanager
    async def lifespan(app):
        _started, notification_http, background_tasks = start_fleet_loops(
            app, console, supervisor=loop_supervision, task_service=task_service,
            start_task_dispatcher=start_task_dispatcher, drive_cancel=drive_cancel,
            proposal_store=proposal_store, mission_dispatcher=mission_dispatcher,
            cell_job_dispatcher=cell_job_dispatcher, goal_evidence_service=goal_evidence_service,
            mission_model_turn_scheduler=mission_model_turn_scheduler,
            mission_model_turn_worker=mission_model_turn_worker,
            localization_service=localization_service, calibration_drift_watch=calibration_drift_watch,
            notification_config=notification_config, identity=identity, log=_LOG,
            lane_compliance_period_s=LANE_COMPLIANCE_PERIOD_S)
        try:
            yield
        finally:
            loop_supervision.stopping()
            async with AsyncExitStack() as cleanup:
                for resource in (getattr(app.state, "power_health_display", None),
                                 getattr(app.state, "motor_health_display", None), notification_http,
                                 app.state.control_unit_http, app.state.control_unit_stops,
                                 calibration_drift_watch, post_action_observation_source, app.state.charge_runtime):
                    if callable(close := getattr(resource, "aclose", None)):
                        cleanup.push_async_callback(close)
                start_points = getattr(app.state, "start_points", None)
                if start_points is not None:
                    cleanup.callback(start_points.close)
                for background in background_tasks:
                    background.cancel()
                for result in await asyncio.gather(*background_tasks, return_exceptions=True):
                    if isinstance(result, Exception):
                        _LOG.error("Fleet background worker failed before shutdown",
                                   exc_info=(type(result), result, result.__traceback__))

    app = FastAPI(
        title="ROSY Fleet",
        version="0.1.0",
        lifespan=lifespan,
        description="사이트 오케스트레이터 — 모음과 원자 액션 흩뿌림 (D-59)",
    )
    app.state.loop_supervision = loop_supervision
    app.state.console = console
    app.state.web_common = Path(web_common) if web_common is not None else None
    app.state.task_service = task_service
    app.state.mission_service = mission_service
    app.state.cell_job_store, app.state.cell_job_compiler = cell_job_store, cell_job_compiler
    app.state.goal_evidence_service = goal_evidence_service
    app.state.mission_progress = mission_progress
    app.state.mission_model_turn_store, app.state.mission_model_turn_scheduler = (
        mission_model_turn_store, mission_model_turn_scheduler)
    app.state.mission_model_turn_worker = mission_model_turn_worker
    app.state.post_action_observation_source = post_action_observation_source
    app.state.mission_dispatcher = mission_dispatcher
    app.state.cell_job_dispatcher = cell_job_dispatcher
    app.state.cell_goal_evidence_service, app.state.deployment_profile = (
        cell_goal_evidence_service, deployment_profile)
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
    if tracking is not None and (sightings is None or tuple(tracking.sources) != tuple(sightings.sources)):
        raise ValueError("overhead tracking must use the configured sighting sources")

    principals = configure_account_sessions(
        app, console=console, task_service=task_service, site_users=site_users, site_logins=site_logins,
        accounts_bootstrap=accounts_bootstrap, account_config=account_config,
        account_client_config=account_client_config)
    other_tokens = assert_credentials_isolated(
        console=console, principals=principals, console_token=console_token, discovery_token=discovery_token,
        vision_lease_secret=vision_lease_secret, robot_credential_key=robot_credential_key,
        pairing_sync_token=pairing_sync_token, workcell_observations=workcell_observations,
        goal_evidence_service=goal_evidence_service, cell_goal_registry=cell_goal_registry,
        cell_goal_evidence_service=cell_goal_evidence_service, sightings=sightings, policy_evidence=policy_evidence)
    if cell_goal_evidence_service is not None:
        from fleet.server.cell_goal_evidence_routes import install_cell_goal_evidence_routes
        install_cell_goal_evidence_routes(app, cell_goal_evidence_service)
    authorize = build_authorize(console_token, principals, task_service, development=development_sessions,
                                password_sessions=app.state.password_sessions)
    require_viewer, require_operator, require_named_operator, require_proposer = build_role_guards(
        authorize, principals, named_logins=app.state.password_sessions is not None)
    install_control_unit(
        app, control_unit_config, tasks=task_service, console=console, principals=principals,
        named_logins=app.state.password_sessions is not None, console_token=console_token, authorize=authorize,
        require_viewer=require_viewer, require_named_operator=require_named_operator, map_snapshot=site_maps.active,
        configured_omx=configured_omx, stop_transport=stop_transport, stop_targets=stop_targets, enrollment=enrollment)
    install_account_login_routes(
        app, sessions=app.state.password_sessions, authorize=authorize, task_service=task_service,
        development_sessions=development_sessions, account_client_config=account_client_config,
        trust_forwarded=lan_camera_proxy)
    read_guard = [Depends(require_viewer)]
    from fleet.server.workcell_observation_routes import install_workcell_observation_routes as install_observations
    install_observations(app, workcell_observations, require_viewer, require_named_operator, task_service, authorize)

    def require_camera_viewer(request: Request) -> SitePrincipal:
        if (lan_camera_proxy and request.headers.get("X-Rosy-Lan-Camera") == "1"
                and not request.headers.get("Authorization")):
            principal = SitePrincipal("lan-camera", "viewer")
            request.state.site_principal = principal
            if task_service is not None and request.method == "POST":
                try:
                    request.state.site_api_audit_id = task_service.store.begin_api_audit(
                        principal_id=principal.principal_id, role=principal.role,
                        method=request.method, path=request.url.path)
                except (OSError, sqlite3.Error, ValueError):
                    raise HTTPException(status_code=503, detail={
                        "code": "AUDIT_STORAGE_UNAVAILABLE", "message": "site command audit is unavailable"}) from None
            return principal
        return authorize(request, request.headers.get("Authorization"))

    operator_guard = [Depends(require_operator)]
    install_arm_transfer_preflight_routes(
        app, instances=configured_omx, deployment_profile=deployment_profile, transport=action_transport,
        socket_root=omx_socket_root, require_proposer=require_proposer)
    install_execution_profile_routes(
        app, deployment_profile=deployment_profile, instances=configured_omx,
        grant_revisions=omx_cell_grant_revisions, transport=action_transport, require_viewer=require_viewer,
        workcell_observations=workcell_observations, arm_transfer_observer=arm_transfer_observer)
    install_arm_transfer_job_routes(
        policy_admission_core=policy_admission_core, app=app, installation=arm_transfer_installation,
        deployment_profile=deployment_profile, intake=intake_supply,
        task_store=task_service.store if mission_configured else None, transport=action_transport,
        socket_root=omx_socket_root, require_proposer=require_proposer, require_viewer=require_viewer,
        require_named_operator=require_named_operator, observer=arm_transfer_observer, console=console,
        grant_revisions=omx_cell_grant_revisions, principals=principals, other_tokens=other_tokens,
        other_services=(sightings, policy_evidence),
        registries=(cell_goal_registry, goal_evidence_service.registry if goal_evidence_service is not None else None))

    from fleet.server.peer_routes import install_peer_catalogue
    catalogue = install_peer_catalogue(
        app, console=console, enrollment=enrollment, pairing=pairing, read_guard=read_guard,
        directory_file=approved_peer_directory_file)
    if discovery is not None:
        install_discovery_routes(
            app, console=console, hub=hub, discovery=discovery, discovery_token=discovery_token,
            enrollment=enrollment, principals=principals, require_viewer=require_viewer,
            read_guard=read_guard, catalogue=catalogue)

        def _link_addresses():
            reasons = address_reasons(console=console, hub=hub, discovery=discovery, enrollment=enrollment)
            return {entry["robot_id"]: entry["status"] for entry in reasons["robots"]}

        console.set_link_address_status(_link_addresses)

    from fleet.server.central_registry_routes import install_registry_routes
    install_registry_routes(
        app, registry=central_registry, enrollment=enrollment, pairing=pairing,
        sync_token=pairing_sync_token, require_viewer=require_viewer, require_operator=require_operator,
        named_identity=bool(principals) or app.state.password_sessions is not None, observations=workcell_observations,
        device_profile_path=task_service and task_service.store.path, require_named_operator=require_named_operator)
    from fleet.server.camera_peer_adapter import install_camera_peer
    app.state.camera_peer = install_camera_peer(
        app, pairing=pairing, current_users=lambda: site_users or {}, require_named_operator=require_named_operator)

    map_pose, execution_pose, _gather_state = install_pose_and_stuck_runtime(
        app, console=console, console_token=console_token, hub=hub, sightings=sightings,
        policy_evidence=policy_evidence, principals=principals, authorize=authorize,
        require_viewer=require_viewer, require_operator=require_operator,
        require_named_operator=require_named_operator, require_proposer=require_proposer,
        read_guard=read_guard, operator_guard=operator_guard, site_maps=site_maps,
        map_pose_config=map_pose_config, map_pose_port=map_pose_port, simulation_pose=simulation_pose,
        localization_service=localization_service, tracking=tracking, station_ingress=station_ingress,
        lane_compliance_config=lane_compliance_config, identity=identity, site_lanes=site_lanes,
        station_recovery=station_recovery, task_service=task_service, notification_config=notification_config,
        ai_facts_acting=ai_facts_acting, ai_first=ai_first, stuck_resolver_clients=stuck_resolver_clients,
        stuck_resolver_enrolled=stuck_resolver_enrolled, realign_config=realign_config,
        autonomous_robots=autonomous_robots, incident_model_config=incident_model_config,
        vision_signer=vision_signer, vision_sources=vision_sources)

    install_task_dispatch_routes(
        app, console=console, task_service=task_service, configured_omx=configured_omx,
        stop_transport=stop_transport, stop_targets=stop_targets, require_viewer=require_viewer,
        require_operator=require_operator, require_named_operator=require_named_operator,
        read_guard=read_guard, operator_guard=operator_guard, drive_cancel=drive_cancel)
    install_berth_parking_routes(
        app, console=console, task_service=task_service, read_guard=read_guard,
        operator_guard=operator_guard, require_operator=require_operator)

    trip_runner = install_trip_and_map_surfaces(
        app, console=console, console_token=console_token, task_service=task_service,
        site_maps=site_maps, routing_config=routing_config, trip_caps_port=trip_caps_port,
        map_pose_port=map_pose_port, map_pose=map_pose, execution_pose=execution_pose,
        gather_state=_gather_state, lane_junction=lane_junction, trip_config=trip_config,
        traffic_zones=traffic_zones, traffic_authority=traffic_authority,
        traffic_signals=traffic_signals, traffic_signal_advice=traffic_signal_advice,
        trip_lease=trip_lease, autonomous_robots=autonomous_robots, hub=hub, sightings=sightings,
        simulation_pose=simulation_pose, tracking=tracking, require_operator=require_operator,
        require_named_operator=require_named_operator, read_guard=read_guard)

    install_mission_and_channel_surfaces(
        app, policy_admission_core=policy_admission_core, mission_service=mission_service,
        proposal_store=proposal_store, cell_job_store=cell_job_store, cell_job_resolver=cell_job_resolver,
        goal_evidence_service=goal_evidence_service, mission_progress=mission_progress,
        candidate_resolver=candidate_resolver, require_viewer=require_viewer, require_operator=require_operator,
        require_named_operator=require_named_operator, require_proposer=require_proposer,
        read_guard=read_guard, operator_guard=operator_guard, task_service=task_service, trip_runner=trip_runner,
        console=console, deployment_profile=deployment_profile, cell_job_compiler=cell_job_compiler,
        cell_app_service_id=cell_app_service_id, principals=principals, channel_config=channel_config,
        site_logins=site_logins, other_tokens=other_tokens, arm_transfer_observer=arm_transfer_observer,
        sightings=sightings, policy_evidence=policy_evidence, conversation_config=conversation_config,
        channel_model_config=channel_model_config, site_maps=site_maps, assistant_config=assistant_config,
        authorize=authorize, vision_signer=vision_signer, vision_sources=vision_sources,
        require_camera_viewer=require_camera_viewer,
        local_stop_fanout=partial(fanout_local_omx_stops, configured_omx, stop_transport, targets=stop_targets),
        cancel_pending=partial(cancel_pending_task_queue, task_service, console))

    install_static_routes(app)
    from fleet.server.charge_bootstrap import install_charge_runtime
    install_charge_runtime(
        app, factory=charge_runtime_factory, runner=trip_runner, plans=site_maps,
        task_service=task_service, ingress=station_ingress, console=console)
    return app
