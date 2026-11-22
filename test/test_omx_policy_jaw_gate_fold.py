"""OMX policy jaw-gate stop-fold, interrupt-fold, and trailing-gate HOLD tests."""
from pathlib import Path
import json
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_timing import _make_guard_bus  # noqa: E402


@pytest.mark.parametrize("bad_mode", ["missing_joint", "nan_joint", "partial_hw_status", "group_hw_timeout"])
def test_native_incomplete_encoder_sample_holds_without_torque_off_in_playback_and_latched_hold(bad_mode):
    from guarded_device import NAMES as DEV_NAMES, normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from omx_adapter.chunk_library import NAMES

    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    for latched in (False, True):
        now = [10.0]
        bus = _make_guard_bus(p_above)
        assert "read" not in vars(bus)
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        present = [normalized(bus, bus.raw)[n] for n in NAMES]
        action = dict(zip(NAMES, present))
        motion.send(action)
        motion.tracking, motion.aligned_since = True, 0.0
        if bad_mode == "group_hw_timeout":
            bus.hw_status = {DEV_NAMES[0]: ConnectionError("motor offline")}
        orig_sync_read = bus.sync_read
        seen = []

        def faulty_sync_read(reg, motors=None, normalize=True, num_retry=0):
            seen.append(reg)
            if bad_mode == "group_hw_timeout" and reg == "Hardware_Error_Status":
                raise ConnectionError("Failed to sync read 'Hardware_Error_Status'")
            data = orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            if bad_mode == "missing_joint" and reg == "Present_Position":
                return {k: v for k, v in data.items() if k != DEV_NAMES[-1]}
            if bad_mode == "nan_joint" and reg == "Present_Position":
                return {**data, DEV_NAMES[-1]: float("nan")}
            if bad_mode == "partial_hw_status" and reg == "Hardware_Error_Status":
                return {k: v for k, v in data.items() if k != DEV_NAMES[-1]}
            return data

        bus.sync_read = faulty_sync_read
        now[0] += 1 / 30
        with pytest.raises(GoalRejected) as rejected:
            motion.send(
                action,
                goal_check=(None if latched else lambda *_a: None),
                hold_on_read_error=True,
                allow_stale_hold=latched,
            )
        assert "Hardware_Error_Status" in seen
        if bad_mode == "group_hw_timeout":
            assert DEV_NAMES[-1] in bus.hw_read_seen
        assert rejected.value.can_send_hold is False and motion.failed is False
        assert all(v == 1 for v in bus.torque.values()) and not any(e[0] == "off" for e in bus.events)

        # Recover cleanly past > 0.5 s gap during latched hold, even with effort sampling due.
        bus.sync_read = orig_sync_read
        bus.hw_status = {}
        if latched:
            now[0] += 2.0
            motion.send(action, hold_on_read_error=True, allow_stale_hold=True)
            assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    # Default hold_on_read_error=False and real Hardware_Error_Status hard faults (even on partial/group-timeout read) cut torque.
    for hard_mode, allow_stale in (
        ("default_partial", False),
        ("hw_error", False),
        ("mixed_hw_error", False),
        ("mixed_hw_error", True),
        ("missing_pos_with_hw_error", False),
        ("missing_pos_with_hw_error", True),
        ("group_hw_timeout_with_fault", False),
        ("group_hw_timeout_with_fault", True),
    ):
        now = [10.0]
        bus = _make_guard_bus(p_above)
        assert "read" not in vars(bus)
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        present = [normalized(bus, bus.raw)[n] for n in NAMES]
        action = dict(zip(NAMES, present))
        motion.send(action)
        if hard_mode == "group_hw_timeout_with_fault":
            bus.hw_status = {DEV_NAMES[0]: ConnectionError("motor offline"), DEV_NAMES[-1]: 1}
        orig_sync_read = bus.sync_read
        seen = []

        def hard_sync_read(reg, motors=None, normalize=True, num_retry=0):
            seen.append(reg)
            if hard_mode == "group_hw_timeout_with_fault" and reg in ("Present_Position", "Hardware_Error_Status"):
                raise ConnectionError(f"Failed to sync read '{reg}'")
            data = orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            if hard_mode == "default_partial" and reg == "Present_Position":
                return {k: v for k, v in data.items() if k != DEV_NAMES[-1]}
            if hard_mode == "hw_error" and reg == "Hardware_Error_Status":
                return {**data, DEV_NAMES[0]: 1}
            if hard_mode == "mixed_hw_error" and reg == "Hardware_Error_Status":
                return {k: (1 if k == DEV_NAMES[-1] else v) for k, v in data.items() if k != DEV_NAMES[0]}
            if hard_mode == "missing_pos_with_hw_error":
                if reg == "Present_Position":
                    return {k: v for k, v in data.items() if k != DEV_NAMES[0]}
                if reg == "Hardware_Error_Status":
                    return {**data, DEV_NAMES[-1]: 1}
            return data

        bus.sync_read = hard_sync_read
        now[0] += 1 / 30
        with pytest.raises(ValueError) as exc:
            motion.send(action, hold_on_read_error=(hard_mode != "default_partial"), allow_stale_hold=allow_stale)
        assert not isinstance(exc.value, GoalRejected)
        if hard_mode != "default_partial":
            assert "Hardware_Error_Status" in seen
            assert "hardware error" in str(exc.value)
        if hard_mode == "group_hw_timeout_with_fault":
            assert DEV_NAMES[-1] in bus.hw_read_seen
        assert motion.failed is True and any(e[0] == "off" for e in bus.events)


