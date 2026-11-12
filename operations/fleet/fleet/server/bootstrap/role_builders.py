"""Role-specific runtime and route builders extracted from Fleet app.py (D-362 / D-766)."""

from __future__ import annotations

import dataclasses
from functools import partial
from types import SimpleNamespace

from fastapi import Depends

from fleet.hub.server import fan_out_events as _fan_out_events
from fleet.incidents.automation.runtime import install_incident_runtime
from fleet.localization.lane_compliance import LaneComplianceConfig
from fleet.server.background_workers import attempt_open
from fleet.server.cell_arm_dispatcher import CellJobDispatcher
from fleet.server.cell_app_routes import install_cell_app_routes
from fleet.server.cell_job_routes import install_cell_job_routes
from fleet.server.cell_job_store import CellJobStore
from fleet.server.channel_requests import install_channel_feature
from fleet.server.console_routes import install_console_routes
from fleet.server.console_view import trip_caps
from fleet.server.formation_mission import install_formation_mission_routes
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.guide_service import GuideService, install_guide_routes
from fleet.server.host_control_routes import install_host_control_routes
from fleet.server.ingest_routes import install_ingest_routes
from fleet.server.lane_compliance_service import LaneComplianceMonitor, install_lane_compliance_routes
from fleet.server.lane_route_routes import install_lane_route_routes
from fleet.server.local_action_transport import UnixLocalActionTransport
from fleet.server.map_pose_service import MapPoseService, install_map_pin_route, install_map_pose_routes
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_model_turn_scheduler import MissionModelTurnScheduler
from fleet.server.mission_model_turn_store import MissionModelTurnStore
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_routes import install_mission_routes
from fleet.server.mission_storage import configure_mission_storage, validate_model_turn_worker
from fleet.server.path_history import PathRecorder, PathStore, install_path_routes
from fleet.server.signal_routes import install_signal_routes
from fleet.server.site_auth import SitePrincipal
from fleet.server.site_map_routes import install_site_map_routes
from fleet.server.step_action_kinds import dispatch_open
from fleet.server.teach_routes import TeachService, install_teach_routes
from fleet.server.tether_routes import install_tether_routes
from fleet.server.trip_guard import engaged, install_trip_guard, release_queue
from fleet.server.trip_job_routes import install_trip_job_routes
from fleet.server.trip_ports import HttpLaneJunction
from fleet.server.trip_routes import install_trip_routes
from fleet.server.trip_runner import TripConfig, TripRunner, cached_battery
from fleet.server.vision_preview_routes import install_vision_preview_routes
from fleet.server.work_routes import install_work_routes
from fleet.stuck.ai_facts import install_ai_routes
from fleet.stuck.ai_first import AiFirst
from fleet.stuck.ai_routes import install_ai_first_routes, rosy_cam_lease
from fleet.stuck.deadlock import AiReplan
from fleet.stuck.episodes import ProblemLog
from fleet.stuck.loop import StuckResolverLoop
from fleet.stuck.problems import ProblemWatch
from fleet.stuck.resolver import ResolverConfig, StuckResolver
from fleet.swarm.anchor import anchored_relay_factory
from rosy.world.state.projections.map_pose import MapPoseConfig


