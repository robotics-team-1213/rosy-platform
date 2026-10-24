"""D-858 S1 real Dynamixel port over a fake bus. No serial device, no SDK, no arm.

Behaviours absorbed from rosy-vault 9a744a3 device_core (tests/test_dynamixel.py,
tests/test_device_core.py), re-expressed against the platform LocalActionPort.
"""

import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import FleetActionGrant, LocalStopRequest, StopRequestSource
from omx_adapter.action_runner import action_grant_digest
from omx_adapter.command_owner import ArmCommandConfig
from omx_adapter.real.dynamixel_bus import (
    ADDR_GOAL, ADDR_HW_ERROR, ADDR_PRESENT, ADDR_PRESENT_CURRENT, ADDR_TORQUE, BusBusy,
    Hardware, HardwareMismatch, SdkBus, _BusClaims, to_raw,
)
from omx_adapter.real.commissioning_record import SCHEMA, revision_of
from omx_adapter.real.dynamixel_gates import Tracking
from omx_adapter.real.dynamixel_port import DynamixelPort, open_real_port
from omx_adapter.local_stop import LocalStopBlocked, LocalStopController

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
HW = Hardware()
BOX = ((-1.0, 1.0), (-1.0, 1.0), (-0.5, 1.0))
STOP_OK = {"passed": True, "driver": "dynamixel", "measured_stop_ms": 180, "joint": "joint1",
           "joint1_deviation_rad": 0.02, "joint1_velocity_rad_s": 0.01,
           "pre_stop_velocity_rad_s": 0.19, "config_revision": "cal-measured-1"}
MEASURED = {"joint_limits": {name: [-1.6, 1.6] for name in JOINTS},
            "gripper": {"open_rad": 0.5, "close_rad": -0.2},
            "workspace": [list(pair) for pair in BOX], "stop_test": STOP_OK}


def record(**items):
    """A commissioning record; an item set to None is left out."""
    return {"schema": SCHEMA, "workcell_id": "omx-1", "instance_id": "omx-1-control",
            "joint_names": list(JOINTS),
            "items": {name: {"value": value, "measured_at": "2026-10-24T09:00:00+00:00",
                             "measured_by": "test", "config_revision": "cal-measured-1"}
                      for name, value in {**MEASURED, **items}.items() if value is not None}}


class FakeStore:
    """CommissioningStore stand-in: the port reads its evidence only through it (S3 L1)."""

    def __init__(self, rec):
        self.record = rec

    def read(self):
        return self.record

    def revision(self):
        return revision_of(self.record)


PASSED = record()
GRASP = {"position_rad": [-0.3, 0.1], "current_ma": [20, 200], "stable_rad": 0.05,
         "samples": 3, "period_s": 0.01}


class FakeBus:
    """Register model. Goal writes move the motor at once unless the ID is stuck."""

    def __init__(self, over=None):
        self.regs = {i: {0: HW.models[i], 11: HW.operating_modes[i], ADDR_HW_ERROR: 0,
                         ADDR_TORQUE: 0, ADDR_PRESENT: 2048, ADDR_GOAL: 2048,
                         ADDR_PRESENT_CURRENT: 0} for i in HW.all_ids}
        for (i, addr), value in (over or {}).items():
            self.regs[i][addr] = value
        self.log, self.stuck, self.fail = [], set(), False
        self.gripper_follows = True

    def _apply(self, i, addr, value):
        self.regs[i][addr] = value
        if addr == ADDR_GOAL and i not in self.stuck and (i != HW.gripper_id or self.gripper_follows):
            self.regs[i][ADDR_PRESENT] = value

    def read(self, i, addr, size):
        if self.fail:
            raise IOError("bus gone")
        return self.regs[i][addr]

    def write(self, i, addr, size, value):
        if self.fail:
            raise IOError("bus gone")
        self.log.append(("w", i, addr, value))
        self._apply(i, addr, value)

    def sync_read(self, ids, addr, size):
        if self.fail:
            raise IOError("bus gone")
        return {i: self.regs[i][addr] for i in ids}

    def sync_write(self, addr, size, values):
        if self.fail:
            raise IOError("bus gone")
        self.log.append(("sw", addr, dict(values)))
        for i, value in values.items():
            self._apply(i, addr, value)

    def close(self):
        self.log.append(("close",))


