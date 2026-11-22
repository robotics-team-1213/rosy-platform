"""OMX policy jaw-gate startup pinning, geometry validation, and stop-now admission tests."""
from pathlib import Path
import json
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from chunk_policy_playback import Playback  # noqa: E402
from test_omx_policy_timing import _make_guard_bus  # noqa: E402


def test_stop_now_status_write_failure_stays_in_loop_and_commands_hold(tmp_path, monkeypatch):
    from chunk_policy_playback import start_jaw_gate
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now = [10.0]
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
    lib_path = tmp_path / "stop-now-status-fail.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    runner, ticks, hold_ticks = None, 0, 0
    pending_batches = [[f"load {lib_path}", "run policy"]]

    def status_cb(row):
        if row.get("command") == "stop now" or "policy_stop" in row or row.get("command") == "human-hold":
            raise OSError("disk full")

    def step(_dt):
        nonlocal ticks, hold_ticks
        ticks += 1
        assert ticks <= 20, "runner did not latch hold or exit on OPERATOR_RELEASE"
        now[0] += 1 / 30
        if ticks == 1:
            motion.velocity["shoulder_lift"] = 36.0
        if ticks == 2:
            pending_batches.append(["stop now"])
        if runner.human_hold_latched:
            hold_ticks += 1
            if hold_ticks == 2:
                runner.signals.append(ci.OPERATOR_RELEASE)

    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=status_cb, clock=lambda: now[0], sleep=step)
    runner.signals = []
    runner.run(lambda: pending_batches.pop(0) if pending_batches else [])
    assert hold_ticks == 2 and ci.OPERATOR_RELEASE in runner.signals
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert runner.policy_playback is None and runner.jaw_gate is None and runner._trailing_jaw_gate is None
    assert motion.velocity["shoulder_lift"] <= 0.0
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    check_gate = start_jaw_gate(runner, gate_spec)
    post_seed_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_seed_goals) >= 2
    for goals in post_seed_goals:
        goal_map = normalized(bus, goals)
        check_gate.check_tick(present_start, [goal_map[n] for n in NAMES])
    assert runner._off_approved == "operator release (SIGUSR2)"
    runner._off_approved = None
    assert ci.gate_allows(runner, []) is False
    closed, slept, release_signals = [], [], []

    def release_sleep(_dt):
        slept.append(_dt)
        assert closed == []
        if len(slept) == 2:
            release_signals.append(ci.OPERATOR_RELEASE)

    ci.gated_close(runner, release_signals, tmp_path / "hold.json", lambda: closed.append("off"), sleep=release_sleep)
    assert len(slept) == 2 and closed == ["off"]


def test_finish_tick_trace_flush_failure_emits_only_hold_and_clears_trailing_gate():
    from chunk_policy_playback import finish_tick, start_jaw_gate
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    class _FailingTrace:
        def flush(self):
            raise OSError("disk full")

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    reports = []
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "chunks": {"home": [p0], "policy": [p0]},
               "gripper_closed": 49.0, "tcp_x_m": 0.0741}
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.0)
    runner.target, runner.chunk, runner.queue, runner.signals = list(p0), "policy", [], []
    runner.trace = _FailingTrace()
    play = Playback(dict(start=1.0, observed=0.98, max_age=0.6, max_step=0.16), 30)
    play.jaw_gate = start_jaw_gate(runner, gate_spec)
    runner.policy_playback = play
    runner.jaw_gate = play.jaw_gate
    finish_tick(runner, play, p0, 0.0, 3.0)
    assert runner.human_hold_latched is True
    assert runner._trailing_jaw_gate is None and runner.policy_playback is None and runner.jaw_gate is None
    assert len(reports) == 1 and reports[0]["ok"] is False
    assert "trace flush failed" in reports[0]["policy_stop"]
    assert not any(r.get("ok") is True for r in reports)


@pytest.mark.parametrize("mode", ["trace_append", "finish_flush"])
def test_post_send_telemetry_hold_defers_ack_until_hold_goal_is_sent(tmp_path, mode):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    class _Trace:
        def __call__(self, row):
            if mode == "trace_append" and row.get("chunk") == "policy":
                raise OSError("disk full")

        def flush(self):
            if mode == "finish_flush":
                raise OSError("disk full")

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    p_next = [present_start[0] + 0.1, *present_start[1:]]
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [p_next]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / f"post-send-ack-{mode}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")
    runner.trace = _Trace()

    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True
    assert runner.torque_hold_commanded is False and runner._human_hold_ack_pending is True
    assert runner.policy_playback is None and runner.jaw_gate is None and runner._trailing_jaw_gate is None
    assert not any(r.get("command") == "human-hold" for r in reports)
    assert not any(r.get("command") == "run policy" and r.get("ok") is True for r in reports)
    assert any(r.get("ok") is False and "policy_stop" in r for r in reports)

    now[0] += 1 / 30
    runner.tick()
    assert runner.torque_hold_commanded is True and runner._human_hold_ack_pending is False
    assert any(r.get("command") == "human-hold" and r.get("ok") is True and r.get("torque_hold_commanded") is True
               for r in reports)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)


@pytest.mark.parametrize(
    "case",
    ["inherit_top_level", "null_playback_gate", "null_playback_only", "null_top_level", "conflicting_gates", "matching_gates"],
)
def test_timed_policy_enforces_top_level_jaw_gate_and_rejects_null_or_conflict(case):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    commands, reports = [], []
    bad_gate = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 25.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    playback = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16}
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "policy": [p0]},
        "policy_playback": playback,
    }
    if case == "inherit_top_level":
        library["jaw_gate"] = dict(bad_gate)
    elif case == "null_playback_gate":
        library["jaw_gate"] = dict(bad_gate)
        playback["jaw_gate"] = None
    elif case == "null_playback_only":
        playback["jaw_gate"] = None
    elif case == "null_top_level":
        library["jaw_gate"] = None
        playback["jaw_gate"] = dict(bad_gate)
    elif case == "conflicting_gates":
        library["jaw_gate"] = dict(bad_gate)
        playback["jaw_gate"] = {**bad_gate, "tol_deg": 40.0}
    else:
        library["jaw_gate"] = dict(bad_gate)
        playback["jaw_gate"] = dict(bad_gate)

    robot = SimpleNamespace(send_action=lambda a: commands.append(dict(a)) or a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.01)
    runner.target = runner.present()
    runner.command("run policy")

    if case in ("inherit_top_level", "matching_gates"):
        assert runner.chunk == "policy" and runner.policy_playback is not None and runner.policy_playback.jaw_gate is not None
        runner.tick()
        assert runner.human_hold_latched is True
        assert any("jaw yaw" in r.get("policy_stop", "") for r in reports)
        assert commands[-1]["wrist_roll.pos"] == -14.0
    else:
        assert runner.chunk is None and runner.policy_playback is None and runner.queue == []
        assert reports[-1]["ok"] is False
        expected = "conflicts with library jaw_gate" if case == "conflicting_gates" else "invalid policy jaw_gate parameters"
        assert expected in reports[-1]["error"]


