"""D-858 S3: timed stop test on the real port over a fake bus with a controlled clock, the HOLD
after a commissioning record save, and the stop-test CLI. No serial, no arm."""

import json
import math
import socket
import threading
import time

import pytest

from omx_adapter.real.commissioning_record import CommissioningStore, load_motion_evidence
from omx_adapter.real.dynamixel_bus import ADDR_GOAL, ADDR_PRESENT, _BusClaims, to_rad, to_raw
from omx_adapter.real.dynamixel_gates import MotionEvidence
from omx_adapter.real.dynamixel_port import DynamixelPort
from omx_adapter.real.dynamixel_stop_test import (
    main, owner_running, record_value, run_stop_test, stop_test_poses,
)
from test_omx_dynamixel_port import (
    HW, JOINTS, PASSED, FakeBus, FakeStore, Fence, _config, _grant, record,
)

JOINT1 = HW.joint_ids[0]
MEASURING = record(stop_test=None)  # measurement mode: everything but the stop test


class Clock:
    """Fake time. The stop test's ``sleep`` moves it; the port's motion thread only ``wait``s
    for it, so the arm moves exactly one cycle per period of fake time."""

    def __init__(self):
        self.t, self._lock = 0.0, threading.Lock()

    def __call__(self):
        with self._lock:
            return self.t

    def sleep(self, seconds):
        with self._lock:
            self.t += seconds
        time.sleep(0.002)  # let the motion thread catch up

    def wait(self, seconds):
        target = self() + seconds - 1e-9
        while self() < target:
            time.sleep(0.0001)


class CoastBus(FakeBus):
    """joint1 follows its goal at once while driven. After the stop's hold-in-place write it runs
    on at ``coast_rad_s`` for ``coast_s`` (the motor's own run-out) on the fake clock. With
    ``coast_rad_s=None`` it keeps the last commanded speed: the hold write was ignored."""

    def __init__(self, clock, *, coast_rad_s=0.3, coast_s=0.1):
        super().__init__()
        self.clock, self.coast_rad_s, self.coast_s, self.coast = clock, coast_rad_s, coast_s, None
        self.goals = []  # (t, joint1 rad) of motion goal writes

    def sync_write(self, addr, size, values):
        hold = (addr == ADDR_GOAL and set(values) == set(HW.joint_ids)
                and all(values[i] == self.regs[i][ADDR_PRESENT] for i in values))
        if addr == ADDR_GOAL and set(values) == set(HW.joint_ids) and not hold:
            self.goals.append((self.clock(), to_rad(values[JOINT1])))
        super().sync_write(addr, size, values)
        if hold and self.coast is None:
            (t1, q1), (t2, q2) = self.goals[-2], self.goals[-1]
            commanded = (q2 - q1) / (t2 - t1) if t2 > t1 else 0.0
            speed = commanded if self.coast_rad_s is None else self.coast_rad_s
            self.coast = (self.clock(), to_rad(values[JOINT1]), speed)

    def sync_read(self, ids, addr, size):
        out = super().sync_read(ids, addr, size)
        if addr == ADDR_PRESENT and JOINT1 in out and self.coast:
            t0, q0, speed = self.coast
            out[JOINT1] = to_raw(q0 + speed * min(self.clock() - t0, self.coast_s))
        return out


def _ready(bus, *, rec=MEASURING, store=None, clock=None):
    fence = Fence()
    port = DynamixelPort(bus, device="/dev/serial/by-id/usb-FAKE-ARM-0", config=_config(),
                         store=store or FakeStore(rec), planner=lambda g: [{"pose": [0.1, 0, 0, 0, 0]}],
                         stop_fence=fence, sleep=clock.wait if clock else (lambda s: None),
                         claims=_BusClaims(), **({} if clock else {"start": lambda fn: fn()}))
    fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    return port, fence


def _run(coast_rad_s, coast_s, **kwargs):
    clock = Clock()
    port, _ = _ready(CoastBus(clock, coast_rad_s=coast_rad_s, coast_s=coast_s), clock=clock)
    return port, run_stop_test(port, authority_epoch=2, dispatch_generation=8,
                               clock=clock, sleep=clock.sleep, **kwargs)