class Fence:
    """LocalStopController stand-in with its own lock: one row (generation, open or latched).
    Starts latched at (2, 7); ``person_rearm`` is the operator rearm at a newer generation."""

    def __init__(self, gen=(2, 7), *, open_=False):
        self._lock = threading.RLock()
        self.gen, self.open, self.trips, self.on_is_open = gen, open_, [], None
        self.reason, self.source = "STARTUP", StopRequestSource.FLEET

    def is_open(self, *, authority_epoch, dispatch_generation):
        with self._lock:
            hook, self.on_is_open = self.on_is_open, None
            if hook:
                hook()
            return self.open and self.gen == (authority_epoch, dispatch_generation)

    def snapshot(self, *, workcell_id, instance_id):
        with self._lock:
            return SimpleNamespace(state="OPEN" if self.open else "LOCAL_LATCHED",
                                   authority_epoch=self.gen[0], dispatch_generation=self.gen[1],
                                   reason=self.reason, source=self.source)

    def trip(self, request, *, source):
        with self._lock:
            self.trips.append(request)
            self.gen = max(self.gen, (request.authority_epoch, request.dispatch_generation))
            self.open, self.reason, self.source = False, request.reason, source

    def person_rearm(self, generation):
        with self._lock:
            assert (2, generation) > self.gen
            self.gen, self.open = (2, generation), True

    def close(self):  # someone else tripped local_stop
        with self._lock:
            self.open = False


class StickyFence(Fence):
    """A fence whose trip does not close it: only the port's own generation rule is left."""

    def trip(self, request, *, source):
        self.trips.append(request)


def _config(workcell="omx-1", instance="omx-1-control"):
    return ArmCommandConfig(
        enabled=True, workcell_id=workcell, instance_id=instance, joint_names=JOINTS,
        position_limits={name: (-1.5, 1.5) for name in JOINTS},
        velocity_limits={name: 2.0 for name in JOINTS},
        allowed_owners=("rule_based",), calibration_revision="cal-measured-1")


def _grant(workcell="omx-1", instance="omx-1-control", generation=8):
    now = datetime.now(timezone.utc)
    source = {"object_id": "block-1", "observation_id": "obs-1", "frame_sha256": "b" * 64,
              "camera_identity": "cam-1", "optical_frame_id": "cam_optical",
              "calibration_revision": "cal-1", "transform_revision": "tf-1",
              "capture_time_ns": 1760000000000000000, "selector_kind": "point",
              "image_bbox_xyxy": [1, 2, 3, 4]}
    value = {"mission_id": "mission-1", "step_id": "step-1", "action_id": "action-1",
             "attempt_id": "attempt-1", "request_digest": "0" * 64, "workcell_id": workcell,
             "instance_id": instance, "action_kind": "PICK_PLACE", "source_evidence": source,
             "destination_evidence": {**source, "object_id": "tray-1"},
             "capability_revision": "pick-place-v1", "config_revision": "cfg-1",
             "observation_revision": "obs-1", "authority_epoch": 2, "dispatch_generation": generation,
             "issued_at": now, "expires_at": now + timedelta(seconds=15)}
    value["request_digest"] = action_grant_digest(value)
    return FleetActionGrant.model_validate(value)


def _port(bus=None, *, plan=None, rec=PASSED, claims=None, config=None,
          device="/dev/serial/by-id/usb-FAKE-ARM-0", fence=None, tracking=Tracking()):
    plan = plan if plan is not None else [{"pose": [0.1, 0.0, 0.0, 0.0, 0.0]}]
    return DynamixelPort(
        bus or FakeBus(), device=device, config=config or _config(), store=FakeStore(rec),
        planner=lambda grant: plan, stop_fence=fence or Fence(), tracking=tracking,
        sleep=lambda s: None, start=lambda fn: fn(), claims=claims or _BusClaims())


def _armed(bus=None, *, fence=None, **kwargs):
    fence = fence if fence is not None else Fence()
    port = _port(bus, fence=fence, **kwargs)
    fence.person_rearm(8)  # a person rearms the platform fence after the startup HOLD
    port.rearm(authority_epoch=2, dispatch_generation=8)
    return port


def _writes(bus):
    return [entry for entry in bus.log if entry[0] in ("w", "sw")]


def _written_addresses(bus):
    return {entry[2] if entry[0] == "w" else entry[1] for entry in _writes(bus)}


def test_starts_latched_in_hold_and_check_only_reads():
    bus = FakeBus()
    port = _port(bus)
    assert port.snapshot()["state"] == "HOLD" and port.latched
    assert port.snapshot()["reason"] == "STARTUP_HOLD"
    assert _writes(bus) == []
    receipt = port.submit(_grant())
    assert receipt.accepted is False and port.last_refusal.startswith("LATCHED")


@pytest.mark.parametrize("over", [{(12, 0): 1200}, {(16, 11): 3}, {(14, ADDR_HW_ERROR): 0x20}])
def test_startup_refuses_wrong_model_mode_or_fault_without_writing(over):
    bus, claims = FakeBus(over), _BusClaims()
    with pytest.raises(HardwareMismatch):
        _port(bus, claims=claims)
    assert _writes(bus) == []
    _port(FakeBus(), claims=claims)  # the failed start released its claim


