"""D-577 (c): rosy-situation polls Fleet, keeps its cursor, bounds its queue, obeys owner_mode, acts never."""

from __future__ import annotations

import io
import json
import urllib.error
from concurrent.futures import Future

from rosy_situation import service
from rosy_situation.service import Situation


class FakeFleet:
    def __init__(self, events=None):
        self.calls = []
        self.events = events or []
        self.refuse_facts = None

    def call(self, path, body=None):
        self.calls.append((path, body))
        if path.startswith("/api/fleet/events"):
            after = int(path.split("after_id=")[1].split("&")[0])
            page = [e for e in self.events if e["audit_id"] > after]
            return {"events": page, "next_cursor": page[-1]["audit_id"] if page else after}
        if path == "/api/fleet/ai/facts" and self.refuse_facts:
            raise urllib.error.HTTPError(path, self.refuse_facts, "no", {}, io.BytesIO(b"{}"))
        return {}

    def paths(self):
        return [p.split("?")[0] for p, _ in self.calls]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _service(tmp_path, fleet, mode="shared", analyzers=service.analyze, clock=None):
    (tmp_path / "mode").write_text(mode)
    return Situation(fleet, tmp_path / "state", tmp_path / "mode", clock=clock or Clock(), analyzers=analyzers)


def _fact(n):
    return {"kind": "stalled", "robot_ids": ["rosy_01"], "value": {"n": n}, "confidence": 0.5,
            "evidence": {"line": n}, "source": "analyzer:stub@0", "observed_at": 1.0, "ttl_s": 5.0}


def test_available_model_reads_one_case_and_posts_its_answer_without_logging_images(tmp_path):
    class Cases(FakeFleet):
        def call(self, path, body=None):
            if path == "/api/fleet/ai/problems":
                self.calls.append((path, body))
                return {"problems": [{"problem_id": "s-1", "robot_id": "pinky", "kind": "stuck"}]}
            if path == "/api/fleet/ai/case/s-1":
                self.calls.append((path, body))
                return {"problem_id": "s-1", "robot_id": "pinky", "kind": "stuck",
                        "views": {"front": {"jpeg_b64": "secret-image"},
                                  "rosy_cam": {"jpeg_b64": "secret-image"}}}
            return super().call(path, body)

    class Model:
        def profile(self):
            return "qwen3-vl:8b-instruct@abc:d610-v1"

        def judge(self, case, now):
            assert case["problem_id"] == "s-1"
            return {"robot_id": "pinky", "stuck_id": "s-1", "decision": "WAIT", "reason": "blocked",
                    "confidence": 0.8, "source": "vlm:qwen3-vl:8b-instruct@abc:d610-v1",
                    "observed_at": now, "ttl_s": 6, "evidence": {}}

    class Immediate:
        def submit(self, fn, *args):
            future = Future()
            future.set_result(fn(*args))
            return future

    fleet, clock = Cases(), Clock()
    (tmp_path / "mode").write_text("available")
    situation = Situation(fleet, tmp_path / "state", tmp_path / "mode", clock=clock,
                          wall=clock, vlm=Model(), executor=Immediate())
    situation.step()  # load the profile off the polling thread
    clock.now += 2
    situation.step()  # report the profile, start one case
    situation.step()  # send the answer
    assert fleet.paths().count("/api/fleet/ai/case/s-1") == 1
    assert fleet.paths().count("/api/fleet/ai/proposals") == 1
    assert any(body["model_profiles"] == [Model().profile()] for path, body in fleet.calls
               if path == "/api/fleet/ai/heartbeat")
    assert all("secret-image" not in path.read_text() for path in (tmp_path / "state" / "logs").glob("*"))


def test_reads_fleet_and_the_event_cursor_survives_a_restart(tmp_path):
    fleet = FakeFleet(events=[{"audit_id": 5, "type": "nav.pose"}, {"audit_id": 7, "type": "nav.pose"}])
    _service(tmp_path, fleet).step()
    assert fleet.paths()[:5] == ["/api/fleet/ai/heartbeat", "/api/fleet/state", "/api/fleet/traffic",
                                 "/api/fleet/line-stuck", "/api/fleet/events"]
    again = FakeFleet()
    _service(tmp_path, again).step()
    assert any(p.startswith("/api/fleet/events?after_id=7&") for p, _ in again.calls)


def test_a_stuck_event_brings_the_next_read_forward(tmp_path):
    fleet = FakeFleet(events=[{"audit_id": 1, "type": "nav.line_stuck_opened"}])
    assert _service(tmp_path, fleet).step() == 0.0


