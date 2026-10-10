"""D-577 4: the AI PC posts facts and heartbeats as `ai_observer`; facts never command, never move a robot."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from hashlib import sha256

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server import ai_facts
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

AI, OPERATOR, VIEWER = "ai-token", "operator-token", "viewer-token"
AI_PATHS = {"/api/fleet/ai/facts", "/api/fleet/ai/heartbeat", "/api/fleet/ai/proposals"}
MOTION_CALLS = {"follow", "swarm_cancel", "navigation_cancel", "navigation_goal", "line_follow_mode",
                "line_stuck_decision", "estop", "identify_lamp", "line_follow_junction", "trip_lease"}


def _app(tmp_path, robot=None, clock=None):
    robot = robot or FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")], [robot])
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    users = {sha256(token.encode()).hexdigest(): {"principal_id": name, "role": role}
             for token, name, role in ((AI, "ai-pc", "ai_observer"), (OPERATOR, "op-7", "operator"),
                                       (VIEWER, "watcher", "viewer"))}
    app = create_app(console, task_service=FleetTaskService(store, robot_ids={"rosy_01"}),
                     start_task_dispatcher=False, site_users=users)
    if clock is not None:
        app.state.ai_facts.clock = clock
    return app, robot, store


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _fact(**over):
    fact = {"kind": "wait_cycle_confirmed", "robot_ids": ["rosy_01", "rosy_02"], "value": {"cycle": 2},
            "confidence": 0.9, "evidence": {"traffic_generation": 41, "events": [12, 13]},
            "source": "analyzer:wait_cycle@0.1", "observed_at": time.time() - 0.2, "ttl_s": 5.0}
    fact.update(over)
    return fact


def _beat(client, mode="shared"):
    response = client.post("/api/fleet/ai/heartbeat", headers=_auth(AI), json={
        "service_version": "0.1.0", "model_profiles": [], "owner_mode": mode,
        "gpu_used_mib": None, "mem_used_mib": 120, "input_lag_s": 0.3})
    assert response.status_code == 200, response.text
    return response.json()


def test_ai_observer_reads_like_a_viewer_and_posts_only_facts_and_heartbeats(tmp_path):
    """No write route but the two AI POSTs passes ai_observer: no stop, no stuck answer, no trip, no goal."""
    app, robot, _ = _app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/fleet/state", headers=_auth(AI)).status_code == 200
    writes = []
    for route in app.routes:
        methods = (getattr(route, "methods", None) or set()) - {"GET", "HEAD", "OPTIONS"}
        path = getattr(route, "path", "")
        if not methods or not path.startswith("/api/") or path in AI_PATHS:
            continue
        concrete = re.sub(r"\{[^}]+\}", "rosy_01", path)
        for method in methods:
            response = client.request(method, concrete, headers=_auth(AI), json={})
            writes.append((method, path))
            assert response.status_code in (401, 403), (method, path, response.status_code, response.text)
    assert ("POST", "/api/fleet/estop") in writes
    assert ("POST", "/api/fleet/robots/{robot_id}/line-stuck/decision") in writes
    assert not [call for call in robot.calls if call[0] in MOTION_CALLS]


def test_only_ai_observer_may_post_facts(tmp_path):
    client = TestClient(_app(tmp_path)[0])
    for token in (OPERATOR, VIEWER):
        assert client.post("/api/fleet/ai/facts", headers=_auth(token), json={"facts": []}).status_code == 403
        assert client.post("/api/fleet/ai/heartbeat", headers=_auth(token), json={}).status_code == 403


@pytest.mark.parametrize("fact", [
    _fact(value="WAIT"),
    _fact(value={"answer": "back_and_retry"}),
    _fact(evidence={"RESUME": 1}),
    _fact(value=["ok", {"next": "STOP"}]),
    _fact(ttl_s=5.5),
    _fact(source="vlm:qwen3-vl-8b@lidar-identity/1", kind="obstacle_identity", ttl_s=8.5),
    _fact(observed_at=time.time() + 30),
    _fact(kind="all_clear"),
    _fact(confidence=1.5),
    _fact(source="human:bob"),
])
def test_a_fact_with_a_command_word_or_out_of_bounds_is_refused(tmp_path, fact):
    client = TestClient(_app(tmp_path)[0])
    _beat(client)
    response = client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [fact]})
    assert response.status_code == 422, response.text


def test_count_and_body_size_are_bounded(tmp_path):
    client = TestClient(_app(tmp_path)[0])
    _beat(client)
    many = client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [_fact()] * 33})
    assert many.status_code == 422
    big = client.post("/api/fleet/ai/facts", headers=_auth(AI),
                      json={"facts": [_fact(value={"pad": "x" * 70_000})]})
    assert big.status_code == 413


def test_more_than_two_fact_posts_a_second_is_429(tmp_path):
    client = TestClient(_app(tmp_path)[0])
    _beat(client)
    codes = [client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [_fact()]}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429]


def test_facts_while_absent_or_owner_busy_are_ignored_and_six_silent_seconds_mean_absent(tmp_path):
    now = [1000.0]
    app, _, store = _app(tmp_path, clock=lambda: now[0])
    client = TestClient(app)
    assert client.get("/api/fleet/ai", headers=_auth(VIEWER)).json()["status"]["state"] == "absent"
    ignored = client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [_fact()]}).json()
    assert ignored == {"accepted": 0, "ignored": 1, "ai": "absent"}

    _beat(client)
    now[0] += 1.0
    assert client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [_fact()]}).json()["accepted"] == 1
    status = client.get("/api/fleet/ai", headers=_auth(VIEWER)).json()
    assert status["status"]["state"] == "present" and status["status"]["owner_mode"] == "shared"
    assert [f["kind"] for f in status["facts"]] == ["wait_cycle_confirmed"]
    assert status["facts"][0]["stage"] == "shadow"

    now[0] += 6.1
    assert client.get("/api/fleet/ai", headers=_auth(VIEWER)).json()["status"]["state"] == "absent"
    now[0] += 1.0
    _beat(client, "owner_busy")
    busy = client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [_fact()]}).json()
    assert busy["accepted"] == 0 and busy["ai"] == "owner_busy"

    with sqlite3.connect(store.path) as db:
        rows = db.execute("SELECT kind, stage, source FROM fleet_ai_facts").fetchall()
    assert rows == [("wait_cycle_confirmed", "shadow", "analyzer:wait_cycle@0.1")]


def test_the_stuck_row_carries_the_ai_chip_and_live_facts_for_its_robot(tmp_path):
    stuck = {"stuck_id": "stuck-abc", "cause": "lane_lost", "phase": "WAITING_CONSOLE", "held_s": 3.0,
             "attempts": 2, "max_attempts": 2, "local_enabled": True}
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "safety": {"estop": False},
                                        "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": stuck}})
    client = TestClient(_app(tmp_path, robot=robot)[0])
    row = client.get("/api/fleet/state", headers=_auth(VIEWER)).json()["robots"][0]["line_stuck"]
    assert row["ai"]["state"] == "absent" and row["ai_facts"] == []

    _beat(client)
    client.post("/api/fleet/ai/facts", headers=_auth(AI), json={"facts": [
        _fact(), _fact(robot_ids=["rosy_09"], kind="stalled"), _fact(observed_at=time.time() - 60)]})
    client.app.state.fleet_gather.max_age_s = 0.0
    row = client.get("/api/fleet/state", headers=_auth(VIEWER)).json()["robots"][0]["line_stuck"]
    assert row["ai"]["state"] == "present"
    assert [(f["kind"], f["confidence"], f["evidence"]["events"]) for f in row["ai_facts"]] == [
        ("wait_cycle_confirmed", 0.9, [12, 13])]                       # other robot and expired dropped


def test_a_stalled_fact_write_does_not_delay_the_emergency_stop(tmp_path, monkeypatch):
    app, robot, _ = _app(tmp_path)
    original = ai_facts.AiFactLog.append

    def slow_append(self, *args, **kwargs):
        time.sleep(1.0)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ai_facts.AiFactLog, "append", slow_append)

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://fleet") as client:
            await client.post("/api/fleet/ai/heartbeat", headers=_auth(AI), json={
                "service_version": "0.1.0", "model_profiles": [], "owner_mode": "shared"})
            facts = asyncio.create_task(client.post("/api/fleet/ai/facts", headers=_auth(AI),
                                                    json={"facts": [_fact()]}))
            await asyncio.sleep(0.05)
            started = time.monotonic()
            stop = await client.post("/api/fleet/estop", headers=_auth(OPERATOR))
            elapsed = time.monotonic() - started
            assert (await facts).status_code == 200
            return stop.status_code, elapsed

    status, elapsed = asyncio.run(main())
    assert status == 200 and elapsed < 0.5, elapsed
    assert ("estop",) in robot.calls


def test_acting_stage_only_for_configured_robots_and_kinds():
    board = ai_facts.AiFactsBoard(acting=frozenset({"rosy_41"}))
    board.heartbeat(ai_facts.AiHeartbeat(service_version="t", owner_mode="shared"))
    now = board.wall()

    def fact(kind, rid):
        return ai_facts.AiFact(kind=kind, robot_ids=[rid], value={"x": 1}, confidence=0.8, evidence={},
                               source="analyzer:stuck_scene@1", observed_at=now, ttl_s=3.0)

    board.accept([fact("rear_blocked", "rosy_41"), fact("rear_blocked", "rosy_40"),
                  fact("stalled", "rosy_41")], "ai-pc")
    assert [f["kind"] for f in board.acting_facts("rosy_41")] == ["rear_blocked"]
    assert board.acting_facts("rosy_40") == []


def test_proposal_is_kept_for_an_acting_robot_only_and_expires(tmp_path):
    app, _, _ = _app(tmp_path)
    board = app.state.ai_facts
    board.acting = frozenset({"rosy_01"})
    client = TestClient(app)
    _beat(client)
    body = {"robot_id": "rosy_01", "stuck_id": "s-1", "decision": "BACK_AND_RETRY", "reason": "no_motion_back_off",
            "confidence": 0.6, "evidence": {}, "source": "analyzer:stuck_scene@1",
            "observed_at": time.time(), "ttl_s": 6.0}
    assert client.post("/api/fleet/ai/proposals", headers=_auth(OPERATOR), json=body).status_code == 403
    assert client.post("/api/fleet/ai/proposals", headers=_auth(AI), json=body).json() == {"state": "queued"}
    assert board.proposal("rosy_01")["decision"] == "BACK_AND_RETRY" and board.waiting("rosy_01")
    other = client.post("/api/fleet/ai/proposals", headers=_auth(AI), json={**body, "robot_id": "rosy_02"})
    assert other.json() == {"state": "robot_not_acting"}
    bad = client.post("/api/fleet/ai/proposals", headers=_auth(AI), json={**body, "decision": "GO"})
    assert bad.status_code == 422
    board.wall = lambda: time.time() + 7.0                     # past ttl_s: expired, rules answer
    assert board.proposal("rosy_01") is None
