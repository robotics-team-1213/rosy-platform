#!/usr/bin/env python3
"""OMX follower joint tuning (IDs 11-16): move one joint, or sweep the gripper to find its ends.

Commissioning tool, not an actuator owner: run it only while no owner or controller holds the bus
and a person watches the arm. Only the chosen motor and the registers below are ever written, and
only that motor's torque is ever turned on. Each run raises that motor's PWM Limit (EEPROM 36),
its Current Limit (EEPROM 38, XL330 only) and, optionally, its position P/I gains (RAM 84/82) for
its own duration only, and always ends with torque OFF and every changed register written back and
read back. EEPROM is written with torque OFF only.

Per joint:
- 16 gripper (XL330, mode 5 current-based position): the goal current caps the force, so `sweep`
  may push to the mechanical ends; an end counts only when the motor stalled near the goal current.
- 14-15 wrist (XL330, mode 4) and 11-13 (XL430, mode 4; 11-13 carry the arm's weight): only the
  PWM Limit caps the force. `move` only, at most --max-delta ticks from the start (default 200). At
  torque ON the joint must hold its position within --sag ticks for the hold window, or the run stops
  before any motion (a weak PWM Limit lets a loaded joint sag).

Every step goes to tune.jsonl; each settled position also saves the top and wrist frames from the
local camera viewer (frames/). A gripper sweep writes gripper-profile.json.

  joint_tune.py --device /dev/serial/by-id/... --id 15 move --delta 50 --pwm 150
  joint_tune.py --device /dev/serial/by-id/... --id 16 sweep --reach 1700 --p-gain 600 --i-gain 200

Measured 2026-10-18 on the lab cell: gripper closed 1982, open 3300, 15-24 mA in free motion;
without an I gain it stops short of its goal under load (P-only steady-state error).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import signal
import time
import urllib.request
from pathlib import Path

GRIPPER = 16
#: id -> (model number, operating mode); XL430-W250 = 1060, XL330-M288 = 1200
FOLLOWER = {11: (1060, 4), 12: (1060, 4), 13: (1060, 4), 14: (1200, 4), 15: (1200, 4), 16: (1200, 5)}
CAP_MAX = 400  # trial ceiling for PWM and Current Limit (PWM max 885)
WRITES = {"torque": (64, 1), "goal_current": (102, 2), "profile_acc": (108, 4), "profile_vel": (112, 4),
          "goal_pos": (116, 4), "pwm_limit": (36, 2), "current_limit": (38, 2), "p_gain": (84, 2),
          "i_gain": (82, 2)}
READS = {"model": (0, 2), "mode": (11, 1), "torque": (64, 1), "hw_error": (70, 1), "moving": (122, 1),
         "present_load": (126, 2), "present_pos": (132, 4),
         **{k: WRITES[k] for k in ("pwm_limit", "current_limit", "p_gain", "i_gain")}}
#: commissioning resting caps; every run starts from and ends at these (D-770)
BASELINE = {"pwm_limit": 20, "current_limit": 50}
SIGNED = {"present_load": 2, "present_pos": 4}  # present_load: XL330 current (mA), XL430 load (0.1 %)
EEPROM = ("pwm_limit", "current_limit")
STATE = ("torque", "hw_error", "moving", "present_load", "present_pos")


def lock_root() -> Path:
    """One place for the cell's session lock: shared by joint_tune, record_session and omx_autoupdate."""
    return Path(os.environ.get("ROSY_OMX_HOME", Path.home() / "rosy-omx"))


def session_lock():
    """Held for a whole tuning run or recording session; another holder means the cell is busy."""
    root = lock_root()
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / "session.lock").open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit("another OMX session holds session.lock")
    return handle


def _interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def protect_signals() -> None:
    """SIGTERM (systemd) and SIGHUP (a dropped SSH session) end the run like Ctrl-C, so cleanup runs."""
    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGHUP, _interrupt)


@contextlib.contextmanager
def no_interrupts():
    """While cleaning up, a second Ctrl-C (or SIGTERM/SIGHUP) must not abort torque OFF or a restore."""
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    try:
        previous = [signal.signal(s, signal.SIG_IGN) for s in signals]
    except ValueError:  # not the main thread: nothing to mask
        yield
        return
    try:
        yield
    finally:
        for s, handler in zip(signals, previous):
            signal.signal(s, handler)


