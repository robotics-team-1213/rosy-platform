"""Timing and handoff behavior with no model, camera, or actuator."""
from pathlib import Path
import json
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from cell_policy_timing import action_window, run_timed, step_count  # noqa: E402
from chunk_policy_playback import Handoff, Playback  # noqa: E402


def test_action_window_drops_elapsed_model_steps_and_rejects_late_observation():
    chunk = np.arange(16)
    rows, dropped = action_window(chunk, observed=1.0, start=1.41, fps=15, steps=8, max_age=0.6)
    assert dropped == 6
    assert rows.tolist() == list(range(6, 14))
    with pytest.raises(ValueError, match="stale"):
        action_window(chunk, observed=1.0, start=1.61, fps=15, steps=8, max_age=0.6)


def test_runner_drops_expired_frames_and_refuses_unsafe_skip():
    spec = dict(start=1.0, observed=0.8, max_age=0.6, max_step=0.5)
    play = Playback(spec, 10)
    target = [0] * 6
    queue = [[0.1] * 6, [0.2] * 6, [0.3] * 6]
    assert play.ready(queue, target, 1.15)
    assert queue[0] == [0.2] * 6 and play.dropped == 1
    with pytest.raises(ValueError, match="step"):
        play.ready([[1.0] * 6], target, 1.15)


@pytest.mark.parametrize("stale", [False, True])
def test_runner_tick_uses_expiry_and_latches_stale_hold(stale):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES

    commands, reports = [], []
    state = dict.fromkeys(NAMES, 0.0)

    def send(target):
        commands.append(target)
        state.update(target)
        return target

    library = {"chunks": {"policy": [[0.05] * 6, [0.1] * 6, [0.15] * 6]}, "gripper_closed": 0,
               "policy_playback": dict(start=1.0, observed=0 if stale else 0.8, max_age=0.6, max_step=0.16)}
    robot = SimpleNamespace(send_action=send, get_observation=lambda: state)
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.04)
    runner.target = runner.present()
    runner.command("run policy")
    runner.tick()
    assert runner.human_hold_latched is stale
    assert commands[-1][NAMES[0]] == (0 if stale else 0.1)
    if stale:
        assert "stale" in reports[0]["policy_stop"]
    else:
        assert runner.policy_playback.dropped == 1


def test_handoff_requires_consecutive_measured_hold_and_pose():
    detector = Handoff(dict(hold_frames=2, min_z=0.10, x=0.2, y=0.1, yaw_deg=0,
                            xy_tol=0.01, angle_tol_deg=5, close_target=51, empty_stop=49), kin=None)
    good = SimpleNamespace(x=0.2, y=0.1, z=0.11, tool_down_error_rad=0, yaw=0)
    low = SimpleNamespace(**{**vars(good), "z": 0.09})
    target, grip = [0] * 5 + [50], [0] * 5 + [53]
    assert not detector.sample([0] * 5 + [49], target, low)["triggered"]
    for _ in range(3):
        assert not detector.sample(grip, target, low)["triggered"]
    assert not detector.sample([0] * 5 + [49], target, good)["triggered"]
    assert not detector.sample(grip, target, good)["triggered"]
    assert not detector.sample(grip, target, good)["triggered"]
    assert detector.sample(grip, target, good)["triggered"]


def test_sim_action_steps_default_to_eight_and_respect_checkpoint_bound():
    shadow = SimpleNamespace(sim_rule={}, chunk_size=16, n_action_steps=4)
    assert step_count(shadow, None) == 8
    assert step_count(shadow, 18) == 16


@pytest.mark.parametrize("late", [False, True])
def test_precomputes_during_current_playback_or_stops_when_late(tmp_path, late):
    started, inferred, release = threading.Event(), threading.Event(), threading.Event()
    state, calls, chunks, rows = [0] * 6, [], [], []

    class Runner:
        def act(self, command):
            calls.append(command)
            if command.startswith("load "):
                self.spec = json.loads(Path(command[5:]).read_text())["policy_playback"]
            if command == "run policy" and not started.is_set():
                started.set()
                assert inferred.wait(1)
            return {"ok": True, "state": state}

        def policy_state(self):
            if started.is_set():
                return {"policy_start": self.spec["start"], "state": state}
            return None

    def infer(_state, _images):
        chunks.append(started.is_set())
        if started.is_set():
            inferred.set()
            if late:
                release.wait(2)
        return np.zeros((16, 6)), {}

    shadow = SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16)
    try:
        result = run_timed(Runner(), shadow, {"fps": 30, "chunks": {}, "gripper_closed": 0}, tmp_path,
                           infer=infer, shape=lambda frames, *_: frames.tolist(), max_step=0.1, n_action=8,
                           max_obs_age_s=1.0, max_chunks=2, dry_run=False, log=rows.append)
    finally:
        release.set()
    assert chunks == [False, True]
    if late:
        assert result["result"] == "refused" and "deadline" in result["reason"]
        assert calls.count("run policy") == 1 and calls[-1] == "human-hold"
    else:
        assert result["result"] == "chunks_done" and calls.count("run policy") == 2


