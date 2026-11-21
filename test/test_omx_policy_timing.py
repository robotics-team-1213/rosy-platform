"""Timing and handoff behavior with no model, camera, or actuator."""
from pathlib import Path
import json
import sys
import threading
import time
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
