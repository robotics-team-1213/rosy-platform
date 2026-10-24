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
5. always, however the command ends (Ctrl-C, SIGTERM, a dropped SSH session's SIGHUP): the recorder
   gets SIGINT and 10 s to finish its episode before it is killed; then, with further interrupts
   ignored, torque OFF on follower 11-16 (retried for up to 30 s, reopening the port after a USB
   drop, until every motor reads 0) and on the leader gripper (6), each motor's caps back to the
   commissioning baseline (PWM 20, Current 50) even if another motor failed, the stopped services
   started again, session.json written. The exit status is non-zero unless that ending was safe.

The session refuses to start unless the follower caps are at the baseline (an earlier session that
did not restore them must be fixed first), and caps files may not exceed 400.
No independent stop exists while LeRobot holds the bus: keep a hand on the follower power switch.
Run it inside tmux so a dropped connection does not even reach it.

  record_session.py --config record-config.json --caps caps.json [--task-card task-card.yaml] [--teleop-only]

caps.json: {"11": {"pwm": 300}, ..., "16": {"pwm": 300, "current": 250}}  (all six IDs)
Tasks plug in and out: the record config holds only what does not change with the task (devices,
cameras, fps); a task card (tasks/<task>.yaml, schema rosy.omx-task-card.v1) holds the task text,
episode timing, dataset name and its design (layout, phases, success and failure labels). With
--task-card the card's `record` block fills the dataset section, the dataset root becomes a new
`<root_prefix>/<task_id>-r<revision>-<stamp>`, and the card is copied verbatim with its sha256 into
session.json, so review knows which design an episode was recorded under.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from joint_tune import BASELINE, CAP_MAX, FOLLOWER, SerialBus, no_interrupts, protect_signals, session_lock
from record_config import validate_config

SERVICES = ("rosy-omx-camera@top.service", "rosy-omx-camera@front.service",
            "rosy-omx-camera-view.service", "rosy-omx-camera-readiness.service")
LEADER_GRIPPER = 6
PWM_MAX = CURRENT_MAX = CAP_MAX  # first sessions stay well below the hardware maximum (885 / 1750)
TORQUE_OFF_DEADLINE_S = 30.0


def interrupt_on_parent_death() -> None:
    """In the recorder (Linux): SIGINT when this wrapper dies, so it never runs on unsupervised."""
    import ctypes

    PR_SET_PDEATHSIG = 1
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGINT)


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
    names = {"pwm": "pwm_limit", "current": "current_limit"}  # caps-file keys -> register names
    return {motor: {names[key]: value for key, value in cap.items()} for motor, cap in caps.items()}


CARD_SCHEMA = "rosy.omx-task-card.v1"


def release() -> str | None:
    """The code commit these tools came from (RELEASE written by omx_autoupdate.py), if installed so."""
    marker = Path(__file__).resolve().parents[3] / "RELEASE"
    return marker.read_text().strip() if marker.exists() else None