@pytest.mark.parametrize("timed", [True, False])
def test_interrupt_during_jaw_gated_policy_stops_retimer_and_keeps_gate(tmp_path, timed):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
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
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
    }
    if timed:
        library["policy_playback"] = {"start": 10.03, "observed": 9.98, "max_age": 0.6, "max_step": 0.16,
                                      "jaw_gate": gate_spec}
    else:
        library["jaw_gate"] = gate_spec
    lib_path = tmp_path / ("interrupt-timed.json" if timed else "interrupt-legacy.json")
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    motion.velocity["wrist_roll"] = 36.0
    motion.velocity["shoulder_lift"] = 36.0
    goal_writes_before = len([e for e in bus.events if e[0] == "goal"])
    raw_wrist, raw_lift = bus.raw["wrist_roll"], bus.raw["shoulder_lift"]
    runner.signals.append(signal.SIGINT)
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False

    assert runner._interrupt["phase"] == "verify"
    assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None
    assert runner._trailing_jaw_gate is not None
    assert motion.velocity["wrist_roll"] == 0.0 and motion.velocity["shoulder_lift"] == 0.0
    post_goals = [e[1] for e in bus.events if e[0] == "goal"][goal_writes_before:]
    assert len(post_goals) == 1
    assert post_goals[0]["wrist_roll"] == raw_wrist and post_goals[0]["shoulder_lift"] == raw_lift
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)


@pytest.mark.parametrize("timed", [True, False])
@pytest.mark.parametrize(
    "override",
    [
        {"tol_deg": 180.0},
        {"tol_deg": 45.1},
        {"tol_deg": 4.9},
        {"tol_deg": 45.0, "square": True},
        {"max_tilt_rad": 4.0},
        {"max_tilt_rad": 0.46},
        {"xy_radius_m": 0.001},
        {"xy_radius_m": 1.0},
    ],
)
def test_runner_rejects_out_of_bounds_jaw_gate_tolerances(timed, override):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    reports = []
    bad_gate = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
        **override,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "policy": [p0]},
    }
    if timed:
        library["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16,
                                      "jaw_gate": bad_gate}
    else:
        library["jaw_gate"] = bad_gate
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.01)
    runner.target = runner.present()
    runner.command("run policy")
    assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
    assert reports[-1]["ok"] is False and "invalid policy jaw_gate parameters" in reports[-1]["error"]


def test_jaw_gate_spec_rejects_out_of_bounds_tolerances():
    import math

    from cell_policy_shape import jaw_gate_spec

    class _Kin:
        def fk(self, _joints):
            return SimpleNamespace(x=0.0495, y=0.1608, z=0.1566, yaw=math.radians(115.0), tool_down_error_rad=0.0)

    lib = {"chunks": {"grasp_pick": [[38.8, -10.0, 2.0, 55.0, -14.0, 49.0]]}}
    with pytest.raises(ValueError, match="invalid policy jaw_gate parameters"):
        jaw_gate_spec(lib, _Kin(), params={"policy.approach_yaw_tol_deg": 180.0})
    with pytest.raises(ValueError, match="invalid policy jaw_gate parameters"):
        jaw_gate_spec(lib, _Kin(), max_tilt_rad=4.0)
    with pytest.raises(ValueError, match="invalid policy jaw_gate parameters"):
        jaw_gate_spec(lib, _Kin(), xy_radius_m=0.001)
    lib_sq = {**lib, "source": {"pick": {"square": True}}}
    with pytest.raises(ValueError, match="invalid policy jaw_gate parameters"):
        jaw_gate_spec(lib_sq, _Kin(), params={"policy.approach_yaw_tol_deg": 45.0})


@pytest.mark.parametrize("timed", [True, False])
def test_state_poll_encoder_failure_during_jaw_gate_latches_hold_and_blocks_close(tmp_path, monkeypatch, timed):
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports, fail_obs = [10.0], [], [False]
    bus = _make_guard_bus(p_above)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
    }
    if timed:
        library["policy_playback"] = {"start": 10.03, "observed": 9.98, "max_age": 0.6, "max_step": 0.16,
                                      "jaw_gate": gate_spec}
    else:
        library["jaw_gate"] = gate_spec
    lib_path = tmp_path / ("state-err-timed.json" if timed else "state-err-legacy.json")
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    runner, ticks, hold_ticks = None, 0, 0
    pending_batches = [[f"load {lib_path}", "run policy"]]

    def read_obs():
        if fail_obs[0]:
            raise TimeoutError("encoder read timed out")
        return normalized(bus, bus.raw)

    def step(_dt):
        nonlocal ticks, hold_ticks
        ticks += 1
        assert ticks <= 20, "runner did not latch hold or exit on OPERATOR_RELEASE"
        now[0] += 1 / 30
        if ticks == 1:
            motion.velocity["shoulder_lift"] = 36.0
        if ticks == 2:
            fail_obs[0] = True
            pending_batches.append(["state"])
        if runner.human_hold_latched:
            hold_ticks += 1
            if hold_ticks == 2:
                runner.signals.append(ci.OPERATOR_RELEASE)

    raw_robot = SimpleNamespace(bus=bus, get_observation=read_obs)
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0], sleep=step)
    runner.signals = []
    runner.run(lambda: pending_batches.pop(0) if pending_batches else [])

    assert hold_ticks == 2 and ci.OPERATOR_RELEASE in runner.signals
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is True
    assert runner.policy_playback is None and runner.jaw_gate is None and runner._trailing_jaw_gate is None
    assert motion.velocity["shoulder_lift"] <= 0.0
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert not any(e[0] == "off" for e in bus.events)
    assert any("encoder read failed" in r.get("policy_stop", "") and r.get("ok") is False for r in reports)
    assert not any(r.get("command") == "state" and r.get("ok") is True for r in reports)
    assert runner._off_approved == "operator release (SIGUSR2)"
    runner._off_approved = None
    assert ci.gate_allows(runner, []) is False
    closed, slept, release_signals = [], [], []

    def release_sleep(_dt):
        slept.append(_dt)
        assert closed == []
        if len(slept) == 2:
            release_signals.append(ci.OPERATOR_RELEASE)

    ci.gated_close(runner, release_signals, tmp_path / "hold.json", lambda: closed.append("off"), sleep=release_sleep)
    assert len(slept) == 2 and closed == ["off"]


