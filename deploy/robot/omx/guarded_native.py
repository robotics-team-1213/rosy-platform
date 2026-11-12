#!/usr/bin/env python3
"""Native LeRobot Real-Time Joint Motion, Alignment, Following-Error & Effort Guard (`guarded_native.py`).

Single Responsibility:
  - `NativeJointMotion`: Seeds follower pose before enabling torque, enforces 1 deg/s alignment and
    10 deg/s, 10 deg/s^2 tracking slew bounds, 5-degree following-error cutoff, hardware-error checks,
    and single-use overload-hold (`HOLD_S`, `HOLD_TEMP_RISE_C`).
  - Device bring-up helpers (`guarded_device.py`) and LeRobot factory/CLI wiring (`guarded_native_cli.py`)
    are re-exported here unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import time

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from guarded_device import (  # noqa: E402,F401  (re-exported: existing importers unchanged)
    BODY,
    HOLD_S,
    HOLD_TEMP_RISE_C,
    MAX_GAP_S,
    MAX_STEP_S,
    NAMES,
    PROFILE,
    PROFILE_ACC,
    PROFILE_VEL,
    PWM_ADMIT_MAX,
    READ_RETRY,
    SEED_TOLERANCE_TICKS,
    TICKS_PER_DEGREE,
    TURN,
    close_device,
    connect_passive,
    finite_values,
    normalized,
    torque_off,
)
from guarded_native_cli import main, run_native  # noqa: E402,F401  (re-exported)


class NativeJointMotion:
    def __init__(
        self,
        follower,
        leader,
        *,
        clock=time.monotonic,
        body_only=False,
        label="follower",
        monitor=None,
        offsets=None,
        teacher=False,
        shed_load=False,
    ):
        if teacher != (leader is None) or (teacher and body_only):
            raise ValueError("teacher mode streams all six joints and has no leader")
        self.follower, self.leader, self.clock = follower, leader, clock
        self.body_only, self.teacher = body_only, teacher
        self.active = BODY if body_only else NAMES
        self.label = label
        self.offsets = offsets
        self.velocity = dict.fromkeys(self.active, 0.0)
        self.tracking = False
        self.aligned_since = None
        self.last_alignment_report = None
        self.last_time = None
        self.command = None
        self.failed = False
        self.pwm_limits = None
        self.effort_pwm = {}
        self.effort_since = dict.fromkeys(BODY)
        self.held, self.held_once, self.shed_load = {}, set(), shed_load
        self.last_effort_time = None
        self.last_present = None
        self.prev_target = None
        self.alignment_deadline = None
        self.monitor = monitor
        self.monitor_admitted = False

    def send(self, action):
        try:
            if self.failed:
                raise ValueError("guard stopped; restart the session")
            return self.commit(self.prepare(action))
        except BaseException as exc:
            self.failed = True
            try:
                torque_off(self.follower)
            finally:
                self.report_fault(exc)
            raise

    def report_fault(self, exc):
        """Call only after torque OFF attempts; logging must preserve the control failure."""
        if self.monitor is not None:
            try:
                self.monitor.fault(self, exc)
            except BaseException:
                pass

    def prepare(self, action):
        """Validate and seed without enabling torque, so both arms can be admitted together."""
        if self.failed:
            raise ValueError("guard stopped; restart the session")
        finite_values(action, [n + ".pos" for n in NAMES])
        started = self.clock()
        if self.last_time is not None and not 0 <= started - self.last_time <= MAX_GAP_S:
            raise ValueError("stale control loop (>0.5 seconds)")
        if self.teacher:
            ids = {self.follower.motors[n].id: n for n in NAMES}
            raw = self.follower._unnormalize({self.follower.motors[n].id: action[n + ".pos"] for n in NAMES})
            leader = {ids[i]: v for i, v in raw.items()}
        else:
            leader = self.leader.sync_read("Present_Position", normalize=False, num_retry=READ_RETRY)
        current = self.follower.sync_read("Present_Position", normalize=False, num_retry=READ_RETRY)
        finite_values(leader, NAMES)
        finite_values(current, NAMES)
        self.last_present = normalized(self.follower, current)
        if self.body_only and self.follower.read("Torque_Enable", "gripper"):
            raise ValueError("passive gripper torque must remain OFF")
        if self.command is not None:
            for name in BODY if self.teacher else self.active:
                sent = int(self.command[name])
                if abs(current[name] - sent) > 5 * TICKS_PER_DEGREE + 1e-9:
                    raise ValueError(f"{name}: following error >5 motor degrees; command={sent}, current={current[name]}")
        if self.offsets is None:
            self.offsets = (
                dict.fromkeys(BODY, 0)
                if self.teacher
                else {n: TURN * round((current[n] - leader[n]) / TURN) for n in BODY}
            )
        target = {n: leader[n] + self.offsets[n] for n in BODY}
        for name in BODY:
            if abs(target[name] - current[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
                raise ValueError(
                    f"{name}: difference >=100 degrees; leader={leader[name]}, "
                    f"target={target[name]}, current={current[name]}, offset={self.offsets[name]}, "
                    f"previous_command={self.command}; align manually with torque OFF"
                )
        for bus, values in (() if self.teacher else ((self.leader, {**target, "gripper": leader["gripper"]}),)) + (
            (self.follower, current),
        ):
            for name, value in values.items():
                calibration = bus.calibration[name]
                if not calibration.range_min <= value <= calibration.range_max:
                    raise ValueError(f"{name}: outside calibrated range")
        if self.teacher:
            target["gripper"] = leader["gripper"]
        elif not self.body_only:
            grip = normalized(self.leader, {"gripper": leader["gripper"]})["gripper.pos"]
            grip_id = self.follower.motors["gripper"].id
            target["gripper"] = self.follower._unnormalize({grip_id: grip})[grip_id]
        for name, value in target.items():
            calibration = self.follower.calibration[name]
            if not calibration.range_min <= value <= calibration.range_max:
                raise ValueError(f"{name}: target outside follower calibrated range")
        if not self.body_only and abs(target["gripper"] - current["gripper"]) >= 100 * TICKS_PER_DEGREE - 1e-9:
            raise ValueError("gripper motor travel >=100 degrees; align manually with torque OFF")
        self._check_hardware_errors()
        if self.pwm_limits is None:
            use_sync = "read" not in vars(self.follower) and hasattr(self.follower, "model_ctrl_table")
            torques = (
                self.follower.sync_read("Torque_Enable", list(BODY), normalize=False, num_retry=READ_RETRY)
                if use_sync
                else None
            )
            raw_limits = (
                self.follower.sync_read("PWM_Limit", list(BODY), normalize=False, num_retry=READ_RETRY)
                if use_sync
                else None
            )
            limits = {}
            for name in BODY:
                if torques[name] if torques is not None else self.follower.read("Torque_Enable", name):
                    raise ValueError(f"{name}: PWM_Limit admission requires torque OFF")
                limit = raw_limits[name] if raw_limits is not None else self.follower.read("PWM_Limit", name)
                if not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 0 < limit <= PWM_ADMIT_MAX[name]:
                    raise ValueError(f"{name}: invalid PWM_Limit {limit}")
                limits[name] = limit
            self.pwm_limits = limits
        if self.monitor is not None and not self.monitor_admitted:
            self.monitor.admit(self)
            self.monitor_admitted = True
        if self.command is not None:
            self._check_effort(current, started)
        now = self.clock()
        if not 0 <= now - started <= MAX_GAP_S:
            raise ValueError("stale joint sample (>0.5 seconds)")
        if self.last_time is not None and not 0 <= now - self.last_time <= MAX_GAP_S:
            raise ValueError("stale control loop including sampling (>0.5 seconds)")
        if self.command is None:
            deadline = started + min(
                105, max(5, max(abs(target[n] - current[n]) for n in BODY) / TICKS_PER_DEGREE + 5)
            )
            current = self._seed({n: current[n] for n in self.active}, target, started)
            return {"started": started, "seed": current, "alignment_deadline": deadline, "target": dict(target)}
        elapsed = min(now - self.last_time, MAX_STEP_S)
        if self.body_only or self.teacher:
            command, state = self._body_command(target, current, elapsed, now)
            return {"started": started, "command": command, "time": now, "body_state": state, "target": dict(target)}
        step = elapsed * TICKS_PER_DEGREE
        frozen = self.frozen()
        command = {
            n: self.command[n]
            if n in frozen
            else self.command[n] + max(-step, min(step, target[n] - self.command[n]))
            for n in self.active
        }
        return {"started": started, "command": command, "time": now}

    def _check_hardware_errors(self):
        if "read" not in vars(self.follower) and hasattr(self.follower, "model_ctrl_table"):
            errors = self.follower.sync_read("Hardware_Error_Status", list(NAMES), normalize=False, num_retry=READ_RETRY)
            for name in NAMES:
                if errors[name]:
                    raise ValueError(f"{name}: hardware error")
            return
        for name in NAMES:
            if self.follower.read("Hardware_Error_Status", name):
                raise ValueError(f"{name}: hardware error")

    def _read_body_pwm(self):
        if "read" not in vars(self.follower) and hasattr(self.follower, "model_ctrl_table"):
            return self.follower.sync_read("Present_PWM", list(BODY), normalize=False, num_retry=READ_RETRY)
        return {name: self.follower.read("Present_PWM", name) for name in BODY}

    def _check_effort(self, current, started):
        before = self.clock()
        if self.last_effort_time is not None and before - self.last_effort_time < 0.2 - 1e-9:
            return
        pwm = self._read_body_pwm()
        finite_values(pwm, BODY)
        if self.monitor is not None:
            self.monitor.sample(self, current, pwm, self.clock())
        now = self.clock()
        if (
            not 0 <= now - started <= MAX_GAP_S
            or not 0 <= now - self.last_time <= MAX_GAP_S
            or (self.last_effort_time is not None and not 0 <= now - self.last_effort_time <= MAX_GAP_S)
        ):
            raise ValueError("stale effort sample (>0.5 seconds)")
        for name in BODY:
            saturated = abs(pwm[name]) >= 0.9 * self.pwm_limits[name]
            if name in self.held:
                self._watch_hold(name, saturated, pwm[name], now)
                continue
            error = abs(current[name] - int(self.command[name])) / TICKS_PER_DEGREE
            loaded = error > 2 and saturated
            since = self.effort_since[name] if loaded else None
            if loaded and since is None:
                since = now
            self.effort_since[name] = since
            if since is not None and now - since >= 1 - 1e-9:
                detail = (
                    f"{name}: overload risk; PWM={pwm[name]} limit={self.pwm_limits[name]} "
                    f"error_deg={error:.2f} duration={now - since:.2f}s"
                )
                if name in self.held_once:
                    raise ValueError(f"{detail}; second overload on this joint")
                self.command[name] = current[name]
                if name in self.velocity:
                    self.velocity[name] = 0.0
                self.held[name] = {
                    "since": now,
                    "saturated_since": now,
                    "temp": self.follower.read("Present_Temperature", name),
                }
                self.held_once.add(name)
                self.effort_since[name] = None
                print(
                    f"{self.label}: overload-hold {detail}; goal set to present, torque on, "
                    f"hold watch {HOLD_S:.0f} s",
                    flush=True,
                )
        self.effort_pwm, self.last_effort_time = pwm, now

    def _watch_hold(self, name, saturated, pwm, now):
        """A held joint: at the cap for HOLD_S in a row, or warming, ends the session. It never frees itself."""
        hold = self.held[name]
        rise = self.follower.read("Present_Temperature", name) - hold["temp"]
        if rise >= HOLD_TEMP_RISE_C:
            raise ValueError(
                f"{name}: overload risk; held joint warmed {rise} C at PWM={pwm} limit={self.pwm_limits[name]} "
                f"duration={now - hold['since']:.2f}s"
            )
        if not saturated:
            hold["saturated_since"] = None
            return
        if hold["saturated_since"] is None:
            hold["saturated_since"] = now
        if now - hold["saturated_since"] >= HOLD_S - 1e-9:
            raise ValueError(
                f"{name}: overload risk; hold timed out at PWM={pwm} limit={self.pwm_limits[name]} "
                f"duration={now - hold['since']:.2f}s"
            )

    def frozen(self):
        """Joints whose command stays put this tick: all of them while anything is held, unless the runner sheds load."""
        if not self.held:
            return ()
        return tuple(self.held) if self.shed_load else self.active

    def release_hold(self):
        """For a runner whose targets no longer push into the stall: streaming resumes toward the targets it sends next."""
        for name, hold in self.held.items():
            print(f"{self.label}: overload-hold released on {name} after {self.clock() - hold['since']:.2f}s", flush=True)
        self.held.clear()

    def _body_command(self, target, current, elapsed, now):
        tracking, since = self.tracking, self.aligned_since
        if not tracking and now >= self.alignment_deadline:
            raise ValueError(
                f"{self.label}: alignment deadline exceeded; current={current}, "
                f"target={target}, command={self.command}"
            )
        if not tracking and (self.last_alignment_report is None or now - self.last_alignment_report >= 1):
            actual_joint = max(self.active, key=lambda n: abs(current[n] - target[n]))
            command_joint = max(self.active, key=lambda n: abs(self.command[n] - target[n]))
            present_pwm = self.effort_pwm.get(actual_joint)
            pwm_limit = self.pwm_limits.get(actual_joint)
            print(
                f"{self.label}: phase=aligning; actual_joint={actual_joint} actual={current[actual_joint]} "
                f"target={target[actual_joint]} error_deg={abs(current[actual_joint] - target[actual_joint]) / TICKS_PER_DEGREE:.2f} "
                f"Present_PWM={present_pwm} PWM_Limit={pwm_limit}; "
                f"command_joint={command_joint} command={self.command[command_joint]} target={target[command_joint]} "
                f"error_deg={abs(self.command[command_joint] - target[command_joint]) / TICKS_PER_DEGREE:.2f}",
                flush=True,
            )
            self.last_alignment_report = now
        if not tracking:
            aligned = all(
                abs(target[n] - current[n]) <= 2.5 * TICKS_PER_DEGREE
                and abs(target[n] - self.command[n]) <= 0.5 * TICKS_PER_DEGREE
                for n in self.active
            )
            since = (now if since is None else since) if aligned else None
            tracking = since is not None and now - since >= 0.5 - 1e-9
        acceleration = 10 * TICKS_PER_DEGREE
        limit = (10 if tracking else 1) * TICKS_PER_DEGREE
        command, velocity = {}, {}
        frozen = self.frozen()
        for name in self.active:
            if name in frozen:
                command[name], velocity[name] = self.command[name], 0.0
                continue
            error = target[name] - self.command[name]
            brake = math.sqrt((acceleration * elapsed) ** 2 + 2 * acceleration * abs(error)) - acceleration * elapsed
            if self.teacher and tracking and self.prev_target is not None and elapsed > 0:
                v_ff = (target[name] - self.prev_target[name]) / elapsed
                if error * v_ff > 0:
                    reach = min(
                        abs(error) / elapsed,
                        math.sqrt(min(limit, abs(v_ff)) ** 2 + 2 * acceleration * abs(error)),
                    )
                    brake = max(brake, reach)
            desired = math.copysign(min(limit, brake), error)
            change = max(-acceleration * elapsed, min(acceleration * elapsed, desired - self.velocity[name]))
            velocity[name] = self.velocity[name] + change
            command[name] = self.command[name] + velocity[name] * elapsed
            calibration = self.follower.calibration[name]
            if not calibration.range_min <= command[name] <= calibration.range_max:
                raise ValueError(f"{name}: streamed command outside calibrated range")
        return command, (velocity, tracking, since)

    def commit(self, prepared):
        if self.body_only and self.follower.read("Torque_Enable", "gripper"):
            raise ValueError("passive gripper torque must remain OFF before body command")
        now = self.clock()
        if (
            self.failed
            or not 0 <= now - prepared["started"] <= MAX_GAP_S
            or (self.last_time is not None and not 0 <= now - self.last_time <= MAX_GAP_S)
        ):
            raise ValueError("stale or stopped prepared action")
        deadline = prepared.get("alignment_deadline", self.alignment_deadline)
        if self.body_only and not self.tracking and now >= deadline:
            raise ValueError(f"{self.label}: alignment deadline exceeded before command commit")
        if "seed" in prepared:
            if self.body_only:
                self.follower.enable_torque(list(BODY))
            else:
                self.follower.enable_torque()
            self.command = dict(prepared["seed"])
            self.prev_target = dict(prepared.get("target") or self.command)
            self.alignment_deadline = prepared["alignment_deadline"]
            self.last_time = self.clock()
            return normalized(self.follower, self.command)
        goals = {n: int(v) for n, v in prepared["command"].items()}
        self.follower.sync_write("Goal_Position", goals, normalize=False)
        self.command = prepared["command"]
        if "target" in prepared:
            self.prev_target = dict(prepared["target"])
        self.last_time = prepared["time"]
        if "body_state" in prepared:
            was_tracking = self.tracking
            self.velocity, self.tracking, self.aligned_since = prepared["body_state"]
            if self.tracking and not was_tracking:
                print(f"{self.label}: aligned; body tracking limit 10 deg/s, acceleration 10 deg/s^2", flush=True)
        return normalized(self.follower, goals)

    def _seed(self, current, target, started):
        """Seed at the present pose; one tick of readback jitter around a fixed origin is the same pose."""
        use_sync = "read" not in vars(self.follower) and hasattr(self.follower, "model_ctrl_table")
        origin = dict(current)
        for _ in range(3):
            self.follower.sync_write("Goal_Position", current, normalize=False)
            goals = self.follower.sync_read("Goal_Position", motors=list(self.active), normalize=False)
            fresh = self.follower.sync_read("Present_Position", motors=list(self.active), normalize=False)
            detail = f"initial goal readback mismatch: expected={current}, readback={goals}, fresh={fresh}"
            finite_values(goals, self.active)
            finite_values(fresh, self.active)
            hw_errs = (
                self.follower.sync_read("Hardware_Error_Status", list(self.active), normalize=False, num_retry=READ_RETRY)
                if use_sync
                else None
            )
            torques = (
                self.follower.sync_read("Torque_Enable", list(self.active), normalize=False, num_retry=READ_RETRY)
                if use_sync
                else None
            )
            for name in self.active:
                calibration = self.follower.calibration[name]
                if not calibration.range_min <= fresh[name] <= calibration.range_max:
                    raise ValueError(f"{name}: seed outside calibrated range; {detail}")
                if abs(target[name] - fresh[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
                    raise ValueError(f"{name}: seed difference >=100 degrees; {detail}")
                err = hw_errs[name] if hw_errs is not None else self.follower.read("Hardware_Error_Status", name)
                tq = torques[name] if torques is not None else self.follower.read("Torque_Enable", name)
                if err or tq:
                    raise ValueError(f"{name}: seed hardware error or torque ON; {detail}")
            if not 0 <= self.clock() - started <= MAX_GAP_S:
                raise ValueError(f"stale seed transaction (>0.5 seconds); {detail}")
            if any(
                abs(goals[n] - origin[n]) > SEED_TOLERANCE_TICKS or abs(fresh[n] - origin[n]) > SEED_TOLERANCE_TICKS
                for n in self.active
            ):
                raise ValueError(detail)
            if all(abs(goals[n] - fresh[n]) <= SEED_TOLERANCE_TICKS for n in self.active):
                self.last_present = normalized(self.follower, fresh)
                return goals
            current = fresh
        raise ValueError(detail)


if __name__ == "__main__":
    main()