def test_runs_plan_and_never_writes_eeprom():
    bus = FakeBus()
    port = _armed(bus, plan=[{"pose": [0.3, -0.2, 0.1, 0.0, 0.0]}, {"grip": "close"},
                             {"grasp_check": GRASP}, {"grip": "open"}])
    for i in HW.all_ids:
        bus.regs[i][ADDR_PRESENT_CURRENT] = 80
    bus.gripper_follows = True
    receipt = port.submit(_grant())
    assert receipt.accepted is True and receipt.driver_goal_id.startswith("dxl-")
    assert port.outcome["result"] == "SUCCEEDED" and port.snapshot()["state"] == "IDLE"
    addresses = _written_addresses(bus)
    assert addresses <= {ADDR_TORQUE, ADDR_GOAL} and min(addresses) >= 64
    # Torque goes on only after goal = present was written.
    first_torque = next(n for n, e in enumerate(bus.log) if e[0] == "w" and e[2] == ADDR_TORQUE)
    assert bus.log[0][:2] == ("sw", ADDR_GOAL) and first_torque > 0
    assert bus.regs[11][ADDR_PRESENT] == to_raw(0.3)


def test_stop_latches_and_holds_in_place_without_torque_off():
    bus = FakeBus()
    port = _armed(bus)
    port.submit(_grant())
    bus.log.clear()
    bus.regs[11][ADDR_PRESENT] = 2100  # wherever the arm is now
    assert port.cancel({"action_id": "action-1"}) is True
    assert port.latched and port.snapshot()["state"] == "STOPPED"
    # Joints hold where they are; the gripper goal is left alone (keeps its grip).
    assert bus.log == [("sw", ADDR_GOAL, {i: bus.regs[i][ADDR_PRESENT] for i in HW.joint_ids})]
    assert ADDR_TORQUE not in _written_addresses(bus)
    assert port.submit(_grant()).accepted is False and port.last_refusal.startswith("LATCHED")


def test_stop_keeps_latch_when_bus_is_gone():
    bus = FakeBus()
    port = _armed(bus)
    port.submit(_grant())
    bus.fail = True
    assert port.cancel({}) is None  # latched, but the hold write is unconfirmed
    assert port.latched and port.last_stop_error


def test_rearm_needs_platform_stop_fence_open_at_that_generation():
    fence = Fence()
    port = _port(fence=fence)
    with pytest.raises(PermissionError):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.latched
    fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    assert not port.latched and port.snapshot()["state"] == "IDLE"


def test_rearm_refuses_while_a_motor_reports_hardware_error():
    bus = FakeBus()
    port = _port(bus)
    bus.regs[13][ADDR_HW_ERROR] = 0x04
    with pytest.raises(PermissionError):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.latched


def test_closed_stop_fence_at_submit_latches_and_refuses():
    fence = Fence()
    port = _armed(fence=fence)
    fence.close()
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal == "STOP_FENCE_CLOSED" and port.latched


def test_joint_limit_is_refused_before_any_motion():
    bus = FakeBus()
    port = _armed(bus, plan=[{"pose": [0.0, 1.6, 0.0, 0.0, 0.0]}])
    bus.log.clear()
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal == "JOINT_LIMIT: joint2" and bus.log == []


def test_per_cycle_step_stays_within_velocity_limit():
    bus = FakeBus()
    tracking = Tracking(period_s=0.02)
    port = _armed(bus, plan=[{"pose": [1.0, 0.0, 0.0, 0.0, 0.0]}], tracking=tracking)
    port.submit(_grant())
    goals = [e[2][11] for e in bus.log if e[0] == "sw" and e[1] == ADDR_GOAL and 11 in e[2]]
    step_ticks = 2.0 * 0.02 * 4096 / (2 * 3.141592653589793)
    assert len(goals) > 10 and max(abs(b - a) for a, b in zip(goals, goals[1:])) <= step_ticks + 1
    assert port.outcome["result"] == "SUCCEEDED"