@pytest.mark.parametrize("timed", [True, False])
@pytest.mark.parametrize(
    "case",
    ["far_x", "far_y", "low_z", "high_z", "grasp_valid", "grasp_shift_x", "grasp_low_z", "grasp_wrong_yaw",
     "grasp_flip_square", "grasp_missing_gate", "grasp_lowered_ceiling", "grasp_widened_tol", "grasp_shrunk_radius",
     "grasp_small_yaw_shift_same_tol", "grasp_small_xy_shift_same_radius", "grasp_small_shifts_compensated"],
)
def test_jaw_gate_admission_validates_reach_and_grasp_pick_geometry(timed, case):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    base_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin), "tcp_x_m": 0.0741}
    chunks = {"home": [p0], "policy": [p0]}
    spec = dict(base_spec)
    if case == "far_x":
        spec["x"] = 1000000.0
    elif case == "far_y":
        spec["y"] = -1000.0
    elif case == "low_z":
        spec["z_m"] = -0.5
    elif case == "high_z":
        spec["z_m"] = 10.0
    else:
        chunks["grasp_pick"] = [p0]
        if case == "grasp_shift_x":
            spec["x"] += 0.02
        elif case == "grasp_low_z":
            spec["z_m"] -= 0.1
        elif case == "grasp_lowered_ceiling":
            spec["z_m"] -= 0.034
        elif case == "grasp_widened_tol":
            spec["tol_deg"] = 40.0
        elif case == "grasp_shrunk_radius":
            spec["xy_radius_m"] = 0.03
        elif case == "grasp_wrong_yaw":
            spec["yaw_deg"] += 45.0
        elif case == "grasp_flip_square":
            spec["square"] = True
        elif case == "grasp_small_yaw_shift_same_tol":
            spec["yaw_deg"] += 0.9
        elif case == "grasp_small_xy_shift_same_radius":
            spec["x"] += 0.003
        elif case == "grasp_small_shifts_compensated":
            spec["x"] += 0.003
            spec["xy_radius_m"] += 0.004
            spec["yaw_deg"] += 0.9
            spec["tol_deg"] -= 1.0
        elif case == "grasp_missing_gate":
            spec = None

    reports = []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
               "chunks": chunks}
    if timed:
        library["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16,
                                      **({"jaw_gate": spec} if spec is not None else {})}
    elif spec is not None:
        library["jaw_gate"] = spec
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.01)
    runner.target = runner.present()
    runner.command("run policy")

    if case in ("grasp_valid", "grasp_small_shifts_compensated"):
        active = runner.policy_playback.jaw_gate if timed else runner.jaw_gate
        assert runner.chunk == "policy" and active is not None
    else:
        assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
        assert reports[-1]["ok"] is False
        conflict_cases = ("grasp_shift_x", "grasp_low_z", "grasp_lowered_ceiling", "grasp_widened_tol",
                          "grasp_shrunk_radius", "grasp_wrong_yaw", "grasp_flip_square",
                          "grasp_small_yaw_shift_same_tol", "grasp_small_xy_shift_same_radius")
        expected = ("conflicts with library grasp_pick geometry" if case in conflict_cases
                    else "requires jaw_gate" if case == "grasp_missing_gate"
                    else "invalid policy jaw_gate parameters")
        assert expected in reports[-1]["error"]


@pytest.mark.parametrize("timed", [True, False])
def test_native_present_position_timeout_during_jaw_gate_keeps_torque_on_and_holds(tmp_path, timed):
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
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
    }
    if timed:
        library["policy_playback"] = {"start": 10.03, "observed": 9.98, "max_age": 0.6, "max_step": 0.16,
                                      "jaw_gate": gate_spec}
    else:
        library["jaw_gate"] = gate_spec
    lib_path = tmp_path / ("native-timeout-timed.json" if timed else "native-timeout-legacy.json")
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    motion.velocity["shoulder_lift"] = 36.0
    orig_sync_read = bus.sync_read
    bus.sync_read = lambda *_a, **_kw: (_ for _ in ()).throw(TimeoutError("Present_Position timeout"))

    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is False
    assert motion.failed is False and motion.velocity["shoulder_lift"] == 0.0
    assert all(v == 1 for v in bus.torque.values()) and not any(e[0] == "off" for e in bus.events)
    assert any("encoder read failed" in r.get("policy_stop", "") for r in reports)
    assert ci.gate_allows(runner, []) is False

    now[0] += 0.6
    runner.tick()
    assert motion.failed is False and runner.torque_hold_commanded is False
    assert all(v == 1 for v in bus.torque.values())

    bus.sync_read = orig_sync_read
    now[0] += 2.0
    runner.tick()
    assert runner.torque_hold_commanded is True
    assert all(v == 1 for v in bus.torque.values())


