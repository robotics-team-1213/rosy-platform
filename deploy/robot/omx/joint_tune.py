#!/usr/bin/env python3
"""OMX joint tuning: follower IDs 11-16, or bounded leader wrist-roll ID 5 only.

Single Responsibility:
  - `SerialBus` and `Run`: Exclusive Dynamixel bus access, register read/write, torque-OFF confirmation,
    and bounded hold/move/sweep execution.
  - Session locking (`joint_tune_lock.py`) and CLI parser/runner (`joint_tune_cli.py`) are re-exported unchanged.
"""
from __future__ import annotations

import contextlib  # noqa: F401
try:
    import fcntl
except ImportError:  # Windows test hosts without POSIX flock
    fcntl = None  # type: ignore[assignment]
import json  # noqa: F401
import math
import os  # noqa: F401
from pathlib import Path
import re  # noqa: F401
import signal  # noqa: F401
import time
import urllib.request  # noqa: F401

import joint_tune_cli as _jtc  # noqa: E402
from joint_tune_lock import (  # noqa: E402,F401
    BUSY_S,
    FOLLOWER_6DOF,
    FOLLOWER_7DOF,
    FOLLOWER_BY_DOF,
    _ArmLocks,
    _interrupt,
    follower_map_for_dof,
    hold_test_jobs,
    lock_root,
    no_interrupts,
    protect_signals,
    session_lock,
)

GRIPPER = 16
#: id -> (model number, operating mode); XL430-W250 = 1060, XL330-M288 = 1200
FOLLOWER = {11: (1060, 4), 12: (1060, 4), 13: (1060, 4), 14: (1200, 4), 15: (1200, 4), 16: (1200, 5)}
LEADER_WRIST = 5
TUNABLE = {LEADER_WRIST: (1200, 4), **FOLLOWER}
_jtc._PARENT_GLOBALS = globals()


def main(argv=None):
    return _jtc.main(argv, _globals=globals())


CAP_MAX = 400  # trial ceiling for PWM and Current Limit (PWM max 885)
WRITES = {
    "torque": (64, 1),
    "goal_current": (102, 2),
    "profile_acc": (108, 4),
    "profile_vel": (112, 4),
    "goal_pos": (116, 4),
    "pwm_limit": (36, 2),
    "current_limit": (38, 2),
    "p_gain": (84, 2),
    "i_gain": (82, 2),
}
READS = {
    "model": (0, 2),
    "mode": (11, 1),
    "drive_mode": (10, 1),
    "hw_error": (70, 1),
    "moving": (122, 1),
    "present_load": (126, 2),
    "present_pos": (132, 4),
    "d_gain": (80, 2),
    **WRITES,
}
#: commissioning resting caps; every run starts from and ends at these (D-770)
BASELINE = {"pwm_limit": 20, "current_limit": 50}
SIGNED = {"present_load": 2, "present_pos": 4, "goal_pos": 4, "goal_current": 2}
EEPROM = ("pwm_limit", "current_limit")
STATE = ("torque", "hw_error", "moving", "present_load", "present_pos")
MAX_FEEDBACK_GAP_S = 0.25  # commissioning polling guard, not a physical stop deadline


def parse(argv=None):
    return _jtc.parse(argv, doc=__doc__ or "")


