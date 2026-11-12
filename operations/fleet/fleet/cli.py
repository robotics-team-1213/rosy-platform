"""fleet CLI — Fleet 서버가 생기기 전까지 운영자가 대형을 여는 입구.

    fleet relay     --robots robots.yaml --leader rosy_01
    fleet formation --robots robots.yaml --leader rosy_01 --formation V --spacing 0.6

`formation` 은 세션을 열고 stdin 명령을 받는다: `reform <FORMATION> [spacing]`,
`resume`, `status`, `stop`. 1 s 마다 릴레이 통계와 세션 상태를 한 줄 찍는다.
SIGINT 는 `stop()` 이다 — 릴레이만 죽이고 팔로워를 무장 상태로 두지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import stat  # noqa: F401
import sys
import threading  # noqa: F401
from pathlib import Path
from typing import Callable, Optional, Sequence  # noqa: F401

from fleet.cli_helpers import (  # noqa: F401
    LOOPBACK_HOSTS,
    _follower_token,
    _hub_link,
    _omx_instances,
    _pending_suffix,
    _resolve_optional_site_config,
    _start_stdin_reader,
    _stats_line,
    _warn_if_world_readable,
    default_web_common,
    formation_console,
    handle_command,
    parse_args,
    policy_from,
    run_formation,
    run_relay,
    spec_from,
    split_robots,
)
from fleet.console_site_config import (  # noqa: F401
    _account_login_config,
    _build_site_map,
    _goal_lease_ttl_s,
    _idle_days,
    _lane_compliance_config,
    _map_pose_config,
    _policy_admission_core,
    _trip_config,
)
from fleet.formation.geometry import DEFAULT_SPACING, Formation, FormationError  # noqa: F401
from fleet.server.console_builders import build_pairing as _build_pairing
from fleet.server.context_options import activate_from_args, add_cli_arguments  # noqa: F401
from fleet.server.sightings_config import _relax_retired_sighting_targets
from fleet.stuck.cli_config import _ai_first, _realign_config, _stuck_resolver_enrolled
from fleet.swarm.api.types import FormationSpec, HoldPolicy, SessionError  # noqa: F401
from fleet.swarm.relay import Relay  # noqa: F401
from fleet.swarm.robots import RobotEndpoint, load_robots  # noqa: F401
from fleet.swarm.session import FormationSession  # noqa: F401
from fleet.swarm.transport import HttpRobotClient
from fleet.traffic.config import (  # noqa: F401
    _station_recovery,
    _traffic_authority,
    _traffic_signal_advice,
    _traffic_signals,
    _traffic_zones,
    _trip_lease,
)


def run_console(args: argparse.Namespace) -> None:
    """관제 서버를 연다. uvicorn 이 자기 루프를 돌리므로 여기는 async 가 아니다."""
    import uvicorn

    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.sightings import SightingService

    _resolve_optional_site_config(args)
    tls_cert = getattr(args, "tls_cert", None)
    tls_key = getattr(args, "tls_key", None)
    if bool(tls_cert) != bool(tls_key):
        sys.exit("--tls-cert and --tls-key must be provided together")
    token_env = getattr(args, "token_env", None)
    if args.token is not None and token_env is not None:
        sys.exit("--token and --token-env cannot be combined")
    console_token = args.token
    if token_env is not None:
        console_token = os.environ.get(token_env)
        if not console_token:
            sys.exit(f"operator token environment variable {token_env} is required")
    discovery_token_env = getattr(args, "discovery_token_env", None)
    discovery_token = None
    if discovery_token_env is not None:
        discovery_token = os.environ.get(discovery_token_env)
        if not discovery_token:
            sys.exit(f"discovery token environment variable {discovery_token_env} is required")
    users_file = getattr(args, "users_file", None)
    site_users = site_logins = None
    if users_file is not None:
        from rosy_account.site_users import load_site_accounts

        site_users, site_logins = load_site_accounts(users_file)
    tasks_db = getattr(args, "tasks_db", None)
    account_config, account_client_config, human_login = _account_login_config(args, site_logins, tasks_db)
    if site_users is not None and tasks_db is None:
        sys.exit("--tasks-db is required with --users-file for persistent audit")
    mission_api = bool(getattr(args, "mission_api", False))
    goal_evidence_config = getattr(args, "goal_evidence_config", None)
    if goal_evidence_config is not None and not mission_api:
        sys.exit("--goal-evidence-config requires --mission-api")
    cell_job_tol_m = getattr(args, "cell_job_stack_tol_m", None)
    if cell_job_tol_m is not None and not mission_api:
        sys.exit("--cell-job-stack-tol-m requires --mission-api")
    if mission_api and tasks_db is None:
        sys.exit("--tasks-db is required with --mission-api")
    development_sessions = None
    if getattr(args, "connection_mode", "paired") == "development":
        # D-473 1: both settings or nothing; a missing one keeps paired, never the other way round.
        if os.environ.get("ROSY_DEPLOYMENT", "").strip() != "development":
            print("warning: --connection-mode development ignored: ROSY_DEPLOYMENT is not development",
                  file=sys.stderr)
        elif tasks_db is None:
            sys.exit("--tasks-db is required with --connection-mode development for the session audit")
        elif not human_login:
            sys.exit("development connection mode requires human login configuration")
        else:
            from fleet.server.development_session import DevelopmentSessions

            development_sessions = DevelopmentSessions()
            print("development connection mode: human login required", file=sys.stderr)
    if mission_api and site_users is None and not human_login:
        sys.exit("--users-file is required with --mission-api for named operator authorization")
    if args.host not in LOOPBACK_HOSTS and not (console_token or users_file is not None or human_login):
        sys.exit("--token or --users-file 없이 루프백 밖으로 열 수 없다")
    if args.host not in LOOPBACK_HOSTS and tasks_db is None:
        sys.exit("--tasks-db is required when the Fleet control surface is externally reachable")
    key_file = getattr(args, "robot_credential_key_file", None)
    if getattr(args, "enrolled_tls_bindings_file", None) is not None and key_file is None:
        sys.exit("--enrolled-tls-bindings-file requires --robot-credential-key-file")
    if key_file is not None and tasks_db is None:
        sys.exit("--tasks-db is required with --robot-credential-key-file")
    if args.robots is None and key_file is None:
        sys.exit("--robots is required unless --robot-credential-key-file is set")
    endpoints = []
    if args.robots is not None:
        endpoints = load_robots(args.robots, allow_empty=bool(key_file or getattr(args, "control_unit_config", None)))
        _warn_if_world_readable(args.robots)
    enrollment_store = robot_key = robot_key_text = robot_key_error = None
    if key_file is not None:
        from fleet.server.enrollment_store import (
            CredentialKeyError, EnrollmentStore, load_key_file,
        )

        enrollment_store = EnrollmentStore(tasks_db)
        try:
            robot_key = load_key_file(key_file)
            robot_key_text = Path(key_file).read_text(encoding="ascii").strip()
        except (CredentialKeyError, OSError, UnicodeDecodeError) as exc:
            # A runtime state only: enrollment answers 503, robots.yaml keeps working.
            robot_key_error = str(exc)
            print(f"warning: robot enrollment unavailable: {exc}", file=sys.stderr)
    signal_console = None
    if args.signals is not None:
        from fleet.server.signals import HttpSignalClient, SignalConsole, load_signals

        signal_eps = load_signals(args.signals)
        _warn_if_world_readable(args.signals)
        signal_console = SignalConsole(signal_eps,
                                       [HttpSignalClient(ep) for ep in signal_eps])
    event_store = None
    events_db = getattr(args, "events_db", None)
    if events_db is not None:
        from fleet.server.core_event_store import CoreEventStore

        event_store = CoreEventStore(events_db)
    pairing_configured = any(ep.fleet_pairing_token is not None for ep in endpoints)
    if pairing_configured and event_store is None:
        sys.exit("--events-db is required when CORE Agent pairing is configured")
    if pairing_configured and not console_token:
        sys.exit("--token or --token-env is required to protect the CORE registry endpoint")
    console = FleetConsole(endpoints, [HttpRobotClient(ep) for ep in endpoints],
                           signal_console=signal_console, event_store=event_store,
                           goal_lease_ttl_s=_goal_lease_ttl_s(args))
    sightings_db = getattr(args, "sightings_db", None)
    sightings_config = getattr(args, "sightings_config", None)
    if sightings_db is not None and sightings_config is None:
        sys.exit("--sightings-db requires --sightings-config")
    sighting_service = None
    tracking_service = None
    identity_config = None
    vision_sources = ()
    vision_preview_secret_env = getattr(args, "vision_preview_secret_env", None)
    vision_preview_secret = (os.environ.get(vision_preview_secret_env)
                             if vision_preview_secret_env else None)
    if vision_preview_secret_env and not vision_preview_secret:
        sys.exit("vision preview secret environment variable is required")
    calibration_drift_watch = None
    if sightings_config is not None:
        from fleet.server.sighting_store import SightingStore
        from fleet.server.sightings_config import load_identity_config, load_sighting_sources

        sources = load_sighting_sources(sightings_config)
        identity_config = load_identity_config(sightings_config)  # D-472, optional identity: block
        if enrollment_store is not None:
            sources = _relax_retired_sighting_targets(
                sources, known={*console.robot_ids, *(
                    row["robot_id"] for row in enrollment_store.rows()
                    if row["state"] != "pending_logout")},
                retired=enrollment_store.retired_robot_ids())
        vision_sources = tuple(source.source_id for source in sources)
        store = SightingStore(sightings_db) if sightings_db is not None else None
        sighting_service = SightingService(
            sources, known_robot_ids=[rid for source in sources for rid in source.robot_ids]
            if enrollment_store is not None else console.robot_ids, store=store,
        )
        if enrollment_store is None:
            sighting_service.retarget(console.robot_ids)  # D-580; enrolled robots sync via SiteRoster
        from fleet.server.tracking import TrackingService
        from fleet.server.tracking_calibration import TrackingCalibrationStore
        from fleet.server.tracking_drift import CalibrationDriftWatch, VisionMapProposalReader

        # D-457: approved tracking calibrations live beside the sightings (memory without a DB).
        calibration_store = TrackingCalibrationStore(sightings_db)
        drift_provider = None
        vision_url = getattr(args, "vision_url", None)
        drift_interval_s = getattr(args, "calibration_drift_interval_s", 60.0)
        if vision_url and drift_interval_s:
            # The watch reads Vision's existing D-375 map-proposal endpoint with a preview
            # lease signed here; without the secret it could not talk to Vision at all.
            if vision_preview_secret is None:
                sys.exit("--vision-url requires --vision-preview-secret-env to sign Vision leases")
            from core_common.protocol.vision_preview import VisionLeaseSigner

            calibration_drift_watch = CalibrationDriftWatch(
                sources=sources, calibrations=calibration_store,
                fetch_proposal=VisionMapProposalReader(
                    base_url=vision_url, signer=VisionLeaseSigner(vision_preview_secret)),
                interval_s=drift_interval_s)
            drift_provider = calibration_drift_watch.verdicts
        elif vision_url:
            print("warning: --calibration-drift-interval-s is 0; the calibration drift "
                  "watch is disabled", file=sys.stderr, flush=True)
        tracking_service = TrackingService(
            sighting_service.sources, calibrations=calibration_store, drift_provider=drift_provider,
            health=getattr(calibration_drift_watch, 'health', None))
        sighting_service.approved_revision = tracking_service.approved_revision
    if getattr(args, "vision_url", None) and tracking_service is None:
        print("warning: --vision-url set but no --sightings-config; the calibration drift "
              "watch is not started", file=sys.stderr, flush=True)
    hub_link = _hub_link(args)
    # D-555: enrolled robots pair at runtime, so the route is up whenever that can happen.
    enrolled_hub = (enrollment_store is not None and event_store is not None and bool(console_token)
                    and (hub_link is not None
                         or any(row.get("hub_digest") for row in enrollment_store.rows())))
    # The outbound CORE Agent route is enabled only for robots with a separate
    # pairing credential. REST-only console configurations remain unchanged.
    hub = console.hub if pairing_configured or enrolled_hub else None
    task_service = None
    if tasks_db is not None:
        from fleet.server.task_service import FleetTaskService
        from fleet.server.task_store import FleetTaskStore

        task_service = FleetTaskService(FleetTaskStore(tasks_db),
                                        robot_ids=console.robot_ids)
    from fleet.server.console_builders import build_enrollment, build_mission_services

    mission_service, proposal_store, goal_evidence_service, cell_job_compiler = build_mission_services(
        mission_api=mission_api, tasks_db=tasks_db, goal_evidence_config=goal_evidence_config,
        cell_job_tol_m=cell_job_tol_m)
    from fleet.server.discovery import DiscoveryStore

    discovery = DiscoveryStore() if discovery_token is not None else None
    enrollment = None
    if enrollment_store is not None:
        enrollment, roster = build_enrollment(
            console=console, task_service=task_service, sighting_service=sighting_service,
            enrollment_store=enrollment_store, robot_key=robot_key, robot_key_error=robot_key_error,
            discovery=discovery, tls_file=getattr(args, "enrolled_tls_bindings_file", None),
            hub_link=hub_link if enrolled_hub else None, tracking_service=tracking_service,
            last_activity=event_store.last_received_times if event_store else None, idle_removal_s=_idle_days(args))
    from fleet.server.site_lanes import parse_lane_graph_flags, unmatched_map_ids

    try:
        site_lanes = parse_lane_graph_flags(getattr(args, "site_lane_graph", None),
                                            getattr(args, "site_lane_paint", None))
    except ValueError as exc:
        sys.exit(str(exc))
    for map_id in unmatched_map_ids(site_lanes, sighting_service.sources if sighting_service is not None else ()):
        print(f"warning: --site-lane-graph/--site-lane-paint map id {map_id!r} matches no sighting "
              "source; that lane entry is served to no camera", file=sys.stderr, flush=True)
    site_maps, routing_config = _build_site_map(args, tasks_db)
    map_pose_config = _map_pose_config(args)
    pairing_service, pairing_sync_token = _build_pairing(
        args, tls_cert=tls_cert, tasks_db=tasks_db, sighting_service=sighting_service,
        site_name=console.fleet_name)
    from fleet.server.localization_service import build_localization_service

    localization_service = build_localization_service(
        console, sighting_service, enabled=getattr(args, "localization_service", True),
        overhead_cue=getattr(args, "localization_overhead_cue", False),
        pose_request_overhead=getattr(args, "pose_request_overhead", True),
        lane_rules=getattr(args, "localization_lane_rules", None))
    stuck_resolver_clients = None
    stuck_resolver_enrolled = _stuck_resolver_enrolled(args)
    if getattr(args, "stuck_resolver_on", True):
        stuck_resolver_clients = {
            ep.robot_id: HttpRobotClient(dataclasses.replace(ep, token=ep.resolver_token))
            for ep in endpoints if ep.resolver_token}
        if stuck_resolver_enrolled:
            print("stuck resolver answers enrolled robots with Fleet's credential: "
                  + ", ".join(sorted(stuck_resolver_enrolled)), file=sys.stderr)
        if not stuck_resolver_clients and not stuck_resolver_enrolled:
            print("note: stuck resolver on, but no robot has a resolver_token; "
                  "every stuck goes to the console (no_resolver_token)", file=sys.stderr)
        else:
            print("stuck resolver answers: " + ", ".join(sorted(stuck_resolver_clients)), file=sys.stderr)
    central_registry = None
    if getattr(args, "central", False):
        # D-454 1단계: 중앙 프로파일 — 등록 로스터가 정본이므로 등록 저장소가 필요하다.
        if enrollment is None:
            sys.exit("--central requires --robot-credential-key-file and --tasks-db; the central "
                     "registry reads the site roster as its source of truth")
        from fleet.server.central_registry import CentralRegistry

        central_registry = CentralRegistry(roster, console=console, discovery=discovery)
    notification_config = None
    channel_config = None
    if getattr(args, 'discord_intake_config', None) is not None:
        from fleet.server.channel_requests import ChannelConfig
        channel_config = ChannelConfig.load(args.discord_intake_config)
    elif getattr(args, 'discord_intake_config_optional', None) is not None:
        from fleet.server.channel_requests import ChannelConfig
        channel_config = ChannelConfig.load(args.discord_intake_config_optional, optional=True)
    from fleet.server.channel.options import load_conversation_options
    model_config, conversation_config, assistant_config = load_conversation_options(args)
    if getattr(args, 'notifications_config', None) is not None:
        from fleet.incidents.notifications import NotificationConfig
        notification_config = NotificationConfig.load(args.notifications_config)
    activate_from_args(args)
    workcell_observations = None
    observation_config = getattr(args, "workcell_observations", None)
    if observation_config is not None:
        from fleet.server.workcell_observation_config import load_workcell_observations
        workcell_observations = load_workcell_observations(observation_config)
    app = create_app(console, console_token=console_token, web_common=args.web_common,
                     control_unit_config=getattr(args, "control_unit_config", None),
                     workcell_observations=workcell_observations,
                     hub=hub, sightings=sighting_service, tracking=tracking_service,
                     calibration_drift_watch=calibration_drift_watch, task_service=task_service,
                     mission_service=mission_service, proposal_store=proposal_store,
                     cell_job_compiler=cell_job_compiler,
                     cell_app_service_id=getattr(args, "cell_app_service_id", None),
                     goal_evidence_service=goal_evidence_service,
                     site_users=site_users, site_logins=site_logins, discovery=discovery,
                     account_config=account_config, account_client_config=account_client_config,
                     discovery_token=discovery_token,
                     approved_peer_directory_file=getattr(args, 'approved_peer_directory_file', None),
                     start_task_dispatcher=not mission_api,
                     vision_lease_secret=vision_preview_secret,
                     vision_sources=vision_sources,
                     lan_camera_proxy=getattr(args, "lan_camera_proxy", False),
                     enrollment=enrollment, robot_credential_key=robot_key_text, site_lanes=site_lanes,
                     pairing=pairing_service, pairing_sync_token=pairing_sync_token,
                     localization_service=localization_service,
                     stuck_resolver_clients=stuck_resolver_clients,
                     stuck_resolver_enrolled=stuck_resolver_enrolled,
                     realign_config=_realign_config(args),
                     ai_facts_acting=_stuck_resolver_enrolled(args, "ai_facts_acting"),
                     ai_first=_ai_first(args),
                     autonomous_robots=_stuck_resolver_enrolled(args, "autonomous_robots"),
                     policy_admission_core=_policy_admission_core(args), central_registry=central_registry,
                     development_sessions=development_sessions,
                     site_maps=site_maps, routing_config=routing_config,
                     map_pose_config=map_pose_config, trip_config=_trip_config(args),
                     traffic_zones=_traffic_zones(args), traffic_authority=_traffic_authority(args),
                     traffic_signals=_traffic_signals(args), traffic_signal_advice=_traffic_signal_advice(args),
                     trip_lease=_trip_lease(args), station_recovery=_station_recovery(args),
                     identity_config=identity_config,
                     lane_compliance_config=_lane_compliance_config(args), notification_config=notification_config,
                     channel_config=channel_config, channel_model_config=model_config,
                     conversation_config=conversation_config, assistant_config=assistant_config, omx_instances=_omx_instances())
    signals_note = f", {len(signal_eps)} signals" if signal_console is not None else ""
    print(f"fleet console: http://{args.host}:{args.port}/console  "
          f"({len(console.robot_ids)} robots{signals_note})",
          flush=True)
    tls_options = ({"ssl_certfile": str(tls_cert), "ssl_keyfile": str(tls_key)}
                   if tls_cert is not None else {})
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", **tls_options)


def run(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if args.command == "console":
        try:
            run_console(args)
        except KeyboardInterrupt:
            pass
        return
    runner = run_relay if args.command == "relay" else run_formation
    try:
        asyncio.run(runner(args))
    except KeyboardInterrupt:
        pass


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Run Fleet through its public execution interface."""
    return run(argv)


if __name__ == "__main__":
    main()