def test_interrupt_hold_tick_keeps_torque_on_when_encoder_times_out_and_recovers_after_stale_gap(tmp_path):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
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
    gate_spec = {
        "x": 0.0495, "y": 0.1608, "z_m": 0.1566, "xy_radius_m": 0.08,
        "yaw_deg": 115.0, "tol_deg": 20.0, "max_tilt_rad": 0.45, "square": False, "tcp_x_m": 0.0741,
    }
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [present_start], "policy": [present_start, present_start]},
        "policy_playback": {"start": 10.03, "observed": 9.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": gate_spec},
    }
    lib_path = tmp_path / "interrupt-hold-timeout.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    orig_sync_read = bus.sync_read
    bus.sync_read = lambda *_a, **_kw: (_ for _ in ()).throw(TimeoutError("Present_Position timeout"))
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
    assert runner.human_hold_latched is True and runner.torque_hold_commanded is False

    runner.signals.append(signal.SIGINT)
    for _ in range(3):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
        assert runner._interrupt["phase"] == "hold"
        assert motion.failed is False and runner.torque_hold_commanded is False
        assert all(v == 1 for v in bus.torque.values())
        assert not any(e[0] == "off" for e in bus.events)

    bus.sync_read = orig_sync_read
    now[0] += 2.0
    assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
    assert runner.torque_hold_commanded is True and motion.failed is False
    assert all(v == 1 for v in bus.torque.values())


@pytest.mark.parametrize(
    "timed, rim_source",
    [
        (True, "spec_rim"),
        (False, "spec_rim"),
        (True, "library_source_rim"),
        (False, "library_source_rim"),
        (True, "handoff_min_z"),
        (True, "runner_rim"),
        (False, "runner_rim"),
    ],
)
def test_jaw_gate_admission_validates_configured_rim_z_and_handoff_min_z(timed, rim_source):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    rim = 0.21
    valid_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}
    base_no_rim = {k: v for k, v in valid_spec.items() if k != "rim_z_m"}

    for expect_valid, z_m in ((False, 0.21), (True, valid_spec["z_m"])):
        spec = dict(valid_spec if rim_source == "spec_rim" else base_no_rim)
        spec["z_m"] = z_m
        library = {
            "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
            "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]},
        }
        if rim_source == "library_source_rim":
            library["source"] = {"rim_z_m": rim}
        if timed:
            pb = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": spec}
            if rim_source == "handoff_min_z":
                pb["handoff"] = {
                    "min_z": valid_spec["z_m"], "x": spec["x"], "y": spec["y"], "yaw_deg": spec["yaw_deg"],
                    "xy_tol": 0.012, "angle_tol_deg": 7.0, "close_target": 50.0, "empty_stop": 49.0, "hold_frames": 8,
                }
            library["policy_playback"] = pb
        else:
            library["jaw_gate"] = spec
        reports = []
        robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
        runner = Runner(
            robot, library, fps=30, status=reports.append, clock=lambda: 1.01,
            rim_z_m=(rim if rim_source == "runner_rim" else None),
        )
        runner.target = runner.present()
        runner.command("run policy")
        if expect_valid:
            active = runner.policy_playback.jaw_gate if timed else runner.jaw_gate
            assert runner.chunk == "policy" and active is not None
        else:
            assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
            assert reports[-1]["ok"] is False and "conflicts with library grasp_pick geometry" in reports[-1]["error"]


@pytest.mark.parametrize("cmd", ["splice policy", "goto policy", "chain run policy", "chain goto policy"])
def test_alternate_commands_refuse_ungated_policy_when_grasp_pick_present(cmd):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    reports = []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
               "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0, p0]}}
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.0)
    runner.target = runner.present()
    runner.command(cmd)
    assert runner.chunk is None and runner.queue == []
    assert reports[-1]["ok"] is False and "policy chunk" in reports[-1]["error"]


@pytest.mark.parametrize("timed", [True, False])
@pytest.mark.parametrize("bad_source", ["bad", [1, 2], {"pick": "bad"}, {"pick": [1, 2]}])
def test_malformed_source_metadata_refused_cleanly_without_crashing_runner(timed, bad_source):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin), "tcp_x_m": 0.0741}
    reports = []
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]},
        "source": bad_source,
    }
    if timed:
        library["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": spec}
    else:
        library["jaw_gate"] = spec
    robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 1.01)
    runner.target = runner.present()
    runner.command("run policy")
    assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
    assert reports[-1]["ok"] is False and "must be a dict" in reports[-1]["error"]


@pytest.mark.parametrize(
    "timed, target",
    [
        (True, "gate_x"), (False, "gate_x"),
        (True, "gate_z"), (False, "gate_z"),
        (True, "gate_yaw"), (False, "gate_yaw"),
        (True, "gate_radius"), (False, "gate_radius"),
        (True, "gate_rim"), (False, "gate_rim"),
        (True, "gate_tcp"), (False, "gate_tcp"),
        (True, "source_rim"), (False, "source_rim"),
        (True, "source_pick_yaw"), (False, "source_pick_yaw"),
        (True, "play_start"),
        (True, "handoff_min_z"),
        (True, "handoff_tcp"),
        (True, "handoff_bad_tcp"),
    ],
)
def test_oversized_json_integer_in_policy_metadata_refused_without_crashing_runner(timed, target):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin), "tcp_x_m": 0.0741}
    sent, reports = [], []
    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]},
    }
    sentinel = 999991.0
    if timed:
        library["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": dict(spec)}
        gate_holder = library["policy_playback"]["jaw_gate"]
    else:
        library["jaw_gate"] = dict(spec)
        gate_holder = library["jaw_gate"]
    if target == "gate_x":
        gate_holder["x"] = sentinel
    elif target == "gate_z":
        gate_holder["z_m"] = sentinel
    elif target == "gate_yaw":
        gate_holder["yaw_deg"] = sentinel
    elif target == "gate_radius":
        gate_holder["xy_radius_m"] = sentinel
    elif target == "gate_rim":
        gate_holder["rim_z_m"] = sentinel
    elif target == "gate_tcp":
        gate_holder["tcp_x_m"] = sentinel
    elif target == "source_rim":
        library["source"] = {"rim_z_m": sentinel}
    elif target == "source_pick_yaw":
        library["source"] = {"pick": {"yaw_deg": sentinel}}
    elif target == "play_start":
        library["policy_playback"]["start"] = sentinel
    elif target.startswith("handoff_"):
        library["policy_playback"]["handoff"] = {
            "min_z": sentinel if target == "handoff_min_z" else spec["z_m"],
            "x": spec["x"], "y": spec["y"], "yaw_deg": spec["yaw_deg"], "xy_tol": 0.012, "angle_tol_deg": 7.0,
            "close_target": 50.0, "empty_stop": 49.0, "hold_frames": 8,
            **({"tcp_x_m": sentinel if target == "handoff_tcp" else 0.5}
               if target in ("handoff_tcp", "handoff_bad_tcp") else {}),
        }
    raw_json = json.dumps(library).replace(str(sentinel), "1" + ("0" * 400))
    parsed = json.loads(raw_json)
    robot = SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0)))
    runner = Runner(robot, parsed, fps=30, status=reports.append, clock=lambda: 1.01)
    runner.target = runner.present()
    assert runner.command("run policy") is True
    assert runner.human_hold_latched is False
    assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
    assert reports[-1]["ok"] is False and reports[-1].get("error") and not sent


