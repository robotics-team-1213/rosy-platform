#!/usr/bin/env python3
"""One leader→follower LeRobot session with the follower's power caps raised only for its duration.

Single Responsibility:
  - `Session`: Validate follower idle state, reboot leader alerts, write/restore session caps, hand over camera units,
    and confirm follower/leader torque OFF at session end.
  - Task-card/pair helpers (`record_session_helpers.py`) and CLI (`record_session_cli.py`) are re-exported unchanged.
"""
from __future__ import annotations

import argparse  # noqa: F401
import hashlib
import json
import os  # noqa: F401
from pathlib import Path
import re
import signal  # noqa: F401
import subprocess  # noqa: F401
import sys
import time
from uuid import uuid4  # noqa: F401

from joint_tune import BASELINE, FOLLOWER, SerialBus, no_interrupts, protect_signals, session_lock  # noqa: F401
from record_config import validate_config
import record_session_cli as _rsc
from record_session_helpers import (  # noqa: F401
    CARD_SCHEMA,
    STATIC_RANGE,
    build_session_command,
    compose,
    finish_pair_sessions,
    interrupt_on_parent_death,
    load_task_card,
    release as _release_for,
    static_episodes,
)
from session_caps import load_caps as load_caps, log_registers, model_tuning, register_dump, robot_tuning  # noqa: F401

SERVICES = (
    "rosy-omx-camera@top.service",
    "rosy-omx-camera@front.service",
    "rosy-omx-camera-view.service",
    "rosy-omx-camera-readiness.service",
)
BIMANUAL_SCRIPT = "bimanual_native.py"
CAMERA_UNIT = re.compile(r"rosy-omx-camera@[\w-]+\.service")
_rsc._REGISTER_GLOBALS(globals())
main = _rsc.main


LEADER_GRIPPER = 6
LEADER = range(1, 7)
TORQUE_OFF_DEADLINE_S = 30.0
SESSION_ONLY = ("p_gain", "i_gain", "profile_acc", "profile_vel")


def release() -> str | None:
    """The code commit these tools came from (RELEASE written by omx_autoupdate.py), if installed so."""
    return _release_for(__file__)


