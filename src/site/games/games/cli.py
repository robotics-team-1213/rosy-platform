"""games match --config ... [--dry-run] [--ticks N] [--preview] [--stair N]"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from games.catalog import OBSERVERS, make_game, make_observer, make_policy
from games.host.loop import MatchHost
from games.host.robots import load_match
from games.host.session import HOST_PERIOD_S, run_match, space_pressed
from games.host.transport import HttpPlayerClient
from games.host.visibility import format_visibility, stair1_expect


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="games")
    sub = parser.add_subparsers(dest="command", required=True)
    match = sub.add_parser("match", help="run or inspect a 1v1 match config")
    match.add_argument("--config", required=True, type=Path)
    match.add_argument("--dry-run", action="store_true")
    match.add_argument("--ticks", type=int, default=None)
    match.add_argument("--observer", choices=tuple(sorted(OBSERVERS)), default="hold")
    match.add_argument("--preview", action="store_true")
    match.add_argument("--preview-port", type=int, default=8765)
    match.add_argument(
        "--stair",
        type=int,
        choices=(1, 2, 3, 4, 5),
        default=None,
        help="D-96 host preset; not FIELD GO",
    )
    drive = match.add_mutually_exclusive_group()
    drive.add_argument("--observe-only", action="store_true")
    drive.add_argument("--drive", nargs="*", metavar="ROBOT_ID")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    setup = load_match(args.config)
    if args.dry_run:
        print(f"field {setup.field.length_m}x{setup.field.width_m} m")
        print(f"game {setup.game} policy {setup.policy}")
        for robot in setup.robots:
            print(f"{robot.id} {robot.url} aruco={robot.aruco_id} attacks={robot.attacks}")
        print(f"goals {setup.goals.home_id}/{setup.goals.away_id}")
        print(_drive_line(_motion(args, setup), setup))
        if args.stair == 1:
            print(format_visibility(stair1_expect(setup), expect=True))
        if args.preview:
            print("preview 127.0.0.1 (not started in dry-run)")
        return 0
    live = args.ticks is None
    period_s = HOST_PERIOD_S if live else 0.0
    if period_s > setup.camera.lost_hold_s:
        raise ValueError(
            f"host period {period_s}s exceeds watchdog lost_hold_s {setup.camera.lost_hold_s}"
        )
    from games.host.preview import PreviewBoard, PreviewServer

    board = PreviewBoard() if args.preview else None
    server = PreviewServer(board, port=args.preview_port) if board is not None else None
    clients = [HttpPlayerClient(endpoint) for endpoint in setup.robots]
    observer = make_observer(args.observer, setup)
    drive_ids = _motion(args, setup)
    host = MatchHost(
        observer,
        clients,
        game=make_game(setup.game, setup.field),
        policy=make_policy(
            setup.policy,
            setup.field,
            speed=setup.linear,
            angular=setup.angular,
        ),
        preview=board,
        max_linear=setup.linear,
        max_angular=setup.angular,
        observe_only=drive_ids is None,
        drive_ids=drive_ids,
    )
    try:
        if server is not None:
            print(server.start())
        run_match(
            host,
            ticks=None if live else args.ticks,
            period_s=period_s,
            halt_check=lambda: (board.stop if board is not None else False) or space_pressed(),
        )
        if args.stair == 1:
            vis = host.last_visibility
            if vis is None:
                print("stair 1 visibility unknown (hold; not FIELD GO)")
            else:
                print(format_visibility(vis))
    finally:
        if server is not None:
            server.close()
        for client in clients:
            close = getattr(client, "close", None)
            if close is not None:
                close()
        close = getattr(observer, "close", None)
        if close is not None:
            close()
    return 0


def _motion(args, setup):
    stair = args.stair
    drive = args.drive
    if stair == 1:
        if drive is not None:
            raise ValueError("--stair 1 is observe-only; do not pass --drive")
        return None
    if stair == 2:
        if drive is None or len(drive) != 1:
            raise ValueError("--stair 2 needs --drive <one robot id>")
        return _drive_ids(drive, setup)
    if stair in (3, 4, 5):
        if args.observe_only:
            raise ValueError(f"--stair {stair} drives both robots; not observe-only")
        if drive is not None and len(drive) == 1:
            raise ValueError(
                f"--stair {stair} drives both robots; do not pass a single --drive id"
            )
        return _drive_ids([] if drive is None else drive, setup)
    return _drive_ids(drive, setup)


def _drive_ids(drive: list[str] | None, setup):
    if drive is None:
        return None
    roster = {robot.id for robot in setup.robots}
    chosen = roster if not drive else set(drive)
    unknown = chosen - roster
    if unknown:
        raise ValueError(f"unknown drive id {sorted(unknown)}")
    return frozenset(chosen)


def _drive_line(ids, setup) -> str:
    if ids is None:
        return "drive off (observe-only)"
    return "drive " + ",".join(robot.id for robot in setup.robots if robot.id in ids)


if __name__ == "__main__":
    raise SystemExit(main())
