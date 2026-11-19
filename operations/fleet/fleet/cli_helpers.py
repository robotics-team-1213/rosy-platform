"""Helper functions and CLI argument parser for ``fleet.cli``."""

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
from fleet.server.context_options import add_cli_arguments
from fleet.swarm.api.types import FormationSpec, HoldPolicy, SessionError
from fleet.swarm.relay import Relay
from fleet.swarm.robots import RobotEndpoint, load_robots
from fleet.swarm.session import FormationSession
from fleet.swarm.transport import HttpRobotClient

#: 이 포트에 닿는 사람은 robots.yaml 의 운영자 토큰으로 현장의 모든 로봇을 움직일 수 있다.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


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
    console.add_argument("--signals", default=None, type=Path, help="signals.yaml — 없으면 신호등 기능은 비어 있는 채로 뜬다")
    console.add_argument("--host", default="127.0.0.1")
    console.add_argument("--port", type=int, default=8090)
    console.add_argument("--web-common", default=default_web_common(), type=Path,
                         help="공용 L1 웹 자산 디렉터리 — /common 아래로 서빙한다(D-157)")
    console.add_argument("--token", default=None, help="관제 UI 접속 토큰. 루프백 밖으로 열 때는 필수다")
    console.add_argument("--token-env", default=None, help="환경변수에서 관제 토큰을 읽는다(명령행 secret 노출 방지)")
    console.add_argument("--discovery-token-env", default=None,
                         help="host mDNS scanner credential environment variable")
    console.add_argument("--approved-peer-directory-file", default=None, type=Path,
                         help="admin-provisioned public peer metadata JSON; no credentials or enrollment")
    console.add_argument("--enrolled-tls-bindings-file",
                         default=os.environ.get("ROSY_ENROLLED_TLS_BINDINGS_FILE") or None, type=Path,
                         help="public approved TLS bindings for existing encrypted enrollments")
    console.add_argument("--hub-link-hostname", default=None,
                         help="D-555: the site's approved <name>.local robots dial for the hub")
    console.add_argument("--hub-link-ca", default=None, type=Path,
                         help="D-555: public site CA PEM robots pin for the hub (pair with --hub-link-hostname)")
    console.add_argument("--vision-preview-secret-env", default=None,
                         help="dedicated Fleet-to-Vision preview lease signing secret")
    console.add_argument("--vision-url", default=None,
                         help="server-side Vision ingest origin (e.g. https://vision:8095) for the "
                              "periodic calibration-drift watch; needs --vision-preview-secret-env")
    console.add_argument("--calibration-drift-interval-s", type=float, default=60.0, metavar="SECONDS",
                         help="cadence of the approved-vs-proposed calibration comparison per "
                              "source (0 disables; default 60)")
    console.add_argument("--lan-camera-proxy", action="store_true",
                         help="trust the site Caddy proxy's LAN camera header for preview only")
    console.add_argument("--users-file", default=None, type=Path, help="개인별 Fleet API 토큰 digest 및 역할을 담은 root 관리 파일")
    console.add_argument("--account-config", default=os.environ.get('ROSY_ACCOUNT_CONFIG') or None, type=Path,
                         help="protected Rosy Account authority JSON; requires --tasks-db")
    from fleet.server.channel.options import add_conversation_options
    add_conversation_options(console)
    discord = console.add_mutually_exclusive_group()
    discord.add_argument("--discord-intake-config", default=None, type=Path,
                         help="D-671 private named Discord intake configuration; absent disables intake")
    discord.add_argument("--discord-intake-config-optional", default=None, type=Path,
                         help="D-675 private intake configuration; missing file disables intake")
    console.add_argument("--stuck-resolver", action="store_true",
                         help="D-577 2: accepted for compatibility; the resolver is on by default")
    console.add_argument("--no-stuck-resolver", action="store_false", dest="stuck_resolver_on",
                         help="D-438/D-577 2: turn off the Fleet stuck resolver (on by default; it answers only "
                              "robots with a resolver_token in robots.yaml, others go to the console)")
    console.add_argument("--tls-cert", default=None, type=Path,
                         help="HTTPS server certificate chain; pair with --tls-key")
    console.add_argument("--tls-key", default=None, type=Path, help="HTTPS private key; mount as a runtime secret")
    console.add_argument("--sightings-config", default=None, type=Path,
                         help="source/map/calibration sighting config (secret values stay in env)")
    console.add_argument("--workcell-observations", default=os.environ.get("ROSY_WORKCELL_OBSERVATIONS") or None, type=Path,
                         help="read-only workcell source manifest; producer credentials stay in env")
    console.add_argument("--site-lane-graph", action="append", default=None, metavar="[MAP_ID=]PATH",
                         help="lane_graph.yaml drawn over the ceiling camera by the D-375 map-fit "
                              "view; without MAP_ID it applies to every map. Display only")
    console.add_argument("--site-lane-paint", action="append", default=None, metavar="[MAP_ID=]PATH",
                         help="lane paint STL (Vision's --map-paint file) drawn by the same view")
    console.add_argument("--site-map-import", default=None, type=Path, metavar="LANE_GRAPH",
                         help="D-488: lane_graph.yaml imported as the first active site map when "
                              "the store has none (stored in --tasks-db, else memory)")
    console.add_argument("--site-config", default=None, type=Path,
                         help="site YAML; its fleet.routing section sets the D-490 planner costs, "
                              "fleet.map_pose the D-494 trip map pose limits, "
                              "fleet.lane_compliance the D-511 lane watch thresholds")
    console.add_argument("--site-config-optional", default=None, type=Path, metavar="PATH",
                         help="like --site-config, but a missing file is only logged and defaults apply")
    console.add_argument("--no-localization-service", dest="localization_service",
                         action="store_false", default=True,
                         help="D-395: do not run the Fleet localization service (on by default)")
    console.add_argument("--localization-overhead-cue", action="store_true", default=False,
                         help="D-395: feed overhead sightings to the localization arbiter and "
                              "monitor. Off by default: the D-257 amendment is not accepted")
    console.add_argument("--pose-request-overhead", action=argparse.BooleanOptionalAction,
                         default=True,
                         help="D-546: answer a robot's pose request from the trusted overhead pose "
                              "(LOCALIZED, anchor <= 2 s; the robot's 3 s scan check decides). "
                              "On by default (user decision 2026-10-09); --no-pose-request-overhead "
                              "turns it off. Does not touch the arbiter/monitor cue")
    console.add_argument("--localization-lane-rules", default=None, type=Path,
                         help="lane_rules.yaml with reference_squares (default: map_v2_fleet)")
    console.add_argument("--sightings-db", default=None, type=Path,
                         help="SQLite path for latest sightings and acceptance audit")
    console.add_argument("--events-db", default=None, type=Path,
                         help="SQLite path for durable CORE Agent event history")
    console.add_argument("--tasks-db", default=None, type=Path,
                         help="SQLite path for durable operator and policy task history")
    console.add_argument("--control-unit-config", default=os.environ.get("ROSY_CONTROL_UNIT_CONFIG") or None, type=Path,
                         help="optional static control-unit ownership and direct-neighbor configuration")
    add_cli_arguments(console)
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
    console.add_argument('--notifications-config', default=None, type=Path,
                         help='explicit team notification YAML (requires --tasks-db; endpoints stay in env)')
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
    console.add_argument("--connection-mode", choices=("paired", "development"), default="paired",
                         help=("development connection metadata; human login is required; "
                               "also needs ROSY_DEPLOYMENT=development"))
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


