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
import stat
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from fleet.formation.geometry import DEFAULT_SPACING, Formation, FormationError
from fleet.swarm.relay import Relay
from fleet.swarm.robots import RobotEndpoint, load_robots
from fleet.swarm.session import FormationSession, FormationSpec, HoldPolicy, SessionError
from fleet.swarm.transport import HttpRobotClient


def default_web_common() -> Path:
    """Resolve installed assets first, with a source-tree fallback for host tools.

    A web_common directory is one that ships ``shared-assets.json``."""
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("web_common"))
        if (share / "shared-assets.json").is_file():
            return share
    except (ImportError, LookupError):
        pass
    return (Path(__file__).resolve().parents[3] / "shared") / "web"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fleet")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--robots", required=True, type=Path, help="robots.yaml")
        p.add_argument("--leader", required=True, help="리더 robot_id")

    relay = sub.add_parser("relay", help="리더 pose → 팔로워 reference 릴레이만")
    common(relay)

    formation = sub.add_parser("formation", help="대형 세션 (무장 + 릴레이 + FOR-004)")
    common(formation)
    formation.add_argument("--formation", default="COLUMN", choices=[f.value for f in Formation])
    formation.add_argument("--spacing", type=float, default=DEFAULT_SPACING)
    formation.add_argument("--grid-cols", type=int, default=2)
    formation.add_argument("--max-speed", type=float, default=0.15)
    formation.add_argument("--stream-timeout-ms", type=int, default=1000)
    formation.add_argument("--policy", default="HOLD", choices=[p.value for p in HoldPolicy])

    console = sub.add_parser("console", help="사이트 관제 서버 (웹 UI + 로봇별 미션 하달)")
    console.add_argument("--robots", default=None, type=Path,
                         help="robots.yaml — optional with --robot-credential-key-file")
    console.add_argument("--signals", default=None, type=Path,
                         help="signals.yaml — 없으면 신호등 기능은 비어 있는 채로 뜬다")
    console.add_argument("--host", default="127.0.0.1")
    console.add_argument("--port", type=int, default=8090)
    console.add_argument("--web-common", default=default_web_common(), type=Path,
                         help="공용 L1 웹 자산 디렉터리 — /common 아래로 서빙한다(D-157)")
    console.add_argument("--token", default=None,
                         help="관제 UI 접속 토큰. 루프백 밖으로 열 때는 필수다")
    console.add_argument("--token-env", default=None,
                         help="환경변수에서 관제 토큰을 읽는다(명령행 secret 노출 방지)")
    console.add_argument("--discovery-token-env", default=None,
                         help="host mDNS scanner credential environment variable")
    console.add_argument("--approved-peer-directory-file", default=None, type=Path,
                         help="admin-provisioned public peer metadata JSON; no credentials or enrollment")
    console.add_argument("--enrolled-tls-bindings-file",
                         default=os.environ.get("ROSY_ENROLLED_TLS_BINDINGS_FILE") or None, type=Path,
                         help="public approved TLS bindings for existing encrypted enrollments")
    console.add_argument("--vision-preview-secret-env", default=None,
                         help="dedicated Fleet-to-Vision preview lease signing secret")
    console.add_argument("--users-file", default=None, type=Path,
                         help="개인별 Fleet API 토큰 digest 및 역할을 담은 root 관리 파일")
    console.add_argument("--stuck-resolver", action="store_true",
                         help="D-438: answer lane stucks with rules for robots that have a "
                              "resolver_token in robots.yaml; others go to the console")
    console.add_argument("--tls-cert", default=None, type=Path,
                         help="HTTPS server certificate chain; pair with --tls-key")
    console.add_argument("--tls-key", default=None, type=Path,
                         help="HTTPS private key; mount as a runtime secret")
    console.add_argument("--sightings-config", default=None, type=Path,
                         help="source/map/calibration sighting config (secret values stay in env)")
    console.add_argument("--site-lane-graph", action="append", default=None, metavar="[MAP_ID=]PATH",
                         help="lane_graph.yaml drawn over the ceiling camera by the D-375 map-fit "
                              "view; without MAP_ID it applies to every map. Display only")
    console.add_argument("--site-lane-paint", action="append", default=None, metavar="[MAP_ID=]PATH",
                         help="lane paint STL (Vision's --map-paint file) drawn by the same view")
    console.add_argument("--no-localization-service", dest="localization_service",
                         action="store_false", default=True,
                         help="D-395: do not run the Fleet localization service (on by default)")
    console.add_argument("--localization-overhead-cue", action="store_true", default=False,
                         help="D-395: feed overhead sightings to the localization arbiter and "
                              "monitor. Off by default: the D-257 amendment is not accepted")
    console.add_argument("--localization-lane-rules", default=None, type=Path,
                         help="lane_rules.yaml with reference_squares (default: map_v2_fleet)")
    console.add_argument("--sightings-db", default=None, type=Path,
                         help="SQLite path for latest sightings and acceptance audit")
    console.add_argument("--events-db", default=None, type=Path,
                         help="SQLite path for durable CORE Agent event history")
    console.add_argument("--tasks-db", default=None, type=Path,
                         help="SQLite path for durable operator and policy task history")
    console.add_argument("--robot-credential-key-file", default=None, type=Path,
                         help="base64 AES key sealing enrolled robot tokens (D-361); needs --tasks-db")
    console.add_argument("--mission-api", action="store_true",
                         help=("enable persistent Mission proposal/read APIs without ER 2 or Mission "
                               "dispatch; existing Fleet operator commands remain available"))
    console.add_argument("--cell-app-service-id", default=None,
                         help="existing site-users service principal for explicit Cell workspace proposals")
    console.add_argument("--cell-job-stack-tol-m", default=None, type=float, help=(
        "recompile Cell Job proposals with palletizing at this stack tolerance; needs --mission-api"))
    console.add_argument("--goal-evidence-config", default=None, type=Path,
                         help="optional scoped goal-evidence producer registry YAML")
    console.add_argument("--pairing-ca", default=None, type=Path,
                         help="site CA PEM (never a leaf) handed to paired cameras; enables the "
                              "D-341 pairing routes, needs --tls-cert and --tasks-db")
    console.add_argument("--pairing-tls-host", default=None,
                         help="site TLS host name (<name>.local) the paired phone checks")
    console.add_argument("--pairing-sync-token-env", default=None,
                         help="environment variable holding Vision's dedicated credential-list token")
    console.add_argument("--central", action="store_true", help=(
        "mount the central Fleet registry (D-454 step 1): /api/v1/fleet/robots reads the "
        "site roster as the source of truth; requires an enrollment store"))
    return parser.parse_args(argv)


