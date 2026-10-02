#!/usr/bin/env python3
"""D-407 lane stuck recovery scenarios against a running CORE (Gazebo sim), ROS-free.

Talks to CORE over its REST API only (stdlib urllib), so it runs from WSL or Windows:

  run       drive line follow hold-to-go (PUT /line-follow/mode CAMERA_LINE hold_s, POST /hold
            at 10 Hz) and record status/stuck/pose/velocity/events at 10 Hz until the stuck
            flow ends. --on-attempt release|estop drops the driver hold or presses e-stop the
            moment a local back-off starts (D-407 5). --answers sends console answers to the
            first open stuck (POST /line-follow/stuck/decision), one every --gap s; the token
            `stale` sends a wrong stuck id, `old` the previous (closed) one.
  summary   timeline of nav.line_* events and odom deltas per back-off from a run's log.jsonl.
  hub       fake Fleet hub (ws://HOST:PORT/ws/robots, needs `websockets`): welcomes the
            FleetAgent and acks heartbeats, so CORE reads console_linked=true and a stuck stays
            ASKING for recovery_ask_s. It never answers a stuck.

Evidence goes to --out (log.jsonl, events.jsonl, answers.jsonl, summary.json).
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

STUCK_EVENTS = ("nav.line_stuck_", "nav.line_obstacle_hold", "nav.lane_lost",
                "nav.line_driver_released")


class Core:
    def __init__(self, base: str, token: str, admin_token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.admin_token = admin_token

    def call(self, method: str, path: str, body=None, *, admin: bool = False,
             timeout: float = 3.0) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.admin_token if admin else self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}

    def save_frame(self, path: Path) -> bool:
        """Front camera preview jpeg (GET /vision/front/status -> /frame?sequence=N)."""
        _, status = self.call("GET", "/api/v1/vision/front/status")
        sequence = status.get("sequence")
        if not sequence:
            return False
        request = urllib.request.Request(
            f"{self.base}/api/v1/vision/front/frame?sequence={sequence}",
            headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=3.0) as response:
                path.write_bytes(response.read())
            return True
        except (urllib.error.URLError, OSError):
            return False


class Recorder(threading.Thread):
    """10 Hz: line-follow status (with stuck), pose, velocity, new events."""

    def __init__(self, core: Core, out: Path, t0: float) -> None:
        super().__init__(daemon=True)
        self.core, self.t0 = core, t0
        self.log = open(out / "log.jsonl", "w", encoding="utf-8")
        self.events_file = open(out / "events.jsonl", "w", encoding="utf-8")
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.latest: dict = {}
        self.events: list[dict] = []
        _, first = core.call("GET", "/api/v1/events?limit=1")
        self.since = first.get("last_seq")

    def run(self) -> None:
        while not self.stop_flag.is_set():
            t = round(time.monotonic() - self.t0, 3)
            _, status = self.core.call("GET", "/api/v1/line-follow")
            _, pose = self.core.call("GET", "/api/v1/robot/pose")
            _, vel = self.core.call("GET", "/api/v1/robot/velocity")
            query = "" if self.since is None else f"since_seq={self.since}&"
            _, ev = self.core.call("GET", f"/api/v1/events?{query}limit=200")
            new = [e for e in ev.get("events", [])
                   if self.since is None or e.get("seq", 0) > self.since]
            if ev.get("last_seq") is not None:
                self.since = ev["last_seq"]
            row = {"t": t, "status": status, "pose": pose, "velocity": vel}
            with self.lock:
                self.latest = row
                for event in new:
                    event = {"t": t, **event}
                    self.events.append(event)
                    if str(event.get("type", "")).startswith(STUCK_EVENTS) or str(
                            event.get("type", "")).startswith(("mode.", "safety.")):
                        self.events_file.write(json.dumps(event) + "\n")
                self.log.write(json.dumps(row) + "\n")
            self.log.flush()
            self.events_file.flush()
            self.stop_flag.wait(0.1)

    def snapshot(self) -> tuple[dict, list[dict]]:
        with self.lock:
            return dict(self.latest), list(self.events)


class Holder(threading.Thread):
    """Driver keeps pressing "go" (D-344 8): POST /hold every 0.1 s while active."""

    def __init__(self, core: Core) -> None:
        super().__init__(daemon=True)
        self.core = core
        self.active = threading.Event()
        self.active.set()
        self.stop_flag = threading.Event()
        self.last_ok: float | None = None
        self.refused = 0

    def run(self) -> None:
        while not self.stop_flag.is_set():
            if self.active.is_set():
                code, _ = self.core.call("POST", "/api/v1/line-follow/hold")
                if code == 200:
                    self.last_ok = time.monotonic()
                else:
                    self.refused += 1
            self.stop_flag.wait(0.1)


def _types(events: list[dict]) -> list[str]:
    return [e.get("type", "") for e in events]


def run(args) -> int:
    core = Core(args.base, args.token, args.admin_token)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    rec = Recorder(core, out, t0)
    rec.start()
    answers_log = open(out / "answers.jsonl", "w", encoding="utf-8")

    def note(kind: str, **data) -> None:
        row = {"t": round(time.monotonic() - t0, 3), "kind": kind, **data}
        answers_log.write(json.dumps(row) + "\n")
        answers_log.flush()
        print(json.dumps(row), flush=True)

    code, body = core.call("PUT", "/api/v1/line-follow/mode",
                           {"mode": "CAMERA_LINE", "hold_s": args.hold_s})
    note("mode_on", code=code, state=body.get("state"), reason=body.get("reason"))
    if code != 200:
        rec.stop_flag.set()
        return 2
    holder = Holder(core)
    holder.start()
    answers = [a for a in (args.answers or "").split(",") if a]
    first_id = previous_id = None
    next_answer_at = None
    attempt_acted = False
    end_reason = "duration"
    end_at = None
    deadline = t0 + args.duration
    while time.monotonic() < deadline:
        time.sleep(0.05)
        latest, events = rec.snapshot()
        status = latest.get("status") or {}
        stuck = status.get("stuck")
        types = _types(events)
        if stuck and first_id is None:
            first_id = stuck["stuck_id"]
            note("stuck_seen", stuck=stuck, state=status.get("state"),
                 frame=core.save_frame(out / "stuck_open.jpg"))
            if answers:
                next_answer_at = time.monotonic() + args.first_answer_after
        if (args.on_attempt and not attempt_acted
                and "nav.line_stuck_local_attempt" in types):
            attempt_acted = True
            time.sleep(args.act_delay)
            if args.on_attempt == "release":
                holder.active.clear()
                note("driver_released_hold", last_hold_ok=round((holder.last_ok or t0) - t0, 3))
            else:
                code, body = core.call("POST", "/api/v1/safety/stop")
                note("estop", code=code, body=body)
            end_at = time.monotonic() + args.tail_s
            end_reason = f"on_attempt_{args.on_attempt}"
        if next_answer_at is not None and time.monotonic() >= next_answer_at and answers:
            token = answers.pop(0)
            current = (stuck or {}).get("stuck_id")
            if token == "stale":
                sid, decision = "stuck-000000000000", "WAIT"
            elif token == "old":
                sid, decision = previous_id or first_id, "WAIT"
            else:
                sid, decision = current or first_id, token
            code, body = core.call("POST", "/api/v1/line-follow/stuck/decision",
                                   {"stuck_id": sid, "decision": decision})
            note("answer", token=token, stuck_id=sid, decision=decision, code=code,
                 outcome=body.get("outcome"), error=body.get("error") or body.get("code"),
                 message=body.get("message") or body.get("detail"),
                 stuck_after=body.get("stuck"), state=body.get("state"))
            if current and current != previous_id and body.get("outcome") in (
                    "resume", "manual", "idle"):
                previous_id = current
            next_answer_at = time.monotonic() + args.gap if answers else None
            if not answers:
                end_at = time.monotonic() + args.tail_s
                end_reason = "answers_done"
        if end_at is None and not answers and not args.on_attempt:
            exhausted = (stuck and stuck.get("phase") == "WAITING_CONSOLE"
                         and stuck.get("attempts", 0) >= stuck.get("max_attempts", 99))
            refused = "nav.line_stuck_local_result" in types and stuck and stuck.get(
                "phase") == "WAITING_CONSOLE"
            if exhausted or refused:
                end_at = time.monotonic() + args.tail_s
                end_reason = "waiting_console"
        if end_at is not None and time.monotonic() >= end_at:
            break
        if status.get("mode") == "OFF" and first_id and end_at is None:
            end_at = time.monotonic() + args.tail_s
            end_reason = f"mode_off:{status.get('reason')}"
    holder.stop_flag.set()
    core.save_frame(out / "end.jpg")
    code, body = core.call("PUT", "/api/v1/line-follow/mode", {"mode": "OFF"})
    note("mode_off", code=code, end_reason=end_reason, hold_refused=holder.refused)
    if args.on_attempt == "estop":
        code, body = core.call("POST", "/api/v1/safety/release", admin=True)
        note("estop_release", code=code, body=body)
    time.sleep(0.5)
    rec.stop_flag.set()
    rec.join(timeout=2)
    rec.log.close()
    rec.events_file.close()
    summary = summarize(out)
    print(json.dumps(summary, indent=1))
    return 0


def _pose_at(rows: list[dict], t: float) -> dict | None:
    best = None
    for row in rows:
        if row["t"] <= t:
            best = row
        else:
            break
    return None if best is None else best.get("pose")


def summarize(out: Path) -> dict:
    rows = [json.loads(line) for line in open(out / "log.jsonl", encoding="utf-8") if line.strip()]
    events = [json.loads(line) for line in open(out / "events.jsonl", encoding="utf-8")
              if line.strip()]
    timeline = []
    for e in events:
        data = e.get("data") or {}
        keep = {k: data[k] for k in ("stuck_id", "cause", "reason", "attempt", "trigger",
                                     "result", "decision", "accepted", "console_linked",
                                     "local_fallback_s", "back_m", "speed_mps",
                                     "rear_clearance_m", "rear_blind_m", "trail_m",
                                     "front_clearance_m", "turn_clearance_m", "preview_seq",
                                     "lane_visible", "front_clear", "held_s", "attempts")
                if k in data}
        timeline.append({"t": e["t"], "type": e.get("type"), **keep})
    backoffs = []
    for e in events:
        if e.get("type") != "nav.line_stuck_local_attempt":
            continue
        start = _pose_at(rows, e["t"] - 0.1)
        # The back-off ends when the stuck leaves BACKING; take the pose 1.5 s later (still).
        end_t = None
        for row in rows:
            stuck = (row.get("status") or {}).get("stuck")
            if row["t"] > e["t"] and (not stuck or stuck.get("phase") != "BACKING"):
                end_t = row["t"]
                break
        end = _pose_at(rows, (end_t or rows[-1]["t"]) + 0.8)
        if start and end:
            dx, dy = end["x"] - start["x"], end["y"] - start["y"]
            yaw = start.get("yaw", 0.0)
            along = dx * math.cos(yaw) + dy * math.sin(yaw)
            backoffs.append({"t": e["t"], "attempt": (e.get("data") or {}).get("attempt"),
                             "along_heading_m": round(along, 4),
                             "dist_m": round(math.hypot(dx, dy), 4),
                             "dyaw_deg": round(math.degrees(end.get("yaw", 0.0) - yaw), 2),
                             "backing_s": None if end_t is None else round(end_t - e["t"], 2)})
    states = []
    for row in rows:
        status = row.get("status") or {}
        stuck = status.get("stuck") or {}
        key = (status.get("mode"), status.get("state"), status.get("reason"), stuck.get("phase"))
        if not states or states[-1]["key"] != key:
            states.append({"t": row["t"], "key": key, "linear": status.get("linear"),
                           "pose": row.get("pose")})
    summary = {"timeline": timeline, "backoffs": backoffs,
               "states": [{"t": s["t"], "mode": s["key"][0], "state": s["key"][1],
                           "reason": s["key"][2], "phase": s["key"][3],
                           "linear": s["linear"], "pose": s["pose"]} for s in states]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def hub(args) -> int:
    import asyncio

    import websockets

    log = open(args.log, "a", encoding="utf-8") if args.log else None

    async def handler(ws, *_):
        async for text in ws:
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "hello":
                await ws.send(json.dumps({"type": "welcome", "payload": {"last_event_seq": 0}}))
                print("hub: robot hello", (msg.get("payload") or {}).get("robot_id"), flush=True)
            elif kind == "heartbeat":
                await ws.send(json.dumps({"type": "ack", "payload": {}}))
            elif kind == "event" and log is not None:
                payload = msg.get("payload") or {}
                if str(payload.get("type", "")).startswith("nav.line_"):
                    log.write(json.dumps(payload) + "\n")
                    log.flush()

    async def main():
        async with websockets.serve(handler, args.host, args.port):
            print(f"hub: ws://{args.host}:{args.port}/ws/robots", flush=True)
            await asyncio.Future()

    asyncio.run(main())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--base", default="http://127.0.0.1:8095")
    r.add_argument("--token", default="rosy-dev-operator")
    r.add_argument("--admin-token", default="rosy-dev-admin")
    r.add_argument("--out", required=True)
    r.add_argument("--duration", type=float, default=240.0, help="wall seconds cap")
    r.add_argument("--hold-s", type=float, default=0.5)
    r.add_argument("--answers", default="", help="e.g. stale,WAIT,RESUME,BACK_AND_RETRY,ABORT,old")
    r.add_argument("--first-answer-after", type=float, default=2.0)
    r.add_argument("--gap", type=float, default=4.0)
    r.add_argument("--on-attempt", choices=("release", "estop"))
    r.add_argument("--act-delay", type=float, default=0.5,
                   help="wall s after the attempt event before acting (mid back-off)")
    r.add_argument("--tail-s", type=float, default=6.0)
    s = sub.add_parser("summary")
    s.add_argument("out")
    h = sub.add_parser("hub")
    h.add_argument("--host", default="127.0.0.1")
    h.add_argument("--port", type=int, default=8096)
    h.add_argument("--log")
    args = parser.parse_args()
    if args.cmd == "run":
        return run(args)
    if args.cmd == "summary":
        print(json.dumps(summarize(Path(args.out)), indent=1))
        return 0
    return hub(args)


if __name__ == "__main__":
    raise SystemExit(main())