def test_interrupt_guard_verdict_requires_all_six_motors_zero_before_approving_shutdown():
    import signal

    from chunk_runner_guards import MOTORS, NAMES
    import chunk_runner_interrupt as ci

    def verdict(torque):
        reports = []
        runner = SimpleNamespace(
            human_hold_latched=True, _interrupt={"signal": signal.SIGTERM, "phase": "hold"}, target=[0.0] * 6,
            last_present=[0.0] * 6, hold_file=None, signals=[], _off_approved=None,
            report=lambda **kw: reports.append(kw), hold=lambda *a, **k: None,
        )
        return ci._guard_verdict(runner, torque, "following error"), runner, reports

    for partial_torque in (
        {"shoulder_pan": 0},
        dict.fromkeys(MOTORS[:5], 0),
        {**dict.fromkeys(MOTORS, 0), "shoulder_pan.pos": False},
        {**dict.fromkeys(MOTORS, 0), "shoulder_pan.pos": 1},
    ):
        ok, runner, reports = verdict(partial_torque)
        assert ok is False and runner._off_approved is None and ci.gate_allows(runner, []) is False
        assert reports[-1].get("partial_guard_stop") is True

    for unknown_torque in (
        dict.fromkeys(MOTORS, False),
        {"shoulder_pan": 0, "shoulder_pan.pos": 1},
        {"error": "timeout"},
    ):
        ok, runner, reports = verdict(unknown_torque)
        assert ok is False and runner._off_approved is None and ci.gate_allows(runner, []) is False
        assert not reports[-1].get("partial_guard_stop")

    for zero_torque in (dict.fromkeys(MOTORS, 0), dict.fromkeys(NAMES, 0)):
        ok, runner, _reports = verdict(zero_torque)
        assert ok is True and runner._off_approved == "guard stopped, every motor reads torque 0"


@pytest.mark.parametrize("rim_source", ["runner_rim", "params_rim", "library_source_rim", "trusted_grasp_rim", "jaw_gate_rim"])
def test_runner_refuses_handoff_min_z_below_configured_rim_clearance(rim_source):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin = load_kinematics(None, 0.0741)[0]
    rim = 0.1712
    full_spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}
    spec = full_spec if rim_source == "jaw_gate_rim" else {k: v for k, v in full_spec.items() if k != "rim_z_m"}

    for expect_ok, min_z in ((False, 0.1562), (True, 0.2012)):
        reports = []
        library = {
            "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
            "chunks": {"home": [p0], **({} if rim_source == "trusted_grasp_rim" else {"grasp_pick": [p0]}), "policy": [p0]},
            "policy_playback": {
                "start": 1.0, "observed": 0.98, "max_age": 0.6, "max_step": 0.16, "jaw_gate": spec,
                "handoff": {
                    "min_z": min_z, "x": spec["x"], "y": spec["y"], "yaw_deg": spec["yaw_deg"],
                    "xy_tol": 0.012, "angle_tol_deg": 7.0, "close_target": 50.0, "empty_stop": 49.0,
                    "hold_frames": 8, "tcp_x_m": 0.0741,
                },
            },
        }
        if rim_source == "library_source_rim":
            library["source"] = {"rim_z_m": rim}
        robot = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, p0)))
        runner = Runner(
            robot, library, fps=30, status=reports.append, clock=lambda: 1.01,
            params=({"policy.source_rim_z_m": rim} if rim_source == "params_rim" else None),
            rim_z_m=(rim if rim_source == "runner_rim" else None),
        )
        if rim_source == "trusted_grasp_rim":
            runner.trusted_grasp = {"chunks": {"grasp_pick": [p0]}, "source": {"rim_z_m": rim}, "tcp_x_m": 0.0741}
            runner.trusted_tcp = 0.0741
        runner.target = runner.present()
        runner.command("run policy")
        if expect_ok:
            assert runner.chunk == "policy"
            assert runner.policy_playback.handoff.spec["min_z"] == pytest.approx(min_z)
        else:
            assert runner.chunk is None and runner.policy_playback is None and runner.queue == []
            assert reports[-1]["ok"] is False and "below source rim clearance" in reports[-1]["error"]