def split_robots(args: argparse.Namespace) -> tuple[RobotEndpoint, list[RobotEndpoint]]:
    robots = load_robots(args.robots)
    _warn_if_world_readable(args.robots)
    leaders = [r for r in robots if r.robot_id == args.leader]
    if not leaders:
        sys.exit(f"leader {args.leader!r} is not in {args.robots}")
    return leaders[0], [r for r in robots if r.robot_id != args.leader]


def _warn_if_world_readable(path: Path) -> None:
    # 그룹도 본다. robots.yaml 은 운영자 토큰이고, 공유 워크스테이션에서 group-readable
    # 은 world-readable 과 실질적으로 같은 노출이다 (dialout/docker 같은 그룹).
    if os.name == "nt":
        return
    try:
        if Path(path).stat().st_mode & (stat.S_IROTH | stat.S_IRGRP):
            print(f"warning: {path} is readable beyond its owner and holds operator tokens",
                  file=sys.stderr)
    except OSError:
        pass


def spec_from(args: argparse.Namespace) -> FormationSpec:
    return FormationSpec(Formation(args.formation), spacing=args.spacing, grid_cols=args.grid_cols,
                         max_speed=args.max_speed, stream_timeout_ms=args.stream_timeout_ms)


def policy_from(args: argparse.Namespace) -> HoldPolicy:
    return HoldPolicy(args.policy)


def _pending_suffix(session) -> str:
    """비어 있지 않으면 ` pending=<n>`. 세션은 항상 이 필드를 갖는다."""
    return f" pending={len(session.pending_triggers)}" if session.pending_triggers else ""