def test_dry_run_reports_command_timing_and_never_sends_motion(tmp_path):
    class Runner:
        def act(self, command):
            assert command == "state"
            return {"ok": True, "state": [0] * 6}

    rows = []
    shadow = SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16)
    result = run_timed(Runner(), shadow, {"fps": 30, "chunks": {}, "gripper_closed": 0}, tmp_path,
                       infer=lambda *_: (np.zeros((16, 6)), {}),
                       shape=lambda actions, *_: actions.tolist(), max_step=0.1, n_action=8,
                       max_obs_age_s=0.6, max_chunks=1, dry_run=True, log=rows.append)
    assert result["result"] == "dry_run"
    assert rows[0]["action_steps"] == 8
    assert rows[0]["observation_age_s"] >= rows[0]["inference_s"]
    assert len(rows[0]["command_gaps_s"]) + rows[0]["dropped_runner_frames"] == 7


def test_hybrid_holds_at_act_budget_without_a_verified_handoff(tmp_path):
    calls, rows = [], []

    def act(command):
        calls.append(command)
        return {"ok": True, "holding": True, "state": [0] * 6, "handoff": {"triggered": False}}

    cell = SimpleNamespace(act=act)
    shadow = SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16)
    handoff = SimpleNamespace(spec={})
    result = run_timed(cell, shadow, {"fps": 30, "chunks": {}}, tmp_path,
                       infer=lambda *_: (np.zeros((16, 6)), {}),
                       shape=lambda actions, *_: actions.tolist(), max_step=0.1, n_action=8,
                       max_obs_age_s=0.6, max_chunks=1, dry_run=False, log=rows.append, handoff=handoff,
                       clock=lambda: 1.0)
    assert result == {"result": "refused", "at": 1, "reason": "ACT ended before a verified handoff"}
    assert calls[:2] == ["state", "state"]
    assert calls[2].startswith("load ")
    assert calls[3:] == ["run policy", "human-hold"]
    assert rows[-2]["policy_stop"] == result["reason"]
    assert rows[-1]["command"] == "human-hold" and rows[-1]["ok"] is True


def test_taught_fallback_runs_the_existing_folded_sequence(tmp_path):
    from cell_policy_handoff import FOLDED, run_taught

    path = tmp_path / "taught.json"
    path.write_text(json.dumps({"gripper_closed": 48}))
    calls = []

    def act(command):
        calls.append(command)
        return {"ok": True, "holding": "run release_place" not in calls, "state": [0] * 5 + [49]}

    cell = SimpleNamespace(act=act)
    assert run_taught(cell, path, dry_run=True, authorize=None, log=lambda _: None)["result"] == "dry_run"
    assert not calls
    assert run_taught(cell, path, dry_run=False, authorize=None, log=lambda _: None)["result"] == "placed"
    assert calls == [f"load {path}", *FOLDED]


def test_hybrid_lifts_then_runs_only_the_taught_carry(tmp_path, monkeypatch):
    import grasp_planner
    from cell_policy_handoff import CellHandoff, FOLDED, RETURN_HELD

    pose = SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0)
    state, target = [0] * 5 + [53], [0] * 5 + [50]
    calls, lifts = [], []

    class Planner:
        kin = SimpleNamespace(fk=lambda _: pose)

        def __init__(self, _plan):
            pass

        def line(self, start, end, _speed, _yaw, grip, _q5):
            lifts.append((start, end))
            return [target, [0, 0.01, 0, 0, 0, grip]], 0

    monkeypatch.setattr(grasp_planner, "Planner", Planner)
    library = {"fps": 30, "gripper_closed": 49, "chunks": {},
               "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}}}
    path = tmp_path / "taught.json"
    path.write_text(json.dumps(library))
    config = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}

    def act(command):
        calls.append(command)
        released = command in RETURN_HELD[2:] and command != "park" or calls.count("park") > 1
        return {"ok": True, "holding": not released, "settled": True,
                "state": [0] * 5 + [49] if released else state, "target": target}

    handoff = CellHandoff(config, "belt", path, library, 51, tmp_path)
    assert handoff.spec["hold_frames"] == 8
    assert handoff.spec["min_z"] == pytest.approx(0.115)
    assert handoff.spec["xy_tol"] == pytest.approx(0.012)
    assert handoff.spec["angle_tol_deg"] == 7
    assert handoff.rise == pytest.approx(0.010)
    result = handoff.carry(SimpleNamespace(act=act), {"handoff": {"holding_frames": 8, "jaw": 53}}, None, lambda _: None)
    assert result["result"] == "placed"
    assert lifts[0][0] == (pose.x, pose.y, pose.z) and lifts[0][1] == pytest.approx((pose.x, pose.y, pose.z + handoff.rise))
    assert calls[2:] == ["run lift_pick_policy_handoff", f"load {path}", *FOLDED[-len(RETURN_HELD) - 1:]]