def test_oversized_json_integer_in_load_library_refused_without_crashing_runner(tmp_path):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    bad_path = tmp_path / "huge-frame.json"
    raw = json.dumps({
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
        "chunks": {"home": [p0], "policy": [[999991.0, *p0[1:]]]},
    }).replace("999991.0", "1" + ("0" * 400))
    bad_path.write_text(raw, encoding="utf-8")
    reports, lib = [], {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [p0]}}
    runner = Runner(SimpleNamespace(send_action=lambda a: None, get_observation=lambda: dict(zip(NAMES, p0))),
                    lib, fps=30, status=reports.append, clock=lambda: 1.0)
    runner.target = runner.present()
    assert runner.command(f"load {bad_path}") is True
    assert runner.human_hold_latched is False and reports[-1]["ok"] is False


@pytest.mark.parametrize("timed", [True, False])
@pytest.mark.parametrize("bind_via", ["params", "startup_library", "cli_arg"])
def test_chunk_runner_main_binds_configured_rim_z_and_refuses_stripped_policy_library(
        tmp_path, monkeypatch, timed, bind_via):
    import bus_watchdog
    import cell_params as prm
    from cell_policy_shape import jaw_gate_spec
    import chunk_runner as cr
    from grasp_planner import load_kinematics
    import guarded_native
    import motor_health
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    rim = 0.21
    kin, _, _ = load_kinematics(None, 0.0741)
    valid_spec = {k: v for k, v in {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}.items()
                  if k != "rim_z_m"}
    assert valid_spec["z_m"] > 0.15
    sent, reports = [], []
    robot = SimpleNamespace(
        bus=SimpleNamespace(read=lambda reg, j: 300),
        send_action=lambda a: sent.append(a) or a,
        get_observation=lambda: dict(zip(NAMES, p0)),
    )

    cfg_path, init_path, low_path, valid_path, params_path = (
        tmp_path / name for name in ("record.json", "init.json", "low.json", "valid.json", "params.json")
    )
    cfg_path.write_text(json.dumps({
        "robot": {"type": "omx_follower", "port": "/dev/fake-session", "max_relative_target": 5},
        "dataset": {"fps": 30},
    }), encoding="utf-8")
    init_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
                "chunks": {"home": [p0]}}
    if bind_via == "startup_library":
        init_lib["source"] = {"rim_z_m": rim}
    init_path.write_text(json.dumps(init_lib), encoding="utf-8")
    if bind_via == "params":
        params_path.write_text(json.dumps({
            "schema": prm.SCHEMA,
            "params": {"policy.source_rim_z_m": {"value": rim, "unit": "m", "source": "measured", "evidence": "test rim"}},
        }), encoding="utf-8")

    now = time.monotonic()
    for path, z_m in ((low_path, 0.15), (valid_path, valid_spec["z_m"])):
        spec = {**valid_spec, "z_m": z_m}
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
               "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]}}
        if timed:
            lib["policy_playback"] = {"start": now + 0.5, "observed": now, "max_age": 5.0, "max_step": 0.16,
                                      "jaw_gate": spec}
        else:
            lib["jaw_gate"] = spec
        path.write_text(json.dumps(lib), encoding="utf-8")

    results = {}

    class SessionRunner(cr.Runner):
        def run(self, lines):
            results["rim_z_m"] = self.rim_z_m
            self.target = self.present()
            assert self.command(f"load {low_path}") is True
            assert self.command("run policy") is True
            results["low_state"] = (self.chunk, self.policy_playback, self.jaw_gate, list(self.queue))
            assert self.command(f"load {valid_path}") is True
            assert self.command("run policy") is True
            active = self.policy_playback.jaw_gate if timed else self.jaw_gate
            results["valid_state"] = (self.chunk, active is not None)
            self.policy_playback = self.jaw_gate = self._trailing_jaw_gate = None
            self.chunk, self.queue = None, []

    class StatusCaptureRunner(SessionRunner):
        def __init__(self, *args, **kwargs):
            orig_status = kwargs.get("status")
            kwargs["status"] = lambda row: (reports.append(row), orig_status(row))
            super().__init__(*args, **kwargs)

    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", SimpleNamespace(
        OmxFollowerConfig=lambda **values: values, OmxFollower=lambda config: robot))
    monkeypatch.setattr(guarded_native, "connect_passive", lambda *a, **k: None)
    monkeypatch.setattr(guarded_native, "close_device", lambda *a: None)
    monkeypatch.setattr(motor_health, "MotorHealth", lambda: SimpleNamespace(end=lambda: None))
    monkeypatch.setattr(bus_watchdog, "arm", lambda *a: None)
    monkeypatch.setattr(cr, "fifo_lines", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cr, "runtime_context", lambda *a, **k: {"scope": "simulation"})
    monkeypatch.setattr(cr, "Runner", StatusCaptureRunner)

    argv = ["--config", str(cfg_path), "--library", str(init_path), "--io", str(tmp_path / "io")]
    if bind_via == "params":
        argv += ["--params", str(params_path)]
    elif bind_via == "cli_arg":
        argv += ["--rim-z-m", str(rim)]
    cr.main(argv)

    assert results["rim_z_m"] == pytest.approx(rim)
    assert results["low_state"] == (None, None, None, [])
    assert reports[1]["ok"] is False and "conflicts with library grasp_pick geometry" in reports[1]["error"]
    assert results["valid_state"] == ("policy", True) and not sent