class Session:
    def __init__(
        self,
        *,
        open_bus,
        systemctl,
        run,
        log,
        sleep=time.sleep,
        clock=time.monotonic,
        replay=None,
        chunks=None,
        operating_profile=None,
    ) -> None:
        self.open_bus, self.systemctl, self.run_command, self.log = open_bus, systemctl, run, log
        self.sleep, self.clock, self.replay, self.chunks = sleep, clock, replay, chunks
        self.operating_profile = operating_profile
        self.hardware_faults = {}

    def handover_units(self):
        """Camera units first, then camera-view and readiness; reversed for stopping (dependents first)."""
        running = CAMERA_UNIT.findall(self.systemctl("list-units", "rosy-omx-camera@*") or "")
        return list(dict.fromkeys(SERVICES[:2] + tuple(running))) + list(SERVICES[2:])

    @staticmethod
    def command(config_path: Path, teleop_only: bool, *, body_only=False, replay: dict | None = None) -> list:
        """Both native CLI routes share the same guarded hardware runner."""
        return build_session_command(config_path, teleop_only, body_only=body_only, replay=replay, anchor_file=__file__)

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
                raise SystemExit(
                    f"follower {motor} not idle: model/mode {(model, mode)}, torque {torque}, error {error}"
                )
            caps = {name: bus.read(name) for name in self._cap_registers(motor)}
            if any(caps[name] != BASELINE[name] for name in caps):
                raise SystemExit(
                    f"follower {motor} caps {caps} are not the baseline: an earlier session did not restore "
                    "them - commissioning_limits.py --baseline (torque OFF) before recording"
                )

    def clear_leader_alerts(self, bus) -> list:
        """A sagging leader supply (3.6 V, 2026-10-24) latches input-voltage alerts: reboot torque-OFF ones once."""
        alerted = []
        for motor in LEADER:
            bus.motor = motor
            torque, alert = bus.alert()
            if alert:
                if torque:
                    raise SystemExit(f"leader {motor} reports a hardware alert with torque ON")
                bus.reboot()
                alerted.append(motor)
        if alerted:
            self.sleep(1.5)
            for motor in alerted:
                bus.motor = motor
                if bus.alert()[1]:
                    raise SystemExit(f"leader {motor} alert persists after reboot: check the leader supply")
        return alerted

    def _with_leader(self, action):
        bus = self.open_bus("leader")
        try:
            return action(bus)
        finally:
            bus.close()

    def baseline(self) -> dict:
        """What every session leaves: the commissioning caps, and any gain back to the value it found."""
        found = getattr(self, "found_gains", {})
        return {
            motor: {**{name: BASELINE[name] for name in self._cap_registers(motor)}, **found.get(motor, {})}
            for motor in FOLLOWER
        }

    def write_caps(self, bus, caps) -> None:
        for motor, values in caps.items():
            bus.motor = motor
            if bus.read("torque"):
                raise RuntimeError(f"follower {motor} torque ON: EEPROM caps not written")
            for name, value in values.items():
                if name in SESSION_ONLY:
                    self.found_gains = getattr(self, "found_gains", {})
                    self.found_gains.setdefault(motor, {})[name] = bus.read(name)
                bus.write(name, value)
                after = bus.read(name)
                self.log(step="cap", motor=motor, name=name, value=value, after=after)
                if after != value:
                    raise RuntimeError(f"follower {motor} {name} readback {after} != {value}")
                if name == "current_limit" and FOLLOWER[motor][1] == 5:
                    bus.write("goal_current", value)
                    self.log(step="cap", motor=motor, name="goal_current", value=value, after=bus.read("goal_current"))
        self.log(step="registers", when="caps written", registers=register_dump(bus, caps))

    def all_torque_off(self, bus) -> dict:
        state = {}
        for motor in FOLLOWER:
            bus.motor = motor
            try:
                bus.cleanup_write("torque", 0)
                state[motor] = bus.cleanup_read("torque")
                self.note_fault(bus)
            except Exception as exc:
                state[motor] = f"error: {exc}"
        return state

    def torque_off_until_confirmed(self) -> tuple[bool, dict]:
        """Retry, reopening the port each time (held by the recorder, re-enumerated), until all read torque 0."""
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
        """Attempt every cap independently (retrying transient bus timeouts)."""
        failures = []
        for motor, values in self.baseline().items():

            def restore(bus, motor=motor, values=values):
                bus.motor = motor
                for name, value in values.items():
                    write, read = (
                        (bus.write, bus.read) if name in SESSION_ONLY else (bus.cleanup_write, bus.cleanup_read)
                    )
                    for attempt in range(3):
                        try:
                            write(name, value)
                            after = read(name)
                            self.note_fault(bus)
                            if after != value:
                                raise RuntimeError(f"{name} readback {after} != {value}")
                            break
                        except Exception as exc:
                            if attempt == 2:
                                failures.append(f"follower {motor} {name}: {exc}")

            try:
                self._with_follower(restore)
            except Exception as exc:
                failures.append(f"follower {motor}: {exc}")
        return failures

    def execute(
        self, config_path: Path, caps: dict, *, teleop_only: bool, task_card: Path | None = None, body_only=False
    ) -> dict:
        if body_only and not teleop_only:
            raise ValueError("body-only mode is manual teleoperation only")
        record = {
            "config": str(config_path),
            "caps": caps,
            "teleop_only": teleop_only,
            "started": time.time(),
            "release": release(),
            "body_only": body_only,
        }
        if task_card is not None:
            text = task_card.read_bytes()
            record["task_card"] = {
                "path": str(task_card),
                "sha256": hashlib.sha256(text).hexdigest(),
                "text": text.decode("utf-8"),
            }
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8-sig")))
        if self.operating_profile:
            from cell_robot_profile import load

            self.operating_profile = Path(self.operating_profile).expanduser().resolve()
            profile = load(self.operating_profile, robot_config=config["robot"])
            record["operating_profile"] = profile["binding"]
        pairs = self.pair_sessions(config)
        for session in pairs.values():
            session._with_follower(session.check_idle)
        if pairs.get("single") is self:
            record["leader_rebooted"] = self._with_leader(self.clear_leader_alerts)
        stopped = []
        try:
            for session in pairs.values():
                session._with_follower(lambda bus, s=session: s.write_caps(bus, caps))
            for unit in () if self.chunks else reversed(self.handover_units()):
                if self.systemctl("is-active", unit) in ("active", "activating"):
                    self.systemctl("stop", unit)
                    stopped.append(unit)
            record["stopped_services"] = stopped
            if self.chunks:
                command = [
                    sys.executable,
                    str(Path(__file__).resolve().with_name("chunk_runner.py")),
                    f"--config={config_path}",
                    f"--library={self.chunks['library']}",
                    f"--io={self.chunks['io']}",
                ]
                if self.operating_profile:
                    command.append(f"--operating-profile={Path(self.operating_profile).expanduser().resolve()}")
                command += [
                    f"--{k.replace('_', '-')}={self.chunks[k]}"
                    for k in ("params", "load_model")
                    if self.chunks.get(k)
                ]
                record["source_mode"] = "scripted_teacher"
                record["chunks"] = self.chunks
            else:
                command = self.command(config_path, teleop_only, body_only=body_only, replay=self.replay)
            if self.replay is not None:
                record["source_mode"] = "scripted_teacher"
                record["replay"] = {k: self.replay[k] for k in ("path", "sha256", "segments", "source")}
                if not teleop_only:
                    record["episode_outcomes"] = [
                        {"episode": 0, "segment": "A", "outcome": "unknown"},
                        {"episode": 1, "segment": "B", "outcome": "unknown"},
                    ]
            self.log(step="run", command=command)
            try:
                record["exit_code"] = self.run_command(command)
            except KeyboardInterrupt:
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
        return {
            name: Session(
                open_bus=lambda which, arm=name: self.open_bus(arm + "." + which),
                systemctl=self.systemctl,
                run=self.run_command,
                log=self.log,
                sleep=self.sleep,
                clock=self.clock,
            )
            for name in ("arm_a", "arm_b")
        }

    def finish_pairs(self, record, stopped, pairs):
        finish_pair_sessions(self, record, stopped, pairs)

    def finish(self, record: dict, stopped: list) -> None:
        torque_ok, record["torque_after"] = self.torque_off_until_confirmed()
        try:
            leader = self.open_bus("leader")
            try:
                leader.motor = LEADER_GRIPPER
                leader.cleanup_write("torque", 0)
                self.note_fault(leader, leader=True)
                try:
                    record["leader_rebooted_after"] = self.clear_leader_alerts(leader)
                except SystemExit as exc:
                    record["leader_rebooted_after"] = f"error: {exc}"
                leader.motor = LEADER_GRIPPER
                record["leader_gripper_torque_after"] = leader.cleanup_read("torque")
            finally:
                leader.close()
        except Exception as exc:
            record["leader_gripper_torque_after"] = f"error: {exc}"
        log_registers(self, "stop", FOLLOWER)
        failures = self.restore_caps()
        record["caps_restored"] = not failures or failures
        record["torque_off_confirmed"], record["hardware_faults"] = torque_ok, self.hardware_faults
        record["manual_attention_required"] = (
            bool(self.hardware_faults)
            or not torque_ok
            or bool(failures)
            or record["leader_gripper_torque_after"] != 0
        )
        for unit in reversed(stopped):
            try:
                self.systemctl("start", unit)
            except Exception as exc:
                record.setdefault("service_errors", []).append(f"{unit}: {exc}")
        record["restarted_services"] = stopped
        record["safe_end"] = (
            torque_ok
            and not failures
            and not self.hardware_faults
            and record["leader_gripper_torque_after"] == 0
        )
        record["ended"] = time.time()
        self.log(step="session", **record)
        if not record["safe_end"]:
            self.log(
                step="UNSAFE_END",
                torque_after=record["torque_after"],
                caps_restored=record["caps_restored"],
                hardware_faults=self.hardware_faults,
                action="manual attention required: keep torque OFF, verify caps and diagnose latched faults before restart",
            )


if __name__ == "__main__":  # session_lock(args.lock_file) via record_session_helpers.main
    main()
