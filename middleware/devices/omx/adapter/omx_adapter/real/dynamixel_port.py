"""Real Dynamixel ``LocalActionPort`` for one OMX arm instance (D-858 S1). Wired nowhere yet.

Absorbed from the retired device-core driver and safety wrapper (rosy-vault 9a744a3,
``device_core/drivers/dynamixel.py``, ``safety.py``, ``service.py``). Meanings kept:

- Starts latched in HOLD. The startup check only reads (model, operating mode, hardware error).
- Writes only RAM Torque Enable (64) and Goal Position (116); never EEPROM (< 64).
- Stop sets the latch before taking any lock, then writes joint goal = present (holds in
  place). It never turns torque off. The gripper keeps its goal (keeps its grip).
- Every HOLD or stop also trips the injected platform stop fence (``local_stop``), so the
  latch clears only after a person rearms that fence at a strictly newer authority/generation
  and ``rearm`` is called at that generation. No automatic retry of anything.
- The fence is re-read every motion cycle; a closed fence HOLDs the arm.
- Joint position and per-cycle speed come from the enabled ``ArmCommandConfig``; the TCP
  (platform FK) must stay inside the measured workspace box, at plan time and every cycle.
- Tracking error, motor hardware error, missed pose, or an empty grasp HOLD the arm.
- Motion goals are refused until measured limits, measured gripper values and a passed stop
  test exist (D-858 §4). Learned-policy steps are refused (D-793).
- The port loads its evidence from the commissioning store itself (S3, no other source).
  When the stored record's revision moves away from the loaded one (checked at submit, before
  each step and at rearm), the port HOLDs; a person reloads (``reload_evidence``) and rearms.
- ``submit_stop_test`` is measurement mode: gate without the stop-test item, at most 20 poses
  that move only joint1 within 0.2 rad of where it is, at 0.15..0.2 rad/s.
- One bus writer: a port claims its arm instance and its serial device in this process; the
  real bus also opens the device exclusively. The claim is per instance, never a wildcard over
  other arms' owners (device-core ``lock.py:64`` defect, D-773).
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol, Sequence

from core_common.protocol.schemas import LocalStopRequest, LocalStopSnapshot, StopRequestSource

from ..action_runner import ActionGrant, DriverSubmission, StopFence
from ..command_owner import ArmCommandConfig
from ..kinematics import OmxKinematics
from .dynamixel_bus import (
    ADDR_GOAL, ADDR_HW_ERROR, ADDR_MODEL, ADDR_OPERATING_MODE, ADDR_PRESENT,
    ADDR_PRESENT_CURRENT, ADDR_TORQUE, BUS_CLAIMS, Bus, Hardware, HardwareMismatch, SdkBus,
    WRITABLE, _BusClaims, _signed, to_rad, to_raw,
)
from .commissioning_record import CommissioningStore, load_motion_evidence
from .dynamixel_gates import (
    STOP_TEST_MAX_AMPLITUDE_RAD, STOP_TEST_MAX_SPEED_RAD_S, STOP_TEST_MAX_STEPS,
    STOP_TEST_MIN_SPEED_RAD_S, STOP_TEST_POSE_TOLERANCE_RAD, Tracking, _finite, _validate_grasp,
)


class TrippableFence(StopFence, Protocol):
    """``LocalStopController``: the port closes it on every HOLD (D-858 S1, H1)."""

    def trip(self, request: LocalStopRequest, *,
             source: StopRequestSource) -> LocalStopSnapshot: ...

    def snapshot(self, *, workcell_id: str, instance_id: str) -> LocalStopSnapshot: ...


class _Hold(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason



Planner = Callable[[ActionGrant], Sequence[Mapping[str, object]]]


class DynamixelPort:
    """``LocalActionPort`` over one Dynamixel bus. One goal at a time, HOLD on any doubt.

    Lock order: the fence's lock is outside ours (``run_if_open`` holds it through
    ``submit``), so the port never calls the fence (``is_open``, ``snapshot``, ``trip``)
    while it holds ``_state_lock``. Decide state inside the lock, call the fence outside.
    """

    def __init__(self, bus: Bus, *, device: str, config: ArmCommandConfig,
                 store: CommissioningStore, planner: Planner, stop_fence: TrippableFence,
                 hardware: Hardware = Hardware(), tracking: Tracking = Tracking(),
                 kinematics: OmxKinematics | None = None,
                 sleep: Callable[[float], None] | None = None,
                 start: Callable[[Callable[[], None]], None] | None = None,
                 claims: _BusClaims = BUS_CLAIMS) -> None:
        if not config.enabled or config.velocity_limits is None:
            raise ValueError("real port needs an enabled owner policy with velocity limits")
        if len(config.joint_names) != len(hardware.joint_ids):
            raise ValueError("owner joint names must map one to one onto the bus joint IDs")
        if not callable(getattr(stop_fence, "trip", None)):
            raise ValueError("real port needs a stop fence it can trip (LocalStopController)")
        self.instance = (config.workcell_id, config.instance_id)
        self.device = device
        self._claims = claims
        claims.acquire(self.instance, device)
        try:
            self.bus, self.hw, self.config = bus, hardware, config
            self.store, self.planner, self.stop_fence = store, planner, stop_fence
            self.evidence = load_motion_evidence(store, config)
            self.tracking = tracking
            self._vel = config.velocity_limits  # capped only while a stop test runs
            self.kinematics = kinematics or OmxKinematics.load()
            self.sleep = sleep or time.sleep
            self.start = start or (lambda fn: threading.Thread(target=fn, daemon=True).start())
            self._bus_lock = threading.Lock()
            self._state_lock = threading.RLock()
            self.latched = True  # restart is HOLD (D-496)
            self.state, self.reason = "HOLD", "STARTUP_HOLD"
            self.goal_id: str | None = None
            self.last_refusal: str | None = None
            self.last_stop_error: str | None = None
            self.fence_error: str | None = None
            # Generation of the current grant/rearm, and the newest one any latch happened at.
            self._gen: tuple[int, int] | None = None
            self._latch_gen: tuple[int, int] | None = None
            self.outcome: dict[str, object] | None = None
            self._running = False
            self._stop_requested = False
            self._stops = 0  # bumped before every latch; rearm re-checks it (no lost stop)
            self._last_command: list[float] | None = None
            self.report = self._check()
            # A fence already open at startup is not a person rearm after this HOLD.
            self._latch_gen = self._fence_generation()
        except BaseException:
            claims.release(self.instance, device)
            raise

    # ---- bus access: the only writes are RAM torque and goal ----
    def _write(self, dxl_id: int, addr: int, size: int, value: int) -> None:
        if addr not in WRITABLE:
            raise HardwareMismatch(f"refusing write to register {addr}")
        self.bus.write(dxl_id, addr, size, value)

    def _sync_write(self, addr: int, size: int, values: Mapping[int, int]) -> None:
        if addr not in WRITABLE:
            raise HardwareMismatch(f"refusing write to register {addr}")
        self.bus.sync_write(addr, size, values)

    def _check(self) -> dict:
        report: dict = {}
        with self._bus_lock:
            for i in self.hw.all_ids:
                model = self.bus.read(i, ADDR_MODEL, 2)
                mode = self.bus.read(i, ADDR_OPERATING_MODE, 1)
                err = self.bus.read(i, ADDR_HW_ERROR, 1)
                torque = self.bus.read(i, ADDR_TORQUE, 1)
                report[i] = {"model": model, "mode": mode, "hw_error": err, "torque": torque}
                if model != self.hw.models[i]:
                    raise HardwareMismatch(f"ID {i}: model {model} != {self.hw.models[i]}")
                if mode != self.hw.operating_modes[i]:
                    raise HardwareMismatch(f"ID {i}: operating mode {mode} != "
                                           f"{self.hw.operating_modes[i]} (not changed)")
                if err:
                    raise HardwareMismatch(f"ID {i}: hardware error {err:#04x}")
        self.torque_on = all(row["torque"] == 1 for row in report.values())
        return report

    def _read_joints(self) -> list[float]:
        with self._bus_lock:
            raw = self.bus.sync_read(self.hw.joint_ids, ADDR_PRESENT, 4)
        return [to_rad(raw[i]) for i in self.hw.joint_ids]

    def _fault(self) -> str | None:
        with self._bus_lock:
            errors = self.bus.sync_read(self.hw.all_ids, ADDR_HW_ERROR, 1)
        return ", ".join(f"ID {i} hardware error {e:#04x}" for i, e in errors.items() if e) or None

    def _ensure_torque(self) -> None:
        """Caller holds the bus lock. Goal = present before torque on, so nothing jumps."""
        if self.torque_on:
            return
        self._sync_write(ADDR_GOAL, 4, self.bus.sync_read(self.hw.all_ids, ADDR_PRESENT, 4))
        for i in self.hw.all_ids:
            self._write(i, ADDR_TORQUE, 1, 1)
        self.torque_on = True

    # ---- LocalActionPort ----
    def _refuse(self, reason: str) -> DriverSubmission:
        self.last_refusal = reason
        return DriverSubmission(accepted=False)

    def _plan_refusal(self, steps: Sequence[Mapping[str, object]]) -> str | None:
        if not steps:
            return "PLAN_EMPTY"
        limits = self.config.position_limits
        last_close = None
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping) or len(step) != 1:
                return "PLAN_STEP_UNSUPPORTED"
            (kind, value), = step.items()
            if kind == "policy":
                return "POLICY_REFUSED_ON_HARDWARE (D-793)"
            if kind == "pose":
                if (not isinstance(value, (list, tuple)) or len(value) != len(limits)
                        or not all(type(v) in (int, float) and math.isfinite(v) for v in value)):
                    return "PLAN_POSE_INVALID"
                for name, q in zip(self.config.joint_names, value):
                    lower, upper = limits[name]
                    if not lower <= q <= upper:
                        return f"JOINT_LIMIT: {name}"
                outside = self._outside_workspace(value)
                if outside:
                    return outside
            elif kind == "grip":
                if value not in ("open", "close"):
                    return "PLAN_STEP_UNSUPPORTED"
                if value == "close":
                    last_close = index
            elif kind == "grasp_check":
                try:
                    _validate_grasp(value)
                except ValueError as exc:
                    return f"GRASP_CHECK_INVALID: {exc}"
                last_close = None
            else:
                return "PLAN_STEP_UNSUPPORTED"
        # A close without a later grasp check could carry an empty gripper as success (V-005 6).
        return "GRASP_CHECK_MISSING" if last_close is not None else None

    def _outside_workspace(self, q: Sequence[float]) -> str | None:
        tcp = self.kinematics.fk(q)
        for name, value, (lower, upper) in zip("xyz", (tcp.x, tcp.y, tcp.z),
                                               self.evidence.workspace_m):
            if not lower <= value <= upper:
                return f"WORKSPACE: tcp {name}={value:.3f} m outside [{lower}, {upper}]"
        return None

    def submit(self, grant: ActionGrant) -> DriverSubmission:
        return self._submit((grant.workcell_id, grant.instance_id),
                            (grant.authority_epoch, grant.dispatch_generation),
                            lambda: self.planner(grant), self.config.velocity_limits, False)

    def submit_stop_test(self, poses: Sequence[Sequence[float]], *, authority_epoch: int,
                         dispatch_generation: int, max_speed_rad_s: float) -> DriverSubmission:
        """Commissioning stop-test motion (D-858 S3 measurement mode): the §4 gate without the
        stop-test item, joint poses only, every joint capped at a slow V-016 speed."""
        if not (_finite(max_speed_rad_s)
                and STOP_TEST_MIN_SPEED_RAD_S <= max_speed_rad_s <= STOP_TEST_MAX_SPEED_RAD_S):
            return self._refuse("STOP_TEST_SPEED")
        present, tol = self._read_joints(), STOP_TEST_POSE_TOLERANCE_RAD
        if not 0 < len(poses) <= STOP_TEST_MAX_STEPS:
            return self._refuse("STOP_TEST_STEPS")
        for q in poses:
            if (len(q) != len(present) or not all(_finite(v) for v in q)
                    or abs(q[0] - present[0]) > STOP_TEST_MAX_AMPLITUDE_RAD + tol
                    or any(abs(a - b) > tol for a, b in zip(q[1:], present[1:]))):
                return self._refuse("STOP_TEST_POSE: joint1 only, within the stop-test amplitude")
        steps = [{"pose": list(q)} for q in poses]
        vel = {name: min(v, max_speed_rad_s) for name, v in self.config.velocity_limits.items()}
        return self._submit(self.instance, (authority_epoch, dispatch_generation),
                            lambda: steps, vel, True)

    def _submit(self, instance: tuple[str, str], gen: tuple[int, int],
                plan: Callable[[], Sequence[Mapping[str, object]]],
                vel: Mapping[str, float], stop_test: bool) -> DriverSubmission:
        with self._state_lock:
            if self._running:
                return self._refuse("BUSY")
            if instance != self.instance:
                return self._refuse("WRONG_INSTANCE")
            if self.latched or self._stop_requested:
                return self._refuse(f"LATCHED: {self.reason}")
            self._gen = gen
            self._running = True  # reserved; fence, record and planner calls run outside the lock
            stops = self._stops
        refusal = self._record_changed()
        if refusal:
            self._halt(refusal)
        elif not self.stop_fence.is_open(authority_epoch=gen[0], dispatch_generation=gen[1]):
            self._halt("STOP_FENCE_CLOSED")
            refusal = "STOP_FENCE_CLOSED"
        else:
            blockers = self.evidence.blockers(config_revision=self.config.calibration_revision,
                                              include_stop_test=not stop_test)
            refusal = "MOTION_GATE: " + "; ".join(blockers) if blockers else None
        steps: list = []
        if refusal is None:
            try:
                steps = list(plan())
                refusal = self._plan_refusal(steps)
            except Exception as exc:
                refusal = f"PLAN_UNAVAILABLE: {type(exc).__name__}"
        with self._state_lock:
            if refusal or self.latched or self._stops != stops:
                self._running = False
                return self._refuse(refusal or f"LATCHED: {self.reason}")
            self.goal_id = f"dxl-{uuid.uuid4().hex}"
            self.state, self.reason, self.last_refusal = "RUNNING", None, None
            self._last_command = None  # _stop_requested is cleared only by rearm
            self._vel = vel
            goal_id = self.goal_id
        self.start(lambda: self._run(goal_id, steps))
        return DriverSubmission(accepted=True, driver_goal_id=goal_id)

    def _record_changed(self) -> str | None:
        """The stored commissioning record is no longer the loaded one (D-858 S3 HOLD after
        save). Reads a file: never call it under the state lock."""
        try:
            current = self.store.revision()
        except Exception as exc:  # unreadable record: fail closed
            return f"COMMISSIONING_RECORD_UNREADABLE: {type(exc).__name__}"
        return None if current == self.evidence.revision else "COMMISSIONING_RECORD_CHANGED"

    def reload_evidence(self) -> None:
        """Re-read the store while HOLD and idle; the latch stays until a person rearms."""
        with self._state_lock:
            if self._running or not self.latched:
                raise PermissionError("reload the commissioning record only while HOLD and idle")
        evidence = load_motion_evidence(self.store, self.config)  # file read: outside the lock
        with self._state_lock:
            if self._running or not self.latched:
                raise PermissionError("reload the commissioning record only while HOLD and idle")
            self.evidence = evidence

    def present_joints(self) -> list[float]:
        return self._read_joints()

    def cancel(self, action: Mapping[str, object]) -> bool | None:
        self.stop()
        return True if self.last_stop_error is None else None

    # ---- stop / recover ----
    def stop(self, reason: str = "STOPPED") -> None:
        # No lock before the flags: a planner call or a bus packet in flight must not delay them.
        self._stops += 1
        self.latched = True
        self._stop_requested = True
        self._halt(reason)

    def _raise_latch_gen(self, gen: tuple[int, int] | None) -> None:
        if gen is not None and (self._latch_gen is None or gen > self._latch_gen):
            self._latch_gen = gen

    def _fence_generation(self) -> tuple[int, int]:
        row = self.stop_fence.snapshot(workcell_id=self.instance[0], instance_id=self.instance[1])
        return (row.authority_epoch, row.dispatch_generation)

    def _halt(self, reason: str) -> None:
        """Latch, hold in place, close the platform fence. Never called under the state lock."""
        self._stops += 1
        self.latched = True  # before the bus lock: later commands are refused before the bus
        self._raise_latch_gen(self._gen)
        if self.state != "HOLD":
            self.state = "STOPPED" if reason == "STOPPED" else "HOLD"
            self.reason = reason
        with self._bus_lock:  # waits for at most one in-flight packet
            try:
                if self.torque_on:  # hold in place; torque off would let the arm sag
                    # Joints only: the gripper keeps its goal so a held part keeps its grip.
                    self._sync_write(ADDR_GOAL, 4,
                                     self.bus.sync_read(self.hw.joint_ids, ADDR_PRESENT, 4))
                self.last_stop_error = None
            except Exception as exc:  # the latch holds even if the bus is gone
                self.last_stop_error = f"{type(exc).__name__}: {exc}"
        try:
            row = self.stop_fence.snapshot(workcell_id=self.instance[0],
                                           instance_id=self.instance[1])
            self._raise_latch_gen((row.authority_epoch, row.dispatch_generation))
            if row.state != "OPEN":  # already stopped: keep that stop's source and reason
                self.fence_error = None
                return
        except Exception:
            pass  # unreadable fence: trip anyway (fail closed)
        epoch, generation = self._latch_gen or (0, 0)
        try:
            # shortcut: StopRequestSource has no driver value; OPERATOR_LOCAL marks a stop raised
            # on this host and the reason says DRIVER_HOLD. Add a source (D-780 style) if audit needs it.
            self.stop_fence.trip(LocalStopRequest(
                workcell_id=self.instance[0], instance_id=self.instance[1],
                authority_epoch=epoch, dispatch_generation=generation,
                requested_at=datetime.now(timezone.utc), reason=f"DRIVER_HOLD: {reason}"[:256],
            ), source=StopRequestSource.OPERATOR_LOCAL)
            self.fence_error = None
        except Exception as exc:  # the local latch holds; a person sees the fence error
            self.fence_error = f"{type(exc).__name__}: {exc}"[:200]

    def rearm(self, *, authority_epoch: int, dispatch_generation: int) -> None:
        """Clear the latch after a person rearmed the platform fence at a strictly newer
        authority/generation than the last latch. Never moves."""
        gen = (authority_epoch, dispatch_generation)
        with self._state_lock:
            if self._running:
                raise RuntimeError("motion thread has not finished")
            if self._latch_gen is not None and not gen > self._latch_gen:
                raise PermissionError("rearm needs a strictly newer authority/generation than the latch")
            stops = self._stops
        if not self.stop_fence.is_open(authority_epoch=authority_epoch,
                                       dispatch_generation=dispatch_generation):
            raise PermissionError("platform stop fence is not open at this generation")
        changed = self._record_changed()
        if changed:
            raise PermissionError(f"{changed}: reload the commissioning record before rearm")
        fault = self._fault()
        if fault:
            raise PermissionError(f"hardware error present: {fault}")
        with self._bus_lock:
            # A motor that lost power while latched comes back torque off.
            torque = self.bus.sync_read(self.hw.all_ids, ADDR_TORQUE, 1)
        with self._state_lock:
            if self._running or self._stops != stops:
                raise PermissionError("a stop or HOLD arrived during rearm")
            self.torque_on = all(torque[i] == 1 for i in self.hw.all_ids)
            self._stop_requested = False
            self.latched = False
            if self._stops != stops:  # stop() bumps the counter without our lock
                self.latched = True
                raise PermissionError("a stop arrived during rearm")
            self._gen = gen
            self.state, self.reason = "IDLE", None

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return {"state": self.state, "reason": self.reason, "latched": self.latched,
                    "goal_id": self.goal_id, "last_refusal": self.last_refusal,
                    "last_stop_error": self.last_stop_error, "fence_error": self.fence_error,
                    "record_revision": self.evidence.revision}

    def close(self) -> None:
        try:
            with self._bus_lock:
                self.bus.close()  # torque stays as is (off would sag)
        finally:
            self._claims.release(self.instance, self.device)

    # ---- motion thread ----
    def _check_cancel(self) -> None:
        if self._stop_requested or self.latched:
            raise _Hold("STOPPED")

    def _check_fence(self) -> None:
        """Every cycle, outside the bus lock (a fence read must not delay a stop write)."""
        self._check_cancel()
        epoch, generation = self._gen
        if not self.stop_fence.is_open(authority_epoch=epoch, dispatch_generation=generation):
            raise _Hold("STOP_FENCE_CLOSED")

    def _send(self, q: Sequence[float]) -> None:
        self._check_fence()
        limits, vel = self.config.position_limits, self._vel
        for name, value in zip(self.config.joint_names, q):
            lower, upper = limits[name]
            if not lower <= value <= upper:
                raise _Hold(f"JOINT_LIMIT: {name}")
        outside = self._outside_workspace(q)
        if outside:
            raise _Hold(outside)
        present = self._read_joints()
        # Goal writes are unacknowledged: a motor that lost torque only shows up as lag.
        if self._last_command is not None:
            lag = max(abs(a - b) for a, b in zip(present, self._last_command))
            if lag > self.tracking.max_tracking_rad:
                raise _Hold(f"TRACKING_ERROR: {lag:.3f} rad")
        last = self._last_command if self._last_command is not None else present
        for name, a, b in zip(self.config.joint_names, q, last):
            if abs(a - b) > vel[name] * self.tracking.period_s + 1e-9:
                raise _Hold(f"VELOCITY_LIMIT: {name}")
        fault = self._fault()
        if fault:
            raise _Hold(f"HARDWARE_FAULT: {fault}")
        with self._bus_lock:
            self._check_cancel()
            self._ensure_torque()
            self._sync_write(ADDR_GOAL, 4, {i: to_raw(v) for i, v in zip(self.hw.joint_ids, q)})
        self._last_command = list(q)

    def _move(self, goal: Sequence[float]) -> None:
        start = self._read_joints() if self._last_command is None else self._last_command
        vel = self._vel
        steps = max(1, math.ceil(max(
            abs(g - s) / (vel[name] * self.tracking.period_s * 0.95)
            for name, g, s in zip(self.config.joint_names, goal, start))))
        for k in range(1, steps + 1):
            self._send([s + (g - s) * k / steps for s, g in zip(start, goal)])
            self.sleep(self.tracking.period_s)
        for _ in range(max(1, math.ceil(self.tracking.arrive_s / self.tracking.period_s))):
            self._check_fence()
            error = max(abs(a - b) for a, b in zip(self._read_joints(), goal))
            if error <= self.tracking.arrive_rad:
                return
            self.sleep(self.tracking.period_s)
        raise _Hold(f"POSE_NOT_REACHED: {error:.3f} rad")

    def _grip(self, close: bool) -> None:
        self._check_fence()
        opened, closed = self.evidence.gripper_open_rad, self.evidence.gripper_close_rad
        rad = float(closed if close else opened)
        if not -math.pi < rad < math.pi:  # Goal Position wraps outside one turn
            raise _Hold("GRIPPER_TARGET_OUT_OF_RANGE")
        fault = self._fault()
        if fault:
            raise _Hold(f"HARDWARE_FAULT: {fault}")
        with self._bus_lock:
            present = to_rad(_signed(self.bus.read(self.hw.gripper_id, ADDR_PRESENT, 4), 32))
        # One write moves the whole way: more than open-to-close means the gripper is not
        # where the measured values assume.
        if abs(rad - present) > abs(opened - closed) + self.tracking.max_tracking_rad:
            raise _Hold(f"GRIPPER_STEP: {abs(rad - present):.3f} rad from present")
        with self._bus_lock:
            self._check_cancel()
            self._ensure_torque()
            self._write(self.hw.gripper_id, ADDR_GOAL, 4, to_raw(rad))

    def _grasp(self, spec: Mapping[str, object]) -> None:
        positions = []
        for index in range(spec["samples"]):
            self._check_fence()
            with self._bus_lock:
                pos = to_rad(_signed(self.bus.read(self.hw.gripper_id, ADDR_PRESENT, 4), 32))
                current = abs(_signed(self.bus.read(self.hw.gripper_id, ADDR_PRESENT_CURRENT, 2), 16))
            for key, value in (("position_rad", pos), ("current_ma", current)):
                lo, hi = spec[key]
                if not lo <= value <= hi:
                    raise _Hold(f"EMPTY_GRASP: {key}={value:.3f} outside measured range")
            positions.append(pos)
            if index + 1 < spec["samples"]:
                self.sleep(spec["period_s"])
        if max(positions) - min(positions) > spec["stable_rad"]:
            raise _Hold("EMPTY_GRASP: gripper position not stable")

    def _run(self, goal_id: str, steps: Sequence[Mapping[str, object]]) -> None:
        result, reason = "SUCCEEDED", None
        try:
            for step in steps:
                changed = self._record_changed()
                if changed:
                    raise _Hold(changed)
                (kind, value), = step.items()
                if kind == "grip":
                    self._grip(value == "close")
                elif kind == "grasp_check":
                    self._grasp(value)
                else:
                    self._move(value)
            self._check_cancel()
        except _Hold as hold:
            result, reason = "HOLD", hold.reason
        except Exception as exc:  # driver errors stop and go to a person, never retried
            result, reason = "HOLD", f"DRIVER_ERROR: {type(exc).__name__}: {exc}"[:200]
        if self._stop_requested:
            result, reason = "STOPPED", "STOPPED"
        if result != "SUCCEEDED":
            self._halt(reason)  # outside the state lock: it calls the fence
        with self._state_lock:
            if self._stop_requested:
                result, reason = "STOPPED", "STOPPED"
            if result == "SUCCEEDED" and not self.latched and self.goal_id == goal_id:
                self.state, self.reason = "IDLE", None
            self.outcome = {"goal_id": goal_id, "result": result, "reason": reason}
            self._vel = self.config.velocity_limits
            self._running = False


def open_real_port(device: str, *, baud: int = 1_000_000, **kwargs) -> DynamixelPort:
    """Claim the instance and device, then open the bus. The SDK is imported only here."""
    config: ArmCommandConfig = kwargs["config"]
    claims: _BusClaims = kwargs.setdefault("claims", BUS_CLAIMS)
    instance = (config.workcell_id, config.instance_id)
    claims.acquire(instance, device)  # before the device opens: a second writer never opens it
    claims.release(instance, device)
    bus = SdkBus(device, baud)
    try:
        return DynamixelPort(bus, device=device, **kwargs)
    except BaseException:
        bus.close()
        raise