@pytest.mark.parametrize("timed", [True, False])
@pytest.mark.parametrize("cmd", ["run policy", "splice policy", "goto policy", "chain run policy", "chain goto policy"])
def test_configured_rim_requires_jaw_gate_even_without_grasp_pick(timed, cmd):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    valid_spec = {k: v for k, v in {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=0.21), "tcp_x_m": 0.0741}.items()
                  if k != "rim_z_m"}

    for runner_kwargs in ({"rim_z_m": 0.21}, {"params": {"policy.source_rim_z_m": 0.21}}):
        sent, reports = [], []
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
               "chunks": {"home": [p0], "policy": [p0, p0]}}
        if timed:
            lib["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16}
        runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                        lib, fps=30, status=reports.append, clock=lambda: 1.0, **runner_kwargs)
        runner.target = runner.present()
        assert runner.command(cmd) is True
        assert runner.chunk is None and runner.policy_playback is None and runner.jaw_gate is None and runner.queue == []
        assert reports[-1]["ok"] is False and not sent

    # Without grasp_pick under a configured rim, even a supplied jaw_gate (off-center or centered) is refused.
    for x_shift in (0.05, 0.0):
        sent, reports = [], []
        spec = {**valid_spec, "x": valid_spec["x"] + x_shift}
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
               "chunks": {"home": [p0], "policy": [p0]}}
        if timed:
            lib["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": spec}
        else:
            lib["jaw_gate"] = spec
        runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                        lib, fps=30, status=reports.append, clock=lambda: 1.0, rim_z_m=0.21)
        runner.target = runner.present()
        assert runner.command("run policy") is True
        assert runner.chunk is None and runner.queue == [] and reports[-1]["ok"] is False and not sent
        assert "requires reviewed grasp_pick geometry" in reports[-1]["error"]

    # With grasp_pick present under a configured rim, off-center or low z_m fails while valid centered succeeds.
    for expect_ok, z_m, x_shift in ((False, valid_spec["z_m"], 0.05), (False, 0.15, 0.0), (True, valid_spec["z_m"], 0.0)):
        sent, reports = [], []
        spec = {**valid_spec, "z_m": z_m, "x": valid_spec["x"] + x_shift}
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
               "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]}}
        if timed:
            lib["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": spec}
        else:
            lib["jaw_gate"] = spec
        runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                        lib, fps=30, status=reports.append, clock=lambda: 1.0, rim_z_m=0.21)
        runner.target = runner.present()
        assert runner.command("run policy") is True
        if expect_ok:
            active = runner.policy_playback.jaw_gate if timed else runner.jaw_gate
            assert runner.chunk == "policy" and active is not None
        else:
            assert runner.chunk is None and reports[-1]["ok"] is False and not sent


def test_oversized_gripper_closed_and_transit_refused_at_load_and_command(tmp_path):
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA, load_library

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    for idx, lib in enumerate([
        {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 999991.0, "chunks": {"home": [p0]}},
        {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
         "transit": {"shoulder_lift.pos": 999991.0}, "chunks": {"home": [p0]}},
    ]):
        bad_path = tmp_path / f"bad-{idx}.json"
        bad_path.write_text(json.dumps(lib).replace("999991.0", "1" + ("0" * 400)), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_library(bad_path)
        reports = []
        base = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [p0]}}
        runner = Runner(SimpleNamespace(send_action=lambda a: None, get_observation=lambda: dict(zip(NAMES, p0))),
                        base, fps=30, status=reports.append, clock=lambda: 1.0)
        runner.target = runner.present()
        assert runner.command(f"load {bad_path}") is True
        assert runner.human_hold_latched is False and reports[-1]["ok"] is False

    reports = []
    mem_bad = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 10**400, "chunks": {"home": [p0]}}
    runner = Runner(SimpleNamespace(send_action=lambda a: None, get_observation=lambda: dict(zip(NAMES, p0))),
                    mem_bad, fps=30, status=reports.append, clock=lambda: 1.0)
    runner.target = runner.present()
    for bad_cmd in ("grip 50", "grip nan"):
        assert runner.command(bad_cmd) is True
        assert reports[-1]["ok"] is False and runner.human_hold_latched is False


def test_handoff_and_jaw_gate_tcp_env_fallback_never_exits_runner(monkeypatch):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin, _, _ = load_kinematics(None, 0.0741)
    base_spec = jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin)
    monkeypatch.setenv("ROSY_OMX_TCP_X_M", "0.5")

    handoff = {"min_z": base_spec["z_m"], "x": base_spec["x"], "y": base_spec["y"], "yaw_deg": base_spec["yaw_deg"],
               "xy_tol": 0.012, "angle_tol_deg": 7.0, "close_target": 50.0, "empty_stop": 49.0, "hold_frames": 8}
    # Case A: valid library tcp_x_m is inherited by handoff even when ROSY_OMX_TCP_X_M is out of range
    reports_a = []
    lib_a = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
             "jaw_gate": dict(base_spec), "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]},
             "policy_playback": {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "handoff": handoff}}
    runner_a = Runner(SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0))),
                      lib_a, fps=30, status=reports_a.append, clock=lambda: 1.0)
    runner_a.target = runner_a.present()
    assert runner_a.command("run policy") is True and runner_a.chunk == "policy"

    # Case B & C: invalid ROSY_OMX_TCP_X_M with no library/gate/handoff tcp_x_m refuses cleanly instead of SystemExit
    for timed in (True, False):
        sent, reports = [], []
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "jaw_gate": dict(base_spec),
               "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]}}
        if timed:
            lib["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "handoff": handoff}
        runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                        lib, fps=30, status=reports.append, clock=lambda: 1.0)
        runner.target = runner.present()
        assert runner.command("run policy") is True
        assert runner.chunk is None and runner.queue == [] and not sent
        assert reports[-1]["ok"] is False and "ROSY_OMX_TCP_X_M" in reports[-1]["error"]