def test_open_stuck_reads_context_once_and_posts_shadow_draft(tmp_path):
    class ContextFleet(FakeFleet):
        def call(self, path, body=None):
            if path == "/api/fleet/line-stuck":
                self.calls.append((path, body))
                return {"pending": [{"robot_id": "pinky", "stuck_id": "one", "cause": "lane_lost"}]}
            if path == "/api/fleet/state":
                self.calls.append((path, body))
                return {"robots": [{"robot_id": "pinky", "state": {"line_follow": {"mode": "CAMERA_LINE"}}}]}
            if path == "/api/fleet/site-map/active":
                self.calls.append((path, body))
                return {"version": 3, "map": {"map_id": "site", "places": []}}
            if path == "/api/fleet/sightings":
                self.calls.append((path, body))
                return {"sightings": [{"robot_id": "pinky", "source_id": "rosy-cam", "seq": 9,
                                       "captured_at": 99.9, "age_ms": 100, "stale": False}]}
            return super().call(path, body)

    fleet = ContextFleet()
    situation = _service(tmp_path, fleet)
    situation.step()
    posts = [body for path, body in fleet.calls if path == "/api/fleet/ai/facts"]
    assert posts[0]["facts"][0]["kind"] == "incident_context"
    assert posts[0]["facts"][0]["value"]["support"][1]["value"]["source_id"] == "rosy-cam"
    situation.step()
    assert fleet.paths().count("/api/fleet/site-map/active") == 1
    assert fleet.paths().count("/api/fleet/sightings") == 1


def test_owner_busy_or_no_owner_file_sends_the_heartbeat_only(tmp_path):
    fleet = FakeFleet()
    situation = _service(tmp_path, fleet, mode="owner_busy")
    situation.step()
    assert fleet.paths() == ["/api/fleet/ai/heartbeat"]
    assert fleet.calls[0][1]["owner_mode"] == "owner_busy"
    (tmp_path / "mode").unlink()
    assert situation.owner_mode() == "owner_busy"


def test_heartbeat_every_two_seconds_even_with_zero_facts(tmp_path):
    fleet, clock = FakeFleet(), Clock()
    situation = _service(tmp_path, fleet, clock=clock)
    for _ in range(5):
        situation.step()
        clock.now += 1.0
    assert fleet.paths().count("/api/fleet/ai/heartbeat") == 3
    assert "/api/fleet/ai/facts" not in fleet.paths()          # the stub analyzers say nothing


def test_queue_drops_oldest_past_256_and_sends_32_per_post_2_posts_a_second(tmp_path):
    fleet, clock = FakeFleet(), Clock()
    situation = _service(tmp_path, fleet, clock=clock, analyzers=lambda _s: [_fact(n) for n in range(300)])
    situation.step()
    posts = [body for path, body in fleet.calls if path == "/api/fleet/ai/facts"]
    assert len(posts) == 2 and all(len(p["facts"]) == 32 for p in posts)
    assert posts[0]["facts"][0]["value"] == {"n": 44}          # 300 - 256 oldest dropped
    assert len(situation.queue) == 256 - 64


def test_429_keeps_the_facts_and_a_down_fleet_does_not_stop_the_heartbeat(tmp_path):
    fleet, clock = FakeFleet(), Clock()
    situation = _service(tmp_path, fleet, clock=clock, analyzers=lambda _s: [_fact(1)])
    fleet.refuse_facts = 429
    situation.step()
    assert len(situation.queue) == 1

    class Down(FakeFleet):
        def call(self, path, body=None):
            self.calls.append((path, body))
            if path != "/api/fleet/ai/heartbeat":
                raise OSError("unreachable")
            return {}

    down = Down()
    situation.fleet = down
    clock.now += 3.0
    situation.step()
    assert down.paths()[0] == "/api/fleet/ai/heartbeat"


def test_input_and_facts_are_logged_as_jsonl_and_old_days_are_removed(tmp_path):
    fleet = FakeFleet()
    situation = _service(tmp_path, fleet, analyzers=lambda _s: [_fact(1)])
    logs = tmp_path / "state" / "logs"
    logs.mkdir(parents=True)
    (logs / "2000-01-01-input.jsonl").write_text("{}\n")
    situation.step()
    names = sorted(p.name for p in logs.iterdir())
    assert any(n.endswith("-input.jsonl") for n in names) and any(n.endswith("-facts.jsonl") for n in names)
    assert "2000-01-01-input.jsonl" not in names
    fact = json.loads(next(logs.glob("*-facts.jsonl")).read_text().splitlines()[0])
    assert fact["kind"] == "stalled"


def test_the_service_talks_to_a_real_fleet_as_ai_observer_and_moves_nothing(tmp_path):
    """Against an in-process Fleet over real HTTP: heartbeat lands, a fact is stored shadow, a stop is 403."""
    import threading
    import time as _time
    from hashlib import sha256

    import uvicorn
    from browser_harness import safe_listener
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint

    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-token")], [robot])
    app = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "f.sqlite3"),
                                                            robot_ids={"rosy_01"}),
                     start_task_dispatcher=False,
                     site_users={sha256(b"ai-token").hexdigest(): {"principal_id": "ai-pc", "role": "ai_observer"}})
    listener = safe_listener()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = _time.monotonic() + 20
        while not server.started and _time.monotonic() < deadline:
            _time.sleep(0.02)
        fleet = service.Fleet(f"http://127.0.0.1:{listener.getsockname()[1]}", "ai-token")
        fact = {**_fact(1), "observed_at": _time.time()}
        situation = _service(tmp_path, fleet, analyzers=lambda _s: [fact])
        situation.step()
        status = fleet.call("/api/fleet/ai")
        assert status["status"]["state"] == "present" and status["status"]["owner_mode"] == "shared"
        assert [f["stage"] for f in status["facts"]] == ["shadow"]
        try:
            fleet.call("/api/fleet/estop", {})
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("ai_observer reached the stop route")
        assert ("estop",) not in robot.calls
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