def test_runner_handoff_discards_the_rest_of_the_active_chunk():
    from chunk_policy_playback import finish_tick

    facts = {"holding": True, "holding_frames": 3, "triggered": True}
    play = Playback(dict(start=1.0, observed=0.8, max_age=0.6, max_step=0.1), 30)
    play.handoff = SimpleNamespace(spec={}, sample=lambda *_args, **_kwargs: facts)
    reports = []
    runner = SimpleNamespace(queue=[[10] * 6], chunk="policy", policy_playback=play,
                             holding=False, target=[0] * 6, report=lambda **k: reports.append(k))
    finish_tick(runner, play, [0] * 6, 0.0, 0.1)
    assert runner.queue == [] and runner.chunk is None
    assert reports[0]["handoff"] == facts


@pytest.mark.parametrize("lagged", [True, False])
def test_runner_jaw_gate_holds_when_lift_rotates_before_measured_clearance(tmp_path, lagged):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    now = [1.0]

    def send(target):
        commands.append(dict(target))
        if not lagged:
            obs.update(target)
        return target

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
        "policy_playback": {
            "start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16,
            "jaw_gate": {
                "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
                "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
                "tcp_x_m": 0.0741,
            },
        },
    }
    lib_path = tmp_path / "jaw-gate.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    robot = SimpleNamespace(send_action=send, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.tick()
    now[0] = 1.04
    runner.tick()
    if lagged:
        assert runner.human_hold_latched is True
        assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
        assert len(commands) == 2 and commands[-1]["wrist_roll.pos"] == -14.0
    else:
        assert runner.human_hold_latched is False
        assert commands[-1]["wrist_roll.pos"] == pytest.approx(-13.85)
        assert reports[-1]["command"] == "run policy" and reports[-1]["ok"] is True


@pytest.mark.parametrize("lagged", [True, False])
def test_legacy_runner_jaw_gate_holds_when_chunk_starts_above_rim_descends_and_rotates(tmp_path, lagged):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p1))

    def send(target):
        commands.append(dict(target))
        if not (lagged and len(commands) >= 2):
            obs.update(target)
        return target

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p0, p1, p2]},
        "jaw_gate": {
            "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
            "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
            "tcp_x_m": 0.0741,
        },
    }
    lib_path = tmp_path / "legacy-jaw-gate.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    robot = SimpleNamespace(send_action=send, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=reports.append)
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.tick()
    runner.tick()
    runner.tick()
    if lagged:
        assert runner.human_hold_latched is True
        assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
        assert commands[-1]["wrist_roll.pos"] == -14.0
    else:
        assert runner.human_hold_latched is False
        assert commands[-1]["wrist_roll.pos"] == pytest.approx(-13.85)


