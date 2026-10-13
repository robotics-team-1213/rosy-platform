#!/usr/bin/env python3
"""D-559 trail follow SIM driver (model PC; Gazebo from run_sim.sh). No rclpy.

The real Fleet path arms the follower: fleet.bench FormationSession with Formation.TRAIL
(arming, relay of /ws/swarm/pose -> /ws/swarm/reference). The leader is driven by CORE
teleop (MANUAL, 10 Hz) along a scripted S-curve / arc / pivot path with a 10 s stop. The
relay is paused for CUT_S on the last straight (stream cut). Gazebo truth for both robots
comes from `gz topic -e .../dynamic_pose/info --json-output`.

    python trail_sim.py --robots robots.yaml --world rosy_swarm_bench --out runs/r1 [--direct]

--direct arms POST /api/v1/swarm/follow (mode trail, no `members`) and relays the leader's
/ws/swarm/pose frames unchanged to the follower's /ws/swarm/reference itself, like
fleet/swarm/relay.py. A Fleet formation always sends `members`, so there a stream loss ends the
follow by succession (D-20); without members it is the SWM-004 HOLD this run measures.

Writes truth.jsonl (t, sim_t, robot, x, y, yaw), swarm.jsonl (follower /swarm/state at 5 Hz,
leader /state mode), events.jsonl (phase marks) and summary.json (analyze.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

import websockets
from core_common.protocol.localization import DecisionSource, LocalizationDecision
from core_common.protocol.schemas import SwarmFollowParams
from fleet.bench import (Formation, FormationSession, FormationSpec, HttpRobotClient,
                         SessionState, load_robots)

V = 0.12
#: (name, seconds, linear, angular). Start (-1.8, -2.2) facing +x in rosy_swarm_bench.
PATH = [
    ("straight_e", 2.0 / V, V, 0.0),
    ("arc_left_r0.4", (math.pi / 2) / (V / 0.4), V, V / 0.4),
    ("straight_n", 0.8 / V, V, 0.0),
    ("s_left_r0.5", (math.pi / 2) / (V / 0.5), V, V / 0.5),
    ("s_right_r0.5", (math.pi / 2) / (V / 0.5), V, -V / 0.5),
    ("straight_n2", 0.6 / V, V, 0.0),
    ("stop_10s", 10.0, 0.0, 0.0),
    ("pivot_right", (math.pi / 2) / 0.5, 0.0, -0.5),
    ("straight_e2", 2.0 / V, V, 0.0),
    ("stop_end", 12.0, 0.0, 0.0),
]
CUT_PHASE, CUT_AT_S, CUT_S = "straight_e2", 4.0, 5.0


class Truth:
    def __init__(self, world: str, names: list[str], path: Path) -> None:
        self.latest: dict[str, tuple] = {}
        self._names = set(names)
        self._fh = path.open("w", encoding="utf-8")
        self._last: dict[str, float] = {}
        self._proc = subprocess.Popen(
            ["gz", "topic", "-e", "-t", f"/world/{world}/dynamic_pose/info", "--json-output"],
            stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self._proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            stamp = msg.get("header", {}).get("stamp", {})
            sim_t = float(stamp.get("sec", 0)) + float(stamp.get("nsec", 0)) * 1e-9
            for p in msg.get("pose", []):
                name = p.get("name")
                if name not in self._names or sim_t - self._last.get(name, -1.0) < 0.02:
                    continue
                self._last[name] = sim_t
                pos, q = p.get("position", {}), p.get("orientation", {})
                w, z = q.get("w", 1.0), q.get("z", 0.0)
                x_, y_ = q.get("x", 0.0), q.get("y", 0.0)
                yaw = math.atan2(2 * (w * z + x_ * y_), 1 - 2 * (y_ * y_ + z * z))
                row = (pos.get("x", 0.0), pos.get("y", 0.0), yaw)
                self.latest[name] = row
                self._fh.write(json.dumps({"t": time.monotonic(), "sim_t": sim_t, "robot": name,
                                           "x": row[0], "y": row[1], "yaw": row[2]}) + "\n")

    def close(self) -> None:
        self._proc.terminate()
        self._fh.close()


async def teleop_loop(leader: HttpRobotClient, mark, cut) -> None:
    await leader._post("/api/v1/mode", {"mode": "MANUAL"})
    for name, seconds, v, w in PATH:
        mark("phase", name)
        t0 = time.monotonic()
        while (elapsed := time.monotonic() - t0) < seconds:
            if name == CUT_PHASE and not cut["done"] and elapsed >= CUT_AT_S:
                cut["done"] = True
                asyncio.get_running_loop().create_task(cut["run"]())
            await leader._post("/api/v1/teleop", {"linear": v, "angular": w})
            await asyncio.sleep(0.1)
    await leader._post("/api/v1/teleop", {"linear": 0.0, "angular": 0.0})
    mark("phase", "done")


def ws_url(robot, path: str) -> str:
    return robot.base_url.replace("http", "ws", 1) + f"{path}?token={robot.token}"


async def pose_frame(robot) -> str:
    """The `frame` of one leader-stream sample of this robot (D-559 field)."""
    async with websockets.connect(ws_url(robot, "/ws/swarm/pose")) as ws:
        return json.loads(await asyncio.wait_for(ws.recv(), 5.0))["payload"].get("frame")


class DirectRelay:
    """fleet/swarm/relay.py in miniature: leader frames to the follower, unchanged, pausable."""

    def __init__(self, leader, follower) -> None:
        self.leader, self.follower, self.paused = leader, follower, False
        self._task = None

    async def _run(self) -> None:
        async with websockets.connect(ws_url(self.leader, "/ws/swarm/pose")) as src,                 websockets.connect(ws_url(self.follower, "/ws/swarm/reference")) as dst:
            async for frame in src:
                if not self.paused:
                    await dst.send(frame)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


async def main_async(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    robots = load_robots(Path(args.robots))
    clients = {r.robot_id: HttpRobotClient(r) for r in robots}
    leader, follower = clients[args.leader], clients[args.follower]
    rows = {r.robot_id: r for r in robots}
    events = (out / "events.jsonl").open("w", encoding="utf-8")

    def mark(kind, value, **extra):
        events.write(json.dumps({"t": time.monotonic(), "kind": kind, "value": value, **extra}) + "\n")
        events.flush()
        print(f"[{time.strftime('%H:%M:%S')}] {kind} {value} {extra or ''}", flush=True)

    truth = Truth(args.world, [args.leader, args.follower], out / "truth.jsonl")
    session = FormationSession(leader, [follower], FormationSpec(Formation.TRAIL, spacing=args.gap,
                                                                   max_speed=args.max_speed))

    relay = DirectRelay(rows[args.leader], rows[args.follower]) if args.direct else None

    async def cut_stream():
        mark("cut", "pause")
        if relay is not None:
            relay.paused = True
            await asyncio.sleep(CUT_S)
            mark("cut", "relay_resume")
            relay.paused = False
            return
        session.relay.pause()
        await asyncio.sleep(CUT_S)
        if session.state is SessionState.HOLDING:
            mark("cut", "session_resume")
            await session.resume()
        else:
            mark("cut", "relay_resume")
            session.relay.resume()

    decided: set = set()

    async def decide(rid, client, gt):
        """D-395: the answer to CANDIDATES. The SIM stands in for the operator who sees the robot
        (source human; the bench has no square/paint/peer cue): it picks the robot's own candidate
        nearest to Gazebo truth, never a made-up pose."""
        report = await client.localization_candidates()
        if report is None or report.request_id in decided:
            return
        best = min(range(len(report.candidates)), key=lambda i: math.hypot(
            report.candidates[i].x - gt[0], report.candidates[i].y - gt[1]))
        decided.add(report.request_id)
        reply = await client.localization_decision(LocalizationDecision(
            request_id=report.request_id, candidate_index=best, source=DecisionSource.HUMAN,
            evidence={"sim_truth": [round(v, 3) for v in gt]}))
        mark("decision", rid, candidate=best, n=len(report.candidates), reply=reply)

    cut = {"done": False, "run": cut_stream}
    swarm_fh = (out / "swarm.jsonl").open("w", encoding="utf-8")
    stop = asyncio.Event()

    async def poll():
        while not stop.is_set():
            try:
                sw = await follower.swarm_state()
                swarm_fh.write(json.dumps({"t": time.monotonic(), "swarm": sw,
                                           "session": "direct" if relay else session.state.value,
                                           "relay_paused": (relay.paused if relay
                                                            else session.relay.paused)}) + "\n")
            except Exception as exc:  # noqa: BLE001 - a missed sample is a gap, not an end
                swarm_fh.write(json.dumps({"t": time.monotonic(), "error": str(exc)}) + "\n")
            await asyncio.sleep(0.2)

    try:
        # Both APIs up, localization LOCALIZED in map (or no D-395 state), then truth flowing.
        locs = None
        for k in range(300):
            try:
                states = [await c.state() for c in clients.values()]
                locs = [s.get("localization") for s in states]
                if all(loc and loc.get("state") == "LOCALIZED" and loc.get("pose_frame") == "map"
                       for loc in locs):
                    break
                if k >= 60 and all(loc is None for loc in locs):
                    break  # no D-395 localization state on this CORE: the follow gate is open
                for rid, loc in zip(clients, locs):
                    if loc and loc.get("state") == "CANDIDATES" and rid in truth.latest:
                        await decide(rid, clients[rid], truth.latest[rid])
            except Exception as exc:  # noqa: BLE001 - CORE still starting
                if k % 10 == 0:
                    mark("wait", repr(exc)[:200])
            await asyncio.sleep(1.0)
        mark("localization", [None if loc is None else {key: loc.get(key) for key in
                                                         ("state", "pose_frame", "reason")}
                              for loc in (locs or [])])
        # Nav2/AMCL start 15 s after launch: wait until both CORE poses are map frame (D-559 field).
        frames = None
        for _ in range(240):
            try:
                frames = [await pose_frame(rows[rid]) for rid in (args.leader, args.follower)]
                if frames == ["map", "map"]:
                    break
            except Exception:  # noqa: BLE001 - not up yet
                frames = None
            await asyncio.sleep(1.0)
        mark("frames", frames)
        await asyncio.sleep(args.settle)
        for _ in range(100):
            if args.leader in truth.latest and args.follower in truth.latest:
                break
            await asyncio.sleep(0.1)
        mark("truth", "ready", latest={k: list(v) for k, v in truth.latest.items()})
        for rid, c in clients.items():
            st = await c.state()
            mark("state", rid, pose=st.get("pose"), mode=st.get("mode"),
                 localization=(st.get("localization") or {}).get("state"))
        if relay is not None:
            relay.start()
            await asyncio.sleep(0.5)
            reply = await follower.follow(SwarmFollowParams(
                target_robot_id=args.leader, distance=args.gap, mode="trail",
                max_speed=args.max_speed))
            mark("armed", {"direct": reply})
        else:
            await session.start()
            mark("armed", session.assignment and {k: vars(v) for k, v in session.assignment.items()})
        poller = asyncio.create_task(poll())
        await teleop_loop(leader, mark, cut)
        stop.set()
        await poller
        sw = await follower.swarm_state()
        mark("final_swarm", sw)
    finally:
        stop.set()
        try:
            if relay is not None:
                await follower.swarm_cancel()
                await relay.stop()
            else:
                await session.stop()
        except Exception as exc:  # noqa: BLE001
            mark("stop_failed", str(exc))
        try:
            await leader._post("/api/v1/mode", {"mode": "IDLE"})
        except Exception:  # noqa: BLE001 - the leader may already be idle
            pass
        truth.close()
        swarm_fh.close()
        events.close()
        for c in clients.values():
            await c.aclose()
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--robots", required=True)
    p.add_argument("--leader", default="rosy_01")
    p.add_argument("--follower", default="rosy_02")
    p.add_argument("--world", default="rosy_swarm_bench")
    p.add_argument("--gap", type=float, default=0.6)
    p.add_argument("--max-speed", type=float, default=0.18)
    p.add_argument("--out", required=True)
    p.add_argument("--settle", type=float, default=10.0, help="s after ready before arming")
    p.add_argument("--direct", action="store_true", help="own relay, follow without members")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