def test_quick_stop_passes_v016_and_is_recorded_bound_to_the_config():
    port, result = _run(0.3, 0.1)
    assert result["started"] and result["stopped_mid_motion"] and result["settled_in_window"]
    assert result["pre_stop_velocity_rad_s"] >= 0.15  # 0.2 rad/s commanded, 0.95x interpolated
    assert 100 <= result["measured_stop_ms"] <= 300  # run-out + one velocity window
    assert result["joint1_deviation_rad"] == pytest.approx(0.03, abs=0.006)
    assert result["joint1_velocity_rad_s"] <= 0.03 and result["passed"] is True
    assert port.snapshot()["state"] == "STOPPED" and port.latched
    value = record_value(result, config_revision="cal-measured-1")
    assert value["driver"] == "dynamixel" and value["pre_stop_velocity_rad_s"] >= 0.15
    gate = MotionEvidence(stop_test=value, config_revision="cal-measured-1")
    assert gate.stop_test_blockers() == []


def test_ignored_stop_that_keeps_sliding_fails():
    """S3 review H1: a hold write the motor ignores keeps joint1 at the commanded speed."""
    port, result = _run(None, math.inf)
    assert port.snapshot()["state"] == "STOPPED"  # the software stop alone is not the verdict
    assert result["started"] and result["passed"] is False
    assert result["settled_in_window"] is False and result["joint1_deviation_rad"] > 0.1


@pytest.mark.parametrize("coast_rad_s,coast_s,why", [
    (0.3, 0.7, "slow"),        # runs on 700 ms: past 500 ms and 0.21 rad
    (0.9, 0.15, "deviation"),  # stops in time but 0.135 rad from where it was
])
def test_slow_or_drifting_stop_fails(coast_rad_s, coast_s, why):
    _, result = _run(coast_rad_s, coast_s)
    assert result["started"] and result["passed"] is False
    if why == "slow":
        assert result["measured_stop_ms"] > 500
    else:
        assert result["measured_stop_ms"] <= 500 and result["joint1_deviation_rad"] > 0.1


def test_stop_test_speed_below_the_floor_is_refused_everywhere():
    with pytest.raises(ValueError, match="speed"):
        _run(0.3, 0.1, speed_rad_s=0.1)
    port, _ = _ready(FakeBus())
    for speed in (0.1, 0.5):
        assert port.submit_stop_test([[0.1, 0, 0, 0, 0]], authority_epoch=2, dispatch_generation=8,
                                     max_speed_rad_s=speed).accepted is False
        assert port.last_refusal == "STOP_TEST_SPEED"
    slow = MotionEvidence(stop_test={**PASSED["items"]["stop_test"]["value"],
                                     "pre_stop_velocity_rad_s": 0.1}, config_revision="cal-measured-1")
    assert "did not pass" in slow.stop_test_blockers()[0]


@pytest.mark.parametrize("poses,reason", [
    ([[0.1, 0.1, 0, 0, 0]], "STOP_TEST_POSE"),   # another joint moves
    ([[0.25, 0, 0, 0, 0]], "STOP_TEST_POSE"),    # past the 0.2 rad amplitude
    ([[0.1, 0, 0, 0]], "STOP_TEST_POSE"),        # wrong length
    ([[0.1, 0, 0, 0, 0]] * 21, "STOP_TEST_STEPS"),
    ([], "STOP_TEST_STEPS"),
])
def test_measurement_mode_moves_only_joint1_a_little(poses, reason):
    bus = FakeBus()
    port, _ = _ready(bus)
    bus.log.clear()
    assert port.submit_stop_test(poses, authority_epoch=2, dispatch_generation=8,
                                 max_speed_rad_s=0.2).accepted is False
    assert port.last_refusal.startswith(reason) and bus.log == []