def test_record_session_binds_site_rim_to_chunk_runner_and_rejects_low_handoff(tmp_path, monkeypatch):
    import contextlib
    import bus_watchdog
    from cell_policy_shape import jaw_gate_spec
    import chunk_runner as cr
    from grasp_planner import load_kinematics
    import guarded_native
    from omx_adapter.chunk_library import NAMES, SCHEMA
    import omx_incident
    import record_session as rs
    import record_session_cli as rsc

    monkeypatch.chdir(tmp_path)
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin = load_kinematics(None, 0.0741)[0]
    rim = 0.1712
    spec_no_rim = {k: v for k, v in jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim).items()
                   if k != "rim_z_m"}
    spec_no_rim["tcp_x_m"] = 0.0741
    now = time.monotonic()

    cfg_path, cell_cfg_path, init_path, low_path, ok_path = (
        tmp_path / name for name in ("record.json", "cell.json", "init.json", "low.json", "ok.json")
    )
    cfg_path.write_text(json.dumps({
        "robot": {"type": "omx_follower", "id": "f", "port": "/dev/serial/by-id/usb-follower", "use_degrees": False,
                  "max_relative_target": 5,
                  "cameras": {"top": {"type": "opencv", "index_or_path": "/dev/v4l/by-id/top", "width": 640,
                                      "height": 480, "fps": 30}}},
        "teleop": {"type": "omx_leader", "id": "l", "port": "/dev/serial/by-id/usb-leader"},
        "dataset": {"repo_id": "local/x", "root": str(tmp_path / "ds"), "single_task": "t", "fps": 30,
                    "num_episodes": 1, "episode_time_s": 1, "reset_time_s": 1, "push_to_hub": False, "private": True},
        "resume": False,
    }), encoding="utf-8")
    cell_cfg_path.write_text(json.dumps({"sites": {"belt": {"surface_z": 0.049, "rim_z": rim}}}), encoding="utf-8")
    init_path.write_text(json.dumps({
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "grasp_pick": [p0]},
    }), encoding="utf-8")
    for path, min_z in ((low_path, 0.1562), (ok_path, 0.2012)):
        path.write_text(json.dumps({
            "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
            "chunks": {"home": [p0], "policy": [p0]},
            "policy_playback": {
                "start": now + 0.5, "observed": now, "max_age": 5.0, "max_step": 0.16, "jaw_gate": spec_no_rim,
                "handoff": {
                    "min_z": min_z, "x": spec_no_rim["x"], "y": spec_no_rim["y"], "yaw_deg": spec_no_rim["yaw_deg"],
                    "xy_tol": 0.012, "angle_tol_deg": 7.0, "close_target": 50.0, "empty_stop": 49.0,
                    "hold_frames": 8, "tcp_x_m": 0.0741,
                },
            },
        }), encoding="utf-8")

    class FakeArm:
        def __init__(self, motors):
            self.motors, self.motor = motors, None

        def read(self, name):
            return self.motors[self.motor].get(name, 0)

        def write(self, name, value):
            self.motors[self.motor][name] = value

        cleanup_read, cleanup_write = read, write

        def close(self):
            pass

    def make_bus(port, _baud):
        if "follower" in port:
            return FakeArm({m: {"model": mdl, "mode": md, "torque": 0, "hw_error": 0, **rs.BASELINE}
                            for m, (mdl, md) in rs.FOLLOWER.items()})
        return FakeArm({m: {"torque": 0, "hw_error": 0} for m in rs.LEADER})

    sent, reports, spawned, outcomes = [], [], [], {}
    runner_robot = SimpleNamespace(
        bus=SimpleNamespace(read=lambda reg, j: 300),
        send_action=lambda a: sent.append(a) or a,
        get_observation=lambda: dict(zip(NAMES, p0)),
    )

    class SessionRunner(cr.Runner):
        def run(self, lines):
            outcomes["rim_z_m"] = self.rim_z_m
            self.target = self.present()
            assert self.command(f"load {low_path}") is True
            assert self.command("run policy") is True
            outcomes["low"] = (self.chunk, reports[-1]["ok"], reports[-1].get("error"))
            assert self.command(f"load {ok_path}") is True
            assert self.command("run policy") is True
            outcomes["ok"] = (self.chunk, self.policy_playback.handoff.spec["min_z"])
            self.policy_playback = self.jaw_gate = self._trailing_jaw_gate = None
            self.chunk, self.queue = None, []

    class StatusCaptureRunner(SessionRunner):
        def __init__(self, *args, **kwargs):
            orig_status = kwargs.get("status")
            kwargs["status"] = lambda row: (reports.append(row), orig_status(row))
            super().__init__(*args, **kwargs)

    def fake_popen(command, **_kwargs):
        spawned.append(command)
        assert command[1].endswith("chunk_runner.py") and f"--rim-z-m={rim}" in command
        cr.main(command[2:])
        return SimpleNamespace(pid=999, wait=lambda timeout=None: 0, poll=lambda: 0)

    monkeypatch.setattr(rs, "load_caps", lambda *a, **k: {})
    monkeypatch.setattr(rs, "model_tuning", lambda: {})
    monkeypatch.setattr(rs, "robot_tuning", lambda *a: {})
    monkeypatch.setattr(rs, "protect_signals", lambda: None)
    monkeypatch.setattr(rs, "session_lock", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(rs, "no_interrupts", contextlib.nullcontext)
    monkeypatch.setattr(rs, "SerialBus", make_bus)
    monkeypatch.setattr(rs, "subprocess", SimpleNamespace(
        Popen=fake_popen, run=lambda *a, **k: SimpleNamespace(stdout="", returncode=0), TimeoutExpired=TimeoutError))
    monkeypatch.setattr(omx_incident, "refuse_if_held", lambda *a, **k: None)
    monkeypatch.setattr(omx_incident, "after_session", lambda *a, **k: {})
    monkeypatch.setitem(sys.modules, "motor_health", SimpleNamespace(
        MotorHealth=lambda: SimpleNamespace(end=lambda: None), finish_snapshot=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", SimpleNamespace(
        OmxFollowerConfig=lambda **values: values, OmxFollower=lambda config: runner_robot))
    monkeypatch.setattr(guarded_native, "connect_passive", lambda *a, **k: None)
    monkeypatch.setattr(guarded_native, "close_device", lambda *a: None)
    monkeypatch.setattr(bus_watchdog, "arm", lambda *a: None)
    monkeypatch.setattr(cr, "fifo_lines", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cr, "runtime_context", lambda *a, **k: {"scope": "simulation"})
    monkeypatch.setattr(cr, "Runner", StatusCaptureRunner)

    with pytest.raises(SystemExit) as exited:
        rsc.main(["--config", str(cfg_path), "--caps", "unused.json", "--chunks", str(init_path),
                  "--io", str(tmp_path / "io"), "--cell-config", str(cell_cfg_path), "--site", "belt"])
    assert exited.value.code == 0 and len(spawned) == 1
    assert outcomes["rim_z_m"] == pytest.approx(rim)
    assert outcomes["low"][0] is None and outcomes["low"][1] is False
    assert "below source rim clearance" in outcomes["low"][2]
    assert outcomes["ok"][0] == "policy" and outcomes["ok"][1] == pytest.approx(0.2012)
    assert not sent


@pytest.mark.parametrize("mode", ["direct_low_transit", "interrupt_low_transit", "interrupt_clear_transit"])
def test_stop_fold_and_interrupt_fold_keep_jaw_gate_active_through_recovery_lift(tmp_path, mode):
    import signal

    from cell_policy_shape import jaw_gate_spec, jaw_zone_error
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from grasp_planner import load_kinematics
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    rim = 0.1712
    kin = load_kinematics(None, 0.0741)[0]
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}

    now, reports = [10.0], []
    bus = _make_guard_bus(p0)
    orig_write = bus.sync_write

    def tracking_sync_write(reg, values, *, normalize=True):
        orig_write(reg, values, normalize=normalize)
        if reg == "Goal_Position":
            bus.raw = dict(values)

    bus.sync_write = tracking_sync_write
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [home], "grasp_pick": [p0], "policy": [p0]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 5.0, "max_step": 0.16, "jaw_gate": spec},
        **({"transit": {"shoulder_lift.pos": -42.0, "elbow_flex.pos": -5.0, "wrist_flex.pos": 40.0}}
           if mode == "interrupt_clear_transit" else {}),
    }
    lib_path = tmp_path / f"fold-{mode}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    now[0] += 1 / 30
    runner.tick()
    assert runner.fault is None and runner.chunk is None and runner._trailing_jaw_gate is not None

    if mode == "direct_low_transit":
        assert runner.command("stop fold") is True
        assert runner.chunk == "park" and runner._trailing_jaw_gate is not None
        for _ in range(500):
            now[0] += 1 / 30
            runner.tick()
            if runner.human_hold_latched or runner.chunk is None:
                break
        assert runner.human_hold_latched is True and motion.failed is False
        assert all(v == 1 for v in bus.torque.values())
        assert any("jaw" in r.get("policy_stop", "") for r in reports)
    else:
        runner.signals.append(signal.SIGINT)
        ended = False
        for _ in range(2500):
            now[0] += 1 / 30
            ended = ci.interrupt_tick(runner, f"run {runner.chunk}" if runner.chunk else "tick", tick_or_report)
            if ended or getattr(runner, "_interrupt", {}).get("phase") == "hold":
                break
        if mode == "interrupt_low_transit":
            assert ended is False and runner._interrupt["phase"] == "hold"
            assert runner.human_hold_latched is True and runner._off_approved is None
            assert ci.gate_allows(runner, runner.signals) is False
            assert motion.failed is False and all(v == 1 for v in bus.torque.values())
            assert any("jaw" in r.get("policy_stop", "") for r in reports)
        else:
            assert ended is True and runner._off_approved == "park settled and home"
            assert ci.gate_allows(runner, runner.signals) is True

    for event in bus.events:
        if event[0] == "goal":
            frame = [normalized(bus, event[1])[n] for n in NAMES]
            assert jaw_zone_error([frame], kin, spec) is None