class SerialBus:
    """Confirmed bus opened exclusively; motor 0 lets session cleanup select its existing IDs."""

    def __init__(self, device: str, motor: int) -> None:
        if motor != 0 and motor not in TUNABLE:
            raise ValueError("only follower IDs 11-16 or confirmed leader wrist 5 may be tuned")
        import fcntl
        import termios
        import serial
        from dynamixel_sdk import PacketHandler, PortHandler

        path = Path(device)
        if path.parent != Path("/dev/serial/by-id") or not path.is_symlink():
            raise RuntimeError("a physically confirmed /dev/serial/by-id symlink is required")
        resolved = str(path.resolve(strict=True))
        self.motor = motor
        self.port = PortHandler(resolved)
        self.port.ser = serial.Serial(port=None, baudrate=1000000, timeout=0, exclusive=True)
        self.port.ser.port = resolved
        self.port.ser.dtr = self.port.ser.rts = False
        self.port.ser.open()
        fcntl.ioctl(self.port.ser.fileno(), termios.TIOCEXCL)
        self.port.is_open = True
        self.port.tx_time_per_byte = 0.01
        self.packet = PacketHandler(2.0)

    def read(self, name: str) -> int:
        address, size = READS[name]
        fn = {1: self.packet.read1ByteTxRx, 2: self.packet.read2ByteTxRx, 4: self.packet.read4ByteTxRx}[size]
        value, comm, error = fn(self.port, self.motor, address)
        if comm or error:
            raise RuntimeError(f"read {name}: comm {comm} error {error}")
        bits = 8 * SIGNED.get(name, 0)
        return value - (1 << bits) if bits and value >= 1 << (bits - 1) else value

    def write(self, name: str, value: int) -> None:
        address, size = WRITES[name]
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}[size]
        comm, error = fn(self.port, self.motor, address, value)
        if comm or error:
            raise RuntimeError(f"write {name}: comm {comm} error {error}")

    def _cleanup_check(self, comm: int, error: int) -> None:
        if comm or error & 0x7F:
            raise RuntimeError(f"cleanup: comm {comm} error {error}")
        if error & 0x80:
            if not hasattr(self, "cleanup_alerts"):
                self.cleanup_alerts = {}
            self.cleanup_alerts[self.motor] = True

    def cleanup_read(self, name: str) -> int:
        """Fault-preserving evidence for torque OFF and baseline-cap restoration only."""
        if name not in ("model", "mode", "torque", "hw_error", "pwm_limit", "current_limit"):
            raise ValueError("register is not cleanup evidence")
        address, size = READS[name]
        fn = {1: self.packet.read1ByteTxRx, 2: self.packet.read2ByteTxRx}[size]
        value, comm, error = fn(self.port, self.motor, address)
        self._cleanup_check(comm, error)
        return value

    def cleanup_write(self, name: str, value: int) -> None:
        """Only torque OFF or verified follower baseline EEPROM writes; never clears a fault."""
        if not (
            (name == "torque" and type(value) is int and value == 0)
            or (name in BASELINE and type(value) is int and value == BASELINE[name])
        ):
            raise ValueError("cleanup permits only torque OFF and baseline caps")
        if name in BASELINE:
            expected = FOLLOWER.get(self.motor)
            if (
                expected is None
                or (name == "current_limit" and expected[0] != 1200)
                or (self.cleanup_read("model"), self.cleanup_read("mode")) != expected
                or self.cleanup_read("torque") != 0
            ):
                raise RuntimeError("baseline caps require confirmed follower model/mode and torque OFF")
        address, size = WRITES[name]
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx}[size]
        comm, error = fn(self.port, self.motor, address, value)
        self._cleanup_check(comm, error)

    def alert(self) -> tuple[int, bool]:
        """Torque and the status packet's hardware-alert bit, readable while an alert makes read() fail."""
        torque, comm, error = self.packet.read1ByteTxRx(self.port, self.motor, READS["torque"][0])
        if comm:
            raise RuntimeError(f"motor {self.motor}: comm {comm}")
        return torque, bool(error & 0x80)

    def reboot(self) -> None:
        comm, _ = self.packet.reboot(self.port, self.motor)
        if comm:
            raise RuntimeError(f"reboot motor {self.motor}: comm {comm}")

    def close(self) -> None:
        self.port.ser.close()