def test_stop_test_motion_needs_the_rest_of_the_gate_and_stays_slow():
    port, _ = _ready(FakeBus(), rec=record(stop_test=None, workspace=None))
    result = run_stop_test(port, authority_epoch=2, dispatch_generation=8, sleep=lambda s: None)
    assert result["started"] is False and "workspace box not measured" in result["reason"]
    bus = FakeBus()
    port, _ = _ready(bus)
    assert port.submit(_grant()).accepted is False and "no stop test record" in port.last_refusal
    port, _ = _ready(bus)
    assert port.submit_stop_test([[0.1, 0, 0, 0, 0]], authority_epoch=2, dispatch_generation=8,
                                 max_speed_rad_s=0.15).accepted
    goals = [to_rad(e[2][JOINT1]) for e in bus.log if e[0] == "sw" and e[1] == ADDR_GOAL
             and set(e[2]) == set(HW.joint_ids)]
    steps = [b - a for a, b in zip(goals, goals[1:])]
    assert max(steps) <= 0.15 * 0.02 + 0.002 and goals[-1] == pytest.approx(0.1, abs=0.002)
    assert port.outcome["result"] == "SUCCEEDED" and port._vel == port.config.velocity_limits


@pytest.mark.parametrize("amplitude,cycles", [(0.0, 1), (0.25, 1), (0.1, 0), (0.1, 6)])
def test_stop_test_poses_stay_small(amplitude, cycles):
    with pytest.raises(ValueError):
        stop_test_poses([0.0] * 5, amplitude_rad=amplitude, cycles=cycles)


def test_saved_record_holds_the_port_until_reload_and_person_rearm():
    store = FakeStore(PASSED)
    port, fence = _ready(FakeBus(), store=store)
    store.record = record(gripper={"open_rad": 0.4, "close_rad": -0.2})  # a save landed
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal == "COMMISSIONING_RECORD_CHANGED"
    assert port.latched and port.snapshot()["reason"] == "COMMISSIONING_RECORD_CHANGED"
    assert fence.trips and not fence.open  # HOLD closed the platform fence too
    fence.person_rearm(9)
    with pytest.raises(PermissionError, match="reload"):
        port.rearm(authority_epoch=2, dispatch_generation=9)
    port.reload_evidence()  # the port reads the store itself; no evidence comes from outside
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert port.evidence.gripper_open_rad == 0.4
    assert port.submit(_grant(generation=9)).accepted is True
    assert port.snapshot()["record_revision"] == store.revision()


def test_record_change_between_steps_holds_the_motion():
    store = FakeStore(PASSED)
    port, _ = _ready(FakeBus(), store=store)
    port.planner = lambda g: [{"pose": [0.05, 0, 0, 0, 0]}, {"pose": [0.1, 0, 0, 0, 0]}]
    original = port._move

    def move_then_save(goal):
        original(goal)
        store.record = record(workspace=[[-0.9, 0.9], [-1.0, 1.0], [-0.5, 1.0]])
    port._move = move_then_save
    assert port.submit(_grant()).accepted is True
    assert port.outcome["result"] == "HOLD"
    assert port.outcome["reason"] == "COMMISSIONING_RECORD_CHANGED"


def test_unreadable_record_holds_and_reload_needs_hold():
    class Broken(FakeStore):
        def revision(self):
            raise ValueError("damaged")
    store = FakeStore(PASSED)
    port, _ = _ready(FakeBus(), store=store)
    with pytest.raises(PermissionError):
        port.reload_evidence()  # not while armed
    port.store = Broken(PASSED)
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal.startswith("COMMISSIONING_RECORD_UNREADABLE")


def _cli_setup(tmp_path):
    config = tmp_path / "owner.json"
    config.write_text(json.dumps({
        "enabled": True, "workcell_id": "omx-1", "instance_id": "omx-1-control",
        "joint_names": list(JOINTS), "position_limits": {n: [-1.5, 1.5] for n in JOINTS},
        "velocity_limits": {n: 2.0 for n in JOINTS}, "allowed_owners": ["rule_based"],
        "calibration_revision": "cal-measured-1"}), encoding="utf-8")
    store = CommissioningStore(tmp_path / "rec", workcell_id="omx-1", instance_id="omx-1-control")
    args = ["--record-root", str(tmp_path / "rec"), "--owner-config", str(config), "--by", "kim"]
    return store, args