def test_runner_jaw_gate_latches_hold_before_status_write_failure(tmp_path, monkeypatch):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    class _Done(Exception):
        pass

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    now, ticks, live_errors, trace_errors = [1.0], 0, 0, 0
    runner = None

    def fail_on_stop(row):
        reports.append(row)
        if "policy_stop" in row or row.get("command") == "human-hold":
            raise OSError("disk full")

    def fail_live(_row):
        nonlocal live_errors
        if runner.human_hold_latched:
            live_errors += 1
            raise OSError("disk full")

    class _Trace:
        def __call__(self, _row):
            nonlocal trace_errors
            if runner.human_hold_latched:
                trace_errors += 1
                raise OSError("disk full")

        def flush(self):
            nonlocal trace_errors
            if runner.human_hold_latched:
                trace_errors += 1
                raise OSError("disk full")

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
        "policy_playback": {
            "start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16,
            "jaw_gate": {
                "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
                "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
                "tcp_x_m": 0.0741,
            },
        },
    }
    lib_path = tmp_path / "fail-status.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    pending_batches = [[f"load {lib_path}", "run policy"]]

    def step(_dt):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            now[0] = 1.04
        elif ticks >= 3 and runner.human_hold_latched:
            raise _Done()

    robot = SimpleNamespace(send_action=lambda t: commands.append(dict(t)) or t, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=fail_on_stop, live=fail_live, clock=lambda: now[0], sleep=step)
    runner.trace = _Trace()
    with pytest.raises(_Done):
        runner.run(lambda: pending_batches.pop(0) if pending_batches else [])
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert live_errors >= 1 and trace_errors >= 1
    assert runner.queue == [] and runner.target[:5] == pytest.approx(p0[:5])
    assert len(commands) == 3 and all(c["wrist_roll.pos"] == -14.0 for c in commands)
    assert ci.gate_allows(runner, []) is False
    signals, closed, slept = [], [], []
    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)

    def release_sleep(_dt):
        slept.append(_dt)
        assert closed == []
        if len(slept) == 2:
            signals.append(ci.OPERATOR_RELEASE)

    runner.hold_file = tmp_path / "hold.json"
    ci.gated_close(runner, signals, runner.hold_file, lambda: closed.append("off"), sleep=release_sleep)
    assert len(slept) == 2 and closed == ["off"]


def test_runner_jaw_gate_refuses_splice_and_checks_adaptive_speed_blend(tmp_path):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
        "jaw_gate": {
            "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
            "yaw_deg": 115.08, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
            "tcp_x_m": 0.0741,
        },
    }
    lib_path = tmp_path / "splice-adapt.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    robot = SimpleNamespace(send_action=lambda t: commands.append(dict(t)) or t, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=reports.append, params={"runner.speed_adapt": 1})
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}")
    for bypass_cmd, word in (("splice policy", "splice"), ("goto policy", "goto"), ("chain run policy", "chain")):
        runner.command(bypass_cmd)
        assert reports[-1]["ok"] is False and word in reports[-1]["error"]
        assert runner.queue == [] and runner.chunk is None
    assert runner.command("run policy")
    runner.command("splice reach")
    assert reports[-1]["ok"] is False and "splice" in reports[-1]["error"]
    assert runner.chunk == "policy" and runner.jaw_gate is not None

    runner.speed = 0.5
    runner.speed_out, runner.speed_base, runner.speed_phase, runner.speed_queue = list(p0), list(p0), 0.8, runner.queue
    runner.tick()
    assert runner.human_hold_latched is True
    assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
    assert commands[-1]["wrist_roll.pos"] == -14.0


def test_runner_jaw_gate_checks_measured_pose_on_pacing_ticks(tmp_path):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
        "jaw_gate": {
            "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
            "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
            "tcp_x_m": 0.0741,
        },
    }
    lib_path = tmp_path / "pacing-jaw.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    robot = SimpleNamespace(send_action=lambda t: commands.append(dict(t)) or t, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=reports.append)
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.lag = 3.0
    obs["wrist_roll.pos"] = -12.0
    runner.tick()
    assert runner.paced_ticks == 1 and runner.paced == 0 and runner.human_hold_latched is True and runner.queue == []
    assert any("measured jaw yaw" in r.get("policy_stop", "") for r in reports)
    assert commands[-1]["shoulder_lift.pos"] == -10.0 and commands[-1]["wrist_roll.pos"] == -12.0


@pytest.mark.parametrize("timed", [True, False])
def test_runner_jaw_gate_holds_on_encoder_read_failure(tmp_path, timed):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    now, fail_read = [1.0], [False]
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
        "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
    }
    if timed:
        library["policy_playback"] = {
            "start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec,
        }
    else:
        library["jaw_gate"] = gate_spec
    lib_path = tmp_path / ("timed-bus-err.json" if timed else "legacy-bus-err.json")
    lib_path.write_text(json.dumps(library), encoding="utf-8")

    def read_obs():
        if fail_read[0]:
            raise OSError("bus timeout")
        return dict(obs)

    robot = SimpleNamespace(send_action=lambda t: commands.append(dict(t)) or t, get_observation=read_obs)
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.tick()
    fail_read[0] = True
    now[0] = 1.04
    runner.tick()
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert runner.queue == []
    assert any("bus timeout" in r.get("policy_stop", "") for r in reports)
    assert commands[-1]["wrist_roll.pos"] == -14.0
    assert ci.gate_allows(runner, []) is False


