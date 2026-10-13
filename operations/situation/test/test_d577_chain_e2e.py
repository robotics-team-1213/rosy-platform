"""D-577 end to end on one host: CORE stuck -> Fleet resolver -> AI PC facts -> console row -> named operator.

A real in-process Fleet over HTTP (uvicorn, lifespan running the resolver), a fake CORE, and the situation
service posting as ``ai_observer``. Nothing here talks to a robot.
"""

from __future__ import annotations

import threading
import time
import urllib.error
from hashlib import sha256

import uvicorn
from browser_harness import safe_listener
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from rosy_situation.service import Fleet, Situation

SID = "stuck-e2e-1"
STUCK = {"stuck_id": SID, "cause": "lane_lost", "phase": "ASKING", "held_s": 6.0, "attempts": 2,
         "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 9.0, "last_answer": None,
         "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]}
JPEG = b"\xff\xd8\xff\xe0e2e\xff\xd9"


def _until(predicate, what, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.02)


def _status(call):
    try:
        call()
    except urllib.error.HTTPError as exc:
        return exc.code
    return 200


def test_lane_lost_stuck_goes_robot_fleet_ai_pc_operator(tmp_path):
    # a. fake CORE: lane_lost with the back-off budget spent, and one front picture
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "NAVIGATION", "safety": {"estop": False},
                                        "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": STUCK}})

    async def front_frame():
        return JPEG, {"age_ms": 40}
    robot.front_frame = front_frame

    # b. Fleet with the resolver (the fake is the resolver's CORE credential), an AI PC and a named operator
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")], [robot])
    app = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "f.sqlite3"),
                                                            robot_ids={"rosy_01"}),
                     start_task_dispatcher=False, stuck_resolver_clients={"rosy_01": robot},
                     site_users={sha256(b"ai-token").hexdigest(): {"principal_id": "ai-pc", "role": "ai_observer"},
                                 sha256(b"op-token").hexdigest(): {"principal_id": "op-7", "role": "operator"}})
    passes = []
    run_once = app.state.stuck_resolver.run_once

    async def counted():
        await run_once()
        passes.append(1)
    app.state.stuck_resolver.run_once = counted

    listener = safe_listener()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        _until(lambda: server.started, "uvicorn")
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        ai, op = Fleet(url, "ai-token"), Fleet(url, "op-token")

        def row():
            return next((p for p in op.call("/api/fleet/line-stuck")["pending"] if p["robot_id"] == "rosy_01"), None)

        # c. the resolver: R5 WAIT to CORE, then a human
        _until(lambda: ("line_stuck_decision", SID, "WAIT") in robot.calls, "resolver WAIT")
        _until(lambda: (row() or {}).get("resolver") and row()["resolver"]["tier"] == "human", "escalation note")
        assert row()["resolver"]["escalated"] == "lane_lost_hold:attempts"
        answers = op.call("/api/fleet/line-stuck")["answers"]
        assert any(a["decision"] == "WAIT" and a["principal_id"] == "fleet-resolver" and a["tier"] == "rule"
                   and a["rule"] == "R5" and a["accepted"] is True for a in answers), answers
        assert any(a["decision"] == "ESCALATE" and a["stuck_id"] == SID for a in answers), answers

        # d. the stuck's evidence picture
        shown = op.call(f"/api/fleet/robots/rosy_01/line-stuck/evidence?stuck_id={SID}")
        assert shown["jpeg_base64"]

        # e. the AI PC sees the scene and posts one fact
        def stalled(_snapshot):
            return [{"kind": "stalled", "robot_ids": ["rosy_01"], "value": {"still_s": 21.0}, "confidence": 0.9,
                     "evidence": {"line_follow_mode": "CAMERA_LINE"}, "source": "analyzer:stub@0",
                     "observed_at": time.time(), "ttl_s": 5.0}]
        (tmp_path / "mode").write_text("shared")
        Situation(ai, tmp_path / "state", tmp_path / "mode", analyzers=stalled).step()

        # f. the console row carries the AI chip and the fact; the AI PC cannot answer
        status = op.call("/api/fleet/ai")["status"]
        assert status["state"] == "present" and status["owner_mode"] == "shared"
        stuck_row = row()
        assert stuck_row["ai"]["state"] == "present" and stuck_row["ai_facts"], stuck_row
        assert stuck_row["ai_facts"][0]["kind"] == "stalled"
        assert _status(lambda: ai.call("/api/fleet/robots/rosy_01/line-stuck/decision",
                                       {"stuck_id": SID, "decision": "WAIT"})) == 403

        # g. the named operator decides; the resolver keeps out of it
        assert op.call("/api/fleet/robots/rosy_01/line-stuck/decision",
                       {"stuck_id": SID, "decision": "ABORT"})["answer"]["accepted"] is True
        assert ("line_stuck_decision", SID, "ABORT") in robot.calls
        assert any(a["decision"] == "ABORT" and a["tier"] == "human" and a["principal_id"] == "op-7"
                   for a in op.call("/api/fleet/line-stuck")["answers"])
        sent = [c for c in robot.calls if c[0] == "line_stuck_decision"]
        seen = len(passes)
        _until(lambda: len(passes) >= seen + 2, "two resolver passes after the claim")
        assert [c for c in robot.calls if c[0] == "line_stuck_decision"] == sent
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