def build_mission_and_cell_runtime(*, task_service, mission_service, proposal_store, goal_evidence_service,
                                   candidate_resolver, cell_job_compiler, cell_item_pose_tolerance,
                                   enable_mission_dispatcher, configured_omx, omx_action_transport, omx_socket_root,
                                   deployment_profile, cell_goal_registry, omx_cell_grant_revisions,
                                   mission_model_turn_max_rows, mission_model_turn_worker,
                                   post_action_observation_source, log):
    mission_configured = configure_mission_storage(
        task_service, mission_service, proposal_store, goal_evidence_service, candidate_resolver, cell_job_compiler)
    cell_job_store = CellJobStore(mission_service.store.path) if mission_configured else None
    if cell_job_store is not None:
        cell_job_store.recover_after_startup()
    cell_job_resolver = None
    if cell_job_compiler is not None:
        from fleet.server.cell_goal_evidence import make_cell_job_resolver
        cell_job_resolver = make_cell_job_resolver(cell_job_compiler, cell_item_pose_tolerance)
    if enable_mission_dispatcher and not mission_configured:
        raise ValueError("Mission dispatcher requires the complete Mission API")
    if enable_mission_dispatcher and not configured_omx:
        raise ValueError("Mission dispatcher requires configured OMX workcells")
    action_transport = omx_action_transport
    if enable_mission_dispatcher and action_transport is None:
        action_transport = UnixLocalActionTransport(omx_socket_root)
    on_terminal = goal_evidence_service.on_action_terminal if goal_evidence_service is not None else None
    mission_dispatcher = (MissionDispatcher(mission_service, task_service.store, action_transport, configured_omx,
                                            on_action_terminal=on_terminal)
                          if enable_mission_dispatcher and dispatch_open(deployment_profile, "PICK_PLACE") else None)
    cell_goal_evidence_service = None
    if cell_goal_registry is not None:
        from fleet.server.cell_goal_evidence_registry import CellGoalRegistry
        from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
        if deployment_profile != "simulation":
            raise ValueError("Cell goal evidence (sim_model_pose) is accepted only in the simulation profile")
        if cell_job_compiler is None or cell_job_store is None or not isinstance(cell_goal_registry, CellGoalRegistry):
            raise ValueError("Cell goal registry requires the persistent Cell Job API and compiler")
        cell_goal_evidence_service = CellGoalEvidenceService(
            cell_job_store, cell_goal_registry, GoalEvidenceStore(mission_service.store.path))

    def on_step_action_succeeded(job, index):
        if cell_goal_evidence_service is None:
            return None
        try:
            return cell_goal_evidence_service.on_action_terminal(job["mission_id"], index)
        except Exception:
            log.exception("stored Cell goal evidence could not be applied for %s", job["mission_id"])
            return None

    cell_job_dispatcher = (CellJobDispatcher(cell_job_store, task_service.store, action_transport, configured_omx,
                                             omx_cell_grant_revisions or {}, deployment_profile=deployment_profile,
                                             on_step_action_succeeded=on_step_action_succeeded)
                           if enable_mission_dispatcher else None)
    mission_progress = MissionProgressService(mission_service.store) if mission_configured else None
    mission_model_turn_store = (MissionModelTurnStore(mission_service.store.path, max_rows=mission_model_turn_max_rows)
                                if mission_configured else None)
    mission_model_turn_scheduler = (MissionModelTurnScheduler(mission_service=mission_service,
                                                              progress_service=mission_progress,
                                                              turn_store=mission_model_turn_store,
                                                              policy_revision="er2-feedback-v1")
                                    if mission_configured else None)
    validate_model_turn_worker(mission_model_turn_worker, mission_model_turn_scheduler, mission_model_turn_store,
                               post_action_observation_source)
    return SimpleNamespace(
        mission_configured=mission_configured, cell_job_store=cell_job_store, cell_job_resolver=cell_job_resolver,
        action_transport=action_transport, mission_dispatcher=mission_dispatcher,
        cell_goal_evidence_service=cell_goal_evidence_service, cell_job_dispatcher=cell_job_dispatcher,
        mission_progress=mission_progress, mission_model_turn_store=mission_model_turn_store,
        mission_model_turn_scheduler=mission_model_turn_scheduler)


