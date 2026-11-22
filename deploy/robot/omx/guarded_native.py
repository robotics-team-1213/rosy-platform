#!/usr/bin/env python3
"""Native LeRobot Real-Time Joint Motion, Alignment, Following-Error & Effort Guard (`guarded_native.py`).

Single Responsibility:
  - `NativeJointMotion`: Alignment & tracking slew bounds (1 deg/s alignment; tracking 10 deg/s body-only/teacher, 30 deg/s full arm; 10 deg/s^2 accel),
    5-degree following-error cutoff, and prepare/commit transaction pipeline.
  - Hardware-error, body PWM effort sampling, overload-hold watch, and seed verification live in
    `guarded_native_effort.py`.
  - Device bring-up (`guarded_device.py`) and LeRobot CLI (`guarded_native_cli.py`) are re-exported unchanged.
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
    ACCEL_DEG_S2,
    BRAKE_DEG_S2,
    BOUNDARY_MAX_S,
    BoundaryExpired,
    boundary_over,
    FULL_TRACK_DEG_S,
    LEAD_DEG,
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
    TRACK_DEG_S,
    TICKS_PER_DEGREE,
    TURN,
    close_device,
    connect_passive,
    finite_values,
    normalized,
    torque_off,
)
from guarded_native_cli import main, run_native  # noqa: E402,F401  (re-exported)
from guarded_native_track import body_command  # noqa: E402
from guarded_native_lag import LagModel, check_following, follows_far  # noqa: E402
from teleop_speed import STAGES, valid as valid_stage  # noqa: E402
from guarded_native_mount import GRIP_ENDS, check_floor, check_grip_map, check_mount  # noqa: E402,F401  (GRIP_ENDS, check_mount re-exported)
from guarded_native_effort import (  # noqa: E402
    check_effort,
    check_hardware_errors,
    read_body_pwm,
    alignment_deadline,
    restart_after_pause,
    stall_watch,
    seed_follower_pose,
    watch_hold,
)


class NativeJointMotion:
    stage = None

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
        mount=None,
        grip_map=None,
        follower_floor=None,
        stage=None,
    ):
        if teacher != (leader is None) or (teacher and body_only):
            raise ValueError("teacher mode streams all six joints and has no leader")
        self.follower, self.leader, self.clock = follower, leader, clock
        self.body_only, self.teacher = body_only, teacher
        self.stage = valid_stage(stage)  # teleop_speed stage of a full-arm Leader session, else None
        self.active = BODY if body_only else NAMES
        self.far = set()  # joints followed while 100+ degrees from the Leader (guarded_native_lag.follows_far)
        self.lag = LagModel(STAGES[self.stage]["tau_s"], STAGES[self.stage]["profile_vel"] * 1.374) if self.stage and not (teacher or body_only) else None
        self.label = label
        self.offsets = offsets
        # A Leader whose joint is assembled half a turn from the Follower's (arm_s pan, 2026-11-21) states it as a
        # commissioned constant; the 100 degree guard below then compares against that mapping, not a guess.
        self.mount = {} if mount is None else mount
        check_mount(self.mount)
        # The Leader trigger travels a few degrees; without a commissioned pair of ends its raw value lands past the
        # Follower's closed jaws (arm_s: trigger 1906..1983 mapped to 1938..2015, closed-empty is 2005).
        self.grip_map = check_grip_map(grip_map, leader, follower)
        # A Leader resting on its stand can sit below where the Follower can travel (arm_s lift: Leader 670..704, Follower
        # stops near 713): the declared floor keeps the target on the reachable side, so the motor is never pushed on its stop.
        self.floor = check_floor(follower_floor, follower)
        self.velocity = dict.fromkeys(self.active, 0.0)
        self.v_ff_ema = dict.fromkeys(BODY, 0.0)
        self.tracking = False
        self.aligned_since = None
        self.last_alignment_report = None
        self.last_time = None
        self.command = None
        self.sent = None
        self.failed = False
        self.pwm_limits = None
        self.effort_pwm = {}
        self.effort_since = dict.fromkeys(BODY)
        self.held, self.held_once, self.shed_load = {}, set(), shed_load
        self.squeeze = {}  # the gripper's own saturation clock while it squeezes a box (never a freeze, never a cut)
        self.grip_way = None  # after a relaxed squeeze: +1/-1 = the squeeze side of the jaws (no lead applied) until the trigger re-arms it
        self.last_effort_time = None
        self.last_present = None
        self.prev_target = None
        self.alignment_deadline = None
        self.monitor = monitor
        self.monitor_admitted = False
        self.boundary = self.resuming = self.grip_ready = False
        self.stall = {}

    def has_stall_hold(self):
        return any(hold.get("stall") for hold in self.held.values())

    def freeze_prepared(self, prepared):
        """The same tick, command unchanged (a bimanual peer holds): what a held arm would have sent."""
        if "command" not in prepared:
            return prepared
        state = prepared.get("body_state")
        return {**prepared, "command": dict(self.command),
                **({"body_state": (dict.fromkeys(self.active, 0.0), state[1], state[2])} if state else {})}

    @property
    def full_arm(self):
        return not (self.teacher or self.body_only)

    @property
    def track_deg_s(self):
        if self.teacher or self.body_only:
            return TRACK_DEG_S
        return STAGES[self.stage]["track_deg_s"] if self.stage else FULL_TRACK_DEG_S

    @property
    def brake_deg_s2(self):
        """Braking limit (slowing or reversing): scaled with the stage so a reversal overruns under 3 degrees at every speed (teleop_speed)."""
        return STAGES[self.stage]["brake_deg_s2"] if self.stage and self.full_arm else BRAKE_DEG_S2

    @property
    def align_deg_s(self):
        """Start alignment rate: a staged full-arm session aligns at ALIGN_DEG_S, everything else at 1 degree/s."""
        return STAGES[self.stage]["align_deg_s"] if self.stage and self.full_arm else 1

    @property
    def accel_deg_s2(self):
        """Command acceleration limit: the full-arm stage's value (teleop_speed), else ACCEL_DEG_S2."""
        return STAGES[self.stage]["accel_deg_s2"] if self.stage and self.full_arm else ACCEL_DEG_S2

    def send(self, action):
        try:
            if self.failed:
                raise ValueError("guard stopped; restart the session")
            return self.commit(self.prepare(action))
        except BoundaryExpired:
            self.failed = True  # no new motion; torque stays ON
            raise
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
        if self.boundary:  # set by run_native at a record loop start, used by that loop's first command only
            self.boundary = False
            if not self.teacher and self.last_time is not None and started - self.last_time > MAX_GAP_S:
                if boundary_over(self.last_time, started):  # never the stale cut after a declared boundary: failed, torque kept, session ends
                    raise BoundaryExpired("record loop pause longer than the bound: ending the session")
                restart_after_pause(self, started)
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
        if self.body_only and self.follower.read("Torque_Enable", "gripper", num_retry=READ_RETRY):
            raise ValueError("passive gripper torque must remain OFF")
        if self.command is not None:
            check_following(self, current, started)  # the legacy 5 degree test, or the servo model's (guarded_native_lag) in a staged full-arm session
        if self.offsets is None:
            self.offsets = (
                dict.fromkeys(BODY, 0)
                if self.teacher
                else {n: self.mount.get(n, 0) + TURN * round((current[n] - leader[n] - self.mount.get(n, 0)) / TURN)
                      for n in BODY}
            )
        mapped = {n: leader[n] + self.offsets[n] for n in BODY}
        # One place: every check and the commands below see the clipped target. Only toward what the Follower can reach,
        # so no check is loosened except that a Leader parked below the floor is judged (100 degrees) at the floor.
        target = {n: max(v, self.floor.get(n, v)) for n, v in mapped.items()}
        for name in () if self.has_stall_hold() else BODY:  # a stall hold is not following the Leader: the command is frozen, torque stays, the arm
            # holds; the comparison would only cut it. Release needs the Leader back within STALL_RELEASE_DEG, and the 100 degree test then applies again
            if max(abs(mapped[name] - current[name]), abs(target[name] - current[name])) >= 100 * TICKS_PER_DEGREE - 1e-9 and not follows_far(self, name, target):  # raw and floored
                raise ValueError(
                    f"{name}: difference >=100 degrees; leader={leader[name]}, "
                    f"target={target[name]}, current={current[name]}, offset={self.offsets[name]}, "
                    f"previous_command={self.command}; align manually with torque OFF"
                )
        for bus, values in (() if self.teacher else ((self.leader, {**mapped, "gripper": leader["gripper"]}),)) + (
            (self.follower, current),
        ):
            for name, value in values.items():
                calibration = bus.calibration[name]
                if not calibration.range_min <= value <= calibration.range_max:
                    raise ValueError(f"{name}: outside calibrated range")
        if self.teacher:
            target["gripper"] = leader["gripper"]
        elif not self.body_only:
            if self.grip_map:  # trigger fraction (clamped to its commissioned ends) onto the Follower's jaw ends
                ends = self.grip_map
                part = (leader["gripper"] - ends["leader_closed"]) / (ends["leader_open"] - ends["leader_closed"])
                target["gripper"] = round(ends["follower_closed"]
                                          + max(0.0, min(1.0, part)) * (ends["follower_open"] - ends["follower_closed"]))
            else:
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
                if torques[name] if torques is not None else self.follower.read("Torque_Enable", name, num_retry=READ_RETRY):
                    raise ValueError(f"{name}: PWM_Limit admission requires torque OFF")
                limit = raw_limits[name] if raw_limits is not None else self.follower.read("PWM_Limit", name, num_retry=READ_RETRY)
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
        if self.full_arm and self.command is not None:
            stall_watch(self, target, current, now, mapped)
        if self.resuming:  # after a declared pause: approach again from the held command
            self.resuming, self.alignment_deadline = False, alignment_deadline(started, target, current)
        if self.command is None:
            deadline = alignment_deadline(started, target, current)
            current = self._seed({n: current[n] for n in self.active}, target, started, mapped)
            return {"started": started, "seed": current, "alignment_deadline": deadline, "target": dict(target)}
        elapsed = min(now - self.last_time, MAX_STEP_S)
        command, state = self._body_command(target, current, elapsed, now)  # every mode: align at 1 deg/s, then track
        return {"started": started, "command": command, "time": now, "body_state": state, "target": dict(target)}

    def _check_hardware_errors(self):
        check_hardware_errors(self)

    def _read_body_pwm(self):
        return read_body_pwm(self)

    def _check_effort(self, current, started):
        check_effort(self, current, started)

    def _watch_hold(self, name, saturated, pwm, now, hold=None):
        watch_hold(self, name, saturated, pwm, now, hold)

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
        if self.full_arm:  # the stalled joint stood still while the target moved on: align again before tracking
            self.tracking, self.aligned_since, self.resuming = False, None, True

    def _body_command(self, target, current, elapsed, now):
        return body_command(self, target, current, elapsed, now)

    def commit(self, prepared):
        if self.body_only and self.follower.read("Torque_Enable", "gripper", num_retry=READ_RETRY):
            raise ValueError("passive gripper torque must remain OFF before body command")
        now = self.clock()
        if (
            self.failed
            or not 0 <= now - prepared["started"] <= MAX_GAP_S
            or (self.last_time is not None and not 0 <= now - self.last_time <= MAX_GAP_S)
        ):
            raise ValueError("stale or stopped prepared action")
        deadline = prepared.get("alignment_deadline", self.alignment_deadline)
        if not self.teacher and not self.tracking and deadline is not None and now >= deadline:
            raise ValueError(f"{self.label}: alignment deadline exceeded before command commit")
        if "seed" in prepared:
            if self.body_only:
                self.follower.enable_torque(list(BODY))
            else:
                self.follower.enable_torque()
            self.command = dict(prepared["seed"])
            if self.lag is not None:
                self.lag.seed(prepared["seed"], self.clock())
            self.prev_target = dict(prepared.get("target") or self.command)
            self.alignment_deadline = prepared["alignment_deadline"]
            self.last_time = self.clock()
            return normalized(self.follower, self.command)
        goals = {}
        for n, v in prepared["command"].items():
            # nearest tick: int() floors, so a rising joint lagged and a falling one led by up to a tick (Z moves
            # drive elbow up and wrist_flex down together, which tilted the jaw; 2026-11-13 traces)
            tick = round(v)
            if (self.teacher and self.sent is not None and n in BODY and n in self.sent
                    and abs(self.velocity.get(n, 0.0)) < 0.25
                    and abs(tick - self.sent[n]) == 1 and abs(v - self.sent[n]) < 0.75):
                tick = self.sent[n]
            goals[n] = tick
        self.follower.sync_write("Goal_Position", goals, normalize=False)
        self.sent = goals
        self.command = prepared["command"]
        if "target" in prepared:
            self.prev_target = dict(prepared["target"])
        self.last_time = prepared["time"]
        if "body_state" in prepared:
            was_tracking = self.tracking
            self.velocity, self.tracking, self.aligned_since = prepared["body_state"]
            if self.tracking and not was_tracking:
                print(f"{self.label}: aligned; {'full-arm tracking (body and gripper)' if self.full_arm else 'body tracking'} limit {self.track_deg_s:g} deg/s, acceleration {self.accel_deg_s2:g} deg/s^2", flush=True)
        return normalized(self.follower, goals)

    def _seed(self, current, target, started, raw=None):
        return seed_follower_pose(self, current, target, started, raw)


if __name__ == "__main__":
    main()