async def handle_command(line: str, session, base: FormationSpec) -> bool:
    """stdin 한 줄. 세션을 계속 돌리면 True, 끝내면 False."""
    parts = line.strip().split()
    if not parts:
        return True
    cmd, rest = parts[0].lower(), parts[1:]
    try:
        if cmd == "reform" and rest:
            spacing = float(rest[1]) if len(rest) > 1 else base.spacing
            spec = FormationSpec(Formation(rest[0].upper()), spacing=spacing, grid_cols=base.grid_cols,
                                 max_speed=base.max_speed, stream_timeout_ms=base.stream_timeout_ms)
            await session.reform(spec)
            if session.state.value == "HOLDING":
                # 무장 중에 무엇인가 걸렸다. 다음 통계 줄을 기다려 알게 하지 않는다.
                print(f"held: {session.reason} — resume when clear")
        elif cmd == "resume":
            was_running = session.state.value == "RUNNING"
            await session.resume()
            if was_running:
                # RUNNING 에서 resume 은 무해한 no-op 이다. 조용히 넘어가면 운영자는
                # 명령이 씹혔는지 이미 달리고 있는지 구분할 수 없다.
                print("already running")
        elif cmd == "status":
            print(f"state={session.state.value} reason={session.reason}{_pending_suffix(session)}")
        elif cmd == "stop":
            await session.stop()
            return False
        else:
            print("commands: reform <FORMATION> [spacing] | resume | status | stop")
    except (ValueError, FormationError, SessionError) as exc:
        print(f"refused: {exc}")
    return True


def _start_stdin_reader(queue: asyncio.Queue, stream=None) -> None:
    """stdin 을 데몬 스레드에서 읽어 명령 큐로 넘긴다.

    `stream` 은 테스트가 진짜 stdin 대신 무엇이든 끼울 수 있게 열어 둔 자리다 —
    기본은 `sys.stdin` 이고, 부를 때 고른다(테스트가 갈아끼운 stdin 도 그대로 쓴다).

    `run_in_executor(None, sys.stdin.readline)` 이면 안 된다: 스레드는 readline 안에서
    막혀 있어 태스크를 `cancel()` 해도 풀리지 않고, `asyncio.run` 은 끝날 때 기본
    실행기를 join 한다 — `stop` 이나 Ctrl-C 뒤에도 다음 한 줄이 들어올 때까지
    (파이프라면 영원히, 터미널이면 stream_timeout 300 s 까지) 콘솔이 붙잡힌다.
    데몬 스레드는 join 되지 않고 프로세스와 함께 죽는다.
    """
    loop = asyncio.get_running_loop()
    source = sys.stdin if stream is None else stream

    def pump() -> None:
        while True:
            try:
                line = source.readline()
            except Exception:
                # 프로세스가 내려가는 중에 stdin 이 닫히면 여기로 온다. 남길 말이 없다.
                return
            try:
                # EOF 는 파이프가 닫힌 것이다 — 명령을 줄 사람이 없으니 대형을 푼다.
                loop.call_soon_threadsafe(queue.put_nowait, line or "stop")
            except RuntimeError:
                return          # 루프가 이미 닫혔다: 세션이 먼저 끝났다.
            if not line:
                return

    threading.Thread(target=pump, name="rosy-fleet-stdin", daemon=True).start()


def _follower_token(rid: str, hz: float, ok: bool, error: Optional[str]) -> str:
    marker = "" if ok else "!"
    suffix = f"({error})" if not ok and error else ""
    return f"{rid}:{hz:.1f}Hz{marker}{suffix}"


def _stats_line(relay: Relay, session: Optional[FormationSession]) -> str:
    st = relay.stats()
    tx = " ".join(_follower_token(rid, hz, st.follower_connected[rid], st.follower_last_error.get(rid))
                  for rid, hz in st.follower_tx_hz.items())
    state = f" {session.state.value}" + (f" {session.reason}" if session and session.reason else "") \
        + (_pending_suffix(session) if session else "") if session else ""
    err = f" LEADER REFUSED: {st.leader_last_error}" if st.leader_last_error else ""
    return f"leader {st.leader_rx_hz:.1f}Hz drop={st.leader_dropped}{' PAUSED' if st.paused else ''}{err} | {tx}{state}"


async def run_relay(args: argparse.Namespace) -> None:
    leader_ep, follower_eps = split_robots(args)
    leader = HttpRobotClient(leader_ep)
    followers = [HttpRobotClient(ep) for ep in follower_eps]
    relay = Relay(leader, followers)
    await relay.start()
    try:
        while True:
            await asyncio.sleep(1.0)
            print(_stats_line(relay, None), flush=True)
    finally:
        await relay.stop()