class Run:
    def __init__(self, bus, motor: int, *, log, grab, clock=time.monotonic, sleep=time.sleep) -> None:
        if motor not in TUNABLE:
            raise ValueError("only follower IDs 11-16 or confirmed leader wrist 5 may be tuned")
        self.bus, self.motor, self.log, self.grab, self.clock, self.sleep = bus, motor, log, grab, clock, sleep
        self.xl330 = TUNABLE[motor][0] == 1200

    def state(self) -> dict:
        return {name: self.bus.read(name) for name in STATE}

    def set(self, name: str, value: int) -> int:
        """Write one whitelisted register and read it back; returns the previous value."""
        if name == "current_limit" and not self.xl330:
            raise RuntimeError("XL430 has no Current Limit register")
        before = self.bus.read(name) if name in READS else None
        if name in EEPROM and self.bus.read("torque") != 0:
            raise RuntimeError("torque must be OFF to write EEPROM")
        self.bus.write(name, value)
        after = self.bus.read(name) if name in READS else value
        self.log(step="set", motor=self.motor, name=name, before=before, value=value, after=after)
        if after != value:
            raise RuntimeError(f"{name} readback {after} != {value}")
        return before

    def settle(
        self, label: str, *, timeout=6.0, still=0.75, grace=1.5, origin=None, sag=None, capture=True
    ) -> dict:
        begun = previous = self.clock()
        if not math.isfinite(begun):
            raise RuntimeError("invalid startup observation clock")
        last, since, s = None, begun, None
        while True:
            s = self.state()
            self.log(step="watch", label=label, motor=self.motor, **s)
            if s["hw_error"]:
                raise RuntimeError(f"hardware error {s['hw_error']}")
            if s["torque"] != 1:
                raise RuntimeError(f"{label}: torque unavailable during hold")
            if sag is not None and abs(s["present_pos"] - origin) > sag:
                raise RuntimeError(f"joint {self.motor} sagged {s['present_pos'] - origin} ticks at torque ON")
            now = self.clock()
            if not math.isfinite(now) or now < previous:
                raise RuntimeError("invalid startup observation clock")
            if now - previous > MAX_FEEDBACK_GAP_S:
                raise RuntimeError(f"{label}: feedback sample gap")
            if now - begun >= timeout:
                raise RuntimeError(f"{label}: did not settle within {timeout} seconds")
            if s["present_pos"] != last or s["moving"]:
                last, since = s["present_pos"], now
            elif now - since >= still and now - begun >= grace:
                if capture:
                    self.grab(label)
                after = self.state()
                if (
                    after["torque"] != 1
                    or after["hw_error"]
                    or after["moving"]
                    or after["present_pos"] != s["present_pos"]
                ):
                    raise RuntimeError(f"{label}: feedback changed during camera capture")
                return after
            self.sleep(0.1)
            advanced = self.clock()
            if not math.isfinite(advanced) or advanced <= now:
                raise RuntimeError("startup observation clock did not advance")
            previous = now

    def execute(self, args) -> dict:
        before = self.state()
        model, mode = self.bus.read("model"), self.bus.read("mode")
        drive_mode = self.bus.read("drive_mode")
        self.log(step="before", motor=self.motor, model=model, mode=mode, **before)
        if (model, mode) != TUNABLE[self.motor] or before["torque"] != 0 or before["hw_error"] != 0:
            raise SystemExit(
                f"precondition failed: motor {self.motor} must be {TUNABLE[self.motor]} "
                f"(model, mode), torque OFF, no hardware error"
            )
        if drive_mode & 0x0C:
            raise SystemExit("drive mode must use velocity profiles without automatic torque enable")
        self.grab("before")

        def target_for(start):
            if args.command != "move":
                return None
            target = args.to if args.to is not None else start + args.delta
            low, high = (0, 4095) if self.motor == GRIPPER else (-1048575, 1048575)
            if not low <= target <= high:
                raise SystemExit(f"motor {self.motor}: target is outside the position range")
            if self.motor != GRIPPER and abs(target - start) > args.max_delta:
                raise SystemExit(f"joint {self.motor}: {target - start} ticks exceeds --max-delta {args.max_delta}")
            return target

        target_for(before["present_pos"])
        limits = ("pwm_limit", "current_limit") if self.xl330 else ("pwm_limit",)
        found = {name: self.bus.read(name) for name in limits}
        leader_wrist = self.motor == LEADER_WRIST
        if leader_wrist:
            if any(found[name] < BASELINE[name] for name in limits):
                raise SystemExit(f"leader wrist caps {found} below baseline; refusing to raise them")
            target = args.to if args.to is not None else before["present_pos"] + args.delta
            if args.command != "move" or abs(target - before["present_pos"]) > args.max_delta:
                raise SystemExit("leader wrist permits bounded move only")
        elif any(found[name] != BASELINE[name] for name in limits):
            raise SystemExit(
                f"motor {self.motor} caps {found} are not the commissioning baseline; an earlier "
                "run did not restore them - lower them with commissioning_limits.py --baseline (torque OFF)"
            )
        restore = {}
        try:
            if leader_wrist:
                restore.update({name: BASELINE[name] for name in limits})
                for name in limits:
                    if found[name] != BASELINE[name]:
                        self.set(name, BASELINE[name])
            if args.command == "hold":
                restore.update(
                    {name: self.bus.read(name) for name in ("profile_acc", "profile_vel", "goal_current", "goal_pos")}
                )
            else:
                for name, value in (
                    ("pwm_limit", args.pwm),
                    ("current_limit", args.current_limit if self.xl330 else None),
                    ("p_gain", args.p_gain),
                    ("i_gain", args.i_gain),
                ):
                    if value is not None:
                        restore[name] = BASELINE[name] if name in BASELINE else self.bus.read(name)
                        self.set(name, value)
            self.set("profile_acc", 1 if leader_wrist else args.acceleration)
            self.set("profile_vel", 1 if leader_wrist else args.velocity)
            if self.motor == GRIPPER:
                self.set("goal_current", args.goal_current)
            fresh = self.state()
            if (
                fresh["torque"] != 0
                or fresh["hw_error"]
                or fresh["moving"]
                or self.bus.read("mode") != mode
                or self.bus.read("drive_mode") != drive_mode
            ):
                raise RuntimeError("startup motor state changed during configuration")
            if abs(fresh["present_pos"] - before["present_pos"]) > args.sag:
                raise RuntimeError("startup position changed during configuration")
            start = fresh["present_pos"]
            target = target_for(start)
            self.set("goal_pos", start)
            self.set("torque", 1)
            held = self.settle(
                "hold",
                timeout=args.hold + 1.0,
                still=args.hold,
                grace=0,
                origin=start,
                sag=args.sag,
                capture=args.command != "hold",
            )
            if args.command == "hold":
                result = {"motor": self.motor, "target": start, "reached": held["present_pos"], "error_ticks": start - held["present_pos"], "load": held["present_load"]}
            elif args.command == "move":
                self.set("goal_pos", target)
                end = self.settle("move")
                result = {"motor": self.motor, "target": target, "reached": end["present_pos"], "error_ticks": target - end["present_pos"], "load": end["present_load"]}
            else:
                ends = {}
                for name, sign in (("open", 1), ("closed", -1)):
                    self.set("goal_pos", max(0, min(4095, start + sign * args.reach)))
                    ends[name] = self.settle(name)
                self.set("goal_pos", ends["closed"]["present_pos"])
                self.settle("rest", timeout=3.0, still=0.3)
                result = {
                    "motor": self.motor, "goal_current": args.goal_current, "pwm_limit": args.pwm,
                    "current_limit": args.current_limit, "p_gain": args.p_gain, "i_gain": args.i_gain,
                    "open_raw": ends["open"]["present_pos"], "closed_raw": ends["closed"]["present_pos"],
                    "stall_current": {k: v["present_load"] for k, v in ends.items()},
                    "end_found": {k: abs(v["present_load"]) >= 0.8 * args.goal_current for k, v in ends.items()},
                    "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            self.log(step="result", **result)
            return result
        finally:
            with no_interrupts():
                self.finish(restore)

    def finish(self, restore: dict) -> None:
        """Torque OFF, then every changed register back; each step is tried even if another failed."""
        failures = []
        torque_off = False
        for attempt in range(5):
            try:
                self.bus.write("torque", 0)
                state = self.state()
                self.log(step="after", motor=self.motor, **state)
                if state["torque"] != 0:
                    raise RuntimeError("torque OFF readback not confirmed")
                torque_off = True
                break
            except Exception as exc:
                if attempt == 4:
                    failures.append(f"torque OFF: {exc}")
                self.sleep(0.5)
        for name, value in (restore.items() if torque_off else ()):
            try:
                self.set(name, value)
            except Exception as exc:
                failures.append(f"restore {name}={value}: {exc}")
        if failures:
            self.log(step="unsafe_end", motor=self.motor, failures=failures)
            raise RuntimeError(f"motor {self.motor} did not end safely: {failures}")
        self.grab("after")


if __name__ == "__main__":
    main()