def install_pose_and_stuck_runtime(app, *, console, console_token, hub, sightings, policy_evidence, principals,
                                   authorize, require_viewer, require_operator, require_named_operator,
                                   require_proposer, read_guard, operator_guard, site_maps, map_pose_config,
                                   map_pose_port, simulation_pose, localization_service, tracking, station_ingress,
                                   lane_compliance_config, identity, site_lanes, station_recovery, task_service,
                                   notification_config, ai_facts_acting, ai_first, stuck_resolver_clients,
                                   stuck_resolver_enrolled, realign_config, autonomous_robots, incident_model_config,
                                   vision_signer, vision_sources):
    async def _gather_state(robot_id: str):
        return (await console._gather_state(robot_id))[0]

    async def _rest_state(robot_id: str):
        return await console._client(robot_id).state()

    map_pose_config = map_pose_config or MapPoseConfig()
    if sightings is not None and map_pose_config.sighting_lease_s > sightings.lease_s:
        raise ValueError("fleet.map_pose.sighting_lease_s must not exceed the sighting ingest lease")
    map_pose = MapPoseService(
        lambda: console.robot_ids, config=map_pose_config,
        map_id=lambda: (active := site_maps.active()) and active[1].map_id,
        source_map_ids=[source.map_id for source in (sightings.sources if sightings is not None else ())],
        gather=_gather_state, gather_rest=_rest_state, client_identity=console._client)
    map_pose.active_map_id()
    execution_pose = map_pose_port if simulation_pose else map_pose
    if simulation_pose:
        execution_pose.bind_active_map(
            lambda: ((active := site_maps.active())[1].map_id, active[0]) if site_maps.active() is not None else (None, None))
    app.state.execution_map_pose = execution_pose
    console.set_state_sink(map_pose.observe_state)
    console.read_state = map_pose.state
    identity.map_pose = map_pose.arbitrated_pose
    console.formation_relay_factory = lambda enabled: anchored_relay_factory(map_pose, enabled)
    if localization_service is not None:
        localization_service.set_overhead_pose(map_pose.arbitrated_pose)
    app.state.map_pose = map_pose
    if tracking is not None:
        tracking.map_pose = map_pose.arbitrated_pose
    install_ingest_routes(app, console=console, console_token=console_token, hub=hub, sightings=sightings,
                          policy_evidence=policy_evidence, principals=principals, require_viewer=require_viewer,
                          read_guard=read_guard, map_pose=map_pose, station_ingress=station_ingress)
    install_map_pose_routes(app, service=execution_pose, read_guard=read_guard)
    app.state.lane_compliance = LaneComplianceMonitor(
        lambda: console.robot_ids, poses=execution_pose, site_maps=site_maps,
        config=lane_compliance_config or LaneComplianceConfig(), identity=identity, clients=console.clients,
        stuck_open=lambda robot_id: (getattr(app.state, "line_stuck", None) is not None
                                     and app.state.line_stuck.view(robot_id) is not None))
    install_lane_compliance_routes(app, monitor=app.state.lane_compliance, read_guard=read_guard)
    db_path = task_service.store.path if task_service else None
    install_console_routes(
        app, console=console, sightings=sightings, require_viewer=require_viewer, read_guard=read_guard,
        operator_guard=operator_guard, site_lanes=site_lanes, require_operator=require_operator,
        require_named_operator=require_named_operator, answer_log_path=db_path,
        tracking=tracking, identity=identity, station_recovery=station_recovery, require_proposer=require_proposer)
    if app.state.line_stuck._log is not None:
        app.state.line_stuck._log.notifications.config = notification_config
    app.state.ai_facts = install_ai_routes(app, read_guard=read_guard, authorize=authorize, db_path=db_path, acting=ai_facts_acting)
    app.state.line_stuck.ai_view = app.state.ai_facts.robot_view
    app.state.ai_first = ai_first or AiFirst()
    app.state.ai_facts.first, app.state.ai_first.profiles = app.state.ai_first, app.state.ai_facts.profiles
    app.state.ai_episodes = ProblemLog(db_path)
    app.state.ai_first.human_classes = app.state.ai_episodes.active
    if tracking is not None and tracking.enabled:
        from fleet.server.measured_calibration import active_map_revision
        from fleet.server.start_point_routes import install_start_point_routes
        from fleet.server.start_points import StartPointService
        from fleet.server.tracking_routes import install_tracking_routes
        install_tracking_routes(app, tracking=tracking, require_operator=require_operator, read_guard=read_guard,
                                operator_guard=operator_guard, require_named_operator=require_named_operator,
                                map_revision=partial(active_map_revision, site_maps), map_pose=map_pose)
        install_start_point_routes(app, service=StartPointService(sources=tracking.sources, calibrations=tracking.calibrations),
                                   read_guard=read_guard, require_named_operator=require_named_operator)
    install_signal_routes(app, signals=console._signals, require_viewer=require_viewer, require_operator=require_operator,
                          require_named_operator=require_named_operator,
                          auth_configured=bool(principals or console_token) or app.state.password_sessions is not None)
    if stuck_resolver_clients is not None:
        resolver_core = StuckResolver(ResolverConfig(), realign=realign_config,
                                      painted=lambda: (site_maps.active() or (None,) * 4)[3])
        resolver_core.autonomous_robots = frozenset(autonomous_robots)
        app.state.line_stuck.peer_config = resolver_core.config
        app.state.stuck_resolver = StuckResolverLoop(
            app.state.fleet_gather, app.state.line_stuck, resolver_core,
            clients=lambda: {**{rid: client for rid, client in console.clients().items()
                                if rid in stuck_resolver_enrolled}, **stuck_resolver_clients})
        app.state.stuck_resolver.map_pose = map_pose.stuck_pose
        app.state.stuck_resolver.stuck_event = console.hub.registry.stuck_event
        app.state.stuck_resolver.heading_review = app.state.lane_compliance.stuck_heading
        app.state.stuck_resolver.realign_evidence = app.state.lane_compliance.realign_evidence
        app.state.line_stuck.heading_review = app.state.lane_compliance.stuck_heading
        resolver_core.at_crosswalk = app.state.lane_compliance.at_crosswalk
        app.state.stuck_resolver.ai_facts = app.state.ai_facts.acting_facts
        app.state.stuck_resolver.ai_board = app.state.ai_facts
        resolver_core.ai_first = app.state.ai_first
        app.state.stuck_resolver.episodes, app.state.stuck_resolver.problems = app.state.ai_episodes, ProblemWatch()
    install_incident_runtime(app, incident_model_config)
    install_ai_first_routes(
        app, first=app.state.ai_first, line_stuck=app.state.line_stuck,
        loop=getattr(app.state, "stuck_resolver", None), episodes=app.state.ai_episodes,
        read_guard=read_guard, authorize=authorize, require_named_operator=require_named_operator,
        clients=console.clients, rosy_cam=lambda rid: rosy_cam_lease(rid, sightings, map_pose, vision_signer, vision_sources),
        pose=map_pose.stuck_pose, deadlock_case=lambda: getattr(app.state.trip_runner.traffic.ai_replan, "case", None))

    def ai_chain() -> dict:
        enrolled = console.clients() if stuck_resolver_enrolled else {}
        return {"resolver": getattr(app.state, "stuck_resolver", None) is not None,
                "robots": [{"robot_id": rid,
                            "credential": ("token" if rid in (stuck_resolver_clients or {})
                                           else "enrolled" if rid in stuck_resolver_enrolled and rid in enrolled else "none"),
                            "ai_acting": rid in ai_facts_acting,
                            "last_answer": app.state.line_stuck.last_resolver_answer(rid)}
                           for rid in console.robot_ids]}
    app.state.ai_facts.chain = ai_chain
    if hub is not None and (task_service is not None or stuck_resolver_clients is not None):
        resolver = getattr(app.state, "stuck_resolver", None)
        hub.set_event_callback(_fan_out_events(task_service.project_core_event if task_service is not None else None,
                                               resolver.wake if resolver is not None else None))
    return map_pose, execution_pose, _gather_state