def test_finish_tick_grip_slip_latches_hold_before_status_write_failure():
    import chunk_runner_interrupt as ci
    from chunk_policy_playback import finish_tick
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    reports = []
    obs = dict(zip(NAMES, p0))

    def fail_on_stop(row):
        reports.append(row)
        if "policy_stop" in row or row.get("command") == "human-hold":
            raise OSError("disk full")

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
        "chunks": {"home": [p0], "policy": [p0]},
    }
    robot = SimpleNamespace(send_action=lambda t: t, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=fail_on_stop)
    runner.target = list(p0)
    runner.holding = True
    runner.chunk = "policy"
    runner.queue = [list(p0)]
    runner.jaw_gate = object()
    facts = {"holding": False, "measured_hold": False, "triggered": False}
    play = Playback(dict(start=1.0, observed=0.8, max_age=0.6, max_step=0.1), 30)
    play.handoff = SimpleNamespace(spec={}, sample=lambda *_args, **_kwargs: facts)
    runner.policy_playback = play
    finish_tick(runner, play, p0, 0.0, 3.0)
    assert runner.human_hold_latched is True
    assert runner.queue == [] and runner.chunk is None
    assert runner.policy_playback is None and runner.jaw_gate is None
    assert reports[0]["handoff"] == facts and reports[0]["human_hold_latched"] is True
    assert ci.gate_allows(runner, []) is False


def test_live_jaw_hold_accepts_operator_release_signal(tmp_path, monkeypatch):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p1 = [38.8, -10.15, 2.0, 55.0, -14.0, 49.0]
    p2 = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    commands, reports = [], []
    obs = dict(zip(NAMES, p0))
    now, ticks, hold_ticks = [1.0], 0, 0
    runner = None

    def fail_on_hold(row):
        reports.append(row)
        if "policy_stop" in row or row.get("command") == "human-hold":
            raise OSError("disk full")

    def fail_live(_row):
        if runner.human_hold_latched:
            raise OSError("disk full")

    class _Trace:
        def __call__(self, _row):
            if runner.human_hold_latched:
                raise OSError("disk full")

        def flush(self):
            if runner.human_hold_latched:
                raise OSError("disk full")

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "reach": [p0, p1, p2], "policy": [p1, p2]},
        "policy_playback": {
            "start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16,
            "jaw_gate": {
                "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
                "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
                "tcp_x_m": 0.0741,
            },
        },
    }
    lib_path = tmp_path / "live-release.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    pending_batches = [[f"load {lib_path}", "run policy"]]

    def step(_dt):
        nonlocal ticks, hold_ticks
        ticks += 1
        assert ticks <= 20, "runner did not exit on operator release"
        if ticks == 2:
            now[0] = 1.04
            runner.signals.append(ci.OPERATOR_RELEASE)
        elif runner.human_hold_latched:
            hold_ticks += 1
            if hold_ticks == 2:
                runner.signals.append(ci.OPERATOR_RELEASE)

    robot = SimpleNamespace(send_action=lambda t: commands.append(dict(t)) or t, get_observation=lambda: dict(obs))
    runner = Runner(robot, library, fps=30, status=fail_on_hold, live=fail_live, clock=lambda: now[0], sleep=step)
    runner.signals, runner.hold_file, runner.trace = [], tmp_path / "hold.json", _Trace()
    runner.run(lambda: pending_batches.pop(0) if pending_batches else [])
    assert runner.human_hold_latched is True and hold_ticks == 2
    assert runner._off_approved == "operator release (SIGUSR2)"
    assert any(r.get("command") == "human-hold" and r.get("released") is True for r in reports)
    assert ci.gate_allows(runner, runner.signals) is True
    closed = []
    ci.gated_close(runner, runner.signals, runner.hold_file, lambda: closed.append("off"),
                   sleep=lambda _dt: pytest.fail("should close immediately after live release"))
    assert closed == ["off"]