def load_task_card(path: Path) -> dict:
    import yaml

    card = yaml.safe_load(path.read_text(encoding="utf-8"))
    record = card.get("record") if isinstance(card, dict) else None
    if not isinstance(card, dict) or card.get("schema") != CARD_SCHEMA or not isinstance(record, dict):
        raise SystemExit(f"task card needs schema {CARD_SCHEMA} and a record block")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(card.get("task_id", ""))):
        raise SystemExit("task_id must be a lowercase slug")
    if type(card.get("revision")) is not int or card["revision"] < 1:
        raise SystemExit("revision must be a positive integer")
    if not isinstance(card.get("single_task"), str) or not card["single_task"].strip():
        raise SystemExit("single_task text is required")
    if not str(record.get("root_prefix", "")).startswith("/"):
        raise SystemExit("record.root_prefix must be an absolute path")
    for key in ("episode_time_s", "reset_time_s", "num_episodes"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise SystemExit(f"record.{key} must be positive")
    return card


def compose(config: dict, card: dict, *, stamp: str) -> dict:
    """The device config with the card's task plugged into its dataset section (config is not changed)."""
    record = card["record"]
    dataset = {**config["dataset"], "single_task": card["single_task"],
               "episode_time_s": record["episode_time_s"], "reset_time_s": record["reset_time_s"],
               "num_episodes": record["num_episodes"],
               "root": f"{record['root_prefix'].rstrip('/')}/{card['task_id']}-r{card['revision']}-{stamp}"}
    if "repo_id" in record:
        dataset["repo_id"] = record["repo_id"]
    return {**config, "dataset": dataset}


class Session:
    def __init__(self, *, open_bus, systemctl, run, log, sleep=time.sleep, clock=time.monotonic) -> None:
        self.open_bus, self.systemctl, self.run_command, self.log = open_bus, systemctl, run, log
        self.sleep, self.clock = sleep, clock

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

    def check_idle(self, bus) -> None:
        for motor in FOLLOWER:
            bus.motor = motor
            model, mode = bus.read("model"), bus.read("mode")
            torque, error = bus.read("torque"), bus.read("hw_error")
            if (model, mode) != FOLLOWER[motor] or torque or error:
                raise SystemExit(f"follower {motor} not idle: model/mode {(model, mode)}, torque {torque}, error {error}")
            caps = {name: bus.read(name) for name in self._cap_registers(motor)}
            if any(caps[name] != BASELINE[name] for name in caps):
                raise SystemExit(f"follower {motor} caps {caps} are not the commissioning baseline; an earlier "
                                 "session did not restore them - lower them with commissioning_limits.py --baseline "
                                 "(torque OFF) before recording")

    def baseline(self) -> dict:
        return {motor: {name: BASELINE[name] for name in self._cap_registers(motor)} for motor in FOLLOWER}

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

    def torque_off_until_confirmed(self) -> tuple[bool, dict]:
        """Retry, reopening the port each time (the recorder may still hold it, a USB drop may have
        re-enumerated it), until every follower motor reads torque 0 or the deadline passes."""
        deadline = self.clock() + TORQUE_OFF_DEADLINE_S
        last = {}
        while True:
            try:
                last = self._with_follower(self.all_torque_off)
            except Exception as exc:
                last = {"open": f"error: {exc}"}
            if last and all(value == 0 for value in last.values()) and len(last) == len(FOLLOWER):
                return True, last
            if self.clock() >= deadline:
                return False, last
            self.sleep(1.0)

    def restore_caps(self) -> list:
        """Each motor back to the baseline; a failure on one motor never skips the others."""
        failures = []
        for motor, values in self.baseline().items():
            try:
                self._with_follower(lambda bus, m=motor, v=values: self.write_caps(bus, {m: v}))
            except Exception as exc:
                failures.append(f"follower {motor}: {exc}")
        return failures

    def execute(self, config_path: Path, caps: dict, *, teleop_only: bool, task_card: Path | None = None) -> dict:
        record = {"config": str(config_path), "caps": caps, "teleop_only": teleop_only, "started": time.time(),
                  "release": release()}
        if task_card is not None:
            text = task_card.read_bytes()
            record["task_card"] = {"path": str(task_card), "sha256": hashlib.sha256(text).hexdigest(),
                                   "text": text.decode("utf-8")}
        validate_config(json.loads(config_path.read_text(encoding="utf-8-sig")))
        self._with_follower(self.check_idle)
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
            try:
                record["exit_code"] = self.run_command(command)
            except KeyboardInterrupt:  # Ctrl-C/SIGTERM/SIGHUP: the normal end of a teleop-only session
                record["interrupted"] = True
        finally:
            with no_interrupts():
                self.finish(record, stopped)
        return record

    def finish(self, record: dict, stopped: list) -> None:
        torque_ok, record["torque_after"] = self.torque_off_until_confirmed()
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
        failures = self.restore_caps()
        record["caps_restored"] = not failures or failures
        for unit in stopped:
            try:
                self.systemctl("start", unit)
            except Exception as exc:
                record.setdefault("service_errors", []).append(f"{unit}: {exc}")
        record["restarted_services"] = stopped
        record["safe_end"] = torque_ok and not failures
        record["ended"] = time.time()
        self.log(step="session", **record)
        if not record["safe_end"]:
            self.log(step="UNSAFE_END", torque_after=record["torque_after"], caps_restored=record["caps_restored"],
                     action="switch off the follower power and restore the caps before the next session")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--caps", required=True, type=Path)
    parser.add_argument("--teleop-only", action="store_true")
    parser.add_argument("--task-card", type=Path, help="task design card to embed in session.json")
    args = parser.parse_args(argv)
    caps = load_caps(args.caps)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.task_card is not None:
        card = load_task_card(args.task_card)
        config = compose(config, card, stamp=time.strftime("%Y%m%d-%H%M%S"))
        args.config = args.config.with_name(f"{args.config.stem}.{card['task_id']}.json")
        args.config.write_text(json.dumps(config, indent=2))
    ports = {"follower": config["robot"]["port"], "leader": config["teleop"]["port"]}
    out = Path("session.jsonl")

    def log(**row):
        row["t"] = round(time.time(), 3)
        with out.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        print(json.dumps(row, default=str), flush=True)

    def systemctl(verb, unit):
        # bounded so a stuck unit cannot stretch the cleanup (torque OFF already ran before the restarts)
        done = subprocess.run(["systemctl", "--user", verb, unit], capture_output=True, text=True, timeout=10)
        return done.stdout.strip()

    def run(command):
        """The recorder in its own session: our Ctrl-C/SIGTERM/SIGHUP reaches it only as one SIGINT,
        with 10 s to save the episode, then it is killed."""
        child = subprocess.Popen(command, start_new_session=True, preexec_fn=interrupt_on_parent_death)
        try:
            return child.wait()
        except KeyboardInterrupt:
            with no_interrupts():
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            raise

    protect_signals()
    session = Session(open_bus=lambda which: SerialBus(ports[which], 0), systemctl=systemctl, run=run, log=log)
    lock = session_lock()
    record = {}
    try:
        record = session.execute(args.config, caps, teleop_only=args.teleop_only, task_card=args.task_card)
    finally:
        lock.close()
        if record:
            Path("session.json").write_text(json.dumps(record, indent=2, default=str))
    if not record.get("safe_end"):
        raise SystemExit("UNSAFE END: follower torque or caps not confirmed restored - see session.json")
    raise SystemExit(record.get("exit_code") or 0)


if __name__ == "__main__":
    main()
