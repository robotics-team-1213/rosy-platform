#!/usr/bin/env python3
"""Swarm formation bench — 리더를 몰고 팔로워를 계측한다. rclpy 없이 fleet 만 쓴다.

시나리오:
  follow  3대 COLUMN, 리더가 waypoint 를 순회. slot_err_m 과 stream 주기.
  reform  주행 중 LINE → V. 재배정과 수렴.
  hold    릴레이 pause 주입 → 전원 holding 까지의 시간.
  stuck   팔로워 하나 앞에 장애물 스폰 → nav.stuck → 세션 HOLDING 까지의 시간.

CSV 열: t, scenario, robot_id, state, holding, stream_age_s, slot_err_m, relay_tx_hz,
        relay_paused, leader_rx_hz, leader_age_s

계측하는 루프를 계측이 세워서는 안 된다. 이 파일 안에서 블로킹 호출은 하나도 하지
않는다 — 리더 폴링도 장애물 스폰도 전부 asyncio 위에 있다. 루프가 한 번 서면 릴레이는
그동안 한 프레임도 못 보내고, 팔로워는 전원 `stream_timeout_ms` 를 넘겨 HOLD 한다.
그 HOLD 는 시나리오가 만든 것이 아니라 벤치가 만든 것이다.

Design: docs/plans/2026-09-08-swarm-formation-slice-design.md §8.2
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import math
import sys
import time
from pathlib import Path
from typing import Optional

# D-148: 시뮬 벤치는 fleet 의 공개면만 본다. fleet.swarm.* / fleet.formation.*
# 내부 직접 import 는 gz_sim 구조 테스트(test_bench_boundary.py)가 금지한다.
from fleet.bench import (
    Formation,
    slot_world_position,
    load_robots,
    FormationSession,
    FormationSpec,
    SessionState,
    HttpRobotClient,
    RobotApiError,
)

OBSTACLE_SDF = """<sdf version='1.9'><model name='{name}'><static>true</static>
<link name='l'><collision name='c'><geometry><box><size>0.3 0.6 0.5</size></box></geometry></collision>
<visual name='v'><geometry><box><size>0.3 0.6 0.5</size></box></geometry></visual></link></model></sdf>"""

#: 항법이 이 상태로 돌아오면 다음 waypoint 를 건다. `BLOCKED` 는 여기 없다 — 그것은
#: 리더가 아직 그 목표를 쥔 채 막혀 있다는 뜻이고, 다음 목표를 걸면 `NAVIGATION_ACTIVE`
#: 로 거절당하거나 (더 나쁘게는) 막힌 경로를 조용히 갈아치운다.
TERMINAL_NAV = ("IDLE", "ARRIVED", "FAILED", "CANCELED")

#: 수렴 요약이 보는 꼬리 길이. 표본은 1 s 마다 하나다.
CONVERGENCE_TAIL = 10


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="swarm_bench")
    p.add_argument("--robots", type=Path, required=True, help="gz_multi core:=true 가 쓴 robots.yaml")
    p.add_argument("--leader", default="rosy_01")
    p.add_argument("--scenario", choices=["follow", "reform", "hold", "stuck"], default="follow")
    p.add_argument("--formation", default="COLUMN", choices=[f.value for f in Formation])
    p.add_argument("--spacing", type=float, default=0.6)
    p.add_argument("--waypoints", default="1.5,0,0;1.5,1.0,1.57;0,1.0,3.14;0,0,0",
                   help="x,y,yaw;x,y,yaw;... (리더 목표 순서)")
    p.add_argument("--duration", type=float, default=90.0, help="계측 시간 (s)")
    p.add_argument("--inject-at", type=float, default=30.0, help="hold/stuck 주입 시각 (s)")
    p.add_argument("--world", default="rosy_factory")
    p.add_argument("--out", type=Path, default=Path("swarm_bench.csv"))
    args = p.parse_args(argv)
    if args.inject_at >= args.duration:
        # 주입이 계측 끝 뒤면 주입도 없고 결과도 없다. 90 s 를 기다린 뒤에 알 일이 아니다.
        p.error(f"--inject-at ({args.inject_at}) must be before --duration ({args.duration})")
    return args


def _parse_waypoints(text: str) -> list[tuple[float, float, float]]:
    out = []
    for chunk in text.split(";"):
        x, y, yaw = (float(v) for v in chunk.split(","))
        out.append((x, y, yaw))
    return out


async def _drive_leader(leader: HttpRobotClient, waypoints, stop: asyncio.Event) -> None:
    """리더에 목표를 차례로 건다. 다음 목표는 항법이 끝난 상태로 돌아오면."""
    i = 0
    while not stop.is_set():
        x, y, yaw = waypoints[i % len(waypoints)]
        try:
            await leader.navigation_goal(x, y, yaw)
        except RobotApiError as exc:
            if exc.code != "NAVIGATION_ACTIVE":
                print(f"leader goal refused: {exc}", file=sys.stderr)
                await asyncio.sleep(2.0)
                continue
            # 앞 목표가 아직 살아 있다 (BLOCKED 로 서 있거나 도착 보고가 늦거나).
            # 한 번만 취소하고 같은 목표를 다시 건다 — 실패하면 평소대로 물러난다.
            print("leader still navigating; cancelling once and retrying", file=sys.stderr)
            try:
                await leader.navigation_cancel()
                await leader.navigation_goal(x, y, yaw)
            except Exception as retry_exc:
                print(f"leader goal refused after cancel: {retry_exc}", file=sys.stderr)
                await asyncio.sleep(2.0)
                continue
        except Exception as exc:
            print(f"leader goal refused: {exc}", file=sys.stderr)
            await asyncio.sleep(2.0)
            continue
        # `goal()` 은 PLANNING 을 동기로 세우므로 경합을 막을 필요는 없다. 이 2 s 는
        # 목표를 걸자마자 다음 목표로 넘어가 제자리에서 떠는 것을 막는 최소 체류 시간이다.
        await asyncio.sleep(2.0)
        while not stop.is_set():
            try:
                state = await leader.state()
            except Exception as exc:
                # 한 번의 읽기 실패로 주행이 끝나면 남은 계측은 정지한 리더를 재는 것이다.
                print(f"leader state unavailable: {exc}", file=sys.stderr)
                await asyncio.sleep(1.0)
                continue
            if state.get("navigation") in TERMINAL_NAV:
                break
            await asyncio.sleep(0.5)
        i += 1


async def _spawn_obstacle(world: str, x: float, y: float, name: str) -> tuple[int, str]:
    """gz service 로 정적 상자를 스폰한다. `(returncode, stderr)`.

    `subprocess.run` 이면 안 된다: gz 의 2 s 타임아웃 + 스폰 동안 asyncio 루프가 통째로
    선다. 그동안 릴레이는 한 프레임도 못 보내고 팔로워는 전원 `stream_timeout_ms` 를
    넘겨 HOLD 한다 — 장애물이 아니라 벤치가 만든 HOLD 다.
    """
    # SDF 템플릿은 홑따옴표만 쓰므로 protobuf 텍스트의 쌍따옴표 안에 그대로 들어간다.
    sdf = OBSTACLE_SDF.format(name=name).replace("\n", " ")
    req = f'sdf: "{sdf}" pose: {{position: {{x: {x}, y: {y}, z: 0.25}}}}'
    try:
        proc = await asyncio.create_subprocess_exec(
            "gz", "service", "-s", f"/world/{world}/create",
            "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean",
            "--timeout", "2000", "--req", req,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        # gz 가 없으면 stuck 는 아무 일도 일어나지 않은 채 끝난다. 조용히 끝나서는 안 된다.
        return 127, "gz not on PATH"
    _out, err = await proc.communicate()
    return proc.returncode or 0, err.decode("utf-8", "replace").strip()


def _convergence(errors: dict[str, list[float]]) -> str:
    """팔로워별 마지막 표본 꼬리의 최대 slot_err_m. reform 이 수렴했는지 한 줄로."""
    parts = []
    for robot_id, samples in errors.items():
        tail = samples[-CONVERGENCE_TAIL:]
        parts.append(f"{robot_id}:{max(tail):.3f}m" if tail else f"{robot_id}:n/a")
    return " ".join(parts)


async def _sample(session: FormationSession, leader: HttpRobotClient, followers, writer,
                  args, t: float, errors: dict[str, list[float]]) -> bool:
    """표본 한 줄씩. 전원이 holding 이면 True."""
    lstate = await leader.state()
    lp = lstate.get("pose") or {}
    stats = session.relay.stats()
    all_holding = True
    for f in followers:
        sw = await f.swarm_state()
        st = await f.state()
        fp = st.get("pose") or {}
        off = session.assignment.get(f.robot_id)
        err = ""
        if off is not None:
            sx, sy = slot_world_position(
                off, float(lp.get("x", 0.0)), float(lp.get("y", 0.0)), float(lp.get("yaw", 0.0)))
            distance = math.dist((sx, sy), (float(fp.get("x", 0.0)), float(fp.get("y", 0.0))))
            errors.setdefault(f.robot_id, []).append(distance)
            err = f"{distance:.3f}"
        holding = bool(sw.get("holding"))
        all_holding = all_holding and holding
        writer.writerow([f"{t:.1f}", args.scenario, f.robot_id, session.state.value, holding,
                         sw.get("stream_age_s"), err,
                         f"{stats.follower_tx_hz.get(f.robot_id, 0.0):.1f}", stats.paused,
                         f"{stats.leader_rx_hz:.1f}",
                         "" if stats.leader_age_s is None else f"{stats.leader_age_s:.2f}"])
    return all_holding


async def _inject(session: FormationSession, followers, args) -> None:
    if args.scenario == "reform":
        await session.reform(FormationSpec(Formation.V, spacing=args.spacing))
    elif args.scenario == "hold":
        session.relay.pause()
    else:
        victim = followers[0]
        st = await victim.state()
        pose = st.get("pose") or {}
        yaw = float(pose.get("yaw", 0.0))
        rc, err = await _spawn_obstacle(args.world,
                                        float(pose.get("x", 0.0)) + 0.5 * math.cos(yaw),
                                        float(pose.get("y", 0.0)) + 0.5 * math.sin(yaw),
                                        "bench_block")
        # rc 를 찍지 않으면 주입되지 않은 stuck 런이 "HOLD 가 안 걸렸다"로 보인다.
        print(f"obstacle spawn rc={rc}" + (f": {err}" if rc != 0 else ""),
              file=sys.stderr if rc != 0 else sys.stdout, flush=True)


async def _measure(session: FormationSession, leader: HttpRobotClient, followers, clients,
                   writer, fh, args) -> None:
    stop = asyncio.Event()
    driver: Optional[asyncio.Task] = None
    errors: dict[str, list[float]] = {}
    try:
        await session.start()
        print(f"armed: {session.assignment}", flush=True)
        driver = asyncio.create_task(_drive_leader(leader, _parse_waypoints(args.waypoints), stop))
        t0 = time.monotonic()
        injected = False
        inject_t = None
        reached_t = None
        while time.monotonic() - t0 < args.duration:
            t = time.monotonic() - t0
            if not injected and t >= args.inject_at and args.scenario in ("reform", "hold", "stuck"):
                injected, inject_t = True, t
                await _inject(session, followers, args)
            all_holding = await _sample(session, leader, followers, writer, args, t, errors)
            fh.flush()
            if injected and reached_t is None:
                if args.scenario == "hold" and all_holding:
                    reached_t = t
                    print(f"HOLD reached after {reached_t - inject_t:.2f} s", flush=True)
                if args.scenario == "stuck" and session.state is SessionState.HOLDING:
                    reached_t = t
                    print(f"FOR-004 HOLD after {reached_t - inject_t:.2f} s: {session.reason}",
                          flush=True)
            # 표본은 1 s 마다 하나다. 수렴 요약의 "마지막 10 표본"도 이 주기를 전제한다.
            await asyncio.sleep(1.0)
        if args.scenario == "reform":
            print(f"reform convergence (max slot_err_m over the last {CONVERGENCE_TAIL} samples): "
                  f"{_convergence(errors)}", flush=True)
    finally:
        stop.set()
        if driver is not None:
            driver.cancel()
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await driver
            except Exception as exc:      # 취소가 아닌 이유로 끝났다 — 조용히 묻지 않는다
                print(f"leader driver failed: {exc!r}", file=sys.stderr)
        try:
            # start() 가 던졌어도 부른다. 반쯤 무장된 팔로워를 남기는 것보다 낫다.
            await session.stop()
        finally:
            for c in clients.values():
                await c.aclose()


async def main_async(args) -> int:
    robots = load_robots(args.robots)
    clients = {r.robot_id: HttpRobotClient(r) for r in robots}
    leader = clients[args.leader]
    followers = [c for rid, c in clients.items() if rid != args.leader]
    spec = FormationSpec(Formation(args.formation), spacing=args.spacing)
    session = FormationSession(leader, followers, spec)

    # CSV 는 무장보다 먼저 연다. 무장 뒤에 열면 열 수 없는 경로(오타, 읽기 전용 디렉터리)
    # 하나가 이미 달리는 대형을 세운다 — 그리고 그 런은 아무것도 남기지 못한다.
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["t", "scenario", "robot_id", "state", "holding", "stream_age_s",
                         "slot_err_m", "relay_tx_hz", "relay_paused", "leader_rx_hz",
                         "leader_age_s"])
        fh.flush()
        await _measure(session, leader, followers, clients, writer, fh, args)
    print(f"wrote {args.out}")
    return 0


def main(argv=None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
