"""OMX policy motor-health hard-limit and overload outage guard tests."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_timing import _make_guard_bus  # noqa: E402


@pytest.mark.parametrize("interrupt_mode", [False, True])
def test_encoder_loss_as_overload_release_timer_expires_blocks_stale_release(tmp_path, monkeypatch, interrupt_mode):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"motor-health-current-{interrupt_mode}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 46.6]
    now, reports, released = [10.0], [], []
    bus = _make_guard_bus(p0)
    orig_sync_read = bus.sync_read
    pos_fail = [False]

    def maybe_fail_pos(reg, motors=None, normalize=True, num_retry=0):
        if pos_fail[0] and reg == "Present_Position":
            raise TimeoutError("encoder read timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = maybe_fail_pos
    monitor = MotorHealth(tmp_path / f"motor-health-{interrupt_mode}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    motion.tracking, motion.aligned_since = True, 0.0
    motion.pwm_limits = dict.fromkeys(BODY, 330)
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}

    def _release_hold():
        released.append(now[0])
        motion.held.clear()

    motion.release_hold = _release_hold

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.signals = [signal.SIGINT] if interrupt_mode else []
    runner.human_hold_latched = True
    runner.target = [10.0, 10.0, 10.0, 10.0, 10.0, 46.6]
    runner.last_present = list(p0)
    runner.hold_file = tmp_path / f"stale-release-hold-{interrupt_mode}.json"
    if interrupt_mode:
        runner._interrupt = {
            "signal": signal.SIGINT, "phase": "hold", "seen": 1, "release_from": 1,
            "may_move": False, "since": 10.0, "still": 0, "last": None, "deadline": 130.0,
        }

        def _step():
            ci.interrupt_tick(runner, "tick", tick_or_report)
    else:
        _step = runner.tick

    for _ in range(14):
        now[0] += 1 / 30
        _step()
    assert runner.shed_clear is not None and "wrist_flex" in motion.held and released == []
    assert monitor.motions[monitor.key(motion)]["last"]["sample_time"] is not None

    # Outage spanning both the 0.5 s shed_clear boundary and a >0.5 s MotorHealth gap must reset shed_clear cleanly.
    pos_fail[0] = True
    now[0] += 1 / 30
    _step()
    assert "wrist_flex" in motion.held and released == []
    assert runner.shed_clear is None
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    for _ in range(19):
        now[0] += 1 / 30
        _step()
    assert "wrist_flex" in motion.held and released == []
    assert runner.shed_clear is None
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    # Recovery after >0.5 s must restart MotorHealth cleanly without releasing on the first sample.
    pos_fail[0] = False
    now[0] += 1 / 30
    _step()
    assert monitor.motions[monitor.key(motion)]["last"]["sample_time"] == pytest.approx(now[0])
    assert motion.last_effort_time == pytest.approx(now[0])
    assert "wrist_flex" in motion.held and released == []
    assert runner.shed_clear == pytest.approx(now[0])

    # After a full fresh 0.5 s window, release fires once with held wrist_flex pinned to measured pose.
    for _ in range(16):
        now[0] += 1 / 30
        _step()
    assert len(released) == 1 and motion.held == {}
    assert runner.target[3] == pytest.approx(7.0, abs=0.2)
    assert ci.gate_allows(runner, runner.signals) is False


def test_motor_health_gap_recovery_enforces_held_overload_watch_and_rejects_normal_gap(tmp_path, monkeypatch):
    from guarded_device import BODY, normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "motor-health-watch-current.json"))
    now, pos_fail = [10.0], [False]
    bus = _make_guard_bus(p0)
    bus.pwms["wrist_flex"] = 310  # >= 90% of 330 cap
    orig_sync_read = bus.sync_read

    def maybe_fail_pos(reg, motors=None, normalize=True, num_retry=0):
        if pos_fail[0] and reg == "Present_Position":
            raise TimeoutError("encoder read timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = maybe_fail_pos
    monitor = MotorHealth(tmp_path / "hold-watch.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}

    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert monitor.motions[monitor.key(motion)]["last"]["sample_time"] == pytest.approx(10.05)

    pos_fail[0] = True
    for t in (10.30, 10.55, 10.80):
        now[0] = t
        with pytest.raises(GoalRejected):
            motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    pos_fail[0] = False
    now[0] = 10.85  # gap = 0.80 s > 0.5 s
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert monitor.motions[monitor.key(motion)]["last"]["sample_time"] == pytest.approx(10.85)
    assert motion.last_effort_time == pytest.approx(10.85)

    while now[0] < 12.80:
        now[0] += 0.25
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    now[0] = 13.05  # >= HOLD_S = 3.0 s continuous saturation
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())

    # Normal motion (allow_stale_hold=False) and default MotorHealth.sample(allow_gap=False) still fail closed >0.5 s.
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "motor-health-normal-current.json"))
    bus2, now2 = _make_guard_bus(p0), [10.0]
    monitor2 = MotorHealth(tmp_path / "normal-gap.jsonl")
    motion2 = NativeJointMotion(bus2, None, teacher=True, clock=lambda: now2[0], monitor=monitor2)
    act2 = dict(zip(NAMES, [normalized(bus2, bus2.raw)[n] for n in NAMES]))
    motion2.send(act2)
    now2[0] = 10.05
    motion2.send(act2)
    now2[0] = 10.75
    with pytest.raises(ValueError, match="stale motor health sample"):
        monitor2.sample(motion2, bus2.raw, dict.fromkeys(BODY, 0), 10.75)
    with pytest.raises(ValueError, match="stale"):
        motion2.send(act2)
    assert motion2.failed is True and all(v == 0 for v in bus2.torque.values())


def test_encoder_loss_during_powered_hold_still_enforces_overload_timeout_and_temp_rise(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]

    # Case A: continuous Present_Position outage past HOLD_S=3s still trips on saturated PWM.
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "enc-loss-timeout-state.json"))
    now, pos_fail = [10.0], [False]
    bus = _make_guard_bus(p0)
    bus.pwms["wrist_flex"] = 310
    orig_sync_read = bus.sync_read

    def maybe_fail_pos(reg, motors=None, normalize=True, num_retry=0):
        if pos_fail[0] and reg == "Present_Position":
            raise TimeoutError("encoder read timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = maybe_fail_pos
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "enc-loss-timeout.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}

    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    pos_fail[0] = True
    for t in (10.3, 11.0, 12.0):
        now[0] = t
        with pytest.raises(GoalRejected):
            motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    now[0] = 13.1
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())

    # Case B: temperature rise (+4 C) during Present_Position timeout immediately trips overload watch.
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "enc-loss-temp-state.json"))
    now2, pos_fail2 = [10.0], [False]
    bus2 = _make_guard_bus(p0)
    bus2.pwms["wrist_flex"] = 310
    orig_sync_read2 = bus2.sync_read

    def maybe_fail_pos2(reg, motors=None, normalize=True, num_retry=0):
        if pos_fail2[0] and reg == "Present_Position":
            raise TimeoutError("encoder read timed out")
        return orig_sync_read2(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus2.sync_read = maybe_fail_pos2
    motion2 = NativeJointMotion(
        bus2, None, teacher=True, clock=lambda: now2[0], monitor=MotorHealth(tmp_path / "enc-loss-temp.jsonl"), shed_load=True
    )
    act2 = dict(zip(NAMES, [normalized(bus2, bus2.raw)[n] for n in NAMES]))
    motion2.send(act2)
    motion2.tracking, motion2.aligned_since = True, 0.0
    motion2.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}

    now2[0] = 10.05
    motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)

    pos_fail2[0] = True
    bus2.temps["wrist_flex"] = 34
    now2[0] = 10.3
    with pytest.raises(ValueError, match="overload risk"):
        motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    assert motion2.failed is True and all(v == 0 for v in bus2.torque.values())


@pytest.mark.parametrize("interrupt_mode", [False, True])
def test_loop_pause_without_failed_ticks_does_not_release_overload_hold_on_first_sample(
    tmp_path, monkeypatch, interrupt_mode
):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    if ci.OPERATOR_RELEASE is None:
        monkeypatch.setattr(ci, "OPERATOR_RELEASE", 12)
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"pause-state-{interrupt_mode}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 46.6]
    now, reports, released = [10.0], [], []
    bus = _make_guard_bus(p0)
    monitor = MotorHealth(tmp_path / f"pause-health-{interrupt_mode}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.pwm_limits = dict.fromkeys(BODY, 330)
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}

    def _release_hold():
        released.append(now[0])
        motion.held.clear()

    motion.release_hold = _release_hold
    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)
    runner = Runner(guarded, library, fps=30, status=reports.append, clock=lambda: now[0])
    runner.signals = [signal.SIGINT] if interrupt_mode else []
    runner.human_hold_latched = True
    runner.target = [10.0, 10.0, 10.0, 10.0, 10.0, 46.6]
    runner.last_present = list(p0)
    runner.hold_file = tmp_path / f"pause-hold-{interrupt_mode}.json"
    if interrupt_mode:
        runner._interrupt = {
            "signal": signal.SIGINT, "phase": "hold", "seen": 1, "release_from": 1,
            "may_move": False, "since": 10.0, "still": 0, "last": None, "deadline": 130.0,
        }

        def _step():
            ci.interrupt_tick(runner, "tick", tick_or_report)
    else:
        _step = runner.tick

    for _ in range(3):
        now[0] += 1 / 30
        _step()
    assert runner.shed_clear == pytest.approx(10.0 + 1 / 30)
    assert "wrist_flex" in motion.held and released == []

    # A 0.7 s pause with zero failed ticks must reset shed_clear rather than releasing on the first sample.
    now[0] += 0.7
    _step()
    assert motion.last_effort_time == pytest.approx(now[0])
    assert motion.last_effort_gap_at == pytest.approx(now[0])
    assert "wrist_flex" in motion.held and released == []
    assert runner.shed_clear == pytest.approx(now[0])

    # Only after a full fresh 0.5 s window does release fire once with held wrist_flex pinned.
    for _ in range(16):
        now[0] += 1 / 30
        _step()
    assert len(released) == 1 and motion.held == {}
    assert runner.target[3] == pytest.approx(7.0, abs=0.2)
    assert ci.gate_allows(runner, runner.signals) is False


def test_combined_read_outage_during_overload_hold_enforces_hold_s_cap(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]

    def _wire_outage_bus(pwm_val: int):
        bus = _make_guard_bus(p0)
        if pwm_val:
            bus.pwms["wrist_flex"] = pwm_val
        orig_sync_read, orig_read = bus.sync_read, bus.read
        all_fail = [False]
        fail_regs = ("Present_Position", "Present_PWM", "Present_Temperature", "Hardware_Error_Status")

        def maybe_fail_sync(reg, motors=None, normalize=True, num_retry=0):
            if all_fail[0] and reg in fail_regs:
                raise TimeoutError(f"{reg} timed out")
            return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

        def maybe_fail_read(reg, motor, **kwargs):
            if all_fail[0] and reg in fail_regs:
                raise TimeoutError(f"{reg} timed out")
            return orig_read(reg, motor, **kwargs)

        bus.sync_read, bus.read = maybe_fail_sync, maybe_fail_read
        return bus, all_fail

    # Case C: saturated_since already recorded before a combined outage still expires at HOLD_S = 3.0 s.
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "combined-outage-sat-state.json"))
    now = [10.0]
    bus, all_fail = _wire_outage_bus(310)
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "combined-sat.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    all_fail[0] = True
    for t in (10.3, 11.0, 12.0):
        now[0] = t
        with pytest.raises(GoalRejected):
            motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    now[0] = 13.1
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())

    # Case D: saturated_since cleared (None) before a combined outage still fails closed at HOLD_S = 3.0 s.
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "combined-outage-clear-state.json"))
    now2 = [10.0]
    bus2, all_fail2 = _wire_outage_bus(0)
    motion2 = NativeJointMotion(
        bus2, None, teacher=True, clock=lambda: now2[0], monitor=MotorHealth(tmp_path / "combined-clr.jsonl"), shed_load=True
    )
    act2 = dict(zip(NAMES, [normalized(bus2, bus2.raw)[n] for n in NAMES]))
    motion2.send(act2)
    motion2.tracking, motion2.aligned_since = True, 0.0
    motion2.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}
    now2[0] = 10.05
    motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    assert motion2.held["wrist_flex"]["saturated_since"] is None and motion2.last_effort_time == pytest.approx(10.05)

    all_fail2[0] = True
    for t in (10.3, 11.0, 12.0):
        now2[0] = t
        with pytest.raises(GoalRejected):
            motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
        assert motion2.failed is False and all(v == 1 for v in bus2.torque.values())

    now2[0] = 13.1
    with pytest.raises(ValueError, match="overload risk"):
        motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    assert motion2.failed is True and all(v == 0 for v in bus2.torque.values())


@pytest.mark.parametrize("recover_pwm", [0, 310])
@pytest.mark.parametrize("full_recovery", [False, True])
def test_recovery_at_expired_hold_deadline_still_cuts_torque(tmp_path, monkeypatch, recover_pwm, full_recovery):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv(
        "ROSY_OMX_MONITOR_STATE", str(tmp_path / f"recover-expired-{recover_pwm}-{full_recovery}.json")
    )
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync_read, orig_read = bus.sync_read, bus.read
    fail_mode = [None]
    fail_all_regs = ("Present_Position", "Present_PWM", "Present_Temperature", "Hardware_Error_Status")

    def maybe_fail_sync(reg, motors=None, normalize=True, num_retry=0):
        if fail_mode[0] == "all" and reg in fail_all_regs:
            raise TimeoutError(f"{reg} timed out")
        if fail_mode[0] == "encoder_only" and reg == "Present_Position":
            raise TimeoutError("Present_Position timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def maybe_fail_read(reg, motor, **kwargs):
        if fail_mode[0] == "all" and reg in fail_all_regs:
            raise TimeoutError(f"{reg} timed out")
        return orig_read(reg, motor, **kwargs)

    bus.sync_read, bus.read = maybe_fail_sync, maybe_fail_read
    now = [10.0]
    motion = NativeJointMotion(
        bus,
        None,
        teacher=True,
        clock=lambda: now[0],
        monitor=MotorHealth(tmp_path / f"recover-expired-{recover_pwm}-{full_recovery}.jsonl"),
        shed_load=True,
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.held["wrist_flex"]["saturated_since"] is None
    assert motion.held["wrist_flex"]["last_telemetry_at"] == pytest.approx(10.05)

    fail_mode[0] = "all"
    for t in (10.3, 11.5):
        now[0] = t
        with pytest.raises(GoalRejected):
            motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    now[0] = 13.10
    bus.pwms["wrist_flex"] = recover_pwm
    fail_mode[0] = None if full_recovery else "encoder_only"
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


def test_healthy_independent_probe_resets_outage_clock_so_brief_dropout_keeps_torque_on(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "brief-dropout-state.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync_read, orig_read = bus.sync_read, bus.read
    fail_mode = [None]
    fail_all_regs = ("Present_Position", "Present_PWM", "Present_Temperature", "Hardware_Error_Status")

    def maybe_fail_sync(reg, motors=None, normalize=True, num_retry=0):
        if fail_mode[0] == "all" and reg in fail_all_regs:
            raise TimeoutError(f"{reg} timed out")
        if fail_mode[0] == "encoder_only" and reg == "Present_Position":
            raise TimeoutError("Present_Position timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def maybe_fail_read(reg, motor, **kwargs):
        if fail_mode[0] == "all" and reg in fail_all_regs:
            raise TimeoutError(f"{reg} timed out")
        return orig_read(reg, motor, **kwargs)

    bus.sync_read, bus.read = maybe_fail_sync, maybe_fail_read
    now = [10.0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "brief-dropout.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.held["wrist_flex"]["saturated_since"] is None
    assert motion.held["wrist_flex"]["last_telemetry_at"] == pytest.approx(10.05)

    # Healthy (Present_PWM, Present_Temperature) probe at 12.95 s refreshes per-joint timestamp during encoder outage.
    fail_mode[0] = "encoder_only"
    now[0] = 12.95
    with pytest.raises(GoalRejected):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert motion.held["wrist_flex"]["last_telemetry_at"] == pytest.approx(12.95)
    assert motion.last_effort_time == pytest.approx(10.05)

    # A 0.15 s combined dropout at 13.10 s must keep torque ON cleanly.
    fail_mode[0] = "all"
    now[0] = 13.10
    with pytest.raises(GoalRejected):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    # Sustained combined outage >= HOLD_S (3.0 s) past 12.95 s cuts torque OFF.
    now[0] = 16.00
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


@pytest.mark.parametrize("case", ["pwm_ok_temp_ok", "pwm_slow_temp_ok", "pwm_ok_temp_timeout", "pwm_timeout_temp_ok"])
def test_slow_telemetry_read_crossing_hold_deadline_cuts_torque(tmp_path, monkeypatch, case):
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"slow-read-{case}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    bus.pwms["wrist_flex"] = 310
    orig_sync_read, orig_read = bus.sync_read, bus.read
    now, slow_phase, pwm_advanced = [10.0], [False], [False]

    def maybe_slow_sync(reg, motors=None, normalize=True, num_retry=0):
        if slow_phase[0] and reg == "Present_Position":
            raise TimeoutError("Present_Position timed out")
        if slow_phase[0] and reg == "Present_PWM":
            if case == "pwm_slow_temp_ok":
                now[0] = 13.10
                pwm_advanced[0] = True
            if case == "pwm_timeout_temp_ok":
                raise TimeoutError("Present_PWM timed out")
        return orig_sync_read(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def maybe_slow_read(reg, motor, **kwargs):
        if slow_phase[0]:
            if reg == "Present_PWM" and case == "pwm_timeout_temp_ok":
                raise TimeoutError("Present_PWM timed out")
            if reg == "Present_Temperature":
                now[0] = 13.10
                if case == "pwm_ok_temp_timeout":
                    raise TimeoutError("Present_Temperature timed out")
        return orig_read(reg, motor, **kwargs)

    bus.sync_read = maybe_slow_sync
    if case != "pwm_slow_temp_ok":
        bus.read = maybe_slow_read
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / f"slow-{case}.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30}}
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.held["wrist_flex"]["saturated_since"] == pytest.approx(10.0)
    assert motion.held["wrist_flex"]["last_telemetry_at"] == pytest.approx(10.05)

    # Start the probe at 12.95 s (before the 13.00 / 13.05 s deadlines); clock crosses to 13.10 s mid-read.
    slow_phase[0] = True
    bus.pwms["wrist_flex"] = 0
    now[0] = 12.95
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    if case == "pwm_slow_temp_ok":
        assert pwm_advanced[0] is True
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


def test_jaw_gate_intake_error_with_failed_status_and_closed_stderr_keeps_guard_ticking(tmp_path, monkeypatch):
    import sys

    from chunk_runner import Guarded
    import chunk_runner_loop
    from chunk_runner_run import Runner
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    class _BrokenStream:
        def write(self, _text):
            raise BrokenPipeError("stderr closed")

        def flush(self):
            raise BrokenPipeError("stderr closed")

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "closed-stderr-state.json"))
    monkeypatch.setattr(sys, "stderr", _BrokenStream())
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 46.6]
    bus = _make_guard_bus(p0)
    bus.pwms["wrist_flex"] = 310
    now, ticks, intake_calls = [10.0], [0], [0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "closed-stderr.jsonl"), shed_load=True
    )
    motion.send(dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES])))
    motion.tracking, motion.aligned_since = True, 0.0
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 30, "last_telemetry_at": 10.0}}

    library = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home]}}
    raw_robot = SimpleNamespace(bus=bus, get_observation=lambda: normalized(bus, bus.raw))
    guarded = Guarded(raw_robot, motion)

    def _failing_status(_row):
        raise OSError("disk full")

    runner = Runner(
        guarded,
        library,
        fps=30,
        status=_failing_status,
        clock=lambda: now[0],
        sleep=lambda _s: now.__setitem__(0, now[0] + 0.25),
    )
    runner.jaw_gate = object()
    runner.hold_file = tmp_path / "closed-stderr-hold.json"
    orig_tick = runner.tick

    def _counted_tick():
        ticks[0] += 1
        orig_tick()

    runner.tick = _counted_tick

    def _lines():
        intake_calls[0] += 1
        if intake_calls[0] == 1:
            raise OSError("fifo read failed")
        return []

    chunk_runner_loop.run(runner, _lines)
    assert runner.human_hold_latched is True
    assert ticks[0] >= 10
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())
    assert "overload risk" in runner._interrupt["guard_cause"]
    assert runner._off_approved == "guard stopped, every motor reads torque 0"


def test_closed_stdout_during_latched_hold_keeps_torque_on_across_health_and_overload(tmp_path, monkeypatch):
    import io
    import sys

    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    closed_out = io.StringIO()
    closed_out.close()
    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "closed-stdout-state.json"))
    monkeypatch.setattr(sys, "stdout", closed_out)
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    now = [10.0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "closed-stdout.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0

    # MotorHealth initial and 1 Hz diagnostics with closed stdout must not trip torque OFF.
    for t in (10.05, 11.20):
        now[0] = t
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    # Entering overload-hold and releasing hold with closed stdout must also keep torque ON.
    bus.pwms["wrist_flex"] = 310
    bus.raw["wrist_flex"] = int(motion.command["wrist_flex"]) - 30
    for t in (11.45, 11.70, 11.95, 12.20, 12.45, 12.70):
        now[0] = t
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        assert motion.failed is False and all(v == 1 for v in bus.torque.values())
    assert "wrist_flex" in motion.held
    motion.release_hold()
    assert motion.held == {} and motion.failed is False and all(v == 1 for v in bus.torque.values())


def test_baseline_temp_timeout_on_overload_entry_keeps_committed_goal_and_enforces_deadline(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]

    def _wire_bus(tag: str):
        monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"base-temp-{tag}.json"))
        bus = _make_guard_bus(p0)
        orig_read, orig_sync = bus.read, bus.sync_read
        temp_fail, pos_fail = [False], [False]

        def maybe_fail_read(reg, motor, **kwargs):
            if temp_fail[0] and reg == "Present_Temperature":
                raise TimeoutError("temperature read timed out")
            return orig_read(reg, motor, **kwargs)

        def maybe_fail_sync(reg, motors=None, normalize=True, num_retry=0):
            if pos_fail[0] and reg == "Present_Position":
                raise TimeoutError("position read timed out")
            return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

        bus.read, bus.sync_read = maybe_fail_read, maybe_fail_sync
        return bus, temp_fail, pos_fail

    # Subcase 1: Baseline temperature timeout leaves committed goal unchanged, then recovery keeps bounded 3 s cap.
    now = [10.0]
    bus, temp_fail, _ = _wire_bus("recover")
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "base-temp-rec.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    committed_goal = int(motion.command["wrist_flex"])
    bus.pwms["wrist_flex"] = 310
    bus.raw["wrist_flex"] = committed_goal - 30

    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.effort_since["wrist_flex"] == pytest.approx(10.05)

    temp_fail[0] = True
    now[0] = 11.10
    with pytest.raises(GoalRejected):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert int(motion.command["wrist_flex"]) == committed_goal
    assert "wrist_flex" not in motion.held
    assert motion.effort_since["wrist_flex"] == pytest.approx(10.05)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    temp_fail[0] = False
    now[0] = 12.10
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert "wrist_flex" in motion.held
    assert motion.held["wrist_flex"]["saturated_since"] == pytest.approx(11.05)

    now[0] = 14.10
    with pytest.raises(ValueError, match="overload risk"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())

    # Subcase 2: Baseline temperature failure followed by encoder loss past 1.0 + HOLD_S still cuts torque OFF.
    now2 = [10.0]
    bus2, temp_fail2, pos_fail2 = _wire_bus("enc-loss")
    motion2 = NativeJointMotion(
        bus2, None, teacher=True, clock=lambda: now2[0], monitor=MotorHealth(tmp_path / "base-temp-enc.jsonl"), shed_load=True
    )
    act2 = dict(zip(NAMES, [normalized(bus2, bus2.raw)[n] for n in NAMES]))
    motion2.send(act2)
    motion2.tracking, motion2.aligned_since = True, 0.0
    committed_goal2 = int(motion2.command["wrist_flex"])
    bus2.pwms["wrist_flex"] = 310
    bus2.raw["wrist_flex"] = committed_goal2 - 30

    now2[0] = 10.05
    motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    temp_fail2[0] = True
    now2[0] = 11.10
    with pytest.raises(GoalRejected):
        motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    assert int(motion2.command["wrist_flex"]) == committed_goal2

    pos_fail2[0] = True
    now2[0] = 14.10
    with pytest.raises(ValueError, match="overload risk"):
        motion2.send(act2, hold_on_read_error=True, allow_stale_hold=True)
    assert motion2.failed is True and all(v == 0 for v in bus2.torque.values())


def test_simultaneous_overload_stages_holds_until_goal_commit(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "staged-hold.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    temp_fail = [False]
    orig_read = bus.read

    def maybe_fail_read(reg, motor, **kwargs):
        if temp_fail[0] and reg == "Present_Temperature" and motor == "wrist_flex":
            raise TimeoutError("wrist_flex temperature timed out")
        return orig_read(reg, motor, **kwargs)

    bus.read = maybe_fail_read
    now = [10.0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / "staged-hold.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0
    committed_sh = int(motion.command["shoulder_lift"])
    committed_wf = int(motion.command["wrist_flex"])
    bus.pwms["shoulder_lift"] = 310
    bus.pwms["wrist_flex"] = 310
    bus.raw["shoulder_lift"] = committed_sh - 30
    bus.raw["wrist_flex"] = committed_wf - 30

    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.effort_since["shoulder_lift"] == pytest.approx(10.05)
    assert motion.effort_since["wrist_flex"] == pytest.approx(10.05)

    # Subcase A: Second-joint Present_Temperature timeout must not mutate first-joint command or held state.
    temp_fail[0] = True
    now[0] = 11.10
    with pytest.raises(GoalRejected):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert int(motion.command["shoulder_lift"]) == committed_sh == bus.goals["shoulder_lift"]
    assert int(motion.command["wrist_flex"]) == committed_wf == bus.goals["wrist_flex"]
    assert motion.held == {} and motion.held_once == set()
    assert motion.effort_since["shoulder_lift"] == pytest.approx(10.05)
    assert motion.effort_since["wrist_flex"] == pytest.approx(10.05)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())

    # Subcase B: goal_check rejection must also leave software command and held state untouched.
    temp_fail[0] = False
    now[0] = 11.20
    with pytest.raises(GoalRejected, match="jaw gate rejected"):
        motion.send(act, goal_check=lambda cur, g: "jaw gate rejected", hold_on_read_error=True, allow_stale_hold=True)
    assert int(motion.command["shoulder_lift"]) == committed_sh == bus.goals["shoulder_lift"]
    assert int(motion.command["wrist_flex"]) == committed_wf == bus.goals["wrist_flex"]
    assert motion.held == {} and motion.held_once == set()

    # Subcase C: Recovery commits both overload holds atomically only after Goal_Position sync_write succeeds.
    now[0] = 11.25
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert set(motion.held) == {"shoulder_lift", "wrist_flex"}
    assert motion.held_once == {"shoulder_lift", "wrist_flex"}
    assert motion.effort_since["shoulder_lift"] is None and motion.effort_since["wrist_flex"] is None
    for j in ("shoulder_lift", "wrist_flex"):
        assert bus.goals[j] == int(motion.command[j]) == bus.raw[j]


@pytest.mark.parametrize(
    "mode",
    [
        "batch_volt_timeout",
        "batch_temp_sync_timeout",
        "per_motor_volt_timeout",
        "position_timeout_overtemp",
        "temp_timeout_undervolt",
    ],
)
def test_telemetry_timeout_cannot_mask_confirmed_hard_limit_in_powered_hold(tmp_path, monkeypatch, mode):
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"mask-{mode}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync, orig_read = bus.sync_read, bus.read
    fault_active = [False]

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if fault_active[0]:
            if mode == "batch_volt_timeout" and reg == "Present_Input_Voltage":
                raise TimeoutError("voltage sync_read timed out")
            if mode == "batch_temp_sync_timeout" and reg == "Present_Temperature":
                raise TimeoutError("temperature sync_read timed out")
            if mode == "position_timeout_overtemp" and reg == "Present_Position":
                raise TimeoutError("position sync_read timed out")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def read(reg, motor, **kwargs):
        if fault_active[0]:
            if mode == "per_motor_volt_timeout" and motor == "shoulder_pan" and reg in (
                "Present_Temperature",
                "Present_Input_Voltage",
            ):
                raise TimeoutError(f"{reg} timed out on {motor}")
            if mode == "temp_timeout_undervolt":
                if reg == "Present_Temperature":
                    raise TimeoutError("temperature timed out")
                if reg == "Present_Input_Voltage" and motor == "wrist_flex":
                    return 80
        return orig_read(reg, motor, **kwargs)

    bus.sync_read = sync_read
    if mode in ("per_motor_volt_timeout", "temp_timeout_undervolt"):
        bus.read = read

    now = [10.0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / f"mask-{mode}.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    fault_active[0] = True
    if mode != "temp_timeout_undervolt":
        bus.temps["wrist_flex"] = 71
    now[0] = 10.30
    match = "voltage" if mode == "temp_timeout_undervolt" else "temperature"
    with pytest.raises(ValueError, match=match):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


@pytest.mark.parametrize("pwm_timeout", [False, True])
def test_held_watch_enforces_absolute_temp_limit_on_first_valid_read(tmp_path, monkeypatch, pwm_timeout):
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"abs-temp-{pwm_timeout}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    bus.temps["wrist_flex"] = 30
    orig_sync, orig_read = bus.sync_read, bus.read
    fault_phase, wf_temp_reads = [False], [0]

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if fault_phase[0] and reg in ("Present_Position", "Present_Temperature"):
            raise TimeoutError(f"{reg} sync_read timed out")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def read(reg, motor, **kwargs):
        if reg == "Temperature_Limit":
            return 60
        if fault_phase[0]:
            if pwm_timeout and reg == "Present_PWM" and motor == "wrist_flex":
                raise TimeoutError("Present_PWM timed out")
            if reg == "Present_Temperature" and motor == "wrist_flex":
                wf_temp_reads[0] += 1
                if wf_temp_reads[0] == 1:
                    return 60
                raise TimeoutError("subsequent Present_Temperature timed out")
        return orig_read(reg, motor, **kwargs)

    bus.sync_read, bus.read = sync_read, read
    now = [10.0]
    motion = NativeJointMotion(
        bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / f"abs-temp-{pwm_timeout}.jsonl"), shed_load=True
    )
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    # Hold baseline 59 C (+1 C rise < HOLD_TEMP_RISE_C), then read 60 C >= 60 C limit once before temp times out.
    motion.held = {"wrist_flex": {"since": 10.0, "saturated_since": 10.0, "temp": 59, "last_telemetry_at": 10.05}}
    fault_phase[0] = True
    now[0] = 10.30
    with pytest.raises(ValueError, match="temperature 60 >= configured limit 60"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert wf_temp_reads[0] == 1
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


@pytest.mark.parametrize("batch_mode", [True, False])
def test_confirmed_overtemp_in_motor_health_sample_does_not_read_gripper_pwm(tmp_path, monkeypatch, batch_mode):
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"no-pwm-{batch_mode}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync, orig_read = bus.sync_read, bus.read
    fault_read, seen_regs = [False], []

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if fault_read[0]:
            seen_regs.append(reg)
            if reg != "Present_Temperature":
                raise AssertionError(f"unexpected batch read after overtemperature: {reg}")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def read(reg, motor, **kwargs):
        if fault_read[0]:
            seen_regs.append(reg)
            if reg != "Present_Temperature":
                raise AssertionError(f"unexpected read after overtemperature: {reg} on {motor}")
        return orig_read(reg, motor, **kwargs)

    bus.sync_read = sync_read
    if not batch_mode:
        bus.read = read

    now = [10.0]
    monitor = MotorHealth(tmp_path / f"no-pwm-{batch_mode}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    bus.temps["wrist_flex"] = 70
    fault_read[0] = True
    with pytest.raises(ValueError, match="temperature 70 >= configured limit 70") as exc:
        monitor.sample(motion, bus.raw, dict.fromkeys(BODY, 0), 10.30, allow_gap=True)
    assert seen_regs and set(seen_regs) == {"Present_Temperature"}
    monitor.fault(motion, exc.value)


@pytest.mark.parametrize("case", ["sample_temp", "sample_volt", "sample_hw", "probe_temp", "probe_volt"])
def test_per_motor_hard_limit_stops_before_reading_remaining_motors(tmp_path, monkeypatch, case):
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"short-circuit-{case}.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    bus.temps["shoulder_pan"] = 30
    orig_read = bus.read
    target_reg = {
        "sample_temp": "Present_Temperature",
        "probe_temp": "Present_Temperature",
        "sample_volt": "Present_Input_Voltage",
        "probe_volt": "Present_Input_Voltage",
        "sample_hw": "Hardware_Error_Status",
    }[case]
    fault_phase, seen_motors = [False], []

    def read(reg, motor, **kwargs):
        if reg == "Temperature_Limit":
            return 60
        if fault_phase[0] and reg == target_reg:
            seen_motors.append(motor)
            if motor != "shoulder_pan":
                raise AssertionError(f"must not read {motor} {reg} after confirmed hard limit")
            if target_reg == "Present_Temperature":
                return 60
            if target_reg == "Present_Input_Voltage":
                return 80
            return 32
        return orig_read(reg, motor, **kwargs)

    bus.read = read
    now = [10.0]
    monitor = MotorHealth(tmp_path / f"short-circuit-{case}.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    fault_phase[0] = True
    expected = "temperature" if "temp" in case else ("voltage" if "volt" in case else "hardware error")
    with pytest.raises(ValueError, match=expected):
        if case.startswith("sample_"):
            monitor.sample(motion, bus.raw, dict.fromkeys(BODY, 0), 10.30, allow_gap=True)
        else:
            monitor.probe_limits(motion)
    assert seen_motors == ["shoulder_pan"]


@pytest.mark.parametrize("mode", ["runner_tick", "interrupt_tick_human_hold", "signal_interrupt_hold"])
def test_runner_health_poll_routes_configured_temp_limit_to_guard_torque_off_during_latched_hold(
    tmp_path, monkeypatch, mode
):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"runner-temp-{mode}.json"))
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    orig_read = bus.read
    bus.read = lambda reg, motor, **kw: 60 if reg == "Temperature_Limit" else orig_read(reg, motor, **kw)
    monitor = MotorHealth(tmp_path / f"runner-temp-{mode}.jsonl")
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

    # Stay inside check_effort's 0.2 s throttle so only Runner's temperature poll sees 60 C (below TEMP_STOP=65).
    now[0] = 10.08
    runner.ticks = 29
    runner.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [30, 30, 30, 60, 30, 30]}
    if mode == "runner_tick":
        with pytest.raises(ValueError, match="wrist_flex: temperature 60 >= configured limit 60"):
            runner.tick()
    else:
        assert ci.interrupt_tick(runner, "human-hold", tick_or_report) is True
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())
    assert monitor.stop_reasons == ["temperature limit"]


@pytest.mark.parametrize("case", ["partial_temp_dict", "pwm_timeout_probe"])
@pytest.mark.parametrize("in_signal_hold", [False, True])
def test_incomplete_runner_health_read_enforces_valid_temp_before_key_error_or_hold(
    tmp_path, monkeypatch, case, in_signal_hold
):
    import signal

    from chunk_runner import Guarded
    import chunk_runner_interrupt as ci
    from chunk_runner_run import Runner
    from chunk_runner_settle import tick_or_report
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES, SCHEMA

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"inc-{case}-{in_signal_hold}.json"))
    p_above = [38.8, -10.15, 2.0, 55.0, -13.85, 49.0]
    now, reports = [10.0], []
    bus = _make_guard_bus(p_above)
    orig_sync, orig_read = bus.sync_read, bus.read
    fault_phase = [False]

    def sync_read(reg, motors=None, normalize=True, num_retry=0):
        if fault_phase[0] and motors is None:
            if case == "partial_temp_dict" and reg == "Present_Temperature":
                return {"wrist_flex": 60}
            if case == "pwm_timeout_probe" and reg == "Present_PWM":
                raise TimeoutError("Present_PWM sync_read timed out")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    bus.sync_read = sync_read
    bus.read = lambda reg, motor, **kw: 60 if reg == "Temperature_Limit" else orig_read(reg, motor, **kw)
    monitor = MotorHealth(tmp_path / f"inc-{case}-{in_signal_hold}.jsonl")
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
    if in_signal_hold:
        runner.signals.append(signal.SIGTERM)
        assert ci.interrupt_tick(runner, "human-hold", tick_or_report) is False
        assert runner._interrupt["phase"] == "hold"

    # Keep elapsed <= 0.03 s so check_effort is throttled and only read_motor_health / probe_limits runs.
    if case == "pwm_timeout_probe":
        bus.temps["wrist_flex"] = 60
    fault_phase[0] = True
    now[0] = 10.08
    runner.ticks = 29
    if in_signal_hold:
        assert ci.interrupt_tick(runner, "human-hold", tick_or_report) is True
    else:
        with pytest.raises(ValueError, match="wrist_flex: temperature 60 >= configured limit 60"):
            runner.tick()
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())
    assert monitor.stop_reasons == ["temperature limit"]


def test_bimanual_peer_freeze_preserves_staged_overload_relief_until_commit():
    from bimanual_native import BimanualMotion
    from guarded_device import NAMES
    from guarded_native import NativeJointMotion

    def _make_pair(label: str):
        p0 = [0.0] * 6
        bus = _make_guard_bus(p0)
        leader = _make_guard_bus(p0)
        return bus, leader, NativeJointMotion(bus, leader, clock=lambda: now[0], label=label, shed_load=True)

    now = [10.0]
    bus_a, leader_a, arm_a = _make_pair("arm_a")
    bus_b, _leader_b, arm_b = _make_pair("arm_b")
    bi = BimanualMotion({"arm_a": arm_a, "arm_b": arm_b})
    zero_act = {f"{arm}.{n}.pos": 0.0 for arm in ("arm_a", "arm_b") for n in NAMES}
    bi.send(zero_act)
    now[0] = 10.05
    bi.send(zero_act)
    arm_a.tracking = arm_b.tracking = True
    arm_a.aligned_since = arm_b.aligned_since = 0.0

    # Arm A enters stall hold (with leader offset past release band) while Arm B pushes wrist_flex +40 ticks at saturated PWM.
    leader_a.raw["shoulder_pan"] += 100
    arm_a.held["shoulder_pan"] = {"since": 10.0, "saturated_since": None, "temp": 30, "stall": True}
    present_wf = bus_b.raw["wrist_flex"]
    arm_b.command["wrist_flex"] = float(present_wf + 40)
    arm_b.sent["wrist_flex"] = present_wf + 40
    bus_b.pwms["wrist_flex"] = 310
    for t in (10.25, 10.50, 10.75, 11.00):
        now[0] = t
        bi.send(zero_act)
        assert "wrist_flex" not in arm_b.held
    now[0] = 11.30
    bi.send(zero_act)
    assert bus_b.goals["wrist_flex"] == present_wf
    assert "wrist_flex" in arm_b.held and arm_b.held_once == {"wrist_flex"}
    assert arm_b.command["wrist_flex"] == present_wf


def test_persistent_monitor_write_failure_keeps_squeeze_relief_and_hard_limit_priority(tmp_path, monkeypatch):
    from guarded_device import BODY, normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "persist-io-state.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    now = [10.0]
    bus = _make_guard_bus(p0)
    bus.pwms["gripper"] = 330
    monitor = MotorHealth(tmp_path / "persist-io.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    motion.tracking, motion.aligned_since = True, 0.0

    def _fail_io(_arg=None):
        raise OSError("disk full")

    monitor.emit = _fail_io
    monitor.publish = _fail_io
    grip_start = int(motion.command["gripper"])
    motion.command["gripper"] = grip_start + 50  # >= LEAD_DEG (3 deg) ahead of present jaws -> squeeze active
    act_squeeze = {**act, "gripper.pos": normalized(bus, {"gripper": grip_start + 50})["gripper.pos"]}
    for step in range(1, 20):
        now[0] = 10.0 + step * 0.25
        motion.send(act_squeeze, hold_on_read_error=True, allow_stale_hold=True)
    assert bus.goals["gripper"] == bus.raw["gripper"]
    assert motion.command["gripper"] == bus.raw["gripper"]
    assert motion.grip_way == 1

    # Hard motor limit still cuts torque immediately even when monitor I/O fails.
    bus.temps["wrist_flex"] = 70
    now[0] += 0.25
    with pytest.raises(ValueError, match="temperature 70 >= configured limit 70"):
        motion.send(act_squeeze, hold_on_read_error=True, allow_stale_hold=True)
    assert motion.failed is True and all(v == 0 for v in bus.torque.values())


def _override_bus(bus, *, sync_read=None, read=None, sync_write=None):
    attrs = {k: v for k, v in (("sync_read", sync_read), ("read", read), ("sync_write", sync_write)) if v is not None}
    bus.__class__ = type(f"{bus.__class__.__name__}Override", (bus.__class__,), attrs)


def test_invalid_batch_temperature_retries_individually_and_enforces_hard_limit_over_encoder_hold(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "batch-nan-temp.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync, orig_read = bus.sync_read, bus.read
    fault_active, batch_regs = [False], []

    def sync_read(_self, reg, motors=None, normalize=True, num_retry=0):
        batch_regs.append(reg)
        if fault_active[0]:
            if reg == "Present_Position":
                raise TimeoutError("encoder read timed out")
            if reg == "Present_Temperature":
                vals = orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)
                return {**vals, "wrist_flex": float("nan")}
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def read(_self, reg, motor, **kwargs):
        if fault_active[0] and reg == "Present_Temperature" and motor == "wrist_flex":
            return 70
        return orig_read(reg, motor, **kwargs)

    _override_bus(bus, sync_read=sync_read, read=read)
    assert "read" not in vars(bus)
    now = [10.0]
    monitor = MotorHealth(tmp_path / "batch-nan.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)

    fault_active[0] = True
    now[0] = 10.30
    with pytest.raises(ValueError, match="temperature 70 >= configured limit 70"):
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert "Present_Temperature" in batch_regs and motion.failed is True and all(v == 0 for v in bus.torque.values())


def test_serial_oserror_during_stale_hold_remains_recoverable_without_committing_or_advancing_clock(tmp_path, monkeypatch):
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / "serial-oserror.json"))
    p0 = [10.0, 10.0, 10.0, 7.0, 10.0, 46.6]
    bus = _make_guard_bus(p0)
    orig_sync, orig_read, orig_write = bus.sync_read, bus.read, bus.sync_write
    fail_tq, writes, batch_regs = [False], 0, []

    def sync_read(_self, reg, motors=None, normalize=True, num_retry=0):
        batch_regs.append(reg)
        if fail_tq[0] and reg == "Torque_Enable":
            raise OSError("serial port I/O error")
        return orig_sync(reg, motors=motors, normalize=normalize, num_retry=num_retry)

    def read(_self, reg, motor, **kwargs):
        if fail_tq[0] and reg == "Torque_Enable":
            raise OSError("serial port I/O error")
        return orig_read(reg, motor, **kwargs)

    def count_write(_self, reg, vals, normalize=False):
        nonlocal writes
        if reg == "Goal_Position":
            writes += 1
        return orig_write(reg, vals, normalize=normalize)

    _override_bus(bus, sync_read=sync_read, read=read, sync_write=count_write)
    assert "read" not in vars(bus)
    now = [10.0]
    monitor = MotorHealth(tmp_path / "serial-oserror.jsonl")
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=monitor, shed_load=True)
    act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(act)
    now[0] = 10.05
    motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    writes_before, last_t, last_et = writes, motion.last_time, motion.last_effort_time

    fail_tq[0] = True
    now[0] = 10.30
    with pytest.raises(GoalRejected) as exc:
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
    assert exc.value.can_send_hold is False and "Torque_Enable" in batch_regs
    assert writes == writes_before
    assert motion.last_time == pytest.approx(last_t) and motion.last_effort_time == pytest.approx(last_et)
    assert motion.failed is False and all(v == 1 for v in bus.torque.values())


def test_invalid_hw_status_and_repeated_invalid_telemetry_hold_safely_and_code_digest_tracks_safety_modules(tmp_path, monkeypatch):
    import cell_envelope
    from guarded_device import normalized
    from guarded_native import GoalRejected, NativeJointMotion
    from motor_health import MotorHealth
    from omx_adapter.chunk_library import NAMES

    for case in ("hw_256_retry_0", "hw_256_retry_4", "temp_nan_twice", "temp_nan_with_undervolt", "torque_invalid_bool"):
        monkeypatch.setenv("ROSY_OMX_MONITOR_STATE", str(tmp_path / f"{case}.json"))
        bus = _make_guard_bus([10.0, 10.0, 10.0, 7.0, 10.0, 46.6])
        orig_sync, orig_read, orig_write = bus.sync_read, bus.read, bus.sync_write
        fault_on, writes = [False], 0

        def sync_read(_self, reg, motors=None, normalize=True, num_retry=0, _c=case, _os=orig_sync):
            vals = _os(reg, motors=motors, normalize=normalize, num_retry=num_retry)
            if not fault_on[0]:
                return vals
            if _c in ("hw_256_retry_0", "hw_256_retry_4") and reg == "Hardware_Error_Status":
                return {**vals, "wrist_flex": 256}
            if _c in ("temp_nan_twice", "temp_nan_with_undervolt") and reg == "Present_Temperature":
                return {**vals, "wrist_flex": float("nan")}
            if _c == "temp_nan_with_undervolt" and reg == "Present_Input_Voltage":
                return {**vals, "shoulder_pan": 50}
            if _c == "torque_invalid_bool" and reg == "Torque_Enable":
                return {**vals, "wrist_flex": 2}
            return vals

        def read(_self, reg, motor, **kwargs):
            if fault_on[0] and motor == "wrist_flex":
                if reg == "Hardware_Error_Status" and case == "hw_256_retry_4":
                    return 4
                if reg == "Present_Temperature" and case in ("temp_nan_twice", "temp_nan_with_undervolt"):
                    return float("nan")
                if reg == "Torque_Enable" and case == "torque_invalid_bool":
                    return True
            return orig_read(reg, motor, **kwargs)

        def count_write(_self, reg, vals, normalize=False):
            nonlocal writes
            writes += reg == "Goal_Position"
            return orig_write(reg, vals, normalize=normalize)

        _override_bus(bus, sync_read=sync_read, read=read, sync_write=count_write)
        now = [10.0]
        motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0], monitor=MotorHealth(tmp_path / f"{case}.jsonl"))
        act = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
        motion.send(act)
        now[0] = 10.05
        motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
        w0, lt, let = writes, motion.last_time, motion.last_effort_time
        fault_on[0], now[0] = True, 10.30
        if case in ("hw_256_retry_4", "temp_nan_with_undervolt"):
            with pytest.raises(ValueError) as exc:
                motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
            assert not isinstance(exc.value, GoalRejected) and motion.failed is True and all(v == 0 for v in bus.torque.values())
        else:
            with pytest.raises(GoalRejected) as exc:
                motion.send(act, hold_on_read_error=True, allow_stale_hold=True)
            assert exc.value.can_send_hold is False and writes == w0 and motion.failed is False
            assert motion.last_time == pytest.approx(lt) and motion.last_effort_time == pytest.approx(let)
            assert all(v == 1 for v in bus.torque.values())

    base, omx_dir, orig_read_bytes = cell_envelope._code_digest(), Path(__file__).resolve().parents[1] / "deploy/robot/omx", Path.read_bytes
    for mod in ("motor_health.py", "chunk_runner_interrupt.py", "chunk_runner_guards.py", "chunk_runner_settle.py"):
        target_p = (omx_dir / mod).resolve()
        monkeypatch.setattr(Path, "read_bytes", lambda self, _tp=target_p: orig_read_bytes(self) + (b"\n# test\n" if self.resolve() == _tp else b""))
        cell_envelope._CODE_DIGEST_CACHE.clear()
        assert cell_envelope._code_digest() != base
