"""D-858 S3: timed stop test on the real port over a fake bus with a controlled clock, the HOLD
after a commissioning record save, and the stop-test CLI in dry-run. No serial, no arm."""

import json
import threading
import time
from dataclasses import replace

import pytest

from omx_adapter.real.commissioning_record import CommissioningStore, load_motion_evidence
from omx_adapter.real.dynamixel_bus import ADDR_GOAL, ADDR_PRESENT, _BusClaims, to_rad, to_raw
from omx_adapter.real.dynamixel_port import DynamixelPort
from omx_adapter.real.dynamixel_stop_test import main, record_value, run_stop_test, stop_test_poses
from test_omx_dynamixel_port import HW, PASSED, FakeBus, Fence, _config, _grant

JOINT1 = HW.joint_ids[0]
HW_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
MEASURING = replace(PASSED, stop_test=None)  # measurement mode: everything but the stop test


class Clock:
    """Fake time: only sleeps move it. The real sleep lets the motion thread run."""

    def __init__(self):
        self.t, self._lock = 0.0, threading.Lock()

    def __call__(self):
        with self._lock:
            return self.t

    def sleep(self, seconds):
        with self._lock:
            self.t += seconds
        time.sleep(0.0005)


class CoastBus(FakeBus):
    """joint1 follows its goal at once while driven. After the stop's hold-in-place write it
    keeps going at ``coast_rad_s`` for ``coast_s`` (the motor's own run-out), on the fake clock."""

    def __init__(self, clock, *, coast_rad_s=0.3, coast_s=0.1):
        super().__init__()
        self.clock, self.coast_rad_s, self.coast_s, self.coast = clock, coast_rad_s, coast_s, None

    def sync_write(self, addr, size, values):
        hold = (addr == ADDR_GOAL and set(values) == set(HW.joint_ids)
                and all(values[i] == self.regs[i][ADDR_PRESENT] for i in values))
        super().sync_write(addr, size, values)
        if hold and self.coast is None:
            self.coast = (self.clock(), to_rad(values[JOINT1]))

    def sync_read(self, ids, addr, size):
        out = super().sync_read(ids, addr, size)
        if addr == ADDR_PRESENT and JOINT1 in out and self.coast:
            t0, q0 = self.coast
            out[JOINT1] = to_raw(q0 + self.coast_rad_s * min(self.clock() - t0, self.coast_s))
        return out


def _ready(bus, *, evidence=MEASURING, revision=lambda: "rec-1", clock=None):
    fence = Fence()
    port = DynamixelPort(bus, device="/dev/serial/by-id/usb-FAKE-ARM-0", config=_config(),
                         evidence=evidence, planner=lambda g: [{"pose": [0.1, 0, 0, 0, 0]}],
                         stop_fence=fence, record_revision=revision,
                         sleep=clock.sleep if clock else (lambda s: None),
                         claims=_BusClaims(), **({} if clock else {"start": lambda fn: fn()}))
    fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    return port, fence


def _run(coast_rad_s, coast_s):
    clock = Clock()
    port, _ = _ready(CoastBus(clock, coast_rad_s=coast_rad_s, coast_s=coast_s), clock=clock)
    return port, run_stop_test(port, authority_epoch=2, dispatch_generation=8,
                               clock=clock, sleep=clock.sleep)


def test_quick_stop_passes_v016_and_is_recorded_bound_to_the_config():
    port, result = _run(0.3, 0.1)
    assert result["started"] and result["stopped_mid_motion"] and result["settled_in_window"]
    assert 100 <= result["measured_stop_ms"] <= 300  # run-out + one velocity window
    assert result["joint1_deviation_rad"] == pytest.approx(0.03, abs=0.005)
    assert result["joint1_velocity_rad_s"] <= 0.1 and result["passed"] is True
    assert port.snapshot()["state"] == "STOPPED" and port.latched
    value = record_value(result, config_revision="cal-measured-1")
    assert value["driver"] == "dynamixel" and value["config_revision"] == "cal-measured-1"
    assert replace(MEASURING, stop_test=value).blockers(config_revision="cal-measured-1") == []


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


def test_stop_test_motion_needs_the_rest_of_the_gate_and_stays_slow():
    bus = FakeBus()
    port, _ = _ready(bus, evidence=replace(MEASURING, workspace_m=None))
    result = run_stop_test(port, authority_epoch=2, dispatch_generation=8, sleep=lambda s: None)
    assert result["started"] is False and "workspace box not measured" in result["reason"]
    port, _ = _ready(FakeBus())
    receipt = port.submit_stop_test([[0.1, 0, 0, 0, 0]], authority_epoch=2, dispatch_generation=8,
                                    max_speed_rad_s=0.5)
    assert receipt.accepted is False and port.last_refusal == "STOP_TEST_SPEED"
    # A normal grant still needs the stop test record.
    assert port.submit(_grant()).accepted is False and "no stop test record" in port.last_refusal


