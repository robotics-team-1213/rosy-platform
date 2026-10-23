#!/usr/bin/env python3
"""Drive the OMX Leader as a commanded reference arm, bounded like the Follower guard.

The Leader is the device a person holds, so it is only driven under an explicit hands-off
attestation and never faster than the Follower's alignment ramp. This module owns one
Leader bus: it reads the resting caps, raises them for the run with torque OFF, enables
torque on the body joints only, ramps goal positions toward a target, and on every exit
path turns torque off and writes back the caps, profiles and gains it found.

The gripper stays passive. Nothing here opens a second bus and nothing here touches the
Follower: the Follower guard keeps that authority (D-846).

  leader_actuator.py is used by two_arm_pipeline.py; the caps, rate and stop rules live here.
"""
from __future__ import annotations

import math
import time

TURN = 4096
TICKS_PER_DEGREE = TURN / 360
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
#: The Leader body motors are XL330-M288, so PWM Limit (36) and Current Limit (38) both exist.
CAP_MAX = 400
CURRENT_MAX = 275
#: Default run caps. The Leader is a light arm that a person holds, so it starts well below
#: the Follower's working caps; the pipeline may raise them only up to CAP_MAX/CURRENT_MAX.
DEFAULT_PWM = 150
DEFAULT_CURRENT = 100
#: The Leader never moves faster than the Follower's alignment ramp (1 degree/s) and never
#: accelerates faster than the Follower's tracking acceleration (10 degree/s^2).
RATE_DEG_S = 1.0
ACCEL_DEG_S2 = 10.0
#: A joint is "loaded" when it holds more than this much error at this much of its PWM cap.
LOADED_ERROR_DEG = 2.0
LOADED_PWM_FRACTION = 0.9
#: How long the load must persist before the run stops.
LOADED_SECONDS = 1.0
#: The cap registers and RAM registers this module writes, with their sizes.
CAP_REGISTERS = ("PWM_Limit", "Current_Limit")
PROFILE_REGISTERS = ("Profile_Velocity", "Profile_Acceleration")
#: Position gains are RAM registers too: the Leader's factory P is low enough that a loaded
#: joint stops short of its goal, so a run may state a gain and the module restores it.
GAIN_REGISTERS = ("Position_P_Gain", "Position_I_Gain")
#: A position-only loop trades position error for holding torque, so a Leader shoulder that
#: carries its own weight settles short of the pose and the run never sees it arrive. A static
#: gravity bias adds that error back to the written goal only: the ramp, the load stop and the
#: arrival check keep using the unbiased command, so the bias cannot hide a blocked joint.
#: The value is ticks at the drive pose and is capped well below the calibrated range.
GRAVITY_MAX_TICKS = 120