def _make_guard_bus(init_pose):
    from guarded_device import NAMES as DEV_NAMES, normalized

    def to_tick(name, val):
        return round((val + (0.0 if name == "gripper" else 100.0)) / (100.0 if name == "gripper" else 200.0) * 4095)

    class GuardBus:
        def __init__(self):
            self.motors = {n: SimpleNamespace(id=i + 11) for i, n in enumerate(DEV_NAMES)}
            self.calibration = {n: SimpleNamespace(range_min=0, range_max=4095, drive_mode=0,
                                                  homing_offset=0) for n in DEV_NAMES}
            self.model_ctrl_table = {}
            self.hw_status = {}
            self.hw_read_seen = []
            self.pwms, self.temps = {}, {}
            self.raw = {n: to_tick(n, v) for n, v in zip(DEV_NAMES, init_pose)}
            self.goals = dict(self.raw)
            self.torque = dict.fromkeys(DEV_NAMES, 0)
            self.events = []

        def enable_torque(self, motors=None):
            for n in (motors or DEV_NAMES):
                self.torque[n] = 1
            self.events.append(("on",))

        def disable_torque(self, motors=None, **kwargs):
            for n in ([motors] if isinstance(motors, str) else (motors or DEV_NAMES)):
                self.torque[n] = 0
            self.events.append(("off", motors))

        def read(self, reg, motor, **kwargs):
            if reg == "Torque_Enable":
                return self.torque[motor]
            if reg == "PWM_Limit":
                return 330
            if reg == "Hardware_Error_Status":
                self.hw_read_seen.append(motor)
                val = self.hw_status.get(motor, 0)
                if isinstance(val, BaseException):
                    raise val
                return val
            if reg == "Present_PWM":
                return self.pwms.get(motor, 0)
            if reg == "Present_Temperature":
                return self.temps.get(motor, 30)
            if reg == "Temperature_Limit":
                return 70
            if reg == "Min_Voltage_Limit":
                return 95
            if reg == "Max_Voltage_Limit":
                return 160
            if reg == "Present_Input_Voltage":
                return 120
            raise AssertionError(reg)

        def sync_read(self, reg, motors=None, *, normalize=True, num_retry=0):
            names = motors or DEV_NAMES
            if reg == "Torque_Enable":
                return {n: self.torque[n] for n in names}
            if reg == "PWM_Limit":
                return dict.fromkeys(names, 330)
            if reg == "Present_PWM":
                return {n: self.pwms.get(n, 0) for n in names}
            if reg == "Present_Temperature":
                return {n: self.temps.get(n, 30) for n in names}
            if reg == "Present_Input_Voltage":
                return dict.fromkeys(names, 120)
            if reg in ("Present_Current", "Hardware_Error_Status"):
                return dict.fromkeys(names, 0)
            src = self.raw if reg == "Present_Position" else self.goals
            vals = {n: src[n] for n in names}
            return normalized(self, vals) if normalize else vals

        def _normalize(self, by_id):
            by_name = {n: by_id[m.id] for n, m in self.motors.items() if m.id in by_id}
            return {self.motors[n].id: v / 4095 * (100 if n == "gripper" else 200) - (0 if n == "gripper" else 100)
                    for n, v in by_name.items()}

        def _unnormalize(self, by_id):
            return {m.id: round((by_id[m.id] + (0 if n == "gripper" else 100)) / (100 if n == "gripper" else 200) * 4095)
                    for n, m in self.motors.items() if m.id in by_id}

        def sync_write(self, reg, values, *, normalize=True):
            assert reg == "Goal_Position" and not normalize
            self.events.append(("goal", dict(values)))
            self.goals = dict(values)

    return GuardBus()


def test_runner_jaw_gate_rejects_guard_retimed_goal_before_sync_write(tmp_path):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import NAMES as DEV_NAMES, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    p_enter = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [bus._normalize({bus.motors[n].id: bus.raw[n]})[bus.motors[n].id] for n in DEV_NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"], motion.velocity["wrist_roll"] = 112.0, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p_above], "policy": [p_enter]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / "guard-retime.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    now[0] += 1 / 30
    runner.tick()
    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert runner.queue == [] and runner.chunk is None
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
    assert (runner.policy_playback.jaw_gate if runner.policy_playback else None) is None
    check_gate = start_jaw_gate(runner, gate_spec)
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 2
    assert all(g["shoulder_lift"] == bus.raw["shoulder_lift"] for g in post_seed_goals)
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])
    assert ci.gate_allows(runner, []) is False


def test_runner_jaw_gate_holds_on_post_completion_idle_coasting(tmp_path):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"], motion.velocity["wrist_roll"] = 36.0, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / "idle-coast.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    for _ in range(3):
        now[0] += 1 / 30
        runner.tick()
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    assert any(r.get("command") == "run policy" and r.get("ok") is True for r in reports)
    assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
    check_gate = start_jaw_gate(runner, gate_spec)
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 3
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])
    assert ci.gate_allows(runner, []) is False