@pytest.mark.parametrize("timed", [True, False])
def test_chunk_runner_main_anchors_startup_grasp_pick_against_tampered_load(tmp_path, monkeypatch, timed):
    import bus_watchdog
    from cell_policy_shape import jaw_gate_spec
    import chunk_runner as cr
    from grasp_planner import load_kinematics
    import guarded_native
    import motor_health
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p_shifted = [55.0, -10.0, 2.0, 55.0, -14.0, 49.0]
    rim = 0.21
    kin, _, _ = load_kinematics(None, 0.0741)
    valid_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}
    shifted_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p_shifted]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}
    sent, reports = [], []
    robot = SimpleNamespace(
        bus=SimpleNamespace(read=lambda reg, j: 300),
        send_action=lambda a: sent.append(a) or a,
        get_observation=lambda: dict(zip(NAMES, p0)),
    )

    cfg_path, init_path, drop_path, shift_path, valid_path = (
        tmp_path / name for name in ("record.json", "init.json", "drop.json", "shift.json", "valid.json")
    )
    cfg_path.write_text(json.dumps({
        "robot": {"type": "omx_follower", "port": "/dev/fake-session", "max_relative_target": 5},
        "dataset": {"fps": 30},
    }), encoding="utf-8")
    init_path.write_text(json.dumps({
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "source": {"rim_z_m": rim}, "chunks": {"home": [p0], "grasp_pick": [p0]},
    }), encoding="utf-8")

    now = time.monotonic()

    def write_policy_lib(path, chunks, spec):
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741, "chunks": chunks}
        if timed:
            lib["policy_playback"] = {"start": now + 0.5, "observed": now, "max_age": 5.0, "max_step": 0.16,
                                      "jaw_gate": spec}
        else:
            lib["jaw_gate"] = spec
        path.write_text(json.dumps(lib), encoding="utf-8")

    off_spec = {**valid_spec, "x": valid_spec["x"] + 0.05}
    write_policy_lib(drop_path, {"home": [p0], "policy": [p0]}, off_spec)
    write_policy_lib(shift_path, {"home": [p0], "grasp_pick": [p_shifted], "policy": [p0]}, shifted_spec)
    write_policy_lib(valid_path, {"home": [p0], "grasp_pick": [p0], "policy": [p0]}, valid_spec)

    outcomes = {}

    class SessionRunner(cr.Runner):
        def run(self, lines):
            self.target = self.present()
            for name, path in (("drop", drop_path), ("shift", shift_path), ("valid", valid_path)):
                assert self.command(f"load {path}") is True
                assert self.command("run policy") is True
                outcomes[name] = (self.chunk, reports[-1]["ok"], reports[-1].get("error"))
            self.policy_playback = self.jaw_gate = self._trailing_jaw_gate = None
            self.chunk, self.queue = None, []

    class StatusCaptureRunner(SessionRunner):
        def __init__(self, *args, **kwargs):
            orig_status = kwargs.get("status")
            kwargs["status"] = lambda row: (reports.append(row), orig_status(row))
            super().__init__(*args, **kwargs)

    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", SimpleNamespace(
        OmxFollowerConfig=lambda **values: values, OmxFollower=lambda config: robot))
    monkeypatch.setattr(guarded_native, "connect_passive", lambda *a, **k: None)
    monkeypatch.setattr(guarded_native, "close_device", lambda *a: None)
    monkeypatch.setattr(motor_health, "MotorHealth", lambda: SimpleNamespace(end=lambda: None))
    monkeypatch.setattr(bus_watchdog, "arm", lambda *a: None)
    monkeypatch.setattr(cr, "fifo_lines", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cr, "runtime_context", lambda *a, **k: {"scope": "simulation"})
    monkeypatch.setattr(cr, "Runner", StatusCaptureRunner)
    cr.main(["--config", str(cfg_path), "--library", str(init_path), "--io", str(tmp_path / "io")])

    assert outcomes["drop"][0] is None and outcomes["drop"][1] is False and "grasp_pick" in outcomes["drop"][2]
    assert outcomes["shift"][0] is None and outcomes["shift"][1] is False and "grasp_pick" in outcomes["shift"][2]
    assert outcomes["valid"][0] == "policy" and not sent


@pytest.mark.parametrize("timed", [True, False])
def test_refusal_status_write_failure_latches_hold_and_blocks_torque_off(tmp_path, monkeypatch, timed):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 31)
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    sent = []

    def fail_status(_row):
        raise OSError("disk full")

    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
           "chunks": {"home": [p0], "policy": [p0]}}
    if timed:
        lib["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16}
    runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                    lib, fps=30, status=fail_status, clock=lambda: 1.0, rim_z_m=0.21)
    runner.target = runner.present()
    assert runner.command("run policy") is True
    assert runner.human_hold_latched is True and runner.chunk is None and runner.queue == [] and not sent
    assert runner.command("stop now") is True and ci.gate_allows(runner, []) is False

    closed, slept, signals = [], [], []

    def release_sleep(_dt):
        slept.append(_dt)
        assert closed == []
        if len(slept) == 2:
            signals.append(ci.OPERATOR_RELEASE)

    ci.gated_close(runner, signals, tmp_path / "hold.json", lambda: closed.append("off"), sleep=release_sleep)
    assert len(slept) == 2 and closed == ["off"]


@pytest.mark.parametrize("timed", [True, False])
def test_startup_tcp_prevents_stock_kinematics_downgrade_on_replacement_load(timed):
    from cell_policy_shape import jaw_gate_spec
    from chunk_policy_playback import JawGate
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    trusted = {"chunks": {"grasp_pick": [p0]}, "tcp_x_m": 0.0741}
    stock_kin = load_kinematics(None)[0]
    cal_kin = load_kinematics(None, 0.0741)[0]
    stock_spec = jaw_gate_spec(trusted, stock_kin, rim_z_m=0.21)
    cal_spec = jaw_gate_spec(trusted, cal_kin, rim_z_m=0.21)
    substituted = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [p0], "policy": [p0]}}
    if timed:
        substituted["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": stock_spec}
    else:
        substituted["jaw_gate"] = stock_spec

    sent, reports = [], []
    runner = Runner(SimpleNamespace(send_action=sent.append, get_observation=lambda: dict(zip(NAMES, p0))),
                    substituted, fps=30, status=reports.append, clock=lambda: 1.0, rim_z_m=0.21)
    runner.trusted_grasp, runner.trusted_tcp = trusted, 0.0741
    runner.target = runner.present()
    assert runner.command("run policy") is True
    assert runner.chunk is None and runner.queue == [] and reports[-1]["ok"] is False and not sent

    with pytest.raises(ValueError, match="conflicts with"):
        JawGate(stock_spec, stock_kin, library=substituted, rim_z_m=0.21, trusted_grasp=trusted)

    valid_sub = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [p0], "policy": [p0]}}
    if timed:
        valid_sub["policy_playback"] = {"start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": cal_spec}
    else:
        valid_sub["jaw_gate"] = cal_spec
    runner_ok = Runner(SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0))),
                       valid_sub, fps=30, status=lambda _r: None, clock=lambda: 1.0, rim_z_m=0.21)
    runner_ok.trusted_grasp, runner_ok.trusted_tcp = trusted, 0.0741
    runner_ok.target = runner_ok.present()
    assert runner_ok.command("run policy") is True and runner_ok.chunk == "policy"
    active = runner_ok.policy_playback.jaw_gate if timed else runner_ok.jaw_gate
    assert active.tcp_x_m == pytest.approx(0.0741)