def test_tracking_error_holds():
    bus = FakeBus()
    bus.stuck.add(12)  # motor lost torque or lacks power: goal writes raise no error
    port = _armed(bus, plan=[{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    assert port.submit(_grant()).accepted is True
    assert port.outcome["result"] == "HOLD" and port.outcome["reason"].startswith("TRACKING_ERROR")
    assert port.latched and port.snapshot()["state"] == "HOLD"


def test_pose_not_reached_holds():
    bus = FakeBus()
    port = _armed(bus, plan=[{"pose": [0.0, 0.0, 0.08, 0.0, 0.0]}],
                  tracking=Tracking(max_tracking_rad=0.5))
    bus.stuck.add(13)  # short move: lag stays under the tracking bound, arrival never happens
    port.submit(_grant())
    assert port.outcome["reason"].startswith("POSE_NOT_REACHED") and port.latched


def test_hardware_fault_during_motion_holds():
    bus = FakeBus()
    port = _armed(bus, plan=[{"pose": [0.5, 0.0, 0.0, 0.0, 0.0]}])
    original = bus.sync_write

    def overload(addr, size, values):
        original(addr, size, values)
        bus.regs[11][ADDR_HW_ERROR] = 0x20
    bus.sync_write = overload
    port.submit(_grant())
    assert port.outcome["reason"].startswith("HARDWARE_FAULT") and port.latched


def test_empty_grasp_holds():
    bus = FakeBus()  # present current stays 0 mA: nothing in the gripper
    port = _armed(bus, plan=[{"grip": "close"}, {"grasp_check": GRASP},
                             {"pose": [0.2, 0.0, 0.0, 0.0, 0.0]}])
    port.submit(_grant())
    assert port.outcome["result"] == "HOLD" and port.outcome["reason"].startswith("EMPTY_GRASP")
    assert bus.regs[11][ADDR_PRESENT] == 2048  # never carried the empty gripper


def test_close_without_grasp_check_is_refused():
    port = _armed(plan=[{"grip": "close"}, {"pose": [0.2, 0.0, 0.0, 0.0, 0.0]}])
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal == "GRASP_CHECK_MISSING"


@pytest.mark.parametrize("rec,missing", [
    (record(joint_limits=None, gripper=None, workspace=None, stop_test=None), "joint limits not measured"),
    (record(gripper=None), "gripper"),
    (record(stop_test=None), "no stop test"),
    (record(stop_test={**STOP_OK, "driver": "fake"}), "did not pass"),
    (record(stop_test={**STOP_OK, "measured_stop_ms": 900}), "did not pass"),
    (record(stop_test={**STOP_OK, "pre_stop_velocity_rad_s": 0.05}), "did not pass"),
    (record(workspace=None), "workspace box not measured"),
    (record(gripper={"open_rad": 0.5, "close_rad": 0.5}), "must differ"),
    (record(gripper={"open_rad": 3.5, "close_rad": -0.2}), "inside (-pi, pi)"),
])
def test_motion_gate_refuses_without_measured_evidence(rec, missing):
    bus = FakeBus()
    port = _armed(bus, rec=rec)
    bus.log.clear()
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal.startswith("MOTION_GATE") and missing in port.last_refusal
    assert bus.log == []


def test_policy_step_is_refused():
    port = _armed(plan=[{"policy": "pick-v3"}])
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal.startswith("POLICY_REFUSED")


def test_wrong_instance_grant_is_refused():
    port = _armed()
    assert port.submit(_grant(instance="omx-2-control")).accepted is False
    assert port.last_refusal == "WRONG_INSTANCE"


def test_one_goal_at_a_time_and_no_retry():
    started = []
    port = DynamixelPort(FakeBus(), device="/dev/serial/by-id/usb-FAKE-ARM-0", config=_config(),
                         store=FakeStore(PASSED), planner=lambda g: [{"pose": [0.1, 0, 0, 0, 0]}],
                         stop_fence=Fence(), sleep=lambda s: None,
                         start=started.append, claims=_BusClaims())
    port.stop_fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.submit(_grant()).accepted is True
    assert port.submit(_grant()).accepted is False and port.last_refusal == "BUSY"
    assert len(started) == 1


def test_same_instance_second_writer_is_refused_other_instance_allowed():
    claims = _BusClaims()
    first = _port(claims=claims)
    with pytest.raises(BusBusy):
        _port(claims=claims, device="/dev/serial/by-id/usb-FAKE-ARM-1")  # same instance
    with pytest.raises(BusBusy):
        _port(claims=claims, config=_config("omx-2", "omx-2-control"))  # same device
    second = _port(claims=claims, config=_config("omx-2", "omx-2-control"),
                   device="/dev/serial/by-id/usb-FAKE-ARM-1")  # D-773 two arms, one host
    first.close()
    _port(claims=claims)  # released on close
    second.close()


@pytest.mark.parametrize("raw,signed", [(0xFFFFFFFF, -1), (0x80000000, -(1 << 31)), (4096, 4096)])
def test_sdk_bus_decodes_signed_present_position(raw, signed):
    group = SimpleNamespace(addParam=lambda i: None, txRxPacket=lambda: 0,
                            isAvailable=lambda i, addr, size: True,
                            getData=lambda i, addr, size: raw)
    bus = object.__new__(SdkBus)  # no SDK, no serial device
    bus._groups = (lambda *args: group, None)
    bus.ph = bus.pk = None
    assert bus.sync_read([11], ADDR_PRESENT, 4) == {11: signed}


def test_sdk_bus_refuses_unstable_device_path_before_import():
    with pytest.raises(HardwareMismatch):
        SdkBus("/dev/ttyACM0")


# ---- D-858 S1 independent review fixes (H1, M1-M6, L) ----

def _hold_by_tracking_error(port, bus):
    bus.stuck.add(12)
    port.submit(_grant())
    assert port.outcome["reason"].startswith("TRACKING_ERROR") and port.latched


def test_port_hold_trips_the_platform_fence():
    bus, fence = FakeBus(), Fence()
    port = _armed(bus, fence=fence, plan=[{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    _hold_by_tracking_error(port, bus)
    assert not fence.open
    request = fence.trips[-1]
    assert (request.authority_epoch, request.dispatch_generation) == (2, 8)
    assert request.reason.startswith("DRIVER_HOLD: TRACKING_ERROR")


def test_rearm_at_the_latched_generation_is_refused_even_if_the_fence_reads_open():
    bus, fence = FakeBus(), StickyFence()
    port = _armed(bus, fence=fence, plan=[{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    _hold_by_tracking_error(port, bus)
    with pytest.raises(PermissionError, match="strictly newer"):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.latched
    fence.person_rearm(9)
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert not port.latched


def test_hold_clears_only_through_the_person_rearm_of_local_stop(tmp_path):
    controller = LocalStopController(tmp_path / "stop.db", workcell_id="omx-1",
                                     instance_id="omx-1-control")
    with closing(sqlite3.connect(tmp_path / "stop.db")) as db:
        db.execute("CREATE TABLE omx_actions (workcell_id TEXT, state TEXT)")
        db.commit()

    def person_rearm(generation):
        controller.rearm(authority_epoch=2, dispatch_generation=generation,
                         operator_confirmed=True, fleet_fence_current=lambda e, g: True)
    bus = FakeBus()
    port = _port(bus, fence=controller, plan=[{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    _hold_by_tracking_error(port, bus)
    snap = controller.snapshot(workcell_id="omx-1", instance_id="omx-1-control")
    assert snap.state == "LOCAL_LATCHED" and snap.reason.startswith("DRIVER_HOLD")
    assert not controller.is_open(authority_epoch=2, dispatch_generation=8)
    with pytest.raises(PermissionError):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    with pytest.raises(LocalStopBlocked):
        person_rearm(8)  # same generation
    person_rearm(9)
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert not port.latched


def test_cancel_trips_the_fence():
    fence = Fence()
    port = _armed(fence=fence)
    port.cancel({"action_id": "action-1"})
    assert fence.trips and not fence.open


def _wait(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.001)
    return predicate()


def test_stop_from_another_thread_during_a_bus_write_latches_without_waiting():
    bus = FakeBus()
    port = _armed(bus, plan=[{"pose": [1.0, 0.0, 0.0, 0.0, 0.0]}])
    original, seen, stopper = bus.sync_write, [], []

    def write(addr, size, values):
        original(addr, size, values)
        if addr == ADDR_GOAL and 11 in values and len(seen) < 3:
            seen.append(1)
            if len(seen) == 3:  # the port holds the bus lock right now
                stopper.append(threading.Thread(target=port.stop))
                stopper[0].start()
                assert _wait(lambda: port.latched and port._stop_requested), "stop waited on a lock"
                seen.append(len(bus.log))
    bus.sync_write = write
    port.submit(_grant())
    stopper[0].join(2)
    assert port.outcome["result"] == "STOPPED"
    after = bus.log[seen[3]:]
    assert after and all(e[0] == "sw" and set(e[2]) == set(HW.joint_ids) for e in after)
    assert all(e[2] == {i: bus.regs[i][ADDR_PRESENT] for i in HW.joint_ids} for e in after)


def test_planner_runs_outside_the_state_lock_and_a_stop_during_planning_refuses():
    holder = {}

    def planner(grant):
        port = holder["port"]
        thread = threading.Thread(target=lambda: (port.snapshot(), port.stop()))
        thread.start()
        assert _wait(lambda: port.latched), "planner held a lock that snapshot/stop need"
        thread.join(2)
        return [{"pose": [0.1, 0.0, 0.0, 0.0, 0.0]}]
    bus = FakeBus()
    port = DynamixelPort(bus, device="/dev/serial/by-id/usb-FAKE-ARM-0", config=_config(),
                         store=FakeStore(PASSED), planner=planner, stop_fence=Fence(),
                         sleep=lambda s: None, start=lambda fn: fn(), claims=_BusClaims())
    holder["port"] = port
    port.stop_fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.submit(_grant()).accepted is False and port.last_refusal.startswith("LATCHED")
    assert ADDR_TORQUE not in _written_addresses(bus)


def test_fence_closing_during_motion_holds_within_a_cycle():
    bus, fence = FakeBus(), StickyFence()
    port = _armed(bus, fence=fence, plan=[{"pose": [1.0, 0.0, 0.0, 0.0, 0.0]}])
    original = bus.sync_write

    def write(addr, size, values):
        original(addr, size, values)
        fence.close()  # someone tripped local_stop
    bus.sync_write = write
    port.submit(_grant())
    assert port.outcome["reason"] == "STOP_FENCE_CLOSED" and port.latched
    assert bus.regs[11][ADDR_PRESENT] < to_raw(0.1)


def test_plan_outside_workspace_is_refused_by_fk():
    bus = FakeBus()
    rec = record(workspace=[[0.1, 0.35], [-0.25, 0.25], [0.01, 0.25]])
    port = _armed(bus, rec=rec, plan=[{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    bus.log.clear()
    assert port.submit(_grant()).accepted is False
    assert port.last_refusal.startswith("WORKSPACE: tcp z") and bus.log == []


def test_interpolated_point_outside_workspace_holds():
    bus = FakeBus()  # q1 0 -> 1: TCP x 0.31 m -> 0.17 m; the end is inside, the path is not
    rec = record(workspace=[[-1.0, 0.2], [-1.0, 1.0], [-0.5, 1.0]])
    port = _armed(bus, rec=rec, plan=[{"pose": [1.0, 0.0, 0.0, 0.0, 0.0]}])
    assert port.submit(_grant()).accepted is True
    assert port.outcome["reason"].startswith("WORKSPACE: tcp x")
    assert bus.regs[11][ADDR_PRESENT] == 2048


def test_gripper_far_from_measured_range_is_not_written():
    bus = FakeBus({(HW.gripper_id, ADDR_PRESENT): to_raw(2.5)})
    port = _armed(bus, plan=[{"grip": "open"}])
    port.submit(_grant())
    assert port.outcome["reason"].startswith("GRIPPER_STEP")
    assert not any(e[0] == "w" and e[2] == ADDR_GOAL for e in bus.log)


def test_gripper_write_waits_for_no_hardware_error():
    bus = FakeBus()
    port = _armed(bus, plan=[{"grip": "open"}])
    bus.regs[HW.gripper_id][ADDR_HW_ERROR] = 0x20
    port.submit(_grant())
    assert port.outcome["reason"].startswith("HARDWARE_FAULT")
    assert not any(e[0] == "w" and e[2] == ADDR_GOAL for e in bus.log)


def test_port_and_sdk_bus_refuse_eeprom_writes():
    bus = FakeBus()
    port = _port(bus)
    with pytest.raises(HardwareMismatch):
        port._write(11, 11, 1, 3)
    with pytest.raises(HardwareMismatch):
        port._sync_write(11, 1, {11: 3})
    assert _writes(bus) == []
    sdk = object.__new__(SdkBus)  # no SDK: a refused address never reaches the packet handler
    sdk.ph = sdk.pk = None
    sdk._groups = (None, None)
    with pytest.raises(HardwareMismatch):
        sdk.write(11, 11, 1, 3)
    with pytest.raises(HardwareMismatch):
        sdk.sync_write(11, 1, {11: 3})


def test_rearm_rereads_torque_so_a_power_cycled_motor_is_reenabled_without_a_jump():
    bus, fence = FakeBus(), Fence()
    port = _armed(bus, fence=fence)
    port.submit(_grant())
    assert port.torque_on
    port.stop()
    bus.regs[12][ADDR_TORQUE] = 0  # the motor lost power while latched
    fence.person_rearm(9)
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert port.torque_on is False
    bus.log.clear()
    assert port.submit(_grant(generation=9)).accepted is True
    first_torque = next(n for n, e in enumerate(bus.log) if e[0] == "w" and e[2] == ADDR_TORQUE)
    assert bus.log[0][:2] == ("sw", ADDR_GOAL) and first_torque > 0


class _FakeSdk:
    """serial / fcntl / termios / dynamixel_sdk modules over a FakeBus register model."""

    def __init__(self, bus, ioctl_fails=False):
        sdk, self.serials, self.ioctls = self, [], []

        class Serial:
            def __init__(self):
                self.closed = False
                sdk.serials.append(self)

            def open(self):
                pass

            def fileno(self):
                return 7

            def reset_input_buffer(self):
                pass

            def close(self):
                self.closed = True

        def ioctl(fd, request):
            sdk.ioctls.append((fd, request))
            if ioctl_fails:
                raise OSError("EBUSY")

        class PacketHandler:
            def __init__(self, version):
                for size, name in ((1, "1Byte"), (2, "2Byte"), (4, "4Byte")):
                    setattr(self, f"read{name}TxRx",
                            lambda ph, i, a, s=size: (bus.read(i, a, s), 0, 0))
                    setattr(self, f"write{name}TxRx",
                            lambda ph, i, a, v, s=size: (bus.write(i, a, s, v), 0, 0)[1:])

        class GroupSyncRead:
            def __init__(self, ph, pk, addr, size):
                self.addr, self.size, self.ids, self.data = addr, size, [], {}

            def addParam(self, i):
                self.ids.append(i)

            def txRxPacket(self):
                self.data = bus.sync_read(self.ids, self.addr, self.size)
                return 0

            def isAvailable(self, i, addr, size):
                return i in self.data

            def getData(self, i, addr, size):
                return self.data[i]

        class GroupSyncWrite:
            def __init__(self, ph, pk, addr, size):
                self.addr, self.size, self.values = addr, size, {}

            def addParam(self, i, data):
                self.values[i] = int.from_bytes(bytes(data), "little")

            def txPacket(self):
                bus.sync_write(self.addr, self.size, self.values)
                return 0

        self.modules = {
            "serial": SimpleNamespace(Serial=Serial),
            "fcntl": SimpleNamespace(ioctl=ioctl),
            "termios": SimpleNamespace(TIOCEXCL=0x540C),
            "dynamixel_sdk": SimpleNamespace(
                PortHandler=lambda device: SimpleNamespace(), PacketHandler=PacketHandler,
                GroupSyncRead=GroupSyncRead, GroupSyncWrite=GroupSyncWrite),
        }


def _open_real(claims, device="/dev/serial/by-id/usb-FAKE-ARM-0"):
    return open_real_port(device, config=_config(), store=FakeStore(PASSED),
                          planner=lambda g: [{"pose": [0.1, 0.0, 0.0, 0.0, 0.0]}],
                          stop_fence=Fence(), sleep=lambda s: None,
                          start=lambda fn: fn(), claims=claims)


def _install(monkeypatch, sdk):
    for name, module in sdk.modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_open_real_port_opens_exclusive_starts_in_hold_and_moves_only_ram(monkeypatch):
    bus = FakeBus()
    sdk = _FakeSdk(bus)
    _install(monkeypatch, sdk)
    claims = _BusClaims()
    port = _open_real(claims)
    serial = sdk.serials[0]
    assert serial.exclusive is True and serial.dtr is False and serial.rts is False
    assert sdk.ioctls == [(7, 0x540C)]
    assert port.snapshot()["state"] == "HOLD" and _writes(bus) == []
    with pytest.raises(BusBusy):
        _open_real(claims)  # a second writer is refused before the device opens
    assert len(sdk.serials) == 1
    port.stop_fence.person_rearm(8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.submit(_grant()).accepted is True and port.outcome["result"] == "SUCCEEDED"
    assert _written_addresses(bus) <= {ADDR_TORQUE, ADDR_GOAL}
    port.close()
    assert serial.closed


def test_sdk_bus_closes_the_port_when_exclusive_ioctl_fails(monkeypatch):
    sdk = _FakeSdk(FakeBus(), ioctl_fails=True)
    _install(monkeypatch, sdk)
    with pytest.raises(OSError):
        _open_real(_BusClaims())
    assert sdk.serials[0].closed


# ---- N1: port never holds its state lock while it calls the fence (real threads) ----

def _controller(tmp_path):
    controller = LocalStopController(tmp_path / "stop.db", workcell_id="omx-1",
                                     instance_id="omx-1-control")
    with closing(sqlite3.connect(tmp_path / "stop.db")) as db:
        db.execute("CREATE TABLE omx_actions (workcell_id TEXT, state TEXT)")
        db.commit()
    return controller


def _person_rearm(controller, generation):
    controller.rearm(authority_epoch=2, dispatch_generation=generation,
                     operator_confirmed=True, fleet_fence_current=lambda e, g: True)


def _threaded_port(bus, controller, plan):
    return DynamixelPort(bus, device="/dev/serial/by-id/usb-FAKE-ARM-0", config=_config(),
                         store=FakeStore(PASSED), planner=lambda g: plan, stop_fence=controller,
                         sleep=lambda s: None, claims=_BusClaims())  # real motion thread


def _submit_through_fence(controller, port, grant):
    try:
        return controller.run_if_open(authority_epoch=2, dispatch_generation=8,
                                      fleet_fence_current=lambda: True,
                                      operation=lambda: port.submit(grant))
    except LocalStopBlocked:
        return None


def test_submit_through_the_fence_while_a_motion_ends_in_hold_does_not_deadlock(tmp_path):
    controller, bus = _controller(tmp_path), FakeBus()
    bus.stuck.add(12)
    port = _threaded_port(bus, controller, [{"pose": [0.0, 1.0, 0.0, 0.0, 0.0]}])
    _person_rearm(controller, 8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    halting, original = threading.Event(), bus.sync_read

    def read(ids, addr, size):
        if port.latched and addr == ADDR_PRESENT and not halting.is_set():
            halting.set()   # the port is holding the arm; let the submitter take the fence lock
            time.sleep(0.3)
        return original(ids, addr, size)
    bus.sync_read = read
    assert _submit_through_fence(controller, port, _grant()).accepted is True
    assert halting.wait(5)
    submitter = threading.Thread(target=_submit_through_fence,
                                 args=(controller, port, _grant()), daemon=True)
    submitter.start()
    submitter.join(5)
    assert not submitter.is_alive(), "submit through run_if_open deadlocked with the HOLD"
    assert _wait(lambda: port.outcome is not None, 5) and port.outcome["result"] == "HOLD"
    assert not controller.is_open(authority_epoch=2, dispatch_generation=8)


def test_rearm_and_submit_through_the_fence_do_not_deadlock(tmp_path):
    controller, bus = _controller(tmp_path), FakeBus()
    port = _threaded_port(bus, controller, [{"pose": [0.1, 0.0, 0.0, 0.0, 0.0]}])
    _person_rearm(controller, 8)
    fence_held, rearm_started = threading.Event(), threading.Event()

    def fleet_current():
        fence_held.set()   # run_if_open holds the fence lock now
        rearm_started.wait(2)
        time.sleep(0.2)    # the rearm thread is inside port.rearm by now
        return True

    def submitter():
        try:
            controller.run_if_open(authority_epoch=2, dispatch_generation=8,
                                   fleet_fence_current=fleet_current,
                                   operation=lambda: port.submit(_grant()))
        except LocalStopBlocked:
            pass

    def rearmer():
        try:
            port.rearm(authority_epoch=2, dispatch_generation=8)
        except PermissionError:
            pass
    first = threading.Thread(target=submitter, daemon=True)
    first.start()
    assert fence_held.wait(5)
    second = threading.Thread(target=rearmer, daemon=True)
    second.start()
    rearm_started.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive(), "rearm and submit deadlocked"


# ---- N2: startup HOLD, N4: stop during rearm, no re-trip over an existing stop ----

def test_startup_hold_needs_a_person_rearm_even_if_the_fence_is_already_open():
    fence = Fence((2, 8), open_=True)
    port = _port(fence=fence)
    with pytest.raises(PermissionError, match="strictly newer"):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.latched
    fence.person_rearm(9)
    port.rearm(authority_epoch=2, dispatch_generation=9)
    assert not port.latched


def test_startup_hold_over_an_open_local_stop_refuses_the_current_generation(tmp_path):
    controller = _controller(tmp_path)
    _person_rearm(controller, 8)
    port = _port(fence=controller)
    with pytest.raises(PermissionError, match="strictly newer"):
        port.rearm(authority_epoch=2, dispatch_generation=8)
    assert port.latched


def test_a_stop_during_rearm_keeps_the_latch():
    fence = StickyFence()  # stays open, so only the stop counter can refuse
    port = _armed(fence=fence)
    port.stop()
    fence.person_rearm(9)
    fence.on_is_open = port.stop  # the stop lands while rearm is checking the fence
    with pytest.raises(PermissionError, match="arrived during rearm"):
        port.rearm(authority_epoch=2, dispatch_generation=9)
    assert port.latched


def test_hold_after_an_operator_stop_keeps_the_operator_stop_record(tmp_path):
    controller = _controller(tmp_path)
    port = _port(fence=controller)
    _person_rearm(controller, 8)
    port.rearm(authority_epoch=2, dispatch_generation=8)
    controller.trip(LocalStopRequest(
        workcell_id="omx-1", instance_id="omx-1-control", authority_epoch=2,
        dispatch_generation=8, requested_at=datetime.now(timezone.utc),
        reason="OPERATOR_STOP"), source=StopRequestSource.FLEET)
    assert port.submit(_grant()).accepted is False and port.last_refusal == "STOP_FENCE_CLOSED"
    port.cancel({"action_id": "action-1"})
    snap = controller.snapshot(workcell_id="omx-1", instance_id="omx-1-control")
    assert snap.reason == "OPERATOR_STOP" and snap.source == StopRequestSource.FLEET
    assert snap.state == "LOCAL_LATCHED"