def test_ordinary_guard_failure_requires_six_motor_torque_off_readback_before_close(tmp_path):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from grasp_planner import load_kinematics
    from guarded_device import NAMES as DEV_NAMES, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin = load_kinematics(None, 0.0741)[0]
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=0.1712), "tcp_x_m": 0.0741}

    for partial in (True, False):
        now, reports = [10.0], []
        bus = _make_guard_bus(p0)
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        present = [normalized(bus, bus.raw)[n] for n in NAMES]
        motion.send(dict(zip(NAMES, present)))
        motion.tracking, motion.aligned_since = True, 0.0

        library = {
            "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
            "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0, p0]},
            "jaw_gate": spec,
        }
        lib_path = tmp_path / f"guard-fail-{partial}.json"
        lib_path.write_text(json.dumps(library), encoding="utf-8")
        raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
        guarded = Guarded(raw_robot, motion)
        runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
        runner.target = runner.present()
        runner.signals = []
        runner.hold_file = tmp_path / f"hold-{partial}.json"
        assert runner.command(f"load {lib_path}") and runner.command("run policy")

        if partial:
            orig_disable = bus.disable_torque

            def partial_disable(motors=None, **kwargs):
                if motors == "shoulder_lift" or (isinstance(motors, (list, tuple)) and "shoulder_lift" in motors):
                    raise ConnectionError("shoulder_lift disable failed")
                orig_disable(motors=motors, **kwargs)

            bus.disable_torque = partial_disable

        orig_sync_read = bus.sync_read

        def fault_sync_read(reg, motors=None, normalize=True, num_retry=0):
            data = orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            return {**data, DEV_NAMES[0]: 1} if reg == "Hardware_Error_Status" else data

        bus.sync_read = fault_sync_read
        now[0] += 1 / 30
        ended = ci.interrupt_tick(runner, "run policy", tick_or_report)

        assert motion.failed is True
        if partial:
            assert ended is False and runner._off_approved is None and ci.gate_allows(runner, []) is False
            assert runner.human_hold_latched is True and runner._interrupt["phase"] == "hold"
            assert any(r.get("partial_guard_stop") is True for r in reports)
            assert json.loads(runner.hold_file.read_text(encoding="utf-8"))["label"] == "PARTIAL_GUARD_STOP"
            goals_before = sum(1 for e in bus.events if e[0] == "goal")
            now[0] += 1.5
            assert ci.interrupt_tick(runner, "run policy", tick_or_report) is False
            assert ci.gate_allows(runner, []) is False
            assert sum(1 for e in bus.events if e[0] == "goal") == goals_before
            bus.torque["shoulder_lift"] = 0
            now[0] += 1.5
            assert ci.interrupt_tick(runner, "run policy", tick_or_report) is True
            assert runner._off_approved == "guard stopped, every motor reads torque 0"
            assert ci.gate_allows(runner, []) is True
        else:
            assert ended is True and runner._off_approved == "guard stopped, every motor reads torque 0"
            assert ci.gate_allows(runner, []) is True


@pytest.mark.parametrize("cmd", ["chain park", "goto home"])
def test_chain_park_and_goto_keep_trailing_jaw_gate_active_below_rim(tmp_path, cmd):
    from cell_policy_shape import jaw_gate_spec, jaw_zone_error
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    rim = 0.1712
    kin = load_kinematics(None, 0.0741)[0]
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=rim), "tcp_x_m": 0.0741}

    now, reports = [10.0], []
    bus = _make_guard_bus(p0)
    orig_write = bus.sync_write

    def tracking_sync_write(reg, values, *, normalize=True):
        orig_write(reg, values, normalize=normalize)
        if reg == "Goal_Position":
            bus.raw = dict(values)

    bus.sync_write = tracking_sync_write
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [home], "grasp_pick": [p0], "policy": [p0]},
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 5.0, "max_step": 0.16, "jaw_gate": spec},
    }
    lib_path = tmp_path / f"trailing-{cmd.replace(' ', '_')}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    now[0] += 1 / 30
    runner.tick()
    assert runner.fault is None and runner.chunk is None and runner._trailing_jaw_gate is not None

    assert runner.command(cmd) is True
    assert not any(r.get("command") == cmd and r.get("ok") is False for r in reports)
    assert runner.human_hold_latched is True if cmd.startswith("jog ") else runner._trailing_jaw_gate is not None
    assert runner.chunk == ("park" if cmd == "chain park" else "goto home")
    for _ in range(500):
        now[0] += 1 / 30
        runner.tick()
        if runner.human_hold_latched or runner.chunk is None:
            break
    assert runner.human_hold_latched is True and motion.failed is False
    assert all(v == 1 for v in bus.torque.values())
    assert any("jaw" in r.get("policy_stop", "") for r in reports)
    for event in bus.events:
        if event[0] == "goal":
            frame = [normalized(bus, event[1])[n] for n in NAMES]
            assert jaw_zone_error([frame], kin, spec) is None