class SerialBus:
    """Confirmed follower bus; motor 0 lets session cleanup select its existing IDs."""

    def __init__(self, device: str, motor: int) -> None:
        if motor != 0 and motor not in FOLLOWER:
            raise ValueError("only follower IDs 11-16 may be tuned")
        import fcntl, termios
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
        self.port.ser.dtr = self.port.ser.rts = False  # no controller reset on open
        self.port.ser.open()
        fcntl.ioctl(self.port.ser.fileno(), termios.TIOCEXCL)
        self.port.is_open = True
        self.port.tx_time_per_byte = .01
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
        # An Alert carries usable payload only when transport and instruction status succeeded.
        if comm or error & 0x7f:
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
        if not ((name == "torque" and type(value) is int and value == 0)
                or (name in BASELINE and type(value) is int and value == BASELINE[name])):
            raise ValueError("cleanup permits only torque OFF and baseline caps")
        if name in BASELINE:
            expected = FOLLOWER.get(self.motor)
            if (expected is None or (name == "current_limit" and expected[0] != 1200)
                    or (self.cleanup_read("model"), self.cleanup_read("mode")) != expected
                    or self.cleanup_read("torque") != 0):
                raise RuntimeError("baseline caps require confirmed follower model/mode and torque OFF")
        address, size = WRITES[name]
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx}[size]
        comm, error = fn(self.port, self.motor, address, value)
        self._cleanup_check(comm, error)

    def close(self) -> None:
        self.port.ser.close()


