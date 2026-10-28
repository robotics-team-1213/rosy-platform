"""The scripted SIM reach teacher against a fake Pilot HTTP server (host only, not ROS-SIM evidence).

The fake speaks the Pilot SIM routes the teacher uses (/pair /seat /target /state /camera
/recordings /goals) with stdlib http.server; goals settle instantly. It checks the task schema,
the greedy plan, that the reset is never recorded, the automatic success/failure label, the lease
renewal and that a failed goal is never retried.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(DEPLOY))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tasks = _load("sim_reach_task")
teacher = _load("sim_reach_teacher")
EXAMPLE = DEPLOY / "sim/reach_task.example.json"
ARM = ("joint1", "joint2", "joint3", "joint4", "joint5")
OFFERED = {"joint1": (-2.58, 2.58), "joint2": (-1.68, 1.18), "joint3": (-1.28, 1.68),
           "joint4": (-0.28, 2.28), "joint5": (-1.98, 1.98)}


def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class FakePilot:
    """Pilot SIM routes with instant goals. ``goals`` logs (joint, delta, recording_active)."""

    def __init__(self):
        self.positions = {**{name: 0.0 for name in ARM}, "gripper_joint_1": 0.5}
        self.sequence = 0
        self.goals, self.renewals, self.stops = [], 0, []
        self.recording = {"status": "idle", "frame_count": 0, "issues": []}
        self.fail_goal_at = None        # index into self.goals that ends UNKNOWN_HOLD
        self.move_scale = 1.0           # readback movement / commanded delta
        self.renew_fails = False
        self.lock = threading.Lock()
        self.receipts = {}

    def handle(self, method, path, body):
        prefix = "/api/v1/sim/omx"
        assert path.startswith(prefix), path
        path = path[len(prefix):].split("?")[0]
        with self.lock:
            return self._route(method, path, body)

    def _route(self, method, path, body):
        if path == "/pair":
            assert body == {"code": "ABCD-EFGH"}
            return 201, {"token": "tok"}
        if path == "/seat" and method == "POST":
            return 200, {"seat_id": "seat-1"}
        if path == "/seat/seat-1":
            if method == "DELETE":
                return 204, None
            if self.renew_fails:
                return 409, {"error": {"message": "seat missing or expired"}}
            self.renewals += 1
            return 200, {"seat_id": "seat-1"}
        if path == "/target":
            return 200, {"instance_id": "sim", "controls": {"items": [{
                "kind": "joint_jog", "max_step_rad": 0.05, "duration_s": 0.4,
                "joints": [{"name": n, "lower": lo, "upper": hi} for n, (lo, hi) in OFFERED.items()]}]}}
        if path == "/state":
            self.sequence += 1
            return 200, {"ready": True, "instance_id": "sim", "state_sequence": self.sequence,
                         "positions": dict(self.positions), "owner_state": "ready", "joint_age_ms": 5}
        if path == "/camera":
            return 200, {"fresh": True}
        if path == "/recordings" and method == "GET":
            if self.recording["status"] == "recording":
                self.recording["frame_count"] += 1
            return 200, dict(self.recording)
        if path == "/recordings" and method == "POST":
            assert body["seat_id"] == "seat-1" and "sim_joint_readback" in body["task"]
            self.recording = {"status": "recording", "episode_id": str(uuid4()), "task": body["task"],
                              "frame_count": 0, "issues": [], "task_outcome": "unspecified"}
            return 201, dict(self.recording)
        if path.endswith("/stop"):
            assert path == f"/recordings/{self.recording['episode_id']}/stop"
            self.stops.append(body["outcome"])
            self.recording.update(status="incomplete" if self.recording["issues"] else "complete",
                                  task_outcome=body["outcome"])
            return 200, dict(self.recording)
        if path == "/goals" and method == "POST":
            assert body["duration_s"] == 0.4 and abs(body["delta_rad"]) <= 0.05
            index = len(self.goals)
            self.goals.append((body["joint"], body["delta_rad"], self.recording["status"] == "recording"))
            if index == self.fail_goal_at:
                self.receipts[body["request_id"]] = "UNKNOWN_HOLD"
                if self.recording["status"] == "recording":
                    self.recording["issues"] = ["goal_terminal_unsuccessful"]
            else:
                self.receipts[body["request_id"]] = "SUCCEEDED"
                self.positions[body["joint"]] += body["delta_rad"] * self.move_scale
                if self.recording["status"] == "recording":
                    self.recording["frame_count"] += 4
            return 202, {"command_id": body["request_id"], "state": "LOCAL_ACCEPTED", "reason": ""}
        if path.startswith("/goals/"):
            state = self.receipts[path.split("/")[2]]
            return 200, {"command_id": path.split("/")[2], "state": state, "ros_goal_id": str(uuid4()),
                         "reason": "terminal_status_6_result_-5" if state != "SUCCEEDED" else ""}
        raise AssertionError((method, path))


@pytest.fixture
def pilot():
    fake = FakePilot()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _serve(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, payload = fake.handle(method, self.path, body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            data = b"" if payload is None else json.dumps(payload).encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def do_PUT(self):
            self._serve("PUT")

        def do_DELETE(self):
            self._serve("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/sim/omx"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()


def run_teacher(pilot, tmp_path, task=None, episodes=2, **options):
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task or example()), encoding="utf-8")
    out = tmp_path / "results.json"
    code = teacher.main(["--inside", "--task", str(path), "--episodes", str(episodes), "--out", str(out)],
                        base=pilot.base, code="ABCD-EFGH", renew_interval_s=0.02, poll_s=0.01, **options)
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_example_task_is_valid_inside_the_cell_profile_and_offered_ranges():
    pytest.importorskip("yaml")
    task = tasks.load_task(EXAMPLE, cell_limits=tasks.load_cell_limits())
    assert task["joint_names"][-1] == "gripper_joint_1" and task["tolerance_rad"]["gripper_joint_1"] is None
    assert tasks.validate_task(task, OFFERED) == task
    assert tasks.load_cell_limits()["joint4"] == pytest.approx((-0.28, 2.28))


@pytest.mark.parametrize("edit, message", [
    (lambda t: t.pop("max_steps"), "missing ['max_steps']"),
    (lambda t: t.update(extra=1), "extra ['extra']"),
    (lambda t: t.update(schema="v0"), "schema must be"),
    (lambda t: t.update(jog_step_rad=0.06), "jog_step_rad"),
    (lambda t: t.update(jog_duration_s=[0.4, 0.5]), "jog_duration_s must be one number"),
    (lambda t: t.update(jog_duration_s=1.5), "jog_duration_s"),
    (lambda t: t.update(max_steps=0), "max_steps"),
    (lambda t: t["target_positions"].update(gripper_joint_1=0.5), "unchecked joint has null target"),
    (lambda t: t["start_sampling"]["ranges"].update(joint2=[0.1, -0.1]), "joint2: range"),
    (lambda t: t["start_sampling"]["ranges"].update(joint4=[-0.5, 0.5]), "joint4: range [-0.5, 0.5] outside"),
    (lambda t: t["target_positions"].update(joint2=1.5), "joint2: target 1.5 outside"),
    (lambda t: t["tolerance_rad"].update(joint1=0.0), "joint1: tolerance_rad"),
    (lambda t: t["start_sampling"].update(seed=-1), "start_sampling must be"),
    (lambda t: t["target_positions"].pop("joint5"), "target_positions must name"),
])
def test_task_validator_refuses_with_reasons(edit, message):
    task = example()
    edit(task)
    with pytest.raises(ValueError) as error:
        tasks.validate_task(task, OFFERED)
    assert message in str(error.value)


def test_sampling_is_seeded_and_greedy_plan_moves_the_worst_joint_by_at_most_one_step():
    task = example()
    start = tasks.sample_start(task, 1000)
    assert start == tasks.sample_start(task, 1000) != tasks.sample_start(task, 1001)
    assert set(start) == set(ARM)
    assert all(task["start_sampling"]["ranges"][n][0] <= v <= task["start_sampling"]["ranges"][n][1]
               for n, v in start.items())
    positions = dict(task["target_positions"], gripper_joint_1=0.7)
    assert tasks.next_jog(task, positions) is None and tasks.within_tolerance(task, positions)
    positions.update(joint1=0.25 - 0.3, joint3=0.15 + 0.02)
    assert tasks.next_jog(task, positions) == ("joint1", 0.05)
    positions.update(joint1=0.25 - 0.013)
    assert tasks.next_jog(task, positions) == ("joint3", -0.02)
    positions.update(joint3=0.15 + 0.009)
    assert tasks.next_jog(task, positions) == ("joint1", 0.013)
    positions.update(joint1=0.25)
    assert tasks.next_jog(task, positions) is None


def test_teacher_resets_unrecorded_then_records_greedy_jogs_and_labels_success(pilot, tmp_path):
    code, results = run_teacher(pilot, tmp_path)
    assert code == 0, results["aborted"]
    assert results["schema"] == teacher.RESULTS_SCHEMA and results["judge"] == "sim_joint_readback"
    assert results["task_sha256"] == tasks.task_sha256(example())
    assert [e["seed"] for e in results["episodes"]] == [1000, 1001] and pilot.stops == ["success"] * 2
    for record in results["episodes"]:
        assert record["success"] and record["reason"] == "" and record["recording"]["status"] == "complete"
        assert record["recording"]["task_outcome"] == "success" and record["recording"]["frame_count"] >= 10
        assert all(abs(v) <= 0.01 for v in record["errors_rad"].values())
        assert record["start_target"] == tasks.sample_start(example(), record["seed"])
    # Reset goals precede each recording and are never recorded; every recorded goal is greedy-bounded.
    flags = [recorded for _, _, recorded in pilot.goals]
    assert flags[0] is False and flags.count(True) == sum(e["steps"] for e in results["episodes"])
    assert all(abs(delta) <= 0.05 for _, delta, _ in pilot.goals)
    assert pilot.renewals > 0


def test_max_steps_without_reaching_is_labelled_failure_from_the_readback(pilot, tmp_path):
    task = example()
    task["max_steps"] = 2
    code, results = run_teacher(pilot, tmp_path, task, episodes=1)
    record = results["episodes"][0]
    assert code == 0 and pilot.stops == ["failure"] and record["steps"] == 2
    assert record["success"] is False and record["reason"] == "max_steps_without_reaching_tolerance"
    assert record["recording"]["task_outcome"] == "failure"


def test_goal_failure_mid_recording_ends_the_run_without_resend(pilot, tmp_path):
    # Replay the reset plan for seed 1000 offline to find where the recording starts.
    reset_goals = 0
    start = tasks.sample_start(example(), 1000)
    positions = {name: 0.0 for name in ARM}
    while True:
        pending = {n: v - positions[n] for n, v in start.items() if abs(v - positions[n]) > 0.005}
        if not pending:
            break
        for name, error in pending.items():
            delta = round(min(abs(error), 0.05) * (1 if error > 0 else -1), 6)
            positions[name] += delta
            reset_goals += 1
    pilot.fail_goal_at = reset_goals + 1          # the second recorded jog
    code, results = run_teacher(pilot, tmp_path, episodes=3)
    assert code == 2 and len(results["episodes"]) == 1
    record = results["episodes"][0]
    assert record["success"] is False and record["reason"].startswith("goal_UNKNOWN_HOLD")
    assert pilot.stops == ["failure"] and record["recording"]["status"] == "incomplete"
    assert len(pilot.goals) == reset_goals + 2    # nothing sent after the failed goal
    assert results["aborted"].startswith("episode 0: goal_UNKNOWN_HOLD")


def test_readback_that_does_not_follow_the_goal_fails_the_reset(pilot, tmp_path):
    pilot.move_scale = 0.5
    code, results = run_teacher(pilot, tmp_path, episodes=1)
    assert code == 2 and "reset jog failed: readback_mismatch" in results["aborted"]
    assert pilot.stops == [] and pilot.recording["status"] == "idle"


def test_lost_lease_ends_the_run_before_any_outcome(pilot, tmp_path):
    pilot.renew_fails = True
    code, results = run_teacher(pilot, tmp_path, episodes=2)
    assert code == 2 and "seat" in results["aborted"]
    assert "success" not in pilot.stops
    assert all(record["success"] is False for record in results["episodes"])


def test_teacher_refuses_a_task_outside_the_offered_ranges(pilot, tmp_path):
    task = copy.deepcopy(example())
    task["target_positions"]["joint4"] = -0.29     # inside the cell profile, outside the inset
    with pytest.raises(ValueError, match="joint4: target -0.29 outside"):
        run_teacher(pilot, tmp_path, task, episodes=1)
    assert pilot.goals == []