@pytest.mark.parametrize("short_of_home", [False, True])
def test_direct_stop_fold_holds_torque_on_when_park_ends_unsettled_or_short_of_home(short_of_home):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import check_chunk_settled
    from omx_adapter.chunk_library import NAMES, SCHEMA

    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    pose = [15.0, -40.0, 40.0, 45.0, 10.0, 46.6] if short_of_home else list(home)
    present = list(pose) if short_of_home else [home[0] + 5.0, *home[1:]]
    now, reports = [0.0], []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    robot = SimpleNamespace(
        get_observation=lambda: dict(zip(NAMES, present)),
        send_action=lambda action: action,
    )
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.signals = []
    runner.chunk, runner.queue, runner.target = "park", [], list(pose)
    runner._stop_after_park = "stop fold"
    runner.settle_since = 0.0
    runner.last_body = list(present[:5]) if short_of_home else None
    check_time = 0.5 if short_of_home else 4.0
    error = 0.0 if short_of_home else 5.0

    check_chunk_settled(runner, present, error, check_time, lambda _name, default: default)

    assert runner._stopped is False and runner._park_settled is False
    assert runner.human_hold_latched is True
    assert ci.gate_allows(runner, []) is False
    assert reports[-1]["command"] == "stop fold"
    assert reports[-1]["ok"] is False and reports[-1]["folded"] is False
    assert reports[-1]["hold"] is True and reports[-1]["person_needed"] is True
    assert "torque stays ON" in reports[-1]["error"]


@pytest.mark.parametrize("mode", ["all_zero", "partial_then_zero", "partial_then_release"])
def test_startup_alignment_guard_failure_uses_six_motor_torque_off_readback_and_release(tmp_path, mode, monkeypatch):
    from cell_policy_shape import jaw_gate_spec
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report, wait_aligned_before_start
    from grasp_planner import load_kinematics
    from guarded_device import NAMES as DEV_NAMES, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    kin = load_kinematics(None, 0.0741)[0]
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=0.1712), "tcp_x_m": 0.0741}

    now, reports = [10.0], []
    bus = _make_guard_bus(p0)
    bus.enable_torque()
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    assert motion.tracking is False

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {"home": [p0], "grasp_pick": [p0], "policy": [p0]},
        "jaw_gate": spec,
    }
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0], sleep=lambda _s: None)
    runner.target = runner.present()
    runner.signals = []
    runner.hold_file = tmp_path / f"align-hold-{mode}.json"

    if mode != "all_zero":
        orig_disable = bus.disable_torque

        def partial_disable(motors=None, **kwargs):
            if motors == "shoulder_lift" or (isinstance(motors, (list, tuple)) and "shoulder_lift" in motors):
                raise ConnectionError("shoulder_lift disable failed")
            orig_disable(motors=motors, **kwargs)

        bus.disable_torque = partial_disable

    if mode == "partial_then_release":
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)

    orig_sync_read = bus.sync_read

    def fault_sync_read(reg, motors=None, normalize=True, num_retry=0):
        data = orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
        return {**data, DEV_NAMES[0]: 1} if reg == "Hardware_Error_Status" else data

    bus.sync_read = fault_sync_read
    res = wait_aligned_before_start(runner, lambda: [], 1 / 30)

    assert motion.failed is True
    if mode == "all_zero":
        assert res is False
        assert runner._off_approved == "guard stopped, every motor reads torque 0"
        assert ci.gate_allows(runner, []) is True
    else:
        assert res is True
        assert runner.human_hold_latched is True and runner._interrupt["phase"] == "hold"
        assert ci.gate_allows(runner, []) is False
        assert json.loads(runner.hold_file.read_text(encoding="utf-8"))["label"] == "PARTIAL_GUARD_STOP"
        if mode == "partial_then_zero":
            bus.torque["shoulder_lift"] = 0
            now[0] += 1.5
            assert ci.interrupt_tick(runner, "start", tick_or_report) is True
            assert runner._off_approved == "guard stopped, every motor reads torque 0"
            assert ci.gate_allows(runner, []) is True
        else:
            runner.signals.append(12)
            now[0] += 1.5
            assert ci.interrupt_tick(runner, "start", tick_or_report) is True
            assert runner._off_approved == "operator release (SIGUSR2)"
            assert ci.gate_allows(runner, runner.signals) is True


def test_direct_stop_fold_status_write_error_on_unsettled_park_latches_hold():
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import check_chunk_settled
    from omx_adapter.chunk_library import NAMES, SCHEMA

    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    present = [home[0] + 5.0, *home[1:]]
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    robot = SimpleNamespace(get_observation=lambda: dict(zip(NAMES, present)), send_action=lambda action: action)

    def io_failure(_row):
        raise OSError("disk full")

    runner = Runner(robot, library, fps=30, status=io_failure, clock=lambda: 0.0)
    runner.signals = []
    runner.chunk, runner.queue, runner.target = "park", [], list(home)
    runner._stop_after_park = "stop fold"
    runner.settle_since, runner.last_body = 0.0, None

    check_chunk_settled(runner, present, 5.0, 4.0, lambda _name, default: default)

    assert runner.human_hold_latched is True
    assert runner._stopped is False and runner._park_settled is False
    assert ci.gate_allows(runner, []) is False


@pytest.mark.parametrize("blocker", ["hard_fault", "guard_held", "no_home", "encoder_error"])
def test_stop_fold_refuses_torque_off_when_extended_and_park_blocked(blocker):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    reports, fail_obs = [], [False]

    def read_obs():
        if fail_obs[0]:
            raise TimeoutError("encoder read timed out")
        return dict(zip(NAMES, p0))

    robot = SimpleNamespace(
        get_observation=read_obs,
        send_action=lambda action: action,
        motion=SimpleNamespace(held=("shoulder_lift",) if blocker == "guard_held" else (), failed=False),
    )
    chunks = {"policy": [p0]} if blocker == "no_home" else {"home": [home], "policy": [p0]}
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": chunks}
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: 0.0)
    runner.signals = []
    runner.target = list(p0)
    runner.last_present = list(p0)
    if blocker == "hard_fault":
        runner.fault = "temperature 70 C"
    elif blocker == "encoder_error":
        fail_obs[0] = True

    assert runner.command("stop fold") is True
    assert runner.human_hold_latched is True
    assert runner.chunk is None
    assert ci.gate_allows(runner, []) is False
    assert reports[-1]["command"] == "stop fold"
    assert reports[-1]["ok"] is False and reports[-1]["folded"] is False
    assert reports[-1]["hold"] is True and reports[-1]["person_needed"] is True