def _save_measured(store):
    store.save({"joint_limits": {n: [-1.6, 1.6] for n in JOINTS},
                "gripper": {"open_rad": 0.5, "close_rad": -0.2},
                "workspace": [[-1, 1], [-1, 1], [-0.5, 1]]}, by="kim",
               config_revision="cal-measured-1", joint_names=JOINTS, expected_revision=None)


def test_cli_dry_run_prints_the_measurement_gate_and_opens_nothing(tmp_path, capsys):
    store, args = _cli_setup(tmp_path)
    assert main(args + ["--dry-run"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and "no commissioning record" in report["measurement_gate_blockers"][0]
    _save_measured(store)
    assert main(args + ["--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["measurement_gate_blockers"] == [] and report["record_revision"] == store.revision()
    assert load_motion_evidence(store, _config()).stop_test is None  # dry run saved nothing
    assert main(args + ["--dry-run", "--speed-rad-s", "0.1"]) == 2  # below the stop-test floor
    capsys.readouterr()
    with pytest.raises(SystemExit):  # a real run needs every device argument and a person
        main(args)


class BenchFence(Fence):
    """LocalStopController stand-in for the CLI; records how it was rearmed."""

    instances = []

    def __init__(self, path, *, workcell_id, instance_id):
        super().__init__()
        self.rearms = []
        BenchFence.instances.append(self)

    def rearm(self, *, authority_epoch, dispatch_generation, operator_confirmed,
              fleet_fence_current, reason):
        assert operator_confirmed and fleet_fence_current(authority_epoch, dispatch_generation)
        self.rearms.append(reason)
        self.person_rearm(dispatch_generation)


def test_cli_real_run_rearms_as_bench_records_and_leaves_the_fence_tripped(tmp_path, monkeypatch, capsys):
    import omx_adapter.local_stop as local_stop
    import omx_adapter.real.dynamixel_port as port_module
    ports = []

    def fake_open(device, **kwargs):
        ports.append(DynamixelPort(FakeBus(), device=device, claims=_BusClaims(), **kwargs))
        return ports[-1]
    monkeypatch.setattr(port_module, "open_real_port", fake_open)
    monkeypatch.setattr(local_stop, "LocalStopController", BenchFence)
    store, args = _cli_setup(tmp_path)
    _save_measured(store)
    real = args + ["--device", "/dev/serial/by-id/usb-FAKE-ARM-0", "--stop-journal",
                   str(tmp_path / "stop.db"), "--owner-socket", str(tmp_path / "none.sock"),
                   "--authority-epoch", "2", "--dispatch-generation", "8", "--operator-confirmed"]
    main(real)
    report = json.loads(capsys.readouterr().out)
    fence = BenchFence.instances[-1]
    assert fence.rearms == ["BENCH_COMMISSIONING_REARM"]
    assert ports[-1].latched and fence.trips and not fence.open  # owner needs a person rearm
    assert report["result"]["started"] and store.read()["items"]["stop_test"]["measured_by"] == "kim"


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets")
def test_cli_refuses_while_this_arms_owner_is_running(tmp_path):
    store, args = _cli_setup(tmp_path)
    _save_measured(store)
    path = tmp_path / "owner.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owner:
        owner.bind(str(path))
        owner.listen(1)
        assert owner_running(path)
        with pytest.raises(SystemExit):
            main(args + ["--device", "/dev/serial/by-id/usb-FAKE-ARM-0", "--stop-journal",
                         str(tmp_path / "stop.db"), "--owner-socket", str(path),
                         "--authority-epoch", "2", "--dispatch-generation", "8",
                         "--operator-confirmed"])
    assert not owner_running(tmp_path / "missing.sock")
