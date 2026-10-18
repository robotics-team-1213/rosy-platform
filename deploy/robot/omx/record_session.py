#!/usr/bin/env python3
"""One leader→follower LeRobot session with the follower's power caps raised only for its duration.

LeRobot's OmxFollower.configure() writes modes and PID but never the PWM/Current Limits, and the
commissioning caps (PWM 20, Current 50) keep the follower from following. This wrapper:

1. validates the record config (record_config.py) and requires follower IDs 11-16 idle (torque OFF,
   no hardware error);
2. saves the follower PWM Limit (36) and XL330 Current Limit (38) and writes the caps file values
   with torque OFF, reading each back;
3. stops the active camera services, because the recorder opens the V4L devices itself (D-770 §3:
   never two openers);
4. runs `lerobot-record` (or `lerobot-teleoperate` with --teleop-only, for a dry run without data);
5. always, however the command ends: torque OFF on follower 11-16 and the leader gripper (6), the
   saved caps written back and read back, the stopped services started again, session.json written.

No independent stop exists while LeRobot holds the bus: keep a hand on the follower power switch.

  record_session.py --config record-config.json --caps caps.json [--teleop-only]

caps.json: {"11": {"pwm": 300}, ..., "16": {"pwm": 300, "current": 250}}  (all six IDs)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from joint_tune import FOLLOWER, SerialBus
from record_config import validate_config

SERVICES = ("rosy-omx-camera@top.service", "rosy-omx-camera@front.service",
            "rosy-omx-camera-view.service", "rosy-omx-camera-readiness.service")
LEADER_GRIPPER = 6
PWM_MAX, CURRENT_MAX = 885, 1750


def load_caps(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    caps = {int(k): v for k, v in raw.items()}
    if set(caps) != set(FOLLOWER):
        raise SystemExit(f"caps must name every follower ID {sorted(FOLLOWER)}")
    for motor, cap in caps.items():
        xl330 = FOLLOWER[motor][0] == 1200
        allowed = {"pwm", "current"} if xl330 else {"pwm"}
        if not set(cap) <= allowed or "pwm" not in cap:
            raise SystemExit(f"motor {motor}: caps keys must be {sorted(allowed)} with pwm")
        if not (type(cap["pwm"]) is int and 1 <= cap["pwm"] <= PWM_MAX):
            raise SystemExit(f"motor {motor}: pwm 1..{PWM_MAX}")
        if "current" in cap and not (type(cap["current"]) is int and 1 <= cap["current"] <= CURRENT_MAX):
            raise SystemExit(f"motor {motor}: current 1..{CURRENT_MAX}")
    return caps


class Session:
    def __init__(self, *, open_bus, systemctl, run, log, sleep=time.sleep) -> None:
        self.open_bus, self.systemctl, self.run_command, self.log, self.sleep = open_bus, systemctl, run, log, sleep

    @staticmethod
    def command(config_path: Path, teleop_only: bool) -> list:
        """lerobot-record on the record config, or lerobot-teleoperate on its robot/teleop part."""
        bin_dir = Path(sys.executable).parent
        if not teleop_only:
            return [str(bin_dir / "lerobot-record"), f"--config_path={config_path}"]
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        teleop = config_path.with_name(config_path.stem + ".teleop.json")
        teleop.write_text(json.dumps({"robot": config["robot"], "teleop": config["teleop"],
                                      "fps": config["dataset"]["fps"], "display_data": False}, indent=2))
        return [str(bin_dir / "lerobot-teleoperate"), f"--config_path={teleop}"]

    def _with_follower(self, action):
        bus = self.open_bus("follower")
        try:
            return action(bus)
        finally:
            bus.close()

    def _cap_registers(self, motor):
        return ("pwm_limit", "current_limit") if FOLLOWER[motor][0] == 1200 else ("pwm_limit",)

    def check_idle(self, bus) -> dict:
        saved = {}
        for motor in FOLLOWER:
            bus.motor = motor
            model, mode = bus.read("model"), bus.read("mode")
            torque, error = bus.read("torque"), bus.read("hw_error")
            if (model, mode) != FOLLOWER[motor] or torque or error:
                raise SystemExit(f"follower {motor} not idle: model/mode {(model, mode)}, torque {torque}, error {error}")
            saved[motor] = {name: bus.read(name) for name in self._cap_registers(motor)}
        return saved

    def write_caps(self, bus, caps) -> None:
        for motor, values in caps.items():
            bus.motor = motor
            if bus.read("torque"):
                raise RuntimeError(f"follower {motor} torque ON: EEPROM caps not written")
            for name, value in values.items():
                bus.write(name, value)
                after = bus.read(name)
                self.log(step="cap", motor=motor, name=name, value=value, after=after)
                if after != value:
                    raise RuntimeError(f"follower {motor} {name} readback {after} != {value}")

    def all_torque_off(self, bus) -> dict:
        state = {}
        for motor in FOLLOWER:
            bus.motor = motor
            try:
                bus.write("torque", 0)
                state[motor] = bus.read("torque")
            except Exception as exc:  # keep turning the others off
                state[motor] = f"error: {exc}"
        return state

    def execute(self, config_path: Path, caps: dict, *, teleop_only: bool) -> dict:
        record = {"config": str(config_path), "caps": caps, "teleop_only": teleop_only, "started": time.time()}
        validate_config(json.loads(config_path.read_text(encoding="utf-8-sig")))
        saved = self._with_follower(self.check_idle)
        record["saved_caps"] = saved
        stopped = []
        try:
            self._with_follower(lambda bus: self.write_caps(bus, caps))
            for unit in SERVICES:
                if self.systemctl("is-active", unit) == "active":
                    self.systemctl("stop", unit)
                    stopped.append(unit)
            record["stopped_services"] = stopped
            command = self.command(config_path, teleop_only)
            self.log(step="run", command=command)
            record["exit_code"] = self.run_command(command)
        finally:
            for attempt in range(5):  # the recorder may still be releasing the port
                try:
                    record["torque_after"] = self._with_follower(self.all_torque_off)
                    break
                except Exception as exc:
                    record["torque_after"] = f"error: {exc}"
                    self.sleep(0.5)
            try:
                leader = self.open_bus("leader")
                try:
                    leader.motor = LEADER_GRIPPER
                    leader.write("torque", 0)
                    record["leader_gripper_torque_after"] = leader.read("torque")
                finally:
                    leader.close()
            except Exception as exc:
                record["leader_gripper_torque_after"] = f"error: {exc}"
            try:
                self._with_follower(lambda bus: self.write_caps(bus, saved))
                record["caps_restored"] = True
            except Exception as exc:
                record["caps_restored"] = f"error: {exc}"
            for unit in stopped:
                self.systemctl("start", unit)
            record["restarted_services"] = stopped
            record["ended"] = time.time()
            self.log(step="session", **record)
        return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--caps", required=True, type=Path)
    parser.add_argument("--teleop-only", action="store_true")
    args = parser.parse_args(argv)
    caps = load_caps(args.caps)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    ports = {"follower": config["robot"]["port"], "leader": config["teleop"]["port"]}
    out = Path("session.jsonl")

    def log(**row):
        row["t"] = round(time.time(), 3)
        with out.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(json.dumps(row, default=str), flush=True)

    def systemctl(verb, unit):
        done = subprocess.run(["systemctl", "--user", verb, unit], capture_output=True, text=True, timeout=30)
        return done.stdout.strip()

    session = Session(open_bus=lambda which: SerialBus(ports[which], 0), systemctl=systemctl,
                      run=lambda command: subprocess.call(command), log=log)
    record = session.execute(args.config, caps, teleop_only=args.teleop_only)
    Path("session.json").write_text(json.dumps(record, indent=2, default=str))
    raise SystemExit(record.get("exit_code") or 0)


if __name__ == "__main__":
    main()