async def formation_console(session, base: FormationSpec, commands: asyncio.Queue,
                            print_stats: Callable[[], None]) -> None:
    """`formation` 의 콘솔 루프. 명령 큐와 통계 출력만 받는다 — 소켓도 argparse 도 모른다.

    `run_formation` 에서 떼어 낸 이유는 이 루프가 시험할 것을 갖고 있기 때문이다:
    스스로 끝난 세션에서 곧장 나오는지, 1 s 마다 통계를 찍는지, `stop` 에 닫히는지.
    """
    try:
        while True:
            if session.state.value == "STOPPED":
                # 세션이 스스로 끝났다 (ABORT 정책, 또는 중단된 reform). 통계 줄만
                # 계속 찍으면 운영자는 대형이 이미 풀렸다는 것을 모른 채 앉아 있다.
                print(f"session stopped: {session.reason_text()}", flush=True)
                return
            try:
                line = await asyncio.wait_for(commands.get(), timeout=1.0)
            except asyncio.TimeoutError:
                print_stats()
                continue
            if not await handle_command(line, session, base):
                return
    finally:
        if session.state.value != "STOPPED":
            await session.stop()


async def run_formation(args: argparse.Namespace) -> None:
    leader_ep, follower_eps = split_robots(args)
    leader = HttpRobotClient(leader_ep)
    followers = [HttpRobotClient(ep) for ep in follower_eps]
    base = spec_from(args)
    session = FormationSession(leader, followers, base, policy=policy_from(args))
    try:
        await session.start()
    except SessionError as exc:
        sys.exit(f"could not arm the formation: {exc}")
    print(f"armed: {session.assignment}", flush=True)
    commands: asyncio.Queue = asyncio.Queue()
    _start_stdin_reader(commands)
    await formation_console(session, base, commands,
                            lambda: print(_stats_line(session.relay, session), flush=True))


