"""Internal motion-thread implementation using the DynamixelPort owner's state and bus."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .dynamixel_bus import ADDR_GOAL, ADDR_PRESENT, ADDR_PRESENT_CURRENT, _signed, to_rad, to_raw


class _Hold(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason



class _DynamixelMotion:
    """Legacy motion execution; the port retains resource and lifecycle ownership."""

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
