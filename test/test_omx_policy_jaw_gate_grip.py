"""OMX policy interrupt voltage check and committed-grip HOLD preservation tests."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_timing import _make_guard_bus  # noqa: E402


@pytest.mark.parametrize("mode", ["signal_interrupt_hold", "runner_tick_latched_hold"])
def test_interrupt_hold_enforces_voltage_limit_when_health_read_succeeds(tmp_path, monkeypatch, mode):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"volt-hold-{mode}.json"))
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    fault_phase = [False]

    class VoltBus(type(bus)):
        def sync_read(self, reg, motors=None, *, normalize=True, num_retry=0):
            vals = super().sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            if fault_phase[0] and reg == "Present_Input_Voltage" and isinstance(vals, dict) and "wrist_flex" in vals:
                vals["wrist_flex"] = 80
            return vals

        def read(self, reg, motor, **kwargs):
            if fault_phase[0] and reg == "Present_Input_Voltage" and motor == "wrist_flex":
                return 80
            return super().read(reg, motor, **kwargs)

    bus.__class__ = VoltBus
    assert "read" not in vars(bus)
    monitor = MotorHealth(tmp_path / f"volt-hold-{mode}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    present_start = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion.send(dict(zip(NAMES, present_start)))
    motion.tracking, motion.aligned_since = True, 0.0
    now[0] = 10.05
    motion.send(dict(zip(NAMES, present_start)), hold_on_read_error=True, allow_stale_hold=True)

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [present_start]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target, runner.signals = runner.present(), []
    runner.hold(present_start, "jaw gate rejected", human=True)
    if mode == "signal_interrupt_hold":
        runner.signals.append(signal.SIGTERM)
        assert ci.interrupt_tick(runner, "human-hold", tick_or_report) is False
        assert runner._interrupt["phase"] == "hold"

    # Complete healthy temperature/PWM/current telemetry succeeds while check_effort is throttled (0.03 s < 0.2 s).
    fault_phase[0] = True
    now[0] = 10.08
    runner.ticks = 29
    if mode == "signal_interrupt_hold":
        assert ci.interrupt_tick(runner, "human-hold", tick_or_report) is True
    else:
        with pytest.raises(ValueError, match=r"wrist_flex: voltage 80 outside configured limits 95\.\.160"):
            runner.tick()
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())
    assert monitor.stop_reasons == ["voltage limit"]


@pytest.mark.parametrize(
    "case",
    [
        "probe_temp_omitted",
        "sample_temp_omitted",
        "probe_volt_omitted",
        "sample_volt_omitted",
        "sample_hw_omitted",
        "partial_batch_hit_skips_missing",
    ],
)
def test_partial_batch_response_probes_omitted_motor_for_hard_limit(tmp_path, monkeypatch, case):
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"partial-batch-{case}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    fault_phase, fallback_reads = [False], []

    class PartialBatchBus(type(bus)):
        def sync_read(self, reg, motors=None, *, normalize=True, num_retry=0):
            vals = super().sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            if not fault_phase[0]:
                return vals
            if case == "partial_batch_hit_skips_missing" and reg == "Present_Temperature":
                return {"shoulder_pan": 71}
            target_reg = (
                "Present_Temperature"
                if "temp" in case
                else ("Present_Input_Voltage" if "volt" in case else "Hardware_Error_Status")
            )
            if reg == target_reg and isinstance(vals, dict):
                vals.pop("wrist_flex", None)
            return vals

        def read(self, reg, motor, **kwargs):
            if fault_phase[0]:
                fallback_reads.append((reg, motor))
                if motor == "wrist_flex":
                    if reg == "Present_Temperature":
                        return 71
                    if reg == "Present_Input_Voltage":
                        return 80
                    if reg == "Hardware_Error_Status":
                        return 32
            return super().read(reg, motor, **kwargs)

    bus.__class__ = PartialBatchBus
    assert "read" not in vars(bus)
    now = [10.0]
    monitor = MotorHealth(tmp_path / f"partial-batch-{case}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    fault_phase[0] = True
    expected = {
        "probe_temp_omitted": "wrist_flex: temperature 71 >= configured limit 70",
        "sample_temp_omitted": "wrist_flex: temperature 71 >= configured limit 70",
        "probe_volt_omitted": r"wrist_flex: voltage 80 outside configured limits 95\.\.160",
        "sample_volt_omitted": r"wrist_flex: voltage 80 outside configured limits 95\.\.160",
        "sample_hw_omitted": "wrist_flex: hardware error 32",
        "partial_batch_hit_skips_missing": "shoulder_pan: temperature 71 >= configured limit 70",
    }[case]
    with pytest.raises(ValueError, match=expected):
        if case.startswith("probe_"):
            monitor.probe_limits(motion)
        else:
            monitor.sample(motion, bus.raw, dict.fromkeys(BODY, 0), 10.30, allow_gap=True)
    if case == "partial_batch_hit_skips_missing":
        assert fallback_reads == []
    elif "temp" in case:
        assert fallback_reads == [("Present_Temperature", "wrist_flex")]
    elif "volt" in case:
        assert fallback_reads == [("Present_Input_Voltage", "wrist_flex")]
    else:
        assert fallback_reads == [("Hardware_Error_Status", "wrist_flex")]


def test_jaw_gate_rejection_discards_pending_grip_close_and_jog_commands(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics, norm_to_rad
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_open = [38.8, -10.0, 2.0, 55.0, -14.0, 75.0]
    kin = load_kinematics(None, 0.0741)[0]
    pose = kin.fk([norm_to_rad(v) for v in p_open[:5]])

    def make_gate_spec(*, tol_deg=20.0):
        return {
            "x": round(float(pose.x), 5),
            "y": round(float(pose.y), 5),
            "z_m": round(float(pose.z) + 0.015, 5),
            "xy_radius_m": 0.08,
            "yaw_deg": round(math.degrees(pose.yaw), 4),
            "tol_deg": tol_deg,
            "max_tilt_rad": 0.45,
            "square": False,
            "tcp_x_m": 0.0741,
        }

    def run_plain_case(cmd: str, *, align_during_cmd: bool):
        obs, sent, reports, now = [dict(zip(NAMES, p_open))], [], [], [10.0]
        lib = {
            "schema": SCHEMA,
            "names": NAMES,
            "fps": 30,
            "gripper_closed": 49.0,
            "tcp_x_m": 0.0741,
            "chunks": {"home": [p_open], "policy": [p_open]},
            "jaw_gate": make_gate_spec(tol_deg=20.0),
        }
        robot = SimpleNamespace(
            send_action=lambda a: sent.append(dict(a)) or a,
            get_observation=lambda: dict(obs[0]),
        )
        runner = Runner(robot, lib, fps=30, status=reports.append, clock=lambda: now[0])
        runner.target = runner.present()
        assert runner.command("run policy")
        now[0] += 1 / 30
        runner.tick()
        assert runner.chunk is None and runner._trailing_jaw_gate is not None
        if not align_during_cmd:
            obs[0]["wrist_roll.pos"] = 31.0  # misaligned (+45)
        assert runner.command(cmd)
        if align_during_cmd:
            obs[0]["wrist_roll.pos"] = 31.0  # drifts misaligned before tick
        now[0] += 1 / 30
        runner.tick()
        assert runner.human_hold_latched is True
        assert runner.target[5] == pytest.approx(75.0)
        assert sent and all(row["gripper.pos"] == pytest.approx(75.0) for row in sent)

    # 1 & 4: Immediate jaw-gate rejection on `grip 49` and `jog gripper.pos -5` under trailing jaw gate.
    run_plain_case("grip 49", align_during_cmd=False)
    run_plain_case("jog gripper.pos -5", align_during_cmd=False)
    # 2: `grip 49` admitted while aligned, then jaw drifts misaligned before `runner.tick()`'s gate check.
    run_plain_case("grip 49", align_during_cmd=True)

    # 3: `grip 49` rejected inside `Guarded.send_action_checked` `goal_check` (`GoalRejected`).
    now, reports = [10.0], []
    bus = _make_guard_bus(p_open)
    present_open = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, present_open)))
    motion.tracking, motion.aligned_since = True, 0.0
    pose_bus = kin.fk([norm_to_rad(v) for v in present_open[:5]])
    lib_g = {
        "schema": SCHEMA,
        "names": NAMES,
        "fps": 30,
        "gripper_closed": 49.0,
        "tcp_x_m": 0.0741,
        "chunks": {"home": [present_open], "policy": [present_open]},
        "jaw_gate": {
            "x": round(float(pose_bus.x), 5),
            "y": round(float(pose_bus.y), 5),
            "z_m": round(float(pose_bus.z) + 0.015, 5),
            "xy_radius_m": 0.08,
            "yaw_deg": round(math.degrees(pose_bus.yaw) + 3.5, 4),
            "tol_deg": 5.0,
            "max_tilt_rad": 0.45,
            "square": False,
            "tcp_x_m": 0.0741,
        },
    }
    raw_reads, orig_sync = [0], bus.sync_read

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if raw_reads[0] and reg == "Present_Position" and not normalize:
            # Fires on NativeJointMotion.prepare() after Runner.present() in check_runner_jaw_gate already passed.
            raw_reads[0] = 0
            bus.raw["wrist_roll"] += 40
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), lib_g, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = runner.present()
    assert runner.command("run policy")
    now[0] += 1 / 30
    runner.tick()
    assert runner.chunk is None and runner._trailing_jaw_gate is not None
    assert runner.command("grip 49")
    assert runner.target[5] == pytest.approx(49.0)
    writes_before = len([e for e in bus.events if e[0] == "goal"])
    raw_reads[0] = 1
    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True
    assert runner.target[5] == pytest.approx(present_open[5], abs=0.2)
    goal_writes = [normalized(bus, e[1])["gripper.pos"] for e in bus.events[writes_before:] if e[0] == "goal"]
    assert goal_writes and all(g >= 74.0 for g in goal_writes)


def test_holding_grip_rejection_preserves_last_committed_grip_target(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from grasp_planner import load_kinematics, norm_to_rad
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 55.0]
    kin = load_kinematics(None, 0.0741)[0]
    pose = kin.fk([norm_to_rad(v) for v in p_hold[:5]])
    gate_spec = {
        "x": round(float(pose.x), 5),
        "y": round(float(pose.y), 5),
        "z_m": round(float(pose.z) + 0.015, 5),
        "xy_radius_m": 0.08,
        "yaw_deg": round(math.degrees(pose.yaw), 4),
        "tol_deg": 20.0,
        "max_tilt_rad": 0.45,
        "square": False,
        "tcp_x_m": 0.0741,
    }

    def setup_plain(present_grip: float):
        p_cur = [*p_hold[:5], present_grip]
        obs, sent, reports, now = [dict(zip(NAMES, p_cur))], [], [], [10.0]
        lib = {
            "schema": SCHEMA,
            "names": NAMES,
            "fps": 30,
            "gripper_closed": 49.0,
            "tcp_x_m": 0.0741,
            "chunks": {"home": [p_hold], "policy": [p_hold]},
            "jaw_gate": dict(gate_spec),
        }
        robot = SimpleNamespace(send_action=lambda a: sent.append(dict(a)) or a, get_observation=lambda: dict(obs[0]))
        runner = Runner(robot, lib, fps=30, status=reports.append, clock=lambda: now[0])
        runner.target = list(p_hold)
        runner.holding = True
        assert runner.command("run policy")
        now[0] += 1 / 30
        runner.tick()
        assert runner.chunk is None and runner._trailing_jaw_gate is not None and runner.holding is True
        sent.clear()
        return runner, obs, sent, now

    # 1: Codex R62 reproduction — holding=True at 55.0, grip 49 admitted while aligned, then jaw drifts before tick().
    runner, obs, sent, now = setup_plain(55.0)
    assert runner.command("grip 49")
    assert runner.target[5] == pytest.approx(49.0)
    obs[0]["wrist_roll.pos"] = 31.0
    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True and runner.target[5] == pytest.approx(55.0)
    assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)

    # 2: Back-to-back uncommitted grip 52 then grip 49 before tick() still preserves original 55.0.
    runner, obs, sent, now = setup_plain(55.0)
    assert runner.command("grip 52") and runner.command("grip 49")
    obs[0]["wrist_roll.pos"] = 31.0
    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True and runner.target[5] == pytest.approx(55.0)
    assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)

    # 3: Uncommitted open (`grip 70`) while pinching (`present=58, target=55`) preserves both 55.0 and holding=True.
    runner, obs, sent, now = setup_plain(58.0)
    assert runner.command("grip 70")
    assert runner.holding is False and runner.target[5] == pytest.approx(70.0)
    obs[0]["wrist_roll.pos"] = 31.0
    now[0] += 1 / 30
    runner.tick()
    assert runner.human_hold_latched is True and runner.holding is True and runner.target[5] == pytest.approx(55.0)
    assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)

    # 4: Real Guarded `GoalRejected` while holding=True preserves committed 55.0 and never writes 49.0 to bus.
    now, reports = [10.0], []
    bus = _make_guard_bus(p_hold)
    present_hold = [normalized(bus, bus.raw)[n] for n in NAMES]
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, present_hold)))
    motion.tracking, motion.aligned_since = True, 0.0
    pose_bus = kin.fk([norm_to_rad(v) for v in present_hold[:5]])
    lib_g = {
        "schema": SCHEMA,
        "names": NAMES,
        "fps": 30,
        "gripper_closed": 49.0,
        "tcp_x_m": 0.0741,
        "chunks": {"home": [present_hold], "policy": [present_hold]},
        "jaw_gate": {
            "x": round(float(pose_bus.x), 5),
            "y": round(float(pose_bus.y), 5),
            "z_m": round(float(pose_bus.z) + 0.015, 5),
            "xy_radius_m": 0.08,
            "yaw_deg": round(math.degrees(pose_bus.yaw) + 3.5, 4),
            "tol_deg": 5.0,
            "max_tilt_rad": 0.45,
            "square": False,
            "tcp_x_m": 0.0741,
        },
    }
    raw_reads, orig_sync = [0], bus.sync_read

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if raw_reads[0] and reg == "Present_Position" and not normalize:
            raw_reads[0] = 0
            bus.raw["wrist_roll"] += 40
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner_g = Runner(Guarded(raw_robot, motion), lib_g, fps=30, status=reports.append, clock=lambda: now[0])
    runner_g.target = list(present_hold)
    runner_g.holding = True
    assert runner_g.command("run policy")
    now[0] += 1 / 30
    runner_g.tick()
    assert runner_g.chunk is None and runner_g._trailing_jaw_gate is not None
    assert runner_g.command("grip 49")
    assert runner_g.target[5] == pytest.approx(49.0)
    writes_before = len([e for e in bus.events if e[0] == "goal"])
    raw_reads[0] = 1
    now[0] += 1 / 30
    runner_g.tick()
    assert runner_g.human_hold_latched is True
    assert runner_g.target[5] == pytest.approx(present_hold[5], abs=0.2)
    goal_writes = [normalized(bus, e[1])["gripper.pos"] for e in bus.events[writes_before:] if e[0] == "goal"]
    assert goal_writes and all(g >= 54.0 for g in goal_writes)


def test_grip_status_write_failure_restores_committed_grip_during_hold(tmp_path):
    from chunk_runner_interrupt import interrupt_step
    from chunk_runner_run import Runner
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 55.0]
    p_pinch = [*p_hold[:5], 58.0]

    def make_runner(*, fail_status=False, clear_last_present=False):
        sent, now = [], [10.0]
        lib = {
            "schema": SCHEMA,
            "names": NAMES,
            "fps": 30,
            "gripper_closed": 49.0,
            "chunks": {"home": [p_hold]},
        }
        robot = SimpleNamespace(
            send_action=lambda a: sent.append(dict(a)) or a,
            get_observation=lambda: dict(zip(NAMES, p_pinch)),
        )

        def status(row):
            if fail_status and row.get("command") in ("grip 70", "grip 49", "jog gripper 15"):
                raise OSError("disk full")

        runner = Runner(robot, lib, fps=30, status=status, clock=lambda: now[0])
        runner.target = list(p_hold)
        runner.holding = True
        if not clear_last_present:
            runner.last_present = list(p_pinch)
        return runner, sent, now

    # 1: Codex R63 reproduction — holding=True at 55, grip 70 status write raises OSError -> direct HOLD keeps 55.0.
    for clear_last in (False, True):
        runner, sent, now = make_runner(fail_status=True, clear_last_present=clear_last)
        assert runner.command("grip 70") is True
        assert runner.human_hold_latched is True
        assert runner._committed_grip is None
        assert runner.target[5] == pytest.approx(55.0)
        assert runner.holding is True
        now[0] += 1 / 30
        runner.tick()
        assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)

    # 2: Status write OSError after grip 49 (close) and jog gripper 15 (open) also restores committed 55.0 and holding.
    for cmd in ("grip 49", "jog gripper 15"):
        runner, sent, now = make_runner(fail_status=True)
        assert runner.command(cmd) is True
        assert runner.human_hold_latched is True
        assert runner._committed_grip is None
        assert runner.target[5] == pytest.approx(55.0)
        assert runner.holding is True
        now[0] += 1 / 30
        runner.tick()
        assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)

    # 3: Direct human-hold and interrupt _start before tick() after uncommitted grip 70 also restore 55.0 and holding.
    runner_h, sent_h, now_h = make_runner(fail_status=False)
    assert runner_h.command("grip 70") is True and runner_h.command("human-hold") is True
    assert runner_h.human_hold_latched is True and runner_h._committed_grip is None
    assert runner_h.target[5] == pytest.approx(55.0) and runner_h.holding is True
    now_h[0] += 1 / 30
    runner_h.tick()
    assert sent_h and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent_h)

    runner_s, _, _ = make_runner(fail_status=False)
    assert runner_s.command("grip 70") is True
    runner_s.signals = [2]
    assert interrupt_step(runner_s) is False
    assert runner_s._committed_grip is None and runner_s.target[5] == pytest.approx(55.0) and runner_s.holding is True


def test_uncommitted_grip_open_keeps_holding_protection_on_encoder_timeout(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 55.0]
    bus = _make_guard_bus(p_hold)
    committed_pose = [normalized(bus, bus.raw)[n] for n in NAMES]
    now, reports = [10.0], []
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, committed_pose)))
    motion.tracking, motion.aligned_since = True, 0.0

    # Object holds the jaws open past EMPTY_MARGIN while holding=True at committed_pose[5].
    bus.raw["gripper"] += 150
    motion.last_present = None
    pinched_pose = [normalized(bus, bus.raw)[n] for n in NAMES]
    assert pinched_pose[5] > committed_pose[5] + 2.5

    lib = {
        "schema": SCHEMA,
        "names": NAMES,
        "fps": 30,
        "gripper_closed": 49.0,
        "chunks": {"home": [committed_pose]},
    }
    timeout_armed, orig_sync = [False], bus.sync_read

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if timeout_armed[0] and reg == "Present_Position" and not normalize:
            timeout_armed[0] = False
            raise TimeoutError("Present_Position timeout")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target = list(committed_pose)
    runner.holding = True
    runner.last_present = list(pinched_pose)

    assert runner.command("grip 70") is True
    assert runner.holding is False and runner.target[5] == pytest.approx(70.0)
    assert runner._committed_grip[0] == pytest.approx(committed_pose[5]) and runner._committed_grip[1] is True

    # Present_Position timeout on the first send after grip 70 must hold with torque ON, not cut torque.
    timeout_armed[0] = True
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False
    assert not any(e[0] == "off" for e in bus.events)
    assert runner.human_hold_latched is True and runner._committed_grip is None
    assert runner.target[5] == pytest.approx(committed_pose[5], abs=0.2) and runner.holding is True

    writes_before = len([e for e in bus.events if e[0] == "goal"])
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False
    goal_writes = [normalized(bus, e[1])["gripper.pos"] for e in bus.events[writes_before:] if e[0] == "goal"]
    assert goal_writes and all(g == pytest.approx(committed_pose[5], abs=0.3) for g in goal_writes)
    assert all(normalized(bus, e[1])["gripper.pos"] < 60.0 for e in bus.events if e[0] == "goal")

    # Encoder timeout inside Runner.report() during grip 70 (no jaw gate) also latches HOLD and keeps 55.0.
    sent, now2 = [], [10.0]
    p_pinch = [*p_hold[:5], 58.0]
    raise_obs = [True]

    def get_obs():
        if raise_obs[0]:
            raise TimeoutError("encoder timeout")
        return dict(zip(NAMES, p_pinch))

    plain_robot = SimpleNamespace(send_action=lambda a: sent.append(dict(a)) or a, get_observation=get_obs)
    runner2 = Runner(plain_robot, lib, fps=30, status=reports.append, clock=lambda: now2[0])
    runner2.target = list(p_hold)
    runner2.holding = True
    runner2.last_present = list(p_pinch)
    assert runner2.command("grip 70") is True
    assert runner2.human_hold_latched is True and runner2._committed_grip is None
    assert runner2.target[5] == pytest.approx(55.0) and runner2.holding is True
    raise_obs[0] = False
    now2[0] += 1 / 30
    runner2.tick()
    assert sent and all(row["gripper.pos"] == pytest.approx(55.0) for row in sent)


def test_grip_open_keeps_hold_protection_across_retimed_ticks_until_release_confirmed(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 55.0]

    def make_guarded_pinch():
        bus = _make_guard_bus(p_hold)
        committed = [normalized(bus, bus.raw)[n] for n in NAMES]
        now, reports = [10.0], []
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        motion.send(dict(zip(NAMES, committed)))
        motion.tracking, motion.aligned_since = True, 0.0
        bus.raw["gripper"] += 150
        motion.last_present = None
        pinched = [normalized(bus, bus.raw)[n] for n in NAMES]
        lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [committed]}}
        timeout = [False]
        orig_sync = bus.sync_read

        def sync_read(reg, motors=None, normalize=True, num_retry=0):
            if timeout[0] and reg == "Present_Position" and not normalize:
                timeout[0] = False
                raise TimeoutError("Present_Position timeout")
            return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

        bus.sync_read = sync_read
        raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
        runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
        runner.target, runner.holding, runner.last_present = list(committed), True, list(pinched)
        return bus, motion, runner, now, timeout, committed

    # 1: Codex R65 reproduction — zero-elapsed tick 1 leaves goal closed, tick 2 Present_Position timeout still holds.
    bus, motion, runner, now, timeout, committed = make_guarded_pinch()
    assert runner.command("grip 70") is True and runner._release_until == pytest.approx(70.0)
    writes_0 = len([e for e in bus.events if e[0] == "goal"])
    runner.tick()
    assert len([e for e in bus.events if e[0] == "goal"]) > writes_0
    assert runner.human_hold_latched is False and runner._release_until == pytest.approx(70.0)
    assert runner._committed_grip == (pytest.approx(committed[5], abs=0.2), True)
    timeout[0] = True
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False and not any(e[0] == "off" for e in bus.events)
    assert runner.human_hold_latched is True and runner._committed_grip is None and runner._release_until is None
    assert runner.target[5] == pytest.approx(committed[5], abs=0.2) and runner.holding is True
    writes_2 = len([e for e in bus.events if e[0] == "goal"])
    now[0] += 1 / 30
    runner.tick()
    goal_writes = [normalized(bus, e[1])["gripper.pos"] for e in bus.events[writes_2:] if e[0] == "goal"]
    assert motion.failed is False and goal_writes and all(g < 60.0 for g in goal_writes)

    # 2: Partial retimed step on tick 1 + timeout on tick 2 keeps torque ON and freezes at last written goal (< 60).
    bus2, motion2, runner2, now2, timeout2, committed2 = make_guarded_pinch()
    assert runner2.command("grip 70") is True
    now2[0] += 1 / 30
    runner2.tick()
    last_written = normalized(bus2, bus2.goals)["gripper.pos"]
    assert committed2[5] <= last_written < 60.0 and runner2._release_until == pytest.approx(70.0)
    timeout2[0] = True
    now2[0] += 1 / 30
    runner2.tick()
    assert motion2.failed is False and not any(e[0] == "off" for e in bus2.events)
    assert runner2.human_hold_latched is True and runner2.target[5] == pytest.approx(last_written, abs=0.2)

    # 3: Fresh feedback reaching open target clears release protection without cutting torque.
    bus3, motion3, runner3, now3, _, _ = make_guarded_pinch()
    assert runner3.command("grip 70") is True
    for _ in range(250):
        now3[0] += 1 / 30
        runner3.tick()
        bus3.raw["gripper"] = bus3.goals["gripper"]
        if runner3._release_until is None:
            break
    now3[0] += 1 / 30
    runner3.tick()
    assert motion3.failed is False and runner3._release_until is None and runner3._committed_grip is None
    assert runner3.last_present[5] >= 68.0


def test_second_grip_release_after_confirm_and_regrasp_keeps_hold_protection(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 55.0]
    bus = _make_guard_bus(p_hold)
    committed_tick = bus.raw["gripper"]
    committed = [normalized(bus, bus.raw)[n] for n in NAMES]
    now, reports = [10.0], []
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, committed)))
    motion.tracking, motion.aligned_since = True, 0.0
    bus.raw["gripper"] = committed_tick + 150
    motion.last_present = None
    pinched = [normalized(bus, bus.raw)[n] for n in NAMES]
    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [committed]}}
    timeout, orig_sync = [False], bus.sync_read

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if timeout[0] and reg == "Present_Position" and not normalize:
            timeout[0] = False
            raise TimeoutError("Present_Position timeout")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target, runner.holding, runner.last_present = list(committed), True, list(pinched)

    # First open + confirmed release resets _release_until and _committed_grip to None.
    assert runner.command("grip 70") is True
    for _ in range(250):
        now[0] += 1 / 30
        runner.tick()
        bus.raw["gripper"] = bus.goals["gripper"]
        if runner._release_until is None:
            break
    now[0] += 1 / 30
    runner.tick()
    assert runner._release_until is None and runner._committed_grip is None

    # Second grasp + second open must not raise TypeError in _release_until tracking and must hold on timeout.
    runner.target[5] = committed[5]
    bus.raw["gripper"] = committed_tick + 150
    motion.command["gripper"] = committed_tick
    runner.holding, runner.last_present = True, list(pinched)
    assert runner.command("grip 70") is True
    assert runner.holding is False and runner._release_until == pytest.approx(70.0)
    assert runner._committed_grip == (pytest.approx(committed[5], abs=0.2), True)
    timeout[0] = True
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False and not any(e[0] == "off" for e in bus.events)
    assert runner.human_hold_latched is True and runner.holding is True
    assert runner.target[5] == pytest.approx(committed[5], abs=0.2)


@pytest.mark.parametrize("cmd", ["run release_place", "splice release_place", "chain run release_place"])
def test_release_chunk_partial_write_timeout_holds_last_written_goal(tmp_path, cmd):
    from chunk_runner import Guarded
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 50.0]
    bus = _make_guard_bus(p_hold)
    committed = [normalized(bus, bus.raw)[n] for n in NAMES]
    now, reports = [10.0], []
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, committed)))
    motion.tracking, motion.aligned_since = True, 0.0
    bus.raw["gripper"] += 150
    pinched = [normalized(bus, bus.raw)[n] for n in NAMES]
    lib = {
        "schema": SCHEMA,
        "names": NAMES,
        "fps": 30,
        "gripper_closed": 49.0,
        "chunks": {"home": [committed], "release_place": [[*committed[:5], 75.0]]},
    }
    timeout, orig_sync = [False], bus.sync_read

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if timeout[0] and reg == "Present_Position" and not normalize:
            timeout[0] = False
            raise TimeoutError("Present_Position timeout")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
    runner.target, runner.holding, runner.last_present = list(committed), True, list(pinched)

    assert runner.command(cmd) is True and runner.chunk is not None
    assert runner.holding is False and runner._release_until == pytest.approx(75.0)
    assert runner._committed_grip == (pytest.approx(committed[5], abs=0.2), True)

    # Zero-elapsed tick 1 keeps native retimer output at ~50 on the bus even after advancing runner.target[5].
    runner.tick()
    assert runner._committed_grip == (pytest.approx(committed[5], abs=0.2), True)
    assert runner.human_hold_latched is False

    timeout[0] = True
    now[0] += 1 / 30
    runner.tick()
    assert motion.failed is False and not any(e[0] == "off" for e in bus.events)
    assert runner.human_hold_latched is True and runner._committed_grip is None and runner._release_until is None
    assert runner.target[5] == pytest.approx(committed[5], abs=0.2) and runner.holding is True

    writes_after = len([e for e in bus.events if e[0] == "goal"])
    now[0] += 1 / 30
    runner.tick()
    goal_writes = [normalized(bus, e[1])["gripper.pos"] for e in bus.events[writes_after:] if e[0] == "goal"]
    assert motion.failed is False and goal_writes and all(g < 55.0 for g in goal_writes)


def test_chained_release_followed_by_park_keeps_release_threshold_and_hold_protection(tmp_path):
    from chunk_runner import Guarded
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from chunk_runner_settle import check_chunk_settled, check_runner_idle, confirm_grip_release
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    p_hold = [38.8, -10.0, 2.0, 55.0, -14.0, 50.0]

    def run_chain(track_gripper: bool):
        bus = _make_guard_bus(p_hold)
        committed = [normalized(bus, bus.raw)[n] for n in NAMES]
        now, reports = [10.0], []
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        motion.send(dict(zip(NAMES, committed)))
        motion.tracking, motion.aligned_since = True, 0.0
        bus.raw["gripper"] += 205  # ~55.0: stuck between closed (49) and open (75)
        stuck_grip = bus.raw["gripper"]
        pinched = [normalized(bus, bus.raw)[n] for n in NAMES]
        home_pose = [32.0, -14.0, 4.0, 50.0, -14.0, 49.0]
        lib = {
            "schema": SCHEMA,
            "names": NAMES,
            "fps": 30,
            "gripper_closed": 49.0,
            "chunks": {"home": [home_pose], "release_place": [[*committed[:5], 75.0]] * 300},
        }
        timeout, orig_sync = [False], bus.sync_read

        def sync_read(reg, motors=None, normalize=True, num_retry=0):
            if timeout[0] and reg == "Present_Position" and not normalize:
                timeout[0] = False
                raise TimeoutError("Present_Position timeout")
            return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

        bus.sync_read = sync_read
        raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
        runner = Runner(Guarded(raw_robot, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
        runner.target, runner.holding, runner.last_present = list(committed), True, list(pinched)
        assert runner.command("chain run release_place ; park") is True
        assert runner.chunk == "run release_place ; park"
        assert runner._release_until == pytest.approx(75.0)
        for _ in range(700):
            now[0] += 1 / 30
            runner.tick()
            for m in BODY:
                bus.raw[m] = bus.goals[m]
            bus.raw["gripper"] = bus.goals["gripper"] if track_gripper else stuck_grip
            if runner.chunk is None:
                break
        assert runner.chunk is None
        return bus, motion, runner, now, timeout, reports, home_pose

    # 1: Stuck jaws at ~55 through park settling must NOT clear _release_until=75 or exit via idle/gate_allows.
    bus_s, motion_s, runner_s, now_s, timeout_s, reports_s, _ = run_chain(track_gripper=False)
    assert runner_s._release_until == pytest.approx(75.0)
    assert runner_s.home_since is None and reports_s[-1]["ok"] is False and reports_s[-1]["holding"] is True
    now_s[0] += 600.0
    assert check_runner_idle(runner_s, lambda n, d: d) is False
    assert gate_allows(runner_s, []) is False
    timeout_s[0] = True
    now_s[0] += 1 / 30
    runner_s.tick()
    assert motion_s.failed is False and not any(e[0] == "off" for e in bus_s.events)
    assert runner_s.human_hold_latched is True

    # 2: Physical opening to 75 mid-chain before park closes to 49 cleanly confirms and clears release protection.
    bus_ok, motion_ok, runner_ok, _, _, reports_ok, home_pose = run_chain(track_gripper=True)
    assert motion_ok.failed is False and runner_ok._release_until is None and runner_ok._committed_grip is None
    assert runner_ok.home_since is not None and reports_ok[-1]["ok"] is True and gate_allows(runner_ok, []) is True

    # 3: Settlement never clears _release_until without a matching written gripper goal >= release_until - EMPTY_MARGIN.
    sent_r, reports_r = [], []
    present_open = [*home_pose[:5], 74.0]
    robot_r = SimpleNamespace(
        send_action=lambda a: sent_r.append(dict(a)) or a,
        get_observation=lambda: dict(zip(NAMES, present_open)),
    )
    lib_r = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [home_pose]}}
    runner_r = Runner(robot_r, lib_r, fps=30, status=reports_r.append, clock=lambda: 20.0)
    runner_r.chunk, runner_r.queue, runner_r.target = "park", [], [*home_pose[:5], 49.0]
    runner_r._release_until, runner_r._committed_grip, runner_r._fresh_present = 75.0, (49.0, True), True
    confirm_grip_release(runner_r, None, present_open, committed=True, empty_margin=2.0)
    assert runner_r._release_until == pytest.approx(75.0)
    confirm_grip_release(runner_r, {**dict(zip(NAMES, home_pose)), "gripper.pos": 49.0}, present_open,
                         committed=True, empty_margin=2.0)
    assert runner_r._release_until == pytest.approx(75.0)
    check_chunk_settled(runner_r, present_open, 0.0, 20.0, lambda n, d: d)
    assert runner_r.chunk is None and runner_r._release_until == pytest.approx(75.0)
    assert runner_r.home_since is None and reports_r[-1]["ok"] is False and gate_allows(runner_r, []) is False
    confirm_grip_release(runner_r, {**dict(zip(NAMES, home_pose)), "gripper.pos": 75.0}, present_open,
                         committed=True, empty_margin=2.0)
    assert runner_r._release_until is None and runner_r._committed_grip is None

    # 4: SIGTERM while folded with stalled jaws at 55 and _release_until=75 must NOT approve "folded and still".
    import signal
    from chunk_runner_interrupt import VERIFY_TICKS, interrupt_step

    present_stuck = [*home_pose[:5], 55.0]
    reports_t = []
    robot_t = SimpleNamespace(
        send_action=lambda a: a,
        get_observation=lambda: dict(zip(NAMES, present_stuck)),
    )
    runner_t = Runner(robot_t, lib_r, fps=30, status=reports_t.append, clock=lambda: 20.0)
    runner_t.target = [*home_pose[:5], 49.0]
    runner_t._release_until, runner_t._committed_grip = 75.0, (49.0, True)
    runner_t.signals = [signal.SIGTERM]
    assert interrupt_step(runner_t) is False
    assert runner_t._release_until == pytest.approx(75.0) and runner_t.target[5] == pytest.approx(49.0)
    for _ in range(VERIFY_TICKS + 2):
        assert interrupt_step(runner_t) is False
    assert not getattr(runner_t, "_off_approved", None) and runner_t._interrupt["phase"] == "hold"
    assert runner_t.human_hold_latched is True and gate_allows(runner_t, runner_t.signals) is False

    # 5: Soft contact hold (human=False) preserves _release_until=75 and keeps torque-off gate and idle shutdown blocked.
    reports_c = []
    runner_c = Runner(robot_t, lib_r, fps=30, status=reports_c.append, clock=lambda: 20.0)
    runner_c.chunk, runner_c.target = "park", [*home_pose[:5], 49.0]
    runner_c._release_until, runner_c._committed_grip = 75.0, (49.0, True)
    runner_c.hold(present_stuck, "contact in park", human=False)
    assert runner_c.human_hold_latched is False and runner_c._release_until == pytest.approx(75.0)
    assert runner_c._committed_grip is None and runner_c.target[5] == pytest.approx(49.0)
    assert gate_allows(runner_c, []) is False and check_runner_idle(runner_c, lambda n, d: d) is False

    # 6: Failed regrasp (holding=False) after unconfirmed release must keep _release_until and still block stop fold.
    present_g = [*home_pose[:5], 55.0]
    now_g = [30.0]
    reports_g = []
    robot_g = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, present_g)))
    lib_g = {
        "schema": SCHEMA,
        "names": NAMES,
        "fps": 30,
        "gripper_closed": 49.0,
        "hold_current_ma": 100.0,
        "chunks": {
            "home": [home_pose],
            "release_place": [[*home_pose[:5], 75.0]] * 12,
            "grasp_pick": [home_pose] * 10,
        },
    }
    runner_g = Runner(robot_g, lib_g, fps=30, status=reports_g.append, clock=lambda: now_g[0])
    runner_g.target, runner_g.holding = list(home_pose), True
    runner_g.read_health = lambda: {"current_ma": [0] * 6, "temp_c": [20] * 6, "pwm": [0] * 6}
    assert runner_g.command("run release_place") is True
    for _ in range(300):
        now_g[0] += 1 / 30
        runner_g.tick()
        if runner_g.chunk is None:
            break
    assert runner_g.chunk is None and reports_g[-1]["ok"] is False and reports_g[-1]["holding"] is True
    assert runner_g._release_until == pytest.approx(75.0)
    assert runner_g.command("state") is True and reports_g[-1]["holding"] is True
    assert runner_g.command("run grasp_pick") is True
    for _ in range(300):
        now_g[0] += 1 / 30
        runner_g.tick()
        if runner_g.chunk is None:
            break
    assert runner_g.chunk is None and runner_g._release_until == pytest.approx(75.0)
    assert reports_g[-1]["ok"] is False and reports_g[-1]["holding"] is True
    assert reports_g[-1]["error"] == "release not confirmed by jaw feedback"
    assert runner_g.command("state") is True and reports_g[-1]["holding"] is True
    assert runner_g.command("stop fold") is True and runner_g.human_hold_latched is True
    assert gate_allows(runner_g, []) is False

    # 7: `stop now` while _release_until is pending must fail, latch human HOLD, and stay in guard loop.
    from chunk_runner_loop import run as run_loop

    reports_sn, ticks_sn = [], []
    robot_sn = SimpleNamespace(send_action=lambda a: a, get_observation=lambda: dict(zip(NAMES, [*home_pose[:5], 55.0])))
    runner_sn = Runner(robot_sn, lib_g, fps=30, status=reports_sn.append, clock=lambda: 40.0)
    runner_sn.target = list(home_pose)
    runner_sn._release_until = 75.0
    runner_sn.idle = lambda: False

    def next_lines_sn():
        if not ticks_sn:
            ticks_sn.append("sent")
            return ["stop now"]
        raise StopIteration

    orig_tick_sn = runner_sn.tick

    def tick_and_count():
        ticks_sn.append("tick")
        return orig_tick_sn()

    runner_sn.tick = tick_and_count
    with pytest.raises(StopIteration):
        run_loop(runner_sn, next_lines_sn)
    stop_row = next(r for r in reports_sn if r.get("command") == "stop now")
    assert stop_row["ok"] is False and stop_row["hold"] is True and stop_row["person_needed"] is True
    assert stop_row["error"] == "unconfirmed grip release; torque stays ON"
    assert runner_sn.human_hold_latched is True and runner_sn._release_until is None
    assert "tick" in ticks_sn and gate_allows(runner_sn, []) is False


def test_small_grip_increase_and_cached_prewrite_sample_keep_release_protection_armed():
    from chunk_runner import Guarded
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    # Case A: Target=49, jaws physically stationary at 55 (holding=True).
    # Small increases (grip 49.5, grip 56.0 < 55 + EMPTY_MARGIN) must stay armed and block stop now + final_gate.
    home_pose = [32.0, -14.0, 4.0, 50.0, -14.0, 49.0]
    p_hold = [*home_pose[:5], 49.0]
    bus_a = _make_guard_bus(p_hold)
    bus_a.raw["gripper"] = bus_a._unnormalize({bus_a.motors["gripper"].id: 55.0})[bus_a.motors["gripper"].id]
    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [home_pose]}}
    raw_a = SimpleNamespace(bus=bus_a, send_action=lambda a: a, get_observation=lambda: normalized(bus_a, bus_a.raw))
    runner_a = Runner(raw_a, lib, fps=30, status=lambda _r: None, clock=lambda: 10.0)
    runner_a.target = [*home_pose[:5], 49.0]
    runner_a.holding = True
    assert runner_a.command("grip 49.5") is True
    assert runner_a._release_until is not None and runner_a._release_floor >= 56.5
    runner_a.tick()
    assert runner_a._release_until is not None
    assert runner_a.command("grip 56.0") is True
    bus_a.raw["gripper"] = bus_a._unnormalize({bus_a.motors["gripper"].id: 56.0})[bus_a.motors["gripper"].id]
    runner_a.tick()
    assert runner_a._release_until is not None
    assert runner_a.command("stop now") is True and runner_a.human_hold_latched is True
    assert gate_allows(runner_a, []) is False

    # Case B: Guarded pre-write sample at 75 while post-write hardware reads 55 must NOT clear _release_until=75.
    bus_b = _make_guard_bus([*home_pose[:5], 75.0])
    committed_b = [normalized(bus_b, bus_b.raw)[n] for n in NAMES]
    now_b = [10.0]
    motion_b = NativeJointMotion(bus_b, None, teacher=True, clock=lambda: now_b[0])
    motion_b.send(dict(zip(NAMES, committed_b)))
    motion_b.tracking, motion_b.aligned_since = True, 0.0
    read_count = [0]

    def get_obs_b():
        read_count[0] += 1
        # Simulate hardware jaws dropping back / stalling at 55 after sync_write
        obs = normalized(bus_b, bus_b.raw)
        obs["gripper.pos"] = 55.0
        return obs

    raw_b = SimpleNamespace(bus=bus_b, get_observation=get_obs_b)
    runner_b = Runner(Guarded(raw_b, motion_b), lib, fps=30, status=lambda _r: None, clock=lambda: now_b[0])
    runner_b.target = [*home_pose[:5], 75.0]
    runner_b._release_until = 75.0
    runner_b._committed_grip = (49.0, True)
    runner_b.queue = [[*home_pose[:5], 75.0]]
    now_b[0] += 1 / 30
    runner_b.tick()
    assert read_count[0] >= 1
    assert runner_b._release_until == pytest.approx(75.0)


@pytest.mark.parametrize("cmd", ["jog gripper.pos 4", "jog shoulder_pan.pos 1 gripper.pos 4"])
def test_opening_gripper_jog_arms_release_protection_including_coordinated_jogs(cmd):
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from omx_adapter.chunk_library import NAMES, SCHEMA

    home_pose = [32.0, -14.0, 4.0, 50.0, -14.0, 49.0]
    p_hold = [*home_pose[:5], 52.0]
    bus = _make_guard_bus(p_hold)
    bus.raw["gripper"] = bus._unnormalize({bus.motors["gripper"].id: 55.0})[bus.motors["gripper"].id]
    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [home_pose]}}
    raw = SimpleNamespace(bus=bus, send_action=lambda a: a, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(raw, lib, fps=30, status=lambda _r: None, clock=lambda: 10.0)
    runner.target = list(p_hold)
    runner.holding = True

    assert runner.command(cmd) is True
    assert runner._release_until == pytest.approx(56.0)
    assert runner._release_floor >= 56.5
    runner.tick()
    assert runner._release_until == pytest.approx(56.0)
    assert runner.command("stop now") is True and runner.human_hold_latched is True
    assert gate_allows(runner, []) is False


@pytest.mark.parametrize("cmd", ["grip 100", "jog gripper.pos 1"])
def test_release_at_opening_limit_keeps_protection_armed_without_measurable_opening(cmd):
    from chunk_runner import Guarded
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    home_pose = [32.0, -14.0, 4.0, 50.0, -14.0, 49.0]
    p_hold = [*home_pose[:5], 99.0]
    now = [10.0]
    bus = _make_guard_bus(p_hold)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0
    bus.raw["gripper"] = bus._unnormalize({bus.motors["gripper"].id: 100.0})[bus.motors["gripper"].id]
    motion.last_present = None
    lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0, "chunks": {"home": [home_pose]}}
    raw = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    runner = Runner(Guarded(raw, motion), lib, fps=30, status=lambda _r: None, clock=lambda: now[0])
    runner.target, runner.holding = list(p_hold), True

    assert runner.command(cmd) is True
    assert runner._release_until == pytest.approx(100.0)
    assert runner._release_floor > 100.0
    expected_goal = bus._unnormalize({bus.motors["gripper"].id: 100.0})[bus.motors["gripper"].id]
    for _ in range(60):
        now[0] += 1 / 30
        runner.tick()
        if bus.goals["gripper"] == expected_goal:
            break
    assert bus.goals["gripper"] == expected_goal
    assert runner._release_until == pytest.approx(100.0)
    assert runner.command("stop now") is True and runner.human_hold_latched is True
    assert gate_allows(runner, []) is False


def test_non_release_chunks_and_composed_paths_opening_held_jaw_arm_release_protection():
    from chunk_runner import Guarded
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    home_pose = [0.0, -60.0, 50.0, 45.0, 10.0, 49.0]
    hold_pose = [*home_pose[:5], 55.0]
    open_pose = [*home_pose[:5], 56.0]
    lib = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
        "chunks": {
            "home": [home_pose],
            "carry": [[*home_pose[:5], 49.0], [*home_pose[:5], 49.0]],
            "custom_open": [hold_pose, open_pose],
            "above_place": [hold_pose],
            "open_target": [open_pose],
        },
    }

    def make_runner(target_grip: float):
        now, reports = [10.0], []
        bus = _make_guard_bus([*home_pose[:5], target_grip])
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
        motion.tracking, motion.aligned_since = True, 0.0
        bus.raw["gripper"] = bus._unnormalize({bus.motors["gripper"].id: 55.0})[bus.motors["gripper"].id]
        orig_sw = bus.sync_write
        def _follow_body(_self, reg, vals, *, normalize=True):
            orig_sw(reg, vals, normalize=normalize)
            _self.raw.update({k: v for k, v in vals.items() if k != "gripper"})
        bus.__class__ = type("BodyFollowBus", (bus.__class__,), {"sync_write": _follow_body})
        motion.last_present = None
        raw = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
        r = Runner(Guarded(raw, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
        r.target, r.holding = [*home_pose[:5], target_grip], True
        return r, bus, motion, now, reports

    # Constant carry/park with held closed target does NOT arm release protection.
    for cmd in ("run carry", "park"):
        r_safe, _, _, _, _ = make_runner(49.0)
        assert r_safe.command(cmd) is True and r_safe._release_until is None

    # Opening a held jaw via non-release run, splice, chain, goto, or retreat arms release protection and blocks stop now.
    for mode in ("run", "splice", "chain", "goto", "retreat"):
        r, bus, _m, now, reports = make_runner(50.0 if mode == "retreat" else 55.0)
        if mode == "splice":
            r.command("run carry")
            assert r.command("splice custom_open") is True
        elif mode == "chain":
            assert r.command("chain goto above_place ; run custom_open ; park") is True
        elif mode == "goto":
            assert r.command("goto open_target") is True
        elif mode == "retreat":
            r.retreat_frames = [[*home_pose[:5], 50.0], [*home_pose[:5], 75.0]]
            assert r.command("retreat") is True
        else:
            assert r.command("run custom_open") is True
        assert r._release_until is not None and r._release_floor >= 56.9
        for _ in range(250):
            now[0] += 1 / 30
            r.tick()
            if r.chunk is None:
                break
        assert r._release_until is not None
        assert r.command("stop now") is True and r.human_hold_latched is True
        assert gate_allows(r, []) is False


def test_mid_chunk_cycle_and_grasp_release_chain_arm_release_protection_on_stuck_jaw():
    from chunk_runner import Guarded
    from chunk_runner_interrupt import gate_allows
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES, SCHEMA

    body = [0.0, -60.0, 50.0, 45.0, 10.0]
    frames = lambda levels: [body + [float(x)] for x in levels]
    opening = [round(49.0 + 0.08 * k, 2) for k in range(138)] + [60.0] * 25
    closing = [round(60.0 - 0.08 * k, 2) for k in range(138)] + [49.0] * 25
    release_short = [round(49.0 + 0.08 * k, 2) for k in range(126)] + [59.0] * 25
    lib = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49.0,
        "chunks": {
            "home": frames([49.0]),
            "cycle": frames(opening + closing + release_short),
            "grasp_pick": frames(closing),
            "release_place": frames(release_short),
            "release_open": frames(opening),
        },
    }
    cases = [
        (True, True, "run cycle"),
        (False, True, "chain run grasp_pick ; run release_place"),
        (False, False, "chain run grasp_pick ; run release_open"),
    ]
    for held, stuck, cmd in cases:
        now, reports, phase = [10.0], [], [0]
        bus = _make_guard_bus([*body, 49.0 if held else 60.0])
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
        motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
        motion.tracking, motion.aligned_since = True, 0.0
        ticks = lambda v: round(v * 4095 / 100.0)
        bus.raw["gripper"] = ticks(55.0 if held else 60.0)
        motion.last_present = None
        orig_sw = bus.sync_write

        def write(_self, reg, vals, *, normalize=True, _held=held, _stuck=stuck, _p=phase, _osw=orig_sw):
            _osw(reg, vals, normalize=normalize)
            if reg == "Goal_Position" and "gripper" in vals:
                g = vals["gripper"]
                if _held:
                    if _p[0] == 0 and g >= ticks(59.0):
                        _p[0], _self.raw["gripper"] = 1, g
                    elif _p[0] == 0:
                        _self.raw["gripper"] = max(ticks(55.0), g)
                    elif _p[0] == 1:
                        _self.raw["gripper"] = max(ticks(55.0), g)
                        if g <= ticks(51.0):
                            _p[0] = 2
                else:
                    if _p[0] == 0:
                        _self.raw["gripper"] = max(ticks(55.0), g)
                        if g <= ticks(51.0):
                            _p[0] = 2
                    elif not _stuck:
                        _self.raw["gripper"] = g

        bus.__class__ = type("CycleBus", (bus.__class__,), {"sync_write": write})
        raw = SimpleNamespace(bus=bus, get_observation=lambda _b=bus: normalized(_b, _b.raw))
        r = Runner(Guarded(raw, motion), lib, fps=30, status=reports.append, clock=lambda: now[0])
        r.target, r.holding = [*body, 49.0 if held else 60.0], held
        assert r.command(cmd) is True and r.chunk
        for _ in range(1000):
            now[0] += 1 / 30
            r.tick()
            if r.chunk is None:
                break
        assert r.chunk is None and phase[0] == 2
        if stuck:
            assert r._release_until is not None and r._release_floor >= 56.9
            assert reports[-1]["ok"] is False and reports[-1]["holding"] is True
            assert r.command("stop now") is True and r.human_hold_latched is True
            assert gate_allows(r, []) is False
        else:
            assert r._release_until is None and reports[-1]["ok"] is True
            assert r.command("stop now") is False and r.human_hold_latched is False
            assert gate_allows(r, []) is True