def install_trip_and_map_surfaces(app, *, console, console_token, task_service, site_maps, routing_config,
                                  trip_caps_port, map_pose_port, map_pose, execution_pose, gather_state, lane_junction,
                                  trip_config, traffic_zones, traffic_authority, traffic_signals, traffic_signal_advice,
                                  trip_lease, autonomous_robots, hub, sightings, simulation_pose, tracking,
                                  require_operator, require_named_operator, read_guard):
    install_lane_route_routes(app, console=console, task_service=task_service, site_maps=site_maps,
                              require_named_operator=require_named_operator)

    async def _trip_caps(robot_id: str):
        display = console._capability_display
        caps = trip_caps(await display.shown(robot_id, wait_s=2.0))
        age = display.age(robot_id)
        if caps is not None and (age is None or age > 2 * display.refresh_s):
            caps = dataclasses.replace(caps, line_camera=None)
        return caps

    if (trip_lease or {}).get("required") and console_token and console.uses_rest_token(console_token):
        raise ValueError("D-541: a robot REST token must be Fleet's own, not the console token")
    trip_runner = TripRunner(
        store=site_maps, routing_config=routing_config or site_maps.routing_config,
        caps=trip_caps_port or _trip_caps, poses=map_pose_port or map_pose,
        junction=lane_junction or HttpLaneJunction(console.clients, map_pose.state, map_pose.read_number),
        goal=lambda *args, **kwargs: console.goal(*args, trip=True, **kwargs),
        cancel_goal=console.cancel, config=trip_config or TripConfig(),
        engaged=partial(engaged, console), release_queue=partial(release_queue, console),
        roster=lambda: console.robot_ids, traffic_zones=traffic_zones, authority=traffic_authority,
        traffic_signals=traffic_signals, signal_advice=traffic_signal_advice,
        lease=trip_lease and {**trip_lease, "holder": console.fleet_name},
        renew_lease=lambda robot_id: console.goal_leases.renew("trip", robot_id), battery=cached_battery(app.state))
    install_trip_guard(console, trip_runner, claims=task_service.store.resource_claims if task_service else None)
    trip_runner.autonomous_robots = frozenset(autonomous_robots)
    trip_runner.traffic.autonomous_robots = frozenset(autonomous_robots)
    if hub is not None:
        from fleet.server.junction_signal import signal_for
        hub.junction_signal = partial(signal_for, traffic=trip_runner.traffic, poses=execution_pose, site_maps=site_maps)
    trip_runner.traffic.ai_replan = AiReplan(app.state.ai_first, app.state.ai_facts, app.state.ai_episodes)
    install_map_pin_route(app, service=map_pose, require_named_operator=require_named_operator,
                          record_event=site_maps.record_event, busy=trip_runner.robot_busy)
    if task_service is not None:
        console.goal_leases.attempt_open = partial(attempt_open, task_service.store)
        console.goal_leases.admit_attempt = task_service.admit_attempt
        console.goal_leases.bind_native_receipt = task_service.bind_native_receipt
        console.goal_leases.native_required = task_service.native_required
        from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
        console.goal_leases.prepare_send = partial(prepare_send, console.goal_leases)
        task_service.core_events = hub.event_store if hub is not None else None

    @app.post("/api/fleet/goal-lease/presence", tags=["fleet"])
    def fleet_goal_lease_presence(principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        console.goal_leases.operator_present()
        return {"present": True}

    app.state.line_stuck.trip_busy = trip_runner.robot_busy
    if getattr(app.state, "stuck_resolver", None) is not None:
        app.state.stuck_resolver.trip_busy = trip_runner.robot_busy
    install_site_map_routes(
        app, site_maps=site_maps, route_active=lambda: trip_runner.running() is not None
        or console.formation_status()["active"] or app.state.teach.view()["recording"] is not None,
        read_guard=read_guard, require_named_operator=require_named_operator)
    marker_sources = sightings is not None and any(s.place_markers for s in sightings.sources)
    install_teach_routes(
        app, service=TeachService(poses=map_pose if simulation_pose else map_pose_port or map_pose,
                                  site_maps=site_maps, roster=lambda: console.robot_ids,
                                  place_markers=sightings.fresh_place_marker if marker_sources else None),
        read_guard=read_guard, require_named_operator=require_named_operator)
    install_tether_routes(app, console=console, trip_runner=trip_runner, read_guard=read_guard,
                          require_named_operator=require_named_operator)
    app.state.paths = PathRecorder(
        PathStore(task_service.store.path if task_service is not None else None),
        roster=lambda: console.robot_ids, gather=gather_state, map_pose=map_pose,
        tracking=tracking if tracking is not None and tracking.enabled else None,
        trips=trip_runner.open_trips, formation=console.formation_status)
    install_path_routes(app, paths=app.state.paths, read_guard=read_guard)
    install_trip_routes(app, console=console, site_maps=site_maps, caps_for=_trip_caps,
                        routing_config=routing_config or site_maps.routing_config, require_operator=require_operator,
                        require_named_operator=require_named_operator, runner=trip_runner, read_guard=read_guard)
    app.state.guide = GuideService(
        gather=app.state.fleet_gather, poses=map_pose, site_maps=site_maps,
        tracking=tracking if tracking is not None and tracking.enabled else None, zones=trip_runner.traffic.zone_edges)
    install_guide_routes(app, service=app.state.guide, read_guard=read_guard)
    return trip_runner


def install_mission_and_channel_surfaces(app, *, policy_admission_core, mission_service, proposal_store, cell_job_store,
                                         cell_job_resolver, goal_evidence_service, mission_progress, candidate_resolver,
                                         require_viewer, require_operator, require_named_operator, require_proposer,
                                         read_guard, operator_guard, task_service, trip_runner, console,
                                         deployment_profile, cell_job_compiler, cell_app_service_id, principals,
                                         channel_config, site_logins, other_tokens, arm_transfer_observer, sightings,
                                         policy_evidence, conversation_config, channel_model_config, site_maps,
                                         assistant_config, authorize, vision_signer, vision_sources,
                                         require_camera_viewer, local_stop_fanout, cancel_pending):
    proposal_create = proposal_resolve = mission_admit = None
    if mission_service is not None:
        proposal_create, proposal_resolve, mission_admit = install_mission_routes(
            app, policy_admission_core=policy_admission_core, mission_service=mission_service,
            proposal_store=proposal_store, cell_job_store=cell_job_store, cell_job_resolver=cell_job_resolver,
            goal_evidence_service=goal_evidence_service, mission_progress=mission_progress,
            candidate_resolver=candidate_resolver, require_viewer=require_viewer, require_operator=require_operator,
            require_named_operator=require_named_operator, require_proposer=require_proposer,
            read_guard=read_guard, operator_guard=operator_guard)
        install_cell_job_routes(app, cell_job_store=cell_job_store, proposal_store=proposal_store,
                                require_viewer=require_viewer, require_named_operator=require_named_operator,
                                operator_guard=operator_guard, read_guard=read_guard)
    install_work_routes(app, task_service=task_service, mission_service=mission_service, require_viewer=require_viewer,
                        require_named=(require_operator, require_named_operator), read_guard=read_guard)
    trip_jobs = install_trip_job_routes(
        app, store=cell_job_store, runner=trip_runner, console=console, deployment_profile=deployment_profile,
        episodes=app.state.ai_episodes, require_named_operator=require_named_operator, operator_guard=operator_guard,
        require_viewer=require_viewer, read_guard=read_guard, require_proposer=require_proposer)
    install_formation_mission_routes(app, console=console, jobs=trip_jobs,
                                     require_named_operator=require_named_operator, operator_guard=operator_guard,
                                     read_guard=read_guard)
    cell_prepare = install_cell_app_routes(
        app, mission_service=mission_service, compiler=cell_job_compiler, service_id=cell_app_service_id,
        principals=principals, proposal_create=proposal_create, proposal_resolve=proposal_resolve,
        require_viewer=require_viewer, require_named_operator=require_named_operator)
    install_channel_feature(
        app, config=channel_config, task_service=task_service, principals=principals, site_logins=site_logins,
        require_operator=require_operator, require_named_operator=require_named_operator, read_guard=read_guard,
        existing_tokens=other_tokens + ((arm_transfer_observer.token,) if arm_transfer_observer else ()),
        console=console, secret_owners=(sightings, policy_evidence), proposals=proposal_store,
        proposal_create=proposal_create, proposal_resolve=proposal_resolve, cell_prepare=cell_prepare,
        mission_admit=mission_admit, cell_service_id=cell_app_service_id)
    from fleet.server.intent_routes import install_intent_routes
    install_intent_routes(
        app, console=console, task_service=task_service, require_operator=require_operator,
        require_named_operator=require_named_operator,
        robot_busy=lambda robot: "trip" if trip_runner.robot_busy(robot) else engaged(console, robot),
        operator_guard=operator_guard, local_stop_fanout=local_stop_fanout, cancel_pending=cancel_pending)
    from ..channel.conversation.runtime import install_conversation_routes
    install_conversation_routes(app, conversation_config, channel_model_config, site_maps, task_service,
                                require_operator, read_guard)
    from ..assistant.runtime import install_assistant
    install_assistant(app, assistant_config, task_service=task_service,
                      require_named_operator=require_named_operator, authorize=authorize)
    install_vision_preview_routes(app, signer=vision_signer, sources=vision_sources,
                                  require_camera_viewer=require_camera_viewer,
                                  require_named_operator=require_named_operator)
    from fleet.host_control import UnavailableHostHelper, helper_from_config
    install_host_control_routes(
        app, require_operator=require_operator, require_named_operator=require_named_operator,
        require_viewer=require_viewer,
        helper=(helper_from_config() if principals or app.state.password_sessions is not None
                else UnavailableHostHelper()))