@pytest.mark.parametrize("cmd", ["goto inside_bad", "jog shoulder_lift.pos 4.5", "run dip_bad", "splice dip_bad"])
def test_successor_outside_to_inside_reentry_keeps_trailing_jaw_gate_active(tmp_path, cmd):
    from cell_policy_shape import jaw_gate_spec, jaw_zone_error
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    p_out = [38.8, -22.0, 2.0, 55.0, 25.0, 49.0]
    p_in = [38.8, -17.5, 2.0, 55.0, 25.0, 49.0]
    dip_bad = [[38.8, round(-22.0 + 0.15 * k, 3), 2.0, 55.0, 25.0, 49.0] for k in range(31)]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    kin = load_kinematics(None, 0.0741)[0]
    spec = {**jaw_gate_spec({"chunks": {"grasp_pick": [p0]}}, kin, rim_z_m=0.1712), "tcp_x_m": 0.0741}

    now, reports = [10.0], []
    bus = _make_guard_bus(p_out)
    orig_write = bus.sync_write

    def tracking_sync_write(reg, values, *, normalize=True):
        orig_write(reg, values, normalize=normalize)
        if reg == "Goal_Position":
            bus.raw = dict(values)

    bus.sync_write = tracking_sync_write
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0

    library = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "tcp_x_m": 0.0741,
        "chunks": {
            "home": [home], "grasp_pick": [p0], "policy": [p_out],
            "inside_bad": [p_in], "dip_bad": dip_bad,
        },
        "policy_playback": {"start": 10.01, "observed": 9.98, "max_age": 5.0, "max_step": 0.16, "jaw_gate": spec},
    }
    lib_path = tmp_path / f"reentry-{cmd.split()[0]}.json"
    lib_path.write_text(json.dumps(library), encoding="utf-8")
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command(f"load {lib_path}") and runner.command("run policy")

    now[0] += 1 / 30
    runner.tick()
    assert runner.fault is None and runner.chunk is None and runner._trailing_jaw_gate is not None

    assert runner.command(cmd) is True
    assert not any(r.get("command") == cmd and r.get("ok") is False for r in reports)
    assert runner.human_hold_latched is True if cmd.startswith("jog ") else runner._trailing_jaw_gate is not None
    for _ in range(500):
        now[0] += 1 / 30
        runner.tick()
        if runner.human_hold_latched or runner.chunk is None:
            break
    assert runner.human_hold_latched is True and motion.failed is False
    assert all(v == 1 for v in bus.torque.values())
    assert any("jaw" in r.get("policy_stop", "") for r in reports)
    for event in bus.events:
        if event[0] == "goal":
            frame = [normalized(bus, event[1])[n] for n in NAMES]
            assert jaw_zone_error([frame], kin, spec) is None


@pytest.mark.parametrize("at_home", [False, True])
def test_startup_alignment_stop_fold_holds_when_extended_and_closes_when_home(tmp_path, at_home):
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import wait_aligned_before_start
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    extended = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    start_pose = home if at_home else extended
    now, reports = [10.0], []
    bus = _make_guard_bus(start_pose)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    assert motion.tracking is False and all(v == 1 for v in bus.torque.values())

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0], sleep=lambda _s: None)
    runner.target = runner.present()
    runner.signals = []
    runner.hold_file = tmp_path / f"startup-stop-fold-{at_home}.json"
    queue = ["stop fold"]

    res = wait_aligned_before_start(runner, lambda: [queue.pop(0)] if queue else [], 1 / 30)

    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    if at_home:
        assert res is False and runner.human_hold_latched is False
        assert ci.gate_allows(runner, []) is True
        assert reports[-1]["command"] == "stop fold" and reports[-1]["ok"] is True and reports[-1]["folded"] is True
    else:
        assert res is True and runner.human_hold_latched is True
        assert ci.gate_allows(runner, []) is False
        assert any(
            r.get("command") == "stop fold" and r.get("ok") is False and r.get("folded") is False
            and r.get("hold") is True and r.get("person_needed") is True
            for r in reports
        )


@pytest.mark.parametrize("fail_kind", ["trace", "live"])
def test_telemetry_write_error_mid_stop_fold_park_latches_hold_without_jaw_gate(tmp_path, fail_kind, monkeypatch):
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    now, reports = [10.0], []
    bus = _make_guard_bus(p0)
    orig_write = bus.sync_write

    def tracking_sync_write(reg, values, *, normalize=True):
        orig_write(reg, values, normalize=normalize)
        if reg == "Goal_Position":
            bus.raw = dict(values)

    bus.sync_write = tracking_sync_write
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = None
    cmds = ["stop fold"]
    triggered = {"queued": 0}
    state = {"ticks": 0, "hold_ticks": 0}

    def maybe_fail_trace(row):
        if fail_kind == "trace" and getattr(runner, "_stop_after_park", None) == "stop fold" and len(runner.queue) > 2:
            triggered["queued"] = len(runner.queue)
            raise OSError("disk full")

    def maybe_fail_live(_row):
        if fail_kind == "live" and getattr(runner, "_stop_after_park", None) == "stop fold" and len(runner.queue) > 2:
            triggered["queued"] = len(runner.queue)
            raise OSError("disk full")

    def step(_dt):
        state["ticks"] += 1
        assert state["ticks"] <= 500
        now[0] += 1 / 30
        if runner.human_hold_latched:
            assert ci.gate_allows(runner, []) is False
            state["hold_ticks"] += 1
            if state["hold_ticks"] == 2:
                runner.signals.append(ci.OPERATOR_RELEASE)

    runner = Runner(guarded, library, fps=30, status=reports.append, live=maybe_fail_live,
                    clock=lambda: now[0], sleep=step)
    runner.trace = maybe_fail_trace
    runner.signals = []
    runner.hold_file = tmp_path / f"mid-park-{fail_kind}.json"
    runner.run(lambda: [cmds.pop(0)] if cmds else [])

    assert triggered["queued"] > 2
    assert runner.human_hold_latched is True and runner._stopped is False
    assert state["hold_ticks"] == 2
    assert not ci.folded(runner.last_present, home)
    assert runner._off_approved == "operator release (SIGUSR2)"
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())


def test_contact_and_status_write_error_during_stop_fold_park_latches_hold():
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    fail_status = [False]

    def status_cb(_row):
        if fail_status[0]:
            raise OSError("disk full")

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    robot = SimpleNamespace(get_observation=lambda: dict(zip(NAMES, p0)), send_action=lambda action: action)
    runner = Runner(robot, library, fps=30, status=status_cb, clock=lambda: 0.0)
    runner.target = runner.present()
    runner.signals = []
    assert runner.command("stop fold") is True
    assert runner.chunk == "park" and runner._stop_after_park == "stop fold"

    fail_status[0] = True
    runner.hold(p0, "contact in park: wrist_roll lag")

    assert runner.human_hold_latched is True and runner._stop_after_park is None
    assert ci.gate_allows(runner, []) is False