class Run:
    def __init__(self, bus, motor: int, *, log, grab, clock=time.monotonic, sleep=time.sleep) -> None:
        self.bus, self.motor, self.log, self.grab, self.clock, self.sleep = bus, motor, log, grab, clock, sleep
        self.xl330 = FOLLOWER[motor][0] == 1200

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

    def settle(self, label: str, *, timeout=6.0, still=0.75, grace=1.5, origin=None, sag=None) -> dict:
        """Until the position has not changed for `still` s. A stall in the first `grace` s is not an
        end: an integrator wound up at the previous end needs time to unwind. With `sag`, any drift
        beyond `sag` ticks from `origin` stops the run."""
        begun = self.clock()
        last, since, s = None, begun, None
        while self.clock() - begun < timeout:
            s = self.state()
            self.log(step="watch", label=label, motor=self.motor, **s)
            if s["hw_error"]:
                raise RuntimeError(f"hardware error {s['hw_error']}")
            if sag is not None and abs(s["present_pos"] - origin) > sag:
                raise RuntimeError(f"joint {self.motor} sagged {s['present_pos'] - origin} ticks at torque ON")
            now = self.clock()
            if s["present_pos"] != last:
                last, since = s["present_pos"], now
            elif now - since >= still and now - begun >= grace:
                break
            self.sleep(0.1)
        self.grab(label)
        return s

    def execute(self, args) -> dict:
        before = self.state()
        model, mode = self.bus.read("model"), self.bus.read("mode")
        self.log(step="before", motor=self.motor, model=model, mode=mode, **before)
        self.grab("before")
        if ((model, mode) != FOLLOWER[self.motor] or before["torque"] != 0 or before["hw_error"] != 0):
            raise SystemExit(f"precondition failed: motor {self.motor} must be {FOLLOWER[self.motor]} "
                             f"(model, mode), torque OFF, no hardware error")
        limits = ("pwm_limit", "current_limit") if self.xl330 else ("pwm_limit",)
        found = {name: self.bus.read(name) for name in limits}
        if any(found[name] != BASELINE[name] for name in limits):
            raise SystemExit(f"motor {self.motor} caps {found} are not the commissioning baseline; an earlier "
                             "run did not restore them - lower them with commissioning_limits.py (torque OFF)")
        restore = {}  # filled before each write, so a write whose readback fails is still restored
        try:
            for name, value in (("pwm_limit", args.pwm),
                                ("current_limit", args.current_limit if self.xl330 else None),
                                ("p_gain", args.p_gain), ("i_gain", args.i_gain)):
                if value is not None:
                    restore[name] = BASELINE[name] if name in BASELINE else self.bus.read(name)
                    self.set(name, value)
            start = before["present_pos"]
            target = None
            if args.command == "move":  # bounded before any torque
                target = args.to if args.to is not None else start + args.delta
                if self.motor != GRIPPER and abs(target - start) > args.max_delta:
                    raise SystemExit(f"joint {self.motor}: {target - start} ticks exceeds --max-delta {args.max_delta}")
            self.set("profile_acc", args.acceleration)
            self.set("profile_vel", args.velocity)
            if self.motor == GRIPPER:
                self.set("goal_current", args.goal_current)
            self.set("goal_pos", start)
            self.set("torque", 1)
            self.settle("hold", timeout=args.hold, still=args.hold, grace=0, origin=start, sag=args.sag)
            if args.command == "move":
                self.set("goal_pos", target)
                end = self.settle("move")
                result = {"motor": self.motor, "target": target, "reached": end["present_pos"],
                          "error_ticks": target - end["present_pos"], "load": end["present_load"]}
            else:
                ends = {}
                for name, sign in (("open", 1), ("closed", -1)):
                    self.set("goal_pos", max(0, min(4095, start + sign * args.reach)))
                    ends[name] = self.settle(name)
                self.set("goal_pos", ends["closed"]["present_pos"])
                self.settle("rest", timeout=3.0, still=0.3)
                result = {"motor": self.motor, "goal_current": args.goal_current, "pwm_limit": args.pwm,
                          "current_limit": args.current_limit, "p_gain": args.p_gain, "i_gain": args.i_gain,
                          "open_raw": ends["open"]["present_pos"], "closed_raw": ends["closed"]["present_pos"],
                          "stall_current": {k: v["present_load"] for k, v in ends.items()},
                          "end_found": {k: abs(v["present_load"]) >= 0.8 * args.goal_current
                                        for k, v in ends.items()},
                          "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self.log(step="result", **result)
            return result
        finally:
            with no_interrupts():
                self.finish(restore)

    def finish(self, restore: dict) -> None:
        """Torque OFF, then every changed register back; each step is tried even if another failed."""
        failures = []
        for attempt in range(5):  # a USB hiccup: try again for a few seconds before declaring it unsafe
            try:
                self.bus.write("torque", 0)
                self.log(step="after", motor=self.motor, **self.state())
                break
            except Exception as exc:
                if attempt == 4:
                    failures.append(f"torque OFF: {exc}")
                self.sleep(0.5)
        self.grab("after")
        for name, value in restore.items():  # torque is OFF, so EEPROM may be written
            try:
                self.set(name, value)
            except Exception as exc:
                failures.append(f"restore {name}={value}: {exc}")
        if failures:
            self.log(step="unsafe_end", motor=self.motor, failures=failures)
            raise RuntimeError(f"motor {self.motor} did not end safely: {failures}")


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", required=True)
    parser.add_argument("--id", type=int, default=GRIPPER, choices=sorted(FOLLOWER))
    parser.add_argument("--viewer", default="http://127.0.0.1:8767", help="local camera viewer ('' to skip frames)")
    parser.add_argument("command", choices=("move", "sweep"))
    parser.add_argument("--to", type=int)
    parser.add_argument("--delta", type=int)
    parser.add_argument("--pwm", type=int, default=300)
    parser.add_argument("--current-limit", type=int, default=250, help="XL330 only")
    parser.add_argument("--goal-current", type=int, default=200, help="gripper only")
    parser.add_argument("--p-gain", type=int)
    parser.add_argument("--i-gain", type=int)
    parser.add_argument("--velocity", type=int, default=20)
    parser.add_argument("--acceleration", type=int, default=10)
    parser.add_argument("--hold", type=float, default=1.0, help="seconds to hold the start at torque ON")
    parser.add_argument("--sag", type=int, default=20, help="ticks the start may drift while holding")
    parser.add_argument("--max-delta", type=int, default=200, help="non-gripper move limit in ticks")
    parser.add_argument("--reach", type=int, default=1700, help="gripper sweep: push this far each way")
    args = parser.parse_args(argv)
    if not (1 <= args.pwm <= CAP_MAX and 1 <= args.current_limit <= CAP_MAX
            and 1 <= args.goal_current <= args.current_limit):
        parser.error(f"caps must be 1..{CAP_MAX} and the goal current at most the current limit")
    if any(gain is not None and not 0 <= gain <= 2000 for gain in (args.p_gain, args.i_gain)):
        parser.error("gains must be 0..2000")
    if not (0 < args.hold <= 5 and 0 < args.sag <= 100 and 0 < args.max_delta <= 400):
        parser.error("--hold 0..5 s, --sag 1..100, --max-delta 1..400")
    if args.command == "sweep" and args.id != GRIPPER:
        parser.error("sweep pushes to mechanical ends: gripper (16) only")
    if args.command == "move":
        if (args.to is None) == (args.delta is None):
            parser.error("move needs exactly one of --to / --delta")
        if args.to is not None and not 0 <= args.to <= 4095:
            parser.error("--to must be 0..4095")
    return args


def main(argv=None):
    args = parse(argv)
    out = Path("tune.jsonl")

    def log(**row):
        row["t"] = round(time.monotonic(), 3)
        with out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def grab(label):
        if not args.viewer:
            return
        Path("frames").mkdir(exist_ok=True)
        saved = {}
        for camera in ("top", "front"):
            name = f"frames/tune-{time.strftime('%H%M%S')}-id{args.id}-{label}-{camera}.jpg"
            try:
                host = args.viewer.split("//", 1)[-1]
                request = urllib.request.Request(f"{args.viewer}/frame/{camera}.jpg", headers={"Host": host})
                Path(name).write_bytes(urllib.request.urlopen(request, timeout=2).read())
                saved[camera] = name
            except Exception as exc:  # a missing frame never stops or skips the safe ending
                saved[camera] = f"unavailable: {exc}"
        log(step="frames", label=label, **saved)

    protect_signals()
    lock = session_lock()
    try:
        bus = SerialBus(args.device, args.id)
        try:
            result = Run(bus, args.id, log=log, grab=grab).execute(args)
        finally:
            bus.close()
    finally:
        lock.close()
    if args.command == "sweep":
        Path("gripper-profile.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
