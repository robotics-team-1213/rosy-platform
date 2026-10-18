#!/usr/bin/env python3
"""OMX gripper (follower ID 16) tuning: move it, or sweep it to find its closed and open ends.

Commissioning tool, not an actuator owner: run it only while no owner or controller holds the bus
and a person watches the arm. Each run raises the gripper's PWM/Current Limit (EEPROM 36/38) and,
optionally, its position P/I gains (RAM 84/82) for its own duration only, and always ends with
torque OFF and every changed register written back and read back. Current-based position mode
(mode 5) caps the force at the goal current, so stopping at a mechanical end is a stall, not a
crash. Only ID 16 and the registers below are ever written.

Every step goes to tune.jsonl; each settled position also saves the top and wrist frames from the
local camera viewer (frames/), so the motion can be checked by eye. A sweep writes
gripper-profile.json; an end counts only when the motor stalled near the goal current.

  gripper_tune.py --device /dev/serial/by-id/... move --to 2030 --p-gain 600 --i-gain 200
  gripper_tune.py --device /dev/serial/by-id/... sweep --reach 1700 --p-gain 600 --i-gain 200

Measured 2026-10-18 on the lab cell: closed 1982, open 3300, 15-24 mA in free motion. Without an
I gain the gripper stops short of its goal under load (P-only steady-state error).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

GRIPPER = 16
CAP_MAX = 400  # trial ceiling for PWM and Current Limit (XL330: PWM 885, current 1750)
WRITES = {"torque": (64, 1), "goal_current": (102, 2), "profile_acc": (108, 4), "profile_vel": (112, 4),
          "goal_pos": (116, 4), "pwm_limit": (36, 2), "current_limit": (38, 2), "p_gain": (84, 2),
          "i_gain": (82, 2)}
READS = {"mode": (11, 1), "torque": (64, 1), "hw_error": (70, 1), "moving": (122, 1),
         "present_current": (126, 2), "present_pos": (132, 4), **{k: WRITES[k] for k in
                                                                   ("pwm_limit", "current_limit", "p_gain", "i_gain")}}
SIGNED = {"present_current": 2, "present_pos": 4}
EEPROM = ("pwm_limit", "current_limit")  # writable with torque OFF only
STATE = ("torque", "hw_error", "moving", "present_current", "present_pos")


class SerialBus:
    """The confirmed follower bus, opened exclusively; reads and the WRITES whitelist on ID 16 only."""

    def __init__(self, device: str) -> None:
        import fcntl, termios
        import serial
        from dynamixel_sdk import PacketHandler, PortHandler

        path = Path(device)
        if path.parent != Path("/dev/serial/by-id") or not path.is_symlink():
            raise SystemExit("a physically confirmed /dev/serial/by-id symlink is required")
        resolved = str(path.resolve(strict=True))
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
        value, comm, error = fn(self.port, GRIPPER, address)
        if comm or error:
            raise RuntimeError(f"read {name}: comm {comm} error {error}")
        bits = 8 * SIGNED.get(name, 0)
        return value - (1 << bits) if bits and value >= 1 << (bits - 1) else value

    def write(self, name: str, value: int) -> None:
        address, size = WRITES[name]
        fn = {1: self.packet.write1ByteTxRx, 2: self.packet.write2ByteTxRx, 4: self.packet.write4ByteTxRx}[size]
        comm, error = fn(self.port, GRIPPER, address, value)
        if comm or error:
            raise RuntimeError(f"write {name}: comm {comm} error {error}")

    def close(self) -> None:
        self.port.ser.close()


class Run:
    def __init__(self, bus, *, log, grab, clock=time.monotonic, sleep=time.sleep) -> None:
        self.bus, self.log, self.grab, self.clock, self.sleep = bus, log, grab, clock, sleep

    def state(self) -> dict:
        return {name: self.bus.read(name) for name in STATE}

    def set(self, name: str, value: int) -> int:
        """Write one whitelisted register and read it back; returns the previous value."""
        before = self.bus.read(name) if name in READS else None
        if name in EEPROM and self.bus.read("torque") != 0:
            raise RuntimeError("torque must be OFF to write EEPROM")
        self.bus.write(name, value)
        after = self.bus.read(name) if name in READS else value
        self.log(step="set", name=name, before=before, value=value, after=after)
        if after != value:
            raise RuntimeError(f"{name} readback {after} != {value}")
        return before

    def settle(self, label: str, *, timeout=6.0, still=0.75, grace=1.5) -> dict:
        """Until the position has not changed for `still` s. A stall in the first `grace` s is not an
        end: an integrator wound up at the previous end needs time to unwind."""
        begun = self.clock()
        last, since, s = None, begun, None
        while self.clock() - begun < timeout:
            s = self.state()
            self.log(step="watch", label=label, **s)
            if s["hw_error"]:
                raise RuntimeError(f"hardware error {s['hw_error']}")
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
        mode = self.bus.read("mode")
        self.log(step="before", mode=mode, **before)
        self.grab("before")
        if mode != 5 or before["torque"] != 0 or before["hw_error"] != 0:
            raise SystemExit("precondition failed: mode 5, torque OFF, no hardware error")
        saved = {}
        try:
            for name, value in (("pwm_limit", args.pwm), ("current_limit", args.current_limit),
                                ("p_gain", args.p_gain), ("i_gain", args.i_gain)):
                if value is not None:
                    saved[name] = self.set(name, value)
            start = before["present_pos"]
            for name, value in (("profile_acc", args.acceleration), ("profile_vel", args.velocity),
                                ("goal_current", args.goal_current), ("goal_pos", start), ("torque", 1)):
                self.set(name, value)
            self.settle("hold", timeout=1.0, still=0.3, grace=0)
            if args.command == "move":
                target = args.to if args.to is not None else start + args.delta
                self.set("goal_pos", target)
                end = self.settle("move")
                result = {"target": target, "reached": end["present_pos"],
                          "error_ticks": target - end["present_pos"], "current": end["present_current"]}
            else:
                ends = {}
                for name, sign in (("open", 1), ("closed", -1)):
                    self.set("goal_pos", max(0, min(4095, start + sign * args.reach)))
                    ends[name] = self.settle(name)
                self.set("goal_pos", ends["closed"]["present_pos"])
                self.settle("rest", timeout=3.0, still=0.3)
                result = {"gripper_id": GRIPPER, "goal_current": args.goal_current, "pwm_limit": args.pwm,
                          "current_limit": args.current_limit, "p_gain": args.p_gain, "i_gain": args.i_gain,
                          "open_raw": ends["open"]["present_pos"], "closed_raw": ends["closed"]["present_pos"],
                          "stall_current": {k: v["present_current"] for k, v in ends.items()},
                          "end_found": {k: abs(v["present_current"]) >= 0.8 * args.goal_current
                                        for k, v in ends.items()},
                          "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            self.log(step="result", **result)
            return result
        finally:
            try:
                self.bus.write("torque", 0)
                self.log(step="after", **self.state())
                self.grab("after")
            finally:
                for name, value in saved.items():  # torque is OFF, so EEPROM may be written
                    self.set(name, value)


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", required=True)
    parser.add_argument("--viewer", default="http://127.0.0.1:8767", help="local camera viewer ('' to skip frames)")
    parser.add_argument("command", choices=("move", "sweep"))
    parser.add_argument("--to", type=int)
    parser.add_argument("--delta", type=int)
    parser.add_argument("--pwm", type=int, default=300)
    parser.add_argument("--current-limit", type=int, default=250)
    parser.add_argument("--goal-current", type=int, default=200)
    parser.add_argument("--p-gain", type=int)
    parser.add_argument("--i-gain", type=int)
    parser.add_argument("--velocity", type=int, default=20)
    parser.add_argument("--acceleration", type=int, default=10)
    parser.add_argument("--reach", type=int, default=1700, help="sweep: how far past the start to push each way")
    args = parser.parse_args(argv)
    if not (1 <= args.pwm <= CAP_MAX and 1 <= args.current_limit <= CAP_MAX
            and 1 <= args.goal_current <= args.current_limit):
        parser.error(f"caps must be 1..{CAP_MAX} and the goal current at most the current limit")
    if any(gain is not None and not 0 <= gain <= 2000 for gain in (args.p_gain, args.i_gain)):
        parser.error("gains must be 0..2000")
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
            name = f"frames/tune-{time.strftime('%H%M%S')}-{label}-{camera}.jpg"
            try:
                host = args.viewer.split("//", 1)[-1]
                request = urllib.request.Request(f"{args.viewer}/frame/{camera}.jpg", headers={"Host": host})
                Path(name).write_bytes(urllib.request.urlopen(request, timeout=2).read())
                saved[camera] = name
            except Exception as exc:  # a missing frame never stops or skips the safe ending
                saved[camera] = f"unavailable: {exc}"
        log(step="frames", label=label, **saved)

    bus = SerialBus(args.device)
    try:
        result = Run(bus, log=log, grab=grab).execute(args)
    finally:
        bus.close()
    if args.command == "sweep":
        Path("gripper-profile.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
