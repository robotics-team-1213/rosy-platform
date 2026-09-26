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
    """Resolve installed assets first, with a source-tree fallback for host tools."""
    try:
        from ament_index_python.packages import get_package_share_directory

        return Path(get_package_share_directory("web_common"))
    except (ImportError, LookupError):
        return Path(__file__).resolve().parents[3] / "hmi" / "web"


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
    console.add_argument("--robots", required=True, type=Path, help="robots.yaml")
    console.add_argument("--signals", default=None, type=Path,
                         help="signals.yaml — 없으면 신호등 기능은 비어 있는 채로 뜬다")
    console.add_argument("--host", default="127.0.0.1")
    console.add_argument("--port", type=int, default=8090)
    console.add_argument("--web-common", default=default_web_common(), type=Path,
                         help="공용 L1 웹 자산 디렉터리 — /common 아래로 서빙한다(D-1005)")
    console.add_argument("--token", default=None,
                         help="관제 UI 접속 토큰. 루프백 밖으로 열 때는 필수다")
    console.add_argument("--token-env", default=None,
                         help="환경변수에서 관제 토큰을 읽는다(명령행 secret 노출 방지)")
    console.add_argument("--discovery-token-env", default=None,
                         help="host mDNS scanner credential environment variable")
    console.add_argument("--users-file", default=None, type=Path,
                         help="개인별 Fleet API 토큰 digest 및 역할을 담은 root 관리 파일")
    console.add_argument("--tls-cert", default=None, type=Path,
                         help="HTTPS server certificate chain; pair with --tls-key")
    console.add_argument("--tls-key", default=None, type=Path,
                         help="HTTPS private key; mount as a runtime secret")
    console.add_argument("--sightings-config", default=None, type=Path,
                         help="source/map/calibration sighting config (secret values stay in env)")
    console.add_argument("--sightings-db", default=None, type=Path,
                         help="SQLite path for latest sightings and acceptance audit")
    console.add_argument("--events-db", default=None, type=Path,
                         help="SQLite path for durable CORE Agent event history")
    console.add_argument("--tasks-db", default=None, type=Path,
                         help="SQLite path for durable operator and policy task history")
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
    if args.host not in LOOPBACK_HOSTS and not (console_token or site_users):
        sys.exit("--token or --users-file 없이 루프백 밖으로 열 수 없다")
    if args.host not in LOOPBACK_HOSTS and tasks_db is None:
        sys.exit("--tasks-db is required when the Fleet control surface is externally reachable")
    endpoints = load_robots(args.robots)
    _warn_if_world_readable(args.robots)
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
    if sightings_config is not None:
        from fleet.server.sighting_store import SightingStore
        from fleet.server.sightings_config import load_sighting_sources

        sources = load_sighting_sources(sightings_config)
        store = SightingStore(sightings_db) if sightings_db is not None else None
        sighting_service = SightingService(
            sources, known_robot_ids=console.robot_ids, store=store,
        )
    # The outbound CORE Agent route is enabled only for robots with a separate
    # pairing credential. REST-only console configurations remain unchanged.
    hub = console.hub if pairing_configured else None
    task_service = None
    if tasks_db is not None:
        from fleet.server.task_service import FleetTaskService
        from fleet.server.task_store import FleetTaskStore

        task_service = FleetTaskService(FleetTaskStore(tasks_db),
                                        robot_ids=console.robot_ids)
    from fleet.server.discovery import DiscoveryStore

    discovery = DiscoveryStore() if discovery_token is not None else None
    app = create_app(console, console_token=console_token, web_common=args.web_common,
                     hub=hub, sightings=sighting_service, task_service=task_service,
                     site_users=site_users, discovery=discovery,
                     discovery_token=discovery_token)
    signals_note = f", {len(signal_eps)} signals" if signal_console is not None else ""
    print(f"fleet console: http://{args.host}:{args.port}/console  "
          f"({len(endpoints)} robots{signals_note})",
          flush=True)
    tls_options = ({"ssl_certfile": str(tls_cert), "ssl_keyfile": str(tls_key)}
                   if tls_cert is not None else {})
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", **tls_options)


def main(argv: Optional[Sequence[str]] = None) -> None:
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


if __name__ == "__main__":
    main()
