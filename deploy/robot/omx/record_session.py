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
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

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
        self.hardware_faults = {}

    @staticmethod
    def command(config_path: Path, teleop_only: bool, *, body_only=False) -> list:
        """Both native CLI routes share the same guarded hardware runner."""
        if body_only and not teleop_only:
            raise ValueError("body-only mode is manual teleoperation only")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        script = "bimanual_native.py" if config["robot"]["type"] == "bi_omx_follower" else "guarded_native.py"
        runner = [sys.executable, str(Path(__file__).with_name(script))]
        if script == "bimanual_native.py":
            # Concrete OMX child types avoid recursive CLI choice discovery; only parents need tags.
            for section in ("robot", "teleop"):
                for arm in ("arm_a", "arm_b"):
                    config[section][arm].pop("type")
            native = config_path.with_name(config_path.stem + ".native.json")
            native.write_text(json.dumps(config, indent=2))
            config_path = native
        if not teleop_only:
            return [*runner, "record", f"--config_path={config_path}"]
        teleop = config_path.with_name(config_path.stem + ".teleop.json")
        teleop.write_text(json.dumps({"robot": config["robot"], "teleop": config["teleop"],
                                      "fps": config["dataset"]["fps"], "display_data": False}, indent=2))
        return [*runner, "teleoperate", f"--config_path={teleop}", *(["--body-only"] if body_only else [])]

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
                bus.cleanup_write("torque", 0)
                state[motor] = bus.cleanup_read("torque")
                self.note_fault(bus)
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

    def note_fault(self, bus, *, leader=False):
        error = bus.cleanup_read("hw_error")
        alert = getattr(bus, "cleanup_alerts", {}).get(bus.motor, False)
        if error or alert:
            key = f"leader {bus.motor}" if leader else bus.motor
            self.hardware_faults[key] = {"hw_error": error, "packet_alert": alert}

    def restore_caps(self) -> list:
        """Attempt every cap independently, including after a faulted motor's OFF confirmation."""
        failures = []
        for motor, values in self.baseline().items():
            def restore(bus, motor=motor, values=values):
                bus.motor = motor
                for name, value in values.items():
                    try:
                        bus.cleanup_write(name, value)
                        after = bus.cleanup_read(name)
                        self.note_fault(bus)
                        if after != value:
                            raise RuntimeError(f"{name} readback {after} != {value}")
                    except Exception as exc:
                        failures.append(f"follower {motor} {name}: {exc}")
            try:
                self._with_follower(restore)
            except Exception as exc:
                failures.append(f"follower {motor}: {exc}")
        return failures

    def execute(self, config_path: Path, caps: dict, *, teleop_only: bool, task_card: Path | None = None,
                body_only=False) -> dict:
        if body_only and not teleop_only:
            raise ValueError("body-only mode is manual teleoperation only")
        record = {"config": str(config_path), "caps": caps, "teleop_only": teleop_only, "started": time.time(),
                  "release": release(), "body_only": body_only}
        if task_card is not None:
            text = task_card.read_bytes()
            record["task_card"] = {"path": str(task_card), "sha256": hashlib.sha256(text).hexdigest(),
                                   "text": text.decode("utf-8")}
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8-sig")))
        pairs = self.pair_sessions(config)
        for session in pairs.values():
            session._with_follower(session.check_idle)
        stopped = []
        try:
            for session in pairs.values():
                session._with_follower(lambda bus, s=session: s.write_caps(bus, caps))
            for unit in SERVICES:
                if self.systemctl("is-active", unit) == "active":
                    self.systemctl("stop", unit)
                    stopped.append(unit)
            record["stopped_services"] = stopped
            command = self.command(config_path, teleop_only, body_only=body_only)
            self.log(step="run", command=command)
            try:
                record["exit_code"] = self.run_command(command)
            except KeyboardInterrupt:  # Ctrl-C/SIGTERM/SIGHUP: the normal end of a teleop-only session
                record["interrupted"] = True
        finally:
            with no_interrupts():
                if pairs.get("single") is self:
                    self.finish(record, stopped)
                else:
                    self.finish_pairs(record, stopped, pairs)
        return record

    def pair_sessions(self, config):
        if config["robot"]["type"] != "bi_omx_follower":
            return {"single": self}
        return {name: Session(open_bus=lambda which, arm=name: self.open_bus(arm + "." + which),
                              systemctl=self.systemctl, run=self.run_command, log=self.log,
                              sleep=self.sleep, clock=self.clock) for name in ("arm_a", "arm_b")}

    def finish_pairs(self, record, stopped, pairs):
        # Reach every follower before one disconnected USB consumes its retry deadline.
        record["initial_torque_off"] = {}
        for name, session in pairs.items():
            try:
                record["initial_torque_off"][name] = session._with_follower(session.all_torque_off)
            except Exception as exc:
                record["initial_torque_off"][name] = str(exc)
        leader_errors = []
        for name, session in pairs.items():
            try:
                bus = session.open_bus("leader")
                try:
                    for motor in range(1, 7):
                        bus.motor = motor
                        try:
                            bus.cleanup_write("torque", 0)
                            session.note_fault(bus, leader=True)
                            if bus.cleanup_read("torque") != 0:
                                raise RuntimeError("torque OFF readback mismatch")
                        except Exception as exc:
                            leader_errors.append(f"{name} leader {motor}: {exc}")
                finally:
                    bus.close()
            except Exception as exc:
                leader_errors.append(f"{name} leader: {exc}")
        record["pairs"] = {}
        for name, session in pairs.items():
            state = record["pairs"][name] = {}
            try:
                session.finish(state, [])
            except Exception as exc:
                state.update(safe_end=False, cleanup_error=str(exc))
        for unit in stopped:
            try:
                self.systemctl("start", unit)
            except Exception as exc:
                record.setdefault("service_errors", []).append(f"{unit}: {exc}")
        record["restarted_services"] = stopped
        record["leader_torque_errors"] = leader_errors
        record["safe_end"] = not leader_errors and all(
            state.get("safe_end") and state.get("leader_gripper_torque_after") == 0
            for state in record["pairs"].values())
        record["ended"] = time.time()
        self.log(step="session", **record)

    def finish(self, record: dict, stopped: list) -> None:
        torque_ok, record["torque_after"] = self.torque_off_until_confirmed()
        try:
            leader = self.open_bus("leader")
            try:
                leader.motor = LEADER_GRIPPER
                leader.cleanup_write("torque", 0)
                record["leader_gripper_torque_after"] = leader.cleanup_read("torque")
                self.note_fault(leader, leader=True)
            finally:
                leader.close()
        except Exception as exc:
            record["leader_gripper_torque_after"] = f"error: {exc}"
        failures = self.restore_caps()
        record["caps_restored"] = not failures or failures
        record["torque_off_confirmed"] = torque_ok
        record["hardware_faults"] = self.hardware_faults
        record["manual_attention_required"] = (bool(self.hardware_faults) or not torque_ok or bool(failures)
                                               or record["leader_gripper_torque_after"] != 0)
        for unit in stopped:
            try:
                self.systemctl("start", unit)
            except Exception as exc:
                record.setdefault("service_errors", []).append(f"{unit}: {exc}")
        record["restarted_services"] = stopped
        record["safe_end"] = (torque_ok and not failures and not self.hardware_faults
                              and record["leader_gripper_torque_after"] == 0)
        record["ended"] = time.time()
        self.log(step="session", **record)
        if not record["safe_end"]:
            self.log(step="UNSAFE_END", torque_after=record["torque_after"], caps_restored=record["caps_restored"],
                     hardware_faults=self.hardware_faults,
                     action="manual attention required: keep torque OFF, verify caps and diagnose latched faults before restart")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--caps", required=True, type=Path)
    parser.add_argument("--teleop-only", action="store_true")
    parser.add_argument("--body-only", action="store_true", help="manual body joints only; grippers remain passive")
    parser.add_argument("--task-card", type=Path, help="task design card to embed in session.json")
    args = parser.parse_args(argv)
    if args.body_only and not args.teleop_only:
        parser.error("--body-only requires --teleop-only")
    caps = load_caps(args.caps)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if args.task_card is not None:
        card = load_task_card(args.task_card)
        config = compose(config, card, stamp=time.strftime("%Y%m%d-%H%M%S"))
        args.config = args.config.with_name(f"{args.config.stem}.{card['task_id']}.json")
        args.config.write_text(json.dumps(config, indent=2))
    if config["robot"]["type"] == "bi_omx_follower":
        ports = {arm + "." + role: config[section][arm]["port"] for arm in ("arm_a", "arm_b")
                 for role, section in (("follower", "robot"), ("leader", "teleop"))}
    else:
        ports = {"follower": config["robot"]["port"], "leader": config["teleop"]["port"]}
    out = Path("session.jsonl")
    monitor_path = Path(f"motor-health-{time.time_ns()}.jsonl").absolute()
    monitor_state = Path(os.environ.get('ROSY_OMX_MONITOR_STATE', 'motor-health-current.json')).absolute()
    monitor_owner = config['robot']['id']
    monitor_session = str(uuid4())

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
        child = subprocess.Popen(command, start_new_session=True, preexec_fn=interrupt_on_parent_death,
                                 env={**os.environ, "ROSY_OMX_MONITOR_LOG": str(monitor_path),
                                      'ROSY_OMX_MONITOR_STATE': str(monitor_state),
                                      'ROSY_OMX_MONITOR_OWNER': monitor_owner,
                                      'ROSY_OMX_MONITOR_SESSION': monitor_session})
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
        record = session.execute(args.config, caps, teleop_only=args.teleop_only, task_card=args.task_card,
                                 body_only=args.body_only)
    finally:
        try:
            from motor_health import finish_snapshot
            finish_snapshot(monitor_state, monitor_owner, monitor_session, safe_end=bool(record.get('safe_end')))
        except Exception as exc:
            record['motor_health_snapshot_error'] = str(exc)
        finally:
            lock.close()
        if record:
            record["motor_health_log"] = str(monitor_path)
            record["motor_health_log_created"] = monitor_path.is_file()
            record['motor_health_state'] = str(monitor_state)
            record['motor_health_owner'] = monitor_owner
            record['motor_health_session'] = monitor_session
            Path("session.json").write_text(json.dumps(record, indent=2, default=str))
    if not record.get("safe_end"):
        raise SystemExit("UNSAFE END: follower torque or caps not confirmed restored - see session.json")
    raise SystemExit(record.get("exit_code") or 0)


if __name__ == "__main__":
    main()