@pytest.mark.parametrize("successor", ["ungated_legacy", "ungated_timed", "different_tcp_timed", "equivalent_timed"])
def test_runner_post_completion_policy_successor_blocks_coasting(tmp_path, successor):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"], motion.velocity["wrist_roll"] = 36.0, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec_no_tcp = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False,
    }
    base_lib = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start]},
    }
    library = {
        **base_lib,
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec_no_tcp},
    }
    lib_path = tmp_path / f"succ-{successor}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    now[0] += 1 / 30
    runner.tick()
    assert runner.chunk is None and runner._trailing_jaw_gate is not None

    if successor == "ungated_legacy":
        runner.library = base_lib
    elif successor == "ungated_timed":
        runner.library = {
            **base_lib,
            "policy_playback": {"start": now[0] + 0.01, "observed": now[0], "max_age": 0.6, "max_step": 0.16},
        }
    elif successor == "different_tcp_timed":
        runner.library = {
            **base_lib,
            "tcp_x_m": 0.091,
            "policy_playback": {
                "start": now[0] + 0.01, "observed": now[0], "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec_no_tcp,
            },
        }
    else:
        runner.library = {
            **base_lib,
            "policy_playback": {
                "start": now[0] + 0.01, "observed": now[0], "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec_no_tcp,
            },
        }
    assert runner.command("run policy")
    for _ in range(2):
        now[0] += 1 / 30
        runner.tick()
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    check_gate = start_jaw_gate(SimpleNamespace(library=None), {**gate_spec_no_tcp, "tcp_x_m": 0.0741})
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 3
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])
    if successor == "equivalent_timed":
        assert runner.human_hold_latched is True and ci.gate_allows(runner, []) is False
    else:
        assert all(g["shoulder_lift"] <= 1841 for g in post_seed_goals)


def test_runner_jaw_gate_survives_thermal_fault_without_coasting(tmp_path):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"], motion.velocity["wrist_roll"] = 36.0, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / "thermal-fault.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.ticks = 29
    runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [70, 35, 35, 35, 35, 35]}
    now[0] += 1 / 30
    runner.tick()
    assert runner.fault == "temperature 70 C" and runner.chunk is None
    assert runner.policy_playback is None and runner._trailing_jaw_gate is not None
    assert motion.velocity["shoulder_lift"] == 0.0
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    check_gate = start_jaw_gate(runner, gate_spec)
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 2 and all(g["shoulder_lift"] <= 1841 for g in post_seed_goals)
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])


@pytest.mark.parametrize("mode", ["thermal", "contact", "push_at_rest"])
def test_runner_gated_fault_and_contact_latch_hold_on_report_write_failure(tmp_path, monkeypatch, mode):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    import joint_push
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"], motion.velocity["wrist_roll"] = 36.0, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / f"fail-halt-{mode}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")

    def fail_on_halt(row):
        reports.append(row)
        if row.get("ok") is False or row.get("command") == "human-hold":
            raise OSError("disk full")

    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=fail_on_halt, clock=lambda: now[0])
    runner.signals = []
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    if mode == "thermal":
        runner.ticks = 29
        runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [70, 35, 35, 35, 35, 35]}
    elif mode == "contact":
        runner.strained = lambda *_a: ("wrist_roll", 3.0, 290, 300)
    else:
        runner.ticks = 28
        runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [35] * 6}
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
        monkeypatch.setattr(joint_push, "pushing", lambda *_a, **_kw: ("shoulder_lift", "pushing down"))

    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
    assert runner.human_hold_latched is True and runner.chunk is None
    assert runner.policy_playback is None and runner.jaw_gate is None and runner._trailing_jaw_gate is None
    assert motion.velocity["shoulder_lift"] <= 0.0
    assert ci.gate_allows(runner, []) is False
    monkeypatch.setattr(joint_push, "pushing", lambda *_a, **_kw: None)
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
    assert runner.torque_hold_commanded is True
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    check_gate = start_jaw_gate(runner, gate_spec)
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 2 and all(g["shoulder_lift"] <= 1841 for g in post_seed_goals)
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])