def test_startup_alignment_state_status_failure_before_stop_fold_stays_in_active_hold(tmp_path):
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import wait_aligned_before_start
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    now = [10.0]
    bus = _make_guard_bus(p0)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    assert motion.tracking is False and all(v == 1 for v in bus.torque.values())

    def failing_status(_row):
        raise OSError("disk full")

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=failing_status, clock=lambda: now[0], sleep=lambda _s: None)
    runner.target = runner.present()
    runner.signals = []
    runner.hold_file = tmp_path / "startup-state-fail.json"
    batch = [["state", "stop fold"]]

    res = wait_aligned_before_start(runner, lambda: batch.pop(0) if batch else [], 1 / 30)

    assert res is True
    assert runner.human_hold_latched is True
    assert ci.gate_allows(runner, []) is False
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())


def test_fifo_read_error_mid_stop_fold_park_stays_in_hold_and_blocks_close(tmp_path, monkeypatch):
    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    stub = SimpleNamespace(
        _stop_after_park="stop fold", _park_settled=False, human_hold_latched=False,
        robot=SimpleNamespace(motion=SimpleNamespace(failed=False)),
    )
    assert ci.gate_allows(stub, []) is False

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    now, reports = [10.0], []
    bus = _make_guard_bus(p0)
    orig_write = bus.sync_write

    def tracking_sync_write(reg, values, *, normalize=True):
        orig_write(reg, values, normalize=normalize)
        if reg == "Goal_Position":
            bus.raw = dict(values)

    bus.sync_write = tracking_sync_write
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = None
    cmds = ["stop fold"]
    state = {"ticks": 0, "hold_ticks": 0, "queued": 0}

    def lines():
        if cmds:
            return [cmds.pop(0)]
        if getattr(runner, "_stop_after_park", None) == "stop fold" and len(runner.queue) > 2:
            state["queued"] = len(runner.queue)
            raise OSError("injected FIFO read error")
        return []

    def step(_dt):
        state["ticks"] += 1
        assert state["ticks"] <= 500
        now[0] += 1 / 30
        if runner.human_hold_latched:
            assert ci.gate_allows(runner, []) is False
            state["hold_ticks"] += 1
            if state["hold_ticks"] == 2:
                runner.signals.append(ci.OPERATOR_RELEASE)

    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0], sleep=step)
    runner.signals = []
    runner.hold_file = tmp_path / "fifo-err-hold.json"
    runner.run(lines)

    assert state["queued"] > 2
    assert runner.human_hold_latched is True and runner._stopped is False
    assert state["hold_ticks"] == 2
    assert not ci.folded(runner.last_present, home)
    assert runner._off_approved == "operator release (SIGUSR2)"
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())


@pytest.mark.parametrize("prior_contact", [False, True])
@pytest.mark.parametrize("abort_kind", ["contact", "thermal", "overload"])
def test_aborted_stop_fold_on_contact_or_thermal_keeps_torque_off_blocked_and_stops_idle_park(prior_contact, abort_kind):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    now, reports, sent = [0.0], [], []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    motion = SimpleNamespace(held={}, effort_pwm={}, pwm_limits={}, failed=False, release_hold=lambda: None)
    robot = SimpleNamespace(
        get_observation=lambda: dict(zip(NAMES, p0)),
        send_action=lambda action: (sent.append(dict(action)), action)[1],
        motion=motion,
    )
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    if prior_contact:
        runner.fault = "contact in descend_pick: earlier lag"

    assert runner.command("stop fold") is True
    assert runner.chunk == "park" and runner._stop_after_park == "stop fold" and len(runner.queue) > 2

    if abort_kind == "contact":
        runner.hold(p0, "contact in park: wrist_roll lag")
    elif abort_kind == "thermal":
        runner.ticks = 29
        runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [70, 35, 35, 35, 35, 35]}
        now[0] += 1 / 30
        runner.tick()
    else:
        motion.held = {"wrist_flex": {"since": 0.0, "temp": 30, "clear_since": None}}
        now[0] += 1 / 30
        runner.tick()

    assert runner.human_hold_latched is True
    assert runner._stop_after_park is None and runner.chunk is None and runner.queue == []
    assert ci.gate_allows(runner, []) is False
    assert any(
        r.get("ok") is False and r.get("hold") is True and r.get("folded") is False and r.get("person_needed") is True
        for r in reports
    )
    if abort_kind == "overload":
        assert any("overload" in (r.get("error") or "") for r in reports)
        assert [runner.target[i] for i in (0, 3, 4)] == [p0[i] for i in (0, 3, 4)]
        motion.held.clear()

    held_body = list(runner.target[:5])
    now[0] += 1 / 30
    runner.tick()
    assert runner.target[:5] == held_body
    assert [sent[-1][n] for n in NAMES[:5]] == held_body

    now[0] += 120.0
    assert runner.idle() is False
    assert runner.chunk is None and runner.queue == [] and runner.idle_parks == 0


@pytest.mark.parametrize("status_fails", [False, True])
def test_thermal_fault_after_contact_hold_preserves_latched_target(status_fails):
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    sag = [38.8, -8.2, 3.5, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    pos = [list(p0)]
    now, reports, fail_status = [0.0], [], [False]
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}

    def status_cb(row):
        if fail_status[0]:
            raise OSError("disk full")
        reports.append(row)

    robot = SimpleNamespace(get_observation=lambda: dict(zip(NAMES, pos[0])), send_action=lambda action: action)
    runner = Runner(robot, library, fps=30, status=status_cb, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = []
    assert runner.command("stop fold") is True
    runner.hold(p0, "contact in park: wrist_roll lag")
    frozen_target = list(runner.target)

    pos[0] = list(sag)
    if status_fails:
        fail_status[0] = True
    runner.ticks = 29
    runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [70, 35, 35, 35, 35, 35]}
    now[0] += 1 / 30
    runner.tick()

    assert runner.target == frozen_target
    assert runner.fault == "temperature 70 C"
    assert runner.human_hold_latched is True
    assert ci.gate_allows(runner, []) is False
    if not status_fails:
        assert any(
            "temperature 70 C" in (r.get("error") or "")
            and r.get("ok") is False and r.get("hold") is True and r.get("person_needed") is True
            for r in reports
        )