#: 이 포트에 닿는 사람은 robots.yaml 의 운영자 토큰으로 현장의 모든 로봇을 움직일 수 있다.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def run_console(args: argparse.Namespace) -> None:
    """관제 서버를 연다. uvicorn 이 자기 루프를 돌리므로 여기는 async 가 아니다."""
    import uvicorn

    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.sightings import SightingService

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
    site_users = None
    if users_file is not None:
        from fleet.server.site_users import load_site_users

        site_users = load_site_users(users_file)
    tasks_db = getattr(args, "tasks_db", None)
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
    if mission_api and site_users is None:
        sys.exit("--users-file is required with --mission-api for named operator authorization")
    if args.host not in LOOPBACK_HOSTS and not (console_token or site_users):
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
        endpoints = load_robots(args.robots, allow_empty=key_file is not None)
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
                           signal_console=signal_console, event_store=event_store)
    sightings_db = getattr(args, "sightings_db", None)
    sightings_config = getattr(args, "sightings_config", None)
    if sightings_db is not None and sightings_config is None:
        sys.exit("--sightings-db requires --sightings-config")
    sighting_service = None
    tracking_service = None
    vision_sources = ()
    if sightings_config is not None:
        from fleet.server.sighting_store import SightingStore
        from fleet.server.sightings_config import load_sighting_sources

        sources = load_sighting_sources(sightings_config)
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
        from fleet.server.tracking import TrackingService
        from fleet.server.tracking_calibration import TrackingCalibrationStore

        # D-457: approved tracking calibrations live beside the sightings (memory without a DB).
        tracking_service = TrackingService(
            sighting_service.sources, calibrations=TrackingCalibrationStore(sightings_db))
    # The outbound CORE Agent route is enabled only for robots with a separate
    # pairing credential. REST-only console configurations remain unchanged.
    hub = console.hub if pairing_configured else None
    task_service = None
    if tasks_db is not None:
        from fleet.server.task_service import FleetTaskService
        from fleet.server.task_store import FleetTaskStore

        task_service = FleetTaskService(FleetTaskStore(tasks_db),
                                        robot_ids=console.robot_ids)
    mission_service = None
    proposal_store = None
    goal_evidence_service = None
    cell_job_compiler = None
    if cell_job_tol_m is not None:  # the palletizing wheel is needed only with this flag
        from fleet.server.cell_compiler import PalletizingCellJobCompiler
        cell_job_compiler = PalletizingCellJobCompiler(tol_m=cell_job_tol_m)
    if mission_api:
        from fleet.server.mission_service import MissionService
        from fleet.server.mission_store import MissionStore
        from fleet.server.proposal_store import ProposalStore

        mission_service = MissionService(MissionStore(tasks_db))
        proposal_store = ProposalStore(tasks_db)
        if goal_evidence_config is not None:
            from fleet.server.goal_evidence_registry import load_goal_evidence_registry
            from fleet.server.goal_evidence_service import GoalEvidenceService
            from fleet.server.goal_evidence_store import GoalEvidenceStore

            registry = load_goal_evidence_registry(goal_evidence_config)
            goal_evidence_service = GoalEvidenceService(
                mission_service, registry, GoalEvidenceStore(tasks_db),
            )
    from fleet.server.discovery import DiscoveryStore

    discovery = DiscoveryStore() if discovery_token is not None else None
    enrollment = None
    if enrollment_store is not None:
        from fleet.server.enrollment import EnrollmentService
        from fleet.server.roster import SiteRoster

        roster = SiteRoster(console, task_service=task_service, sightings=sighting_service)
        from fleet.server.enrollment_tls import EnrolledTlsBindings
        tls_file = getattr(args, "enrolled_tls_bindings_file", None)
        enrollment = EnrollmentService(enrollment_store, roster, key=robot_key,
                                       key_error=robot_key_error,
                                       fleet_name=console.fleet_name, discovery=discovery,
                                       tls_bindings=EnrolledTlsBindings(tls_file) if tls_file else None)
        enrollment.load()
        roster.sync()
    from fleet.server.site_lanes import parse_lane_graph_flags, unmatched_map_ids

    try:
        site_lanes = parse_lane_graph_flags(getattr(args, "site_lane_graph", None),
                                            getattr(args, "site_lane_paint", None))
    except ValueError as exc:
        sys.exit(str(exc))
    for map_id in unmatched_map_ids(site_lanes, sighting_service.sources if sighting_service is not None else ()):
        print(f"warning: --site-lane-graph/--site-lane-paint map id {map_id!r} matches no sighting "
              "source; that lane entry is served to no camera", file=sys.stderr, flush=True)
    vision_preview_secret_env = getattr(args, "vision_preview_secret_env", None)
    vision_preview_secret = (os.environ.get(vision_preview_secret_env)
                             if vision_preview_secret_env else None)
    if vision_preview_secret_env and not vision_preview_secret:
        sys.exit("vision preview secret environment variable is required")
    pairing_service, pairing_sync_token = _build_pairing(
        args, tls_cert=tls_cert, tasks_db=tasks_db, sighting_service=sighting_service,
        site_name=console.fleet_name)
    from fleet.server.localization_service import build_localization_service

    localization_service = build_localization_service(
        console, sighting_service, enabled=getattr(args, "localization_service", True),
        overhead_cue=getattr(args, "localization_overhead_cue", False),
        lane_rules=getattr(args, "localization_lane_rules", None))
    stuck_resolver_clients = None
    if getattr(args, "stuck_resolver", False):
        stuck_resolver_clients = {
            ep.robot_id: HttpRobotClient(dataclasses.replace(ep, token=ep.resolver_token))
            for ep in endpoints if ep.resolver_token}
        if not stuck_resolver_clients:
            print("warning: --stuck-resolver set but no robot has a resolver_token; "
                  "every stuck will be escalated", file=sys.stderr)
    central_registry = None
    if getattr(args, "central", False):
        # D-454 1단계: 중앙 프로파일 — 등록 로스터가 정본이므로 등록 저장소가 필요하다.
        if enrollment is None:
            sys.exit("--central requires --robot-credential-key-file and --tasks-db; the central "
                     "registry reads the site roster as its source of truth")
        from fleet.server.central_registry import CentralRegistry

        central_registry = CentralRegistry(roster, console=console, discovery=discovery)
    app = create_app(console, console_token=console_token, web_common=args.web_common,
                     hub=hub, sightings=sighting_service, tracking=tracking_service, task_service=task_service,
                     mission_service=mission_service, proposal_store=proposal_store,
                     cell_job_compiler=cell_job_compiler,
                     cell_app_service_id=getattr(args, "cell_app_service_id", None),
                     goal_evidence_service=goal_evidence_service,
                     site_users=site_users, discovery=discovery,
                     discovery_token=discovery_token,
                     approved_peer_directory_file=getattr(args, 'approved_peer_directory_file', None),
                     start_task_dispatcher=not mission_api,
                     vision_lease_secret=vision_preview_secret,
                     vision_sources=vision_sources, enrollment=enrollment,
                     robot_credential_key=robot_key_text, site_lanes=site_lanes,
                     pairing=pairing_service, pairing_sync_token=pairing_sync_token,
                     localization_service=localization_service,
                     stuck_resolver_clients=stuck_resolver_clients,
                     central_registry=central_registry)
    signals_note = f", {len(signal_eps)} signals" if signal_console is not None else ""
    print(f"fleet console: http://{args.host}:{args.port}/console  "
          f"({len(console.robot_ids)} robots{signals_note})",
          flush=True)
    tls_options = ({"ssl_certfile": str(tls_cert), "ssl_keyfile": str(tls_key)}
                   if tls_cert is not None else {})
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", **tls_options)