def test_runner_post_completion_push_at_rest_stops_retimer_momentum(tmp_path, monkeypatch):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    import joint_push
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_in_zone = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_in_zone)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.velocity["shoulder_lift"] = 36.0
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 95.1, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / "push-rest.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    now[0] += 1 / 30
    runner.tick()
    assert runner.chunk is None and runner._trailing_jaw_gate is not None
    assert motion.velocity["shoulder_lift"] > 0.0

    runner.ticks = 29
    runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [35] * 6}
    monkeypatch.setattr(joint_push, "pushing", lambda *_a, **_kw: ("shoulder_lift", "pushing down"))
    now[0] += 1 / 30
    runner.tick()
    assert runner.fault == "pushing at rest: pushing down"
    assert motion.velocity["shoulder_lift"] == 0.0
    goal_after_push = bus.goals["shoulder_lift"]

    monkeypatch.setattr(joint_push, "pushing", lambda *_a, **_kw: None)
    now[0] += 1 / 30
    runner.tick()
    assert bus.goals["shoulder_lift"] <= goal_after_push and motion.velocity["shoulder_lift"] <= 0.0
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())


@pytest.mark.parametrize("fresh_tick", [False, True])
def test_runner_holds_when_grip_current_or_health_read_fails_while_holding(fresh_tick):
    import chunk_runner_interrupt as ci
    from chunk_policy_playback import Handoff
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from grasp_planner import load_kinematics, norm_to_rad
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    pose = kin.fk([norm_to_rad(v) for v in p0[:5]])
    reports = []
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "chunks": {"home": [p0], "policy": [p0]}, "gripper_closed": 49.0}
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.0)
    runner.target = runner.present()
    runner.chunk, runner.queue, runner.holding, runner.signals = "policy", [list(p0)], True, []
    if fresh_tick:
        runner.ticks = 29
    play = Playback(dict(start=1.0, observed=0.98, max_age=0.6, max_step=0.16), 30)
    play.handoff = Handoff(dict(
        hold_current_ma=140, min_z=0.15, x=pose.x, y=pose.y, yaw_deg=115.0,
        xy_tol=0.01, angle_tol_deg=20.0, close_target=49.0, empty_stop=45.0, hold_frames=3,
    ), kin)
    runner.policy_playback = play
    runner.read_health = lambda: (_ for _ in ()).throw(OSError("Present_Current read timed out"))
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
    assert runner.human_hold_latched is True and runner.queue == [] and runner.chunk is None
    assert any("Present_Current read timed out" in r.get("policy_stop", "") for r in reports)
    assert ci.gate_allows(runner, runner.signals) is False


@pytest.mark.parametrize("sink", ["trace", "live", "status"])
def test_runner_telemetry_write_failure_during_jaw_gate_latches_hold(tmp_path, monkeypatch, sink):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    class _Done(Exception):
        pass

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
        "policy_playback": {"start": 10.03, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / f"telemetry-fail-{sink}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    runner, ticks, hold_ticks = None, 0, 0
    pending_batches = [[f"load {lib_path}", "run policy"]]

    def status_cb(row):
        reports.append(row)
        if row.get("command") == "state" and sink == "status":
            raise OSError("disk full")
        if "policy_stop" in row or row.get("command") == "human-hold":
            raise OSError("disk full")

    def live_cb(_row):
        if sink == "live" and runner.chunk == "policy":
            raise OSError("disk full")

    def trace_cb(_row):
        if sink == "trace" and runner.chunk == "policy":
            raise OSError("disk full")

    def step(_dt):
        nonlocal ticks, hold_ticks
        ticks += 1
        assert ticks <= 15, "runner did not latch hold"
        now[0] += 1 / 30
        if ticks == 1:
            motion.velocity["shoulder_lift"] = 36.0
        if sink == "status" and ticks == 2:
            pending_batches.append(["state"])
        if runner.human_hold_latched:
            hold_ticks += 1
            if hold_ticks >= 2:
                raise _Done()

    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=status_cb, live=live_cb, clock=lambda: now[0], sleep=step)
    runner.signals, runner.trace = [], trace_cb
    with pytest.raises(_Done):
        runner.run(lambda: pending_batches.pop(0) if pending_batches else [])
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert runner.policy_playback is None and runner.jaw_gate is None and runner._trailing_jaw_gate is None
    assert motion.velocity["shoulder_lift"] <= 0.0
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    assert ci.gate_allows(runner, runner.signals) is False
    closed, slept = [], []

    def release_sleep(_dt):
        slept.append(_dt)
        assert closed == []
        if len(slept) == 2:
            runner.signals.append(ci.OPERATOR_RELEASE)

    ci.gated_close(runner, runner.signals, tmp_path / "hold.json", lambda: closed.append("off"), sleep=release_sleep)
    assert len(slept) == 2 and closed == ["off"]
    check_gate = start_jaw_gate(runner, gate_spec)
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 2 and all(g["shoulder_lift"] <= 1841 for g in post_seed_goals)
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])