class LeaderActuator:
    """One Leader bus driven under caps and restored on every exit.

    The bus is a LeRobot dynamixel bus; only the body joints are ever touched and the
    gripper is never enabled. `admit` is the only place that raises the caps, and it does
    so with torque OFF and reads every write back.
    """

    def __init__(self, bus, *, clock=time.monotonic, log=None, label="leader"):
        self.bus = bus
        self.clock = clock
        self.log = log or (lambda **row: None)
        self.label = label
        self.saved: dict[str, dict[str, int]] = {}
        self.pwm_limits: dict[str, int] = {}
        self.gravity: dict[str, int] = {}
        self.command: dict[str, float] | None = None
        self.velocity = dict.fromkeys(BODY, 0.0)
        self.loaded_since: dict[str, float | None] = dict.fromkeys(BODY)
        self.failed = False

    # ------------------------------------------------------------------ admission

    def admit(self, *, pwm=DEFAULT_PWM, current=DEFAULT_CURRENT, gains=None, gravity=None) -> dict:
        """Read the resting state, then raise the caps and disable the vendor profile.

        Torque must be OFF everywhere and no joint may carry a hardware error. The caps, the
        profile registers and the requested position gains are written with torque OFF and
        read back; the values that were found are kept for `restore`. The gravity bias is not
        a motor register: it is applied to each written goal by `write`.
        """
        if not 1 <= pwm <= CAP_MAX or not 1 <= current <= CURRENT_MAX:
            raise ValueError(f"leader caps must be 1..{CAP_MAX} PWM and 1..{CURRENT_MAX} current")
        for name, ticks in (gravity or {}).items():
            if name not in BODY:
                raise ValueError(f"leader gravity bias names no body joint: {name}")
            if not isinstance(ticks, int) or isinstance(ticks, bool):
                raise ValueError(f"leader gravity bias for {name} must be an integer of ticks")
            if not 0 <= ticks <= GRAVITY_MAX_TICKS:
                raise ValueError(f"leader gravity bias for {name} must be 0..{GRAVITY_MAX_TICKS} ticks")
        self.gravity = dict(gravity or {})
        for name in BODY:
            if self.bus.read("Torque_Enable", name):
                raise ValueError(f"{self.label} {name}: torque is ON; admission needs torque OFF")
            error = self.bus.read("Hardware_Error_Status", name)
            if error:
                raise ValueError(f"{self.label} {name}: hardware error {error} latched; "
                                 "power-cycle the arm, then re-run admission")
            self.saved[name] = {register: self.bus.read(register, name)
                                 for register in CAP_REGISTERS + PROFILE_REGISTERS + GAIN_REGISTERS}
        for name in BODY:
            self._write("PWM_Limit", name, pwm)
            self._write("Current_Limit", name, current)
            # The vendor profile is disabled so the host ramp owns the motion (D-770 family).
            self._write("Profile_Velocity", name, 0)
            self._write("Profile_Acceleration", name, 0)
            for key, register in (("p", "Position_P_Gain"), ("i", "Position_I_Gain")):
                if gains and name in gains and key in gains[name]:
                    self._write(register, name, gains[name][key])
            self.pwm_limits[name] = pwm
        self.log(step="admit", label=self.label, pwm=pwm, current=current,
                 saved={name: dict(values) for name, values in self.saved.items()})
        return {"pwm": pwm, "current": current}

    def _write(self, register: str, name: str, value: int) -> None:
        self.bus.write(register, name, value)
        after = self.bus.read(register, name)
        if after != value:
            raise RuntimeError(f"{self.label} {name}: {register} readback {after} != {value}")

    # ------------------------------------------------------------------ motion

    def enable(self) -> None:
        """Enable torque on the body joints only; the gripper stays passive."""
        if self.bus.read("Torque_Enable", "gripper"):
            raise ValueError(f"{self.label}: the gripper must stay passive")
        self.bus.enable_torque(list(BODY))
        for name in BODY:
            if not self.bus.read("Torque_Enable", name):
                raise RuntimeError(f"{self.label} {name}: torque enable readback failed")

    def seed(self, current: dict[str, int]) -> dict[str, int]:
        """Start the ramp from the present position so the first goal is continuous."""
        self.command = {name: float(current[name]) for name in BODY}
        self.velocity = dict.fromkeys(BODY, 0.0)
        self.loaded_since = dict.fromkeys(BODY)
        return dict(self.command)

    def step(self, target: dict[str, float], elapsed: float) -> dict[str, float]:
        """One ramped step toward the target; returns the goal to write.

        The step size is bounded by the rate limit and the braking distance, so a target
        that moves away cannot make the Leader run away from it.
        """
        if self.command is None:
            raise ValueError("seed before stepping")
        if elapsed <= 0:
            raise ValueError("a step needs a positive elapsed time")
        acceleration = ACCEL_DEG_S2 * TICKS_PER_DEGREE
        limit = RATE_DEG_S * TICKS_PER_DEGREE
        command = {}
        for name in BODY:
            error = target[name] - self.command[name]
            brake = math.sqrt((acceleration * elapsed) ** 2 + 2 * acceleration * abs(error)) - acceleration * elapsed
            desired = math.copysign(min(limit, brake), error)
            change = max(-acceleration * elapsed, min(acceleration * elapsed, desired - self.velocity[name]))
            self.velocity[name] = self.velocity[name] + change
            command[name] = self.command[name] + self.velocity[name] * elapsed
        self.command = command
        return command

    def write(self, command: dict[str, float]) -> None:
        """Write the ramped goal to the Leader, plus any static gravity bias.

        The bias is added here and nowhere else: `self.command` stays the unbiased ramp, so the
        load stop and the caller's arrival check still measure the pose the run asked for.
        """
        goals = {}
        for name, value in command.items():
            goal = int(value) + self.gravity.get(name, 0)
            calibration = self.bus.calibration[name]
            if not calibration.range_min <= goal <= calibration.range_max:
                raise ValueError(f"{self.label} {name}: goal {goal} outside the calibrated range")
            goals[name] = goal
        self.bus.sync_write("Goal_Position", goals, normalize=False)

    def check_effort(self, current: dict[str, int]) -> None:
        """Stop the run when a joint holds its load at the cap.

        This is the Leader's version of the Follower guard's overload rule: an error that
        persists at most of the PWM cap means the arm is blocked, not that it is slow.
        """
        now = self.clock()
        for name in BODY:
            pwm = self.bus.read("Present_PWM", name)
            if not isinstance(pwm, (int, float)) or not math.isfinite(pwm):
                raise ValueError(f"{self.label} {name}: PWM read is not a number")
            error = abs(current[name] - int(self.command[name])) / TICKS_PER_DEGREE
            limit = self.pwm_limits.get(name)
            loaded = (limit is not None and error > LOADED_ERROR_DEG
                      and abs(pwm) >= LOADED_PWM_FRACTION * limit)
            since = now if loaded else None
            if loaded and self.loaded_since.get(name) is None:
                self.loaded_since[name] = now
            elif not loaded:
                self.loaded_since[name] = None
            since = self.loaded_since.get(name)
            if since is not None and now - since >= LOADED_SECONDS - 1e-9:
                raise ValueError(f"{self.label} {name}: blocked at the cap; PWM={pwm} limit={limit} "
                                 f"error_deg={error:.2f} duration={now - since:.2f}s")

    def read_positions(self) -> dict[str, int]:
        return self.bus.sync_read("Present_Position", normalize=False)

    # ------------------------------------------------------------------ ending

    def restore(self) -> list[str]:
        """Torque OFF, then the caps and profiles that were found; every step is tried.

        Returns the failures instead of raising, so the caller can report an unsafe end.
        """
        failures = []
        try:
            self.bus.disable_torque(list(BODY))
        except Exception as exc:  # keep restoring the other registers
            failures.append(f"torque OFF: {exc}")
        for name, values in self.saved.items():
            for register, value in values.items():
                try:
                    self._write(register, name, value)
                except Exception as exc:
                    failures.append(f"restore {name} {register}={value}: {exc}")
        self.log(step="restore", label=self.label, failures=failures)
        return failures
