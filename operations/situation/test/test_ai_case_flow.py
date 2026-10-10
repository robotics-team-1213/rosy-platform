"""Real Fleet cases reach VLM and validated replan; every retry reads a fresh front frame."""

import base64
import json
import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.stuck.ai_first import AiFirst
from fleet.stuck.ai_routes import install_ai_first_routes
from fleet.stuck.deadlock import AiReplan
from rosy_situation.service import Situation
from rosy_situation.vlm import Vlm

WALL = 1_760_000_000.0
JPEG = b"\xff\xd8frame\xff\xd9"


class Front:
    sequence = 0

    async def front_frame(self, *, overlay=True):
        assert overlay is False
        self.sequence += 1
        return JPEG, {"source": "front", "sequence": self.sequence, "age_ms": 100,
                      "captured_at": WALL - 4 + self.sequence}


def routes(first, line, clients, loop=None, deadlock=lambda: None):
    app = FastAPI()
    principal = lambda: SimpleNamespace(role="ai_observer")
    install_ai_first_routes(app, first=first, line_stuck=line, loop=loop, episodes=None,
                            read_guard=[], authorize=principal, require_named_operator=principal,
                            clients=lambda: clients, deadlock_case=deadlock,
                            pose=lambda _rid: {"state": "LOCALIZED", "age_s": 0.1},
                            rosy_cam=lambda rid: {"frame_path": f"/api/vision/sources/{rid}/frame", "lease": "private"})
    return TestClient(app)


@pytest.mark.parametrize("enrolled", [(), ("a",)])
def test_stuck_ai_retry_reads_new_front_without_replacing_operator_preview(enrolled):
    first = AiFirst(enrolled)
    first.wall = lambda: WALL
    line = SimpleNamespace(pending=lambda: [{"robot_id": "a", "stuck_id": "s1"}],
                           preview=lambda *_args: {"sequence": 0})
    front = Front()
    client = routes(first, line, {"a": front}, SimpleNamespace(problems=None, _rows={}))
    assert client.get("/api/fleet/ai/problems").json()["problems"] == [{"problem_id": "s1", "kind": "stuck", "robot_id": "a"}]
    one = client.get("/api/fleet/ai/case/s1").json()
    first.wall = lambda: WALL + 8
    two = client.get("/api/fleet/ai/case/s1").json()
    assert one["views"]["front"]["frame_id"] == "front:1"
    assert two["views"]["front"]["frame_id"] == "front:2"
    assert two["views"]["front"]["captured_at"] == WALL - 2
    assert first.on("a") == bool(enrolled)


def test_deadlock_case_service_vlm_and_fleet_replan_are_connected(tmp_path):
    first = AiFirst(("a", "b"))
    first.wall = lambda: WALL
    board = SimpleNamespace(proposal=None, verdicts=[])
    board.problem_proposal = lambda _pid: board.proposal
    replan = AiReplan(first, board)
    replan(("a", "b"), {"b": ["y"]}, 0.0)
    client = routes(first, SimpleNamespace(pending=lambda: []), {"a": Front(), "b": Front()},
                    deadlock=lambda: replan.case)

    class Fleet:
        def call(self, path, body=None):
            if body is not None:
                assert path == "/api/fleet/ai/proposals"
                board.proposal = body
                return {}
            reply = client.get(path)
            assert reply.status_code == 200, reply.text
            return reply.json()

        def frame(self, path, _lease):
            return {"jpeg_b64": base64.b64encode(JPEG).decode(), "captured_at": WALL,
                    "frame_id": f"{path.split('/')[4]}:cam"}

    def chat(_url, body, _timeout):
        assert len(body["messages"][0]["images"]) == 4
        return {"message": {"content": json.dumps({"decision": "REPLAN", "robot_id": "b",
            "blocked_edges": ["y"], "confidence": 0.8,
            "assessment": {"type": "resource_conflict", "direction": "replan", "observations": {
                "front": "Another robot is ahead.", "rosy_cam": "Two robots share the corridor."},
                "uncertainties": ["Current traffic ownership needs Fleet confirmation."]}})}}

    vlm = Vlm(post=chat, get=lambda *_args: {"models": [{"name": "qwen3-vl:8b-instruct", "digest": "a" * 64}]})
    first.profiles = lambda: [vlm.profile()]
    mode = tmp_path / "mode"
    mode.write_text("available")
    situation = Situation(Fleet(), tmp_path / "state", mode, wall=lambda: WALL, vlm=vlm)
    situation._ai_cycle()
    assert board.proposal["robot_id"] == "b" and board.proposal["body"] == {"blocked_edges": ["y"]}
    assert board.proposal["evidence"]["views"]["rosy_cam"]["frame_id"] == "b:cam"
    assert replan(("a", "b"), {"b": ["y"]}, 1.0) == ("b", ("y",))


def test_live_case_context_uses_cached_state_age_and_open_time_clearance(monkeypatch):
    monkeypatch.setattr("fleet.stuck.closed_loop.time.monotonic", lambda: 10.0)
    first = AiFirst(())
    first.wall = lambda: WALL
    line = SimpleNamespace(pending=lambda: [{"robot_id": "a", "stuck_id": "s1",
                                            "front_clearance_m": 0.2, "cause": "lane_lost",
                                            "inquiry": {"version": "situation-inquiry-v1", "problem_id": "s1"}}])
    loop = SimpleNamespace(problems=None, _rows={"a": {"_state_mono": 8.0,
                           "state": {"mode": "EMERGENCY", "line_follow": {"mode": "OFF"}}}})
    case = routes(first, line, {"a": Front()}, loop).get("/api/fleet/ai/case/s1").json()
    assert case["context"]["state_age_s"] == 2.0
    assert case["context"]["current_mode"] == "EMERGENCY"
    assert case["context"]["cause"] == "lane_lost"
    assert case["context"]["clearance_at_open_m"]["front_clearance_m"] == 0.2
    assert "clearance_m" not in case["context"]
    assert case["context"]["robot_inquiry"]["problem_id"] == "s1"


def test_unknown_front_capture_stamp_is_not_reconstructed_as_fresh():
    class MissingStamp:
        async def front_frame(self, *, overlay=True):
            return JPEG, {"source": "front", "sequence": 1, "age_ms": 0}
    first = AiFirst(())
    first.wall = lambda: WALL
    line = SimpleNamespace(pending=lambda: [{"robot_id": "a", "stuck_id": "s1"}])
    case = routes(first, line, {"a": MissingStamp()}).get("/api/fleet/ai/case/s1").json()
    assert "front" not in case["views"]