def test_stop_test_moves_at_the_capped_speed():
    bus = FakeBus()
    port, _ = _ready(bus)
    assert port.submit_stop_test([[0.1, 0, 0, 0, 0]], authority_epoch=2, dispatch_generation=8,
                                 max_speed_rad_s=0.1).accepted
    goals = [to_rad(e[2][JOINT1]) for e in bus.log if e[0] == "sw" and e[1] == ADDR_GOAL
             and set(e[2]) == set(HW.joint_ids)]
    steps = [b - a for a, b in zip(goals, goals[1:])]
    assert max(steps) <= 0.1 * 0.02 + 0.002 and goals[-1] == pytest.approx(0.1, abs=0.002)
    assert port.outcome["result"] == "SUCCEEDED" and port._vel == port.config.velocity_limits


@pytest.mark.parametrize("amplitude,cycles", [(0.0, 1), (0.25, 1), (0.1, 0), (0.1, 6)])
def test_stop_test_poses_stay_small(amplitude, cycles):
    with pytest.raises(ValueError):
        stop_test_poses([0.0] * 5, amplitude_rad=amplitude, cycles=cycles)


def test_saved_record_holds_the_port_until_reload_and_person_rearm():
    stored = {"rev": "rec-1"}
    bus = FakeBus()
    port, fence = _ready(bus, evidence=PASSED, revision=lambda: stored["rev"])
    stored["rev"] = "rec-2"  # a commissioning save landed
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal == "COMMISSIONING_RECORD_CHANGED"
    assert port.latched and port.snapshot()["reason"] == "COMMISSIONING_RECORD_CHANGED"
    assert fence.trips and not fence.open  # HOLD closed the platform fence too
    fence.person_rearm(9)
    with pytest.raises(PermissionError, match="reload"):
        port.rearm(authority_epoch=2, dispatch_generation=9)
    port.reload_evidence(replace(PASSED, revision="rec-2"))
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert port.submit(_grant(generation=9)).accepted is True
    assert port.snapshot()["record_revision"] == "rec-2"


def test_record_change_between_steps_holds_the_motion():
    stored = {"rev": "rec-1"}
    port, _ = _ready(FakeBus(), evidence=PASSED, revision=lambda: stored["rev"])
    port.planner = lambda g: [{"pose": [0.05, 0, 0, 0, 0]}, {"pose": [0.1, 0, 0, 0, 0]}]
    original = port._move

    def move_then_save(goal):
        original(goal)
        stored["rev"] = "rec-2"
    port._move = move_then_save
    assert port.submit(_grant()).accepted is True
    assert port.outcome["result"] == "HOLD"
    assert port.outcome["reason"] == "COMMISSIONING_RECORD_CHANGED"


def test_unreadable_record_holds_and_reload_needs_hold():
    def broken():
        raise ValueError("damaged")
    port, _ = _ready(FakeBus(), evidence=PASSED, revision=lambda: "rec-1")
    with pytest.raises(PermissionError):
        port.reload_evidence(PASSED)  # not while armed
    port._record_revision = broken
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal.startswith("COMMISSIONING_RECORD_UNREADABLE")


def test_cli_dry_run_prints_the_measurement_gate_and_opens_nothing(tmp_path, capsys):
    config = tmp_path / "owner.json"
    config.write_text(json.dumps({
        "enabled": True, "workcell_id": "omx-1", "instance_id": "omx-1-control",
        "joint_names": list(HW_JOINTS), "position_limits": {n: [-1.5, 1.5] for n in HW_JOINTS},
        "velocity_limits": {n: 2.0 for n in HW_JOINTS}, "allowed_owners": ["rule_based"],
        "calibration_revision": "cal-measured-1"}), encoding="utf-8")
    args = ["--record-root", str(tmp_path / "rec"), "--owner-config", str(config), "--by", "kim",
            "--dry-run"]
    assert main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and "no commissioning record" in report["measurement_gate_blockers"][0]
    store = CommissioningStore(tmp_path / "rec", workcell_id="omx-1", instance_id="omx-1-control")
    store.save({"joint_limits": {n: [-1.6, 1.6] for n in HW_JOINTS},
                "gripper": {"open_rad": 0.5, "close_rad": -0.2},
                "workspace": [[-1, 1], [-1, 1], [-0.5, 1]]}, by="kim",
               config_revision="cal-measured-1", joint_names=HW_JOINTS, expected_revision=None)
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["measurement_gate_blockers"] == [] and report["record_revision"] == store.revision()
    assert load_motion_evidence(store, _config()).stop_test is None  # dry run saved nothing
    with pytest.raises(SystemExit):  # a real run needs every device argument and a person
        main(args[:-1])