def test_signal_driven_fold_overload_keeps_bounded_relief_and_release_in_interrupt_hold(monkeypatch):
    import signal

    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    pos = [list(p0)]
    now, reports, released = [0.0], [], []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    motion = SimpleNamespace(
        held={}, effort_pwm={"wrist_flex": 300}, pwm_limits={"wrist_flex": 300}, failed=False,
        release_hold=lambda: (released.append(now[0]), motion.held.clear()),
    )
    robot = SimpleNamespace(
        get_observation=lambda: dict(zip(NAMES, pos[0])),
        send_action=lambda action: (pos.__setitem__(0, [action[n] for n in NAMES]), action)[1],
        motion=motion,
    )
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    runner.signals = [signal.SIGINT]

    for _ in range(30):
        now[0] += 1 / 30
        ci.interrupt_tick(runner, "tick", tick_or_report)
        if getattr(runner, "_interrupt", {}).get("phase") == "park":
            break
    assert runner._interrupt["phase"] == "park" and runner.chunk == "park"

    motion.held = {"wrist_flex": {"since": now[0], "temp": 30, "clear_since": None}}
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "run park", tick_or_report) is False
    assert runner._interrupt["phase"] == "hold" and runner.human_hold_latched is True

    target_at_hold = list(runner.target)
    for _ in range(5):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
    assert abs(runner.target[1] - home[1]) < abs(target_at_hold[1] - home[1])
    assert abs(runner.target[2] - home[2]) < abs(target_at_hold[2] - home[2])
    assert [runner.target[i] for i in (0, 3, 4)] == [target_at_hold[i] for i in (0, 3, 4)]
    assert [runner.target[i] for i in (0, 3, 4)] == [pytest.approx(p0[i], abs=1e-3) for i in (0, 3, 4)]
    assert ci.gate_allows(runner, runner.signals) is False

    motion.effort_pwm["wrist_flex"] = 120
    for _ in range(20):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
    assert len(released) == 1 and motion.held == {}

    post_release_body = list(runner.target[:5])
    for _ in range(3):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
    assert runner.target[:5] == post_release_body
    assert ci.gate_allows(runner, runner.signals) is False

    runner.signals.append(ci.OPERATOR_RELEASE)
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "tick", tick_or_report) is True
    assert ci.gate_allows(runner, runner.signals) is True


def test_overload_after_interrupt_hold_latched_pins_frozen_joint_before_release(monkeypatch):
    import signal

    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    p0 = [10.0, 10.0, 10.0, 10.0, 10.0, 46.6]
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 46.6]
    pos = [[10.0, 10.0, 10.0, 7.0, 10.0, 46.6]]
    now, reports, sent = [0.0], [], []
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    motion = SimpleNamespace(
        held={"wrist_flex": {"since": 0.0, "temp": 30, "clear_since": None}},
        effort_pwm={"wrist_flex": 10}, pwm_limits={"wrist_flex": 100}, failed=False,
    )
    motion.release_hold = lambda: motion.held.clear()

    def send_action(action):
        sent.append(dict(action))
        for i, (m_name, name) in enumerate(zip(ci.MOTORS[:5], NAMES[:5])):
            if m_name not in motion.held:
                pos[0][i] = action[name]
        return action

    robot = SimpleNamespace(get_observation=lambda: dict(zip(NAMES, pos[0])), send_action=send_action, motion=motion)
    runner = Runner(robot, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = list(p0)
    runner.signals = [signal.SIGINT]
    runner.human_hold_latched = True
    runner._interrupt = {
        "signal": signal.SIGINT, "phase": "hold", "seen": 1, "release_from": 1,
        "may_move": False, "since": 0.0, "still": 0, "last": None, "deadline": 120.0,
    }

    for _ in range(20):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False

    assert motion.held == {}
    assert runner.target[3] == pytest.approx(7.0)
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
    assert sent[-1]["wrist_flex.pos"] == pytest.approx(7.0)
    assert ci.gate_allows(runner, runner.signals) is False

    runner.signals.append(ci.OPERATOR_RELEASE)
    now[0] += 1 / 30
    assert ci.interrupt_tick(runner, "tick", tick_or_report) is True
    assert ci.gate_allows(runner, runner.signals) is True


@pytest.mark.parametrize("mode", ["ordinary_run", "stop_fold"])
def test_fresh_runner_first_overload_hold_keeps_ticking_without_attribute_error(tmp_path, monkeypatch, mode):
    from test_omx_policy_timing import _make_guard_bus

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"fresh-overload-{mode}.json"))
    p0 = [38.8, -10.0, 2.0, 55.0, -14.0, 49.0]
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    p_move = [38.8, -10.0, 2.0, 58.5, -14.0, 49.0]
    bus = _make_guard_bus(p0)
    now, reports = [10.0], []
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], shed_load=True)
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0
    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": [p_move] * 90}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
    assert runner.shed_clear is None
    runner.target = list(p0)
    assert runner.command("stop fold" if mode == "stop_fold" else "run reach") is True

    # Stall wrist_flex near ~3 deg lag (< 5 deg cutoff, > 2 deg cap) so the first overload hold triggers cleanly via NativeJointMotion.
    bus.pwms["wrist_flex"] = 310
    for _ in range(90):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
        for m in BODY:
            if m != "wrist_flex":
                bus.raw[m] = bus.goals[m]
            elif abs(bus.goals[m] - bus.raw[m]) > 34:
                bus.raw[m] = bus.goals[m] - (34 if bus.goals[m] > bus.raw[m] else -34)
        if "wrist_flex" in motion.held:
            break
    assert "wrist_flex" in motion.held and bus.goals["wrist_flex"] == bus.raw["wrist_flex"]

    # Subsequent ticks continue running without AttributeError on shed_clear, keeping guard active.
    for _ in range(5):
        now[0] += 1 / 30
        assert ci.interrupt_tick(runner, "tick", tick_or_report) is False
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    if mode == "stop_fold":
        assert runner.human_hold_latched is True and ci.gate_allows(runner, []) is False