def _assert_main_pins_startup_tcp(tmp_path, monkeypatch, *, timed, env_tcp, expected_tcp, conflict_tcp):
    import bus_watchdog
    from cell_policy_shape import jaw_gate_spec
    import chunk_runner as cr
    from grasp_planner import load_kinematics
    import guarded_native
    import motor_health
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    rim = 0.21
    if env_tcp is None:
        monkeypatch.delenv("ROSY_OMX_TCP_X_M", raising=False)
        ok_kin = load_kinematics(None)[0]
    else:
        monkeypatch.setenv("ROSY_OMX_TCP_X_M", env_tcp)
        ok_kin = load_kinematics(None, float(env_tcp))[0]
    conflict_kin = load_kinematics(None, conflict_tcp)[0]
    ok_spec = dict(jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, ok_kin, rim_z_m=rim))
    conflict_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, conflict_kin, rim_z_m=rim), "tcp_x_m": conflict_tcp}
    sent, reports = [], []
    robot = SimpleNamespace(
        bus=SimpleNamespace(read=lambda reg, j: 300),
        send_action=lambda a: sent.append(a) or a,
        get_observation=lambda: dict(zip(NAMES, p0)),
    )

    cfg_path, init_path, conflict_path, ok_path = (
        tmp_path / name for name in ("record.json", "init.json", "conflict.json", "ok.json")
    )
    cfg_path.write_text(json.dumps({
        "robot": {"type": "omx_follower", "port": "/dev/fake-session", "max_relative_target": 5},
        "dataset": {"fps": 30},
    }), encoding="utf-8")
    init_path.write_text(json.dumps({
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
        "source": {"rim_z_m": rim}, "chunks": {"home": [p0], "grasp_pick": [p0]},
    }), encoding="utf-8")
    now = time.monotonic()
    for path, extra_tcp, spec in ((conflict_path, conflict_tcp, conflict_spec), (ok_path, None, ok_spec)):
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
               **({"tcp_x_m": extra_tcp} if extra_tcp is not None else {}),
               "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]}}
        if timed:
            lib["policy_playback"] = {"start": now + 0.5, "observed": now, "max_age": 5.0, "max_step": 0.16,
                                      "jaw_gate": spec}
        else:
            lib["jaw_gate"] = spec
        path.write_text(json.dumps(lib), encoding="utf-8")

    outcomes = {}

    class SessionRunner(cr.Runner):
        def run(self, lines):
            outcomes["trusted_tcp"] = self.trusted_tcp
            outcomes["trusted_grasp_tcp"] = (self.trusted_grasp or {}).get("tcp_x_m")
            self.target = self.present()
            assert self.command(f"load {conflict_path}") is True
            assert self.command("run policy") is True
            outcomes["conflict"] = (self.chunk, reports[-1]["ok"], reports[-1].get("error"))
            assert self.command(f"load {ok_path}") is True
            assert self.command("run policy") is True
            active = self.policy_playback.jaw_gate if timed else self.jaw_gate
            outcomes["ok"] = (self.chunk, active.tcp_x_m)
            self.policy_playback = self.jaw_gate = self._trailing_jaw_gate = None
            self.chunk, self.queue = None, []

    class StatusCaptureRunner(SessionRunner):
        def __init__(self, *args, **kwargs):
            orig_status = kwargs.get("status")
            kwargs["status"] = lambda row: (reports.append(row), orig_status(row))
            super().__init__(*args, **kwargs)

    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", SimpleNamespace(
        OmxFollowerConfig=lambda **values: values, OmxFollower=lambda config: robot))
    monkeypatch.setattr(guarded_native, "connect_passive", lambda *a, **k: None)
    monkeypatch.setattr(guarded_native, "close_device", lambda *a: None)
    monkeypatch.setattr(motor_health, "MotorHealth", lambda: SimpleNamespace(end=lambda: None))
    monkeypatch.setattr(bus_watchdog, "arm", lambda *a: None)
    monkeypatch.setattr(cr, "fifo_lines", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cr, "runtime_context", lambda *a, **k: {"scope": "simulation"})
    monkeypatch.setattr(cr, "Runner", StatusCaptureRunner)
    cr.main(["--config", str(cfg_path), "--library", str(init_path), "--io", str(tmp_path / "io")])

    assert outcomes["trusted_tcp"] == pytest.approx(expected_tcp)
    assert outcomes["trusted_grasp_tcp"] == pytest.approx(expected_tcp)
    assert outcomes["conflict"][0] is None and outcomes["conflict"][1] is False
    assert "conflicts with" in outcomes["conflict"][2]
    assert outcomes["ok"][0] == "policy" and outcomes["ok"][1] == pytest.approx(expected_tcp)
    assert not sent


@pytest.mark.parametrize("timed", [True, False])
def test_chunk_runner_main_pins_env_tcp_against_replacement_load(tmp_path, monkeypatch, timed):
    _assert_main_pins_startup_tcp(tmp_path, monkeypatch, timed=timed, env_tcp="0.0740",
                                  expected_tcp=0.0740, conflict_tcp=0.09193)


@pytest.mark.parametrize("timed", [True, False])
def test_chunk_runner_main_pins_stock_tcp_against_replacement_load(tmp_path, monkeypatch, timed):
    _assert_main_pins_startup_tcp(tmp_path, monkeypatch, timed=timed, env_tcp=None,
                                  expected_tcp=0.09193, conflict_tcp=0.0740)