def _resolve_optional_site_config(args) -> None:
    """``--site-config-optional PATH``: becomes ``--site-config`` when the file exists, else defaults apply."""
    optional = getattr(args, "site_config_optional", None)
    if optional is None:
        return
    if getattr(args, "site_config", None) is not None:
        sys.exit("--site-config and --site-config-optional cannot be combined")
    if Path(optional).is_file():
        args.site_config = optional
    else:
        print(f"site config {optional} not found; using defaults", file=sys.stderr)


def _hub_link(args) -> dict | None:
    """D-555: what robots receive with a hub credential, or None when not configured."""
    hostname, ca = getattr(args, "hub_link_hostname", None) or None, getattr(args, "hub_link_ca", None)
    if ca is not None and str(ca) in ("", "."):
        ca = None                      # compose passes "" when the site leaves the hub link unset
    if hostname is None and ca is None:
        return None
    from core_common.protocol.discovery_txt import HOSTNAME

    hostname = (hostname or "").lower().rstrip(".")
    if not HOSTNAME.fullmatch(hostname) or ca is None:
        sys.exit("--hub-link-hostname <name>.local and --hub-link-ca go together")
    try:
        pem = ca.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        sys.exit("--hub-link-ca is not a readable PEM file")
    if len(pem) > 16384 or "-----BEGIN CERTIFICATE-----" not in pem:
        sys.exit("--hub-link-ca must be one PEM certificate under 16 KiB")
    return {"expected_hostname": hostname, "ca_pem": pem}


def _omx_instances() -> dict[str, str]:
    """D-785: unique WORKCELL=INSTANCE pairs from ROSY_FLEET_OMX_INSTANCES (compose.omx.yaml); unset = none."""
    pairs = [tuple(v.split("=")) for v in os.environ.get("ROSY_FLEET_OMX_INSTANCES", "").split(",") if v]
    if any(len(p) != 2 or not all(x and x == x.strip() for x in p) for p in pairs) or len(dict(pairs)) != len(pairs):
        raise SystemExit(f"ROSY_FLEET_OMX_INSTANCES needs unique WORKCELL=INSTANCE pairs, got {pairs}")
    return dict(pairs)