def _build_pairing(args: argparse.Namespace, *, tls_cert, tasks_db, sighting_service, site_name):
    """D-341 2: pairing exists only on a TLS Fleet with a site CA and a durable store."""
    pairing_ca = getattr(args, "pairing_ca", None)
    sync_env = getattr(args, "pairing_sync_token_env", None)
    if pairing_ca is None:
        if sync_env is not None:
            sys.exit("--pairing-sync-token-env requires --pairing-ca")
        return None, None
    if tls_cert is None:
        sys.exit("--pairing-ca requires --tls-cert: pairing routes exist only over TLS (D-341 2)")
    if tasks_db is None:
        sys.exit("--pairing-ca requires --tasks-db for credential digests and the pairing audit")
    tls_host = getattr(args, "pairing_tls_host", None)
    if not tls_host:
        sys.exit("--pairing-ca requires --pairing-tls-host (the <name>.local in the site certificate)")
    from core_common.protocol.pairing import der_sha256
    from fleet.server.pairing import PairingService
    from fleet.server.pairing_store import PairingStore

    sources = ({source.source_id: source.credential for source in sighting_service.sources}
               if sighting_service is not None else {})
    if "paired" not in sources.values():
        print("warning: D-341 pairing is on but no sighting source is credential: paired; "
              "requests can be listed but not approved", file=sys.stderr)
    try:
        served_leaf_pem = Path(tls_cert).read_text(encoding="utf-8-sig")
        leaf_sha256 = der_sha256(served_leaf_pem)
        site_ca_pem = Path(pairing_ca).read_text(encoding="utf-8-sig")
        service = PairingService(PairingStore(tasks_db), leaf_cert_sha256=leaf_sha256,
                                 site_ca_pem=site_ca_pem, tls_host=tls_host,
                                 site_name=site_name, sources=sources, served_leaf_pem=served_leaf_pem)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        sys.exit(f"D-341 pairing configuration refused: {exc}")
    sync_token = None
    if sync_env is not None:
        sync_token = os.environ.get(sync_env)
        if not sync_token:
            sys.exit(f"pairing sync token environment variable {sync_env} is required")
    return service, sync_token


def _relax_retired_sighting_targets(sources, *, known: set, retired: set):
    """D-361 5: a mapping to an unenrolled/pending-logout robot is disabled with a warning;
    an id never seen in robots.yaml or the register still refuses start (a typo)."""
    from dataclasses import replace

    kept = []
    for source in sources:
        unknown = set(source.robot_ids) - known
        if unknown - retired:
            sys.exit(f"sighting source {source.source_id!r} has an unknown robot target")
        if unknown:
            print(f"warning: sighting source {source.source_id!r}: mapping disabled for "
                  f"unenrolled robots {sorted(unknown)}", file=sys.stderr)
        robot_ids = tuple(rid for rid in source.robot_ids if rid not in unknown)
        if robot_ids:
            kept.append(replace(source, robot_ids=robot_ids))
        else:
            print(f"warning: sighting source {source.source_id!r} disabled: no enrolled targets",
                  file=sys.stderr)
    return kept


def _main_impl(argv: Optional[Sequence[str]] = None) -> None:
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
    """Use the gateway app composition when installed, retaining the legacy fallback."""
    try:
        from rosy_gateway.compose import main as gateway_main
    except ImportError:
        return _main_impl(argv)
    return gateway_main(argv)


if __name__ == "__main__":
    main()
