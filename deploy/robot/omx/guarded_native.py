#!/usr/bin/env python3
"""Native LeRobot manual/record child: passive leader, seeded follower and bounded motion.

`record --teacher` (scripted teacher, D-872): no leader; the follower target is the teleop's action
(rosy_replay trajectory). It streams with the body-only profile (1 deg/s until aligned, then
10 deg/s, 10 deg/s^2) over all six joints under the same seed, following-error, effort, hardware
and monitor rules. The gripper is current-limited (mode 5) and stops on the box by design, so it is
the one joint without a following-error bound."""
from __future__ import annotations

import importlib
import math
import sys
import time

TURN = 4096
TICKS_PER_DEGREE = TURN / 360
MAX_GAP_S = 0.5
MAX_STEP_S = 0.1
# one corrupt status packet on the shared hub ended three arm S sessions on 2026-10-27, once with the arm low;
# a read is safe to repeat, and a bus that is really gone still fails after the retries
READ_RETRY = 2
#: A torque-off servo follows its Present_Position with Goal_Position, so a seed write is
#: replaced within one sample and the readback can be one tick away from the next pose read.
SEED_TOLERANCE_TICKS = 1
BODY = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
NAMES = (*BODY, "gripper")
#: PWM_Limit admitted per body joint: the XL430 base, shoulder and elbow carry the arm at reach up to
#: record_session's XL430_PWM_MAX (2026-10-26: 78 % of 300 at 0.23 m); the XL330 wrist stays at 400.
PWM_ADMIT_MAX = {"shoulder_pan": 600, "shoulder_lift": 600, "elbow_flex": 600, "wrist_flex": 400, "wrist_roll": 400}
#: Session servo profile (record_session caps "acc"/"vel", raw X-series units: 21.46 deg/s^2, 1.374 deg/s) kept at
#: connect so the servo ramps between the whole-tick goals instead of snapping to each (2026-10-27: arm S shook on
#: 1-2 tick steps). Velocity >= 20.6 deg/s, twice the 10 deg/s this guard streams at most, so it never slows a stream;
#: acceleration >= 107 deg/s^2 adds a steady lag of v^2/2a <= 0.47 deg at 10 deg/s (0.06 at RISE_SPEED 3.6 deg/s)
#: against the 5 deg following-error bound. Anything else is cleared to 0 (step goals) as before.
PROFILE_ACC, PROFILE_VEL = (5, 100), (15, 200)
PROFILE = {"Profile_Acceleration": PROFILE_ACC, "Profile_Velocity": PROFILE_VEL}


def torque_off(bus):
    """One failed motor must not prevent attempts on the remaining motors."""
    errors = []
    for name in bus.motors:
        try:
            bus.disable_torque(name, num_retry=2)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError(f"torque OFF not confirmed: {errors}")


def close_device(device):
    failures = []
    try:
        if device.bus.is_connected:
            try:
                torque_off(device.bus)
            except BaseException as exc:
                failures.append(exc)
            try:
                device.bus.disconnect()
            except BaseException as exc:
                failures.append(exc)
    finally:
        for camera in getattr(device, "cameras", {}).values():
            if camera.is_connected:
                camera.disconnect()
    if failures:
        # one message, not the last failure: the first is usually the cause
        raise RuntimeError("; ".join(str(failure) for failure in failures))


def connect_passive(device, *, follower):
    """Never call vendor configure/calibrate: those enable torque or write EEPROM."""
    bus = device.bus
    try:
        bus.connect()  # installed SDK handshake verifies each ID/model
        torque_off(bus)
        if not bus.calibration or not bus.is_calibrated:
            raise ValueError("calibration mismatch; commission with torque OFF before use")
        for name in NAMES:
            calibration = bus.calibration[name]
            if calibration.range_min >= calibration.range_max:
                raise ValueError(f"{name}: invalid calibrated range")
            if name in BODY and (calibration.drive_mode != 0 or calibration.homing_offset != 0):
                raise ValueError(f"{name}: unsupported body calibration")
            if bus.read("Operating_Mode", name) != (5 if name == "gripper" else 4):
                raise ValueError(f"{name}: expected commissioned mode 4 body / 5 gripper")
            if bus.read("Hardware_Error_Status", name) or bus.read("Torque_Enable", name):
                raise ValueError(f"{name}: error or torque is ON")
            if follower and not (all(low <= bus.read(r, name) <= high for r, (low, high) in PROFILE.items())
                                 and not bus.read("Drive_Mode", name) & 4):  # bit 2: time-based, other units
                for register in PROFILE:
                    bus.write(register, name, 0)
                    if bus.read(register, name) != 0:
                        raise ValueError(f"{name}: {register} readback mismatch")
        for camera in getattr(device, "cameras", {}).values():
            camera.connect()
    except BaseException as exc:
        try:
            close_device(device)
        except BaseException as close_exc:
            # A latched motor error makes the closing torque-OFF fail too. Without this the
            # close error replaced the handshake error and the receipt named the wrong cause.
            if isinstance(exc, Exception):
                raise RuntimeError(f"{exc}; the close after it also failed: {close_exc}") from exc
        raise


def finite_values(values, names):
    if set(values) != set(names) or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                                        for v in values.values()):
        raise ValueError("missing or non-finite joint sample")


def normalized(bus, raw):
    values = bus._normalize({bus.motors[n].id: v for n, v in raw.items()})
    return {n + ".pos": values[bus.motors[n].id] for n in raw}


class NativeJointMotion:
    def __init__(self, follower, leader, *, clock=time.monotonic, body_only=False, label="follower", monitor=None,
                 offsets=None, teacher=False):
        if teacher != (leader is None) or (teacher and body_only):
            raise ValueError("teacher mode streams all six joints and has no leader")
        self.follower, self.leader, self.clock = follower, leader, clock
        self.body_only, self.teacher = body_only, teacher
        self.active = BODY if body_only else NAMES
        self.label = label
        #: An explicit per-joint seed makes the Follower copy the Leader's *relative* motion
        #: instead of its absolute pose: target = leader + offset. Without it the offset is
        #: measured once from the first sample, which aligns the absolute poses.
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
        self.last_effort_time = None
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
            leader = {ids[i]: v for i, v in raw.items()}  # the teacher's target, in follower ticks
        else:
            leader = self.leader.sync_read("Present_Position", normalize=False, num_retry=READ_RETRY)
        current = self.follower.sync_read("Present_Position", normalize=False, num_retry=READ_RETRY)
        finite_values(leader, NAMES)
        finite_values(current, NAMES)
        if self.body_only and self.follower.read("Torque_Enable", "gripper"):
            raise ValueError("passive gripper torque must remain OFF")
        if self.command is not None:
            for name in BODY if self.teacher else self.active:
                sent = int(self.command[name])  # the bus serialized the previous fractional target as integer ticks
                if abs(current[name] - sent) > 5 * TICKS_PER_DEGREE + 1e-9:
                    raise ValueError(f"{name}: following error >5 motor degrees; command={sent}, current={current[name]}")
        if self.offsets is None:
            self.offsets = (dict.fromkeys(BODY, 0) if self.teacher
                            else {n: TURN * round((current[n] - leader[n]) / TURN) for n in BODY})
        target = {n: leader[n] + self.offsets[n] for n in BODY}
        for name in BODY:
            if abs(target[name] - current[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
                raise ValueError(f"{name}: difference >=100 degrees; leader={leader[name]}, "
                                 f"target={target[name]}, current={current[name]}, offset={self.offsets[name]}, "
                                 f"previous_command={self.command}; align manually with torque OFF")
        for bus, values in (() if self.teacher else ((self.leader, {**target, "gripper": leader["gripper"]}),)) + (
                (self.follower, current),):
            for name, value in values.items():
                calibration = bus.calibration[name]
                if not calibration.range_min <= value <= calibration.range_max:
                    raise ValueError(f"{name}: outside calibrated range")
        # Use the installed SDK's calibrated gripper conversion, including drive inversion.
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
        for name in NAMES:
            if self.follower.read("Hardware_Error_Status", name):
                raise ValueError(f"{name}: hardware error")
        if self.pwm_limits is None:
            limits = {}
            for name in BODY:
                if self.follower.read("Torque_Enable", name):
                    raise ValueError(f"{name}: PWM_Limit admission requires torque OFF")
                limit = self.follower.read("PWM_Limit", name)
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
            deadline = started + min(105, max(5, max(abs(target[n] - current[n]) for n in BODY)
                                               / TICKS_PER_DEGREE + 5))
            current = self._seed({n: current[n] for n in self.active}, target, started)
            return {"started": started, "seed": current, "alignment_deadline": deadline}
        elapsed = min(now - self.last_time, MAX_STEP_S)
        if self.body_only or self.teacher:
            command, state = self._body_command(target, current, elapsed, now)
            return {"started": started, "command": command, "time": now, "body_state": state}
        step = elapsed * TICKS_PER_DEGREE  # one degree/second, independent of loop frequency
        command = {n: self.command[n] + max(-step, min(step, target[n] - self.command[n])) for n in self.active}
        return {"started": started, "command": command, "time": now}

    def _check_effort(self, current, started):
        before = self.clock()
        if self.last_effort_time is not None and before - self.last_effort_time < 0.2 - 1e-9:
            return
        pwm = {name: self.follower.read("Present_PWM", name) for name in BODY}
        finite_values(pwm, BODY)
        if self.monitor is not None:
            self.monitor.sample(self, current, pwm, self.clock())
        now = self.clock()
        if (not 0 <= now - started <= MAX_GAP_S
                or not 0 <= now - self.last_time <= MAX_GAP_S
                or (self.last_effort_time is not None and not 0 <= now - self.last_effort_time <= MAX_GAP_S)):
            raise ValueError("stale effort sample (>0.5 seconds)")
        for name in BODY:
            error = abs(current[name] - int(self.command[name])) / TICKS_PER_DEGREE
            loaded = error > 2 and abs(pwm[name]) >= 0.9 * self.pwm_limits[name]
            since = self.effort_since[name] if loaded else None
            if loaded and since is None:
                since = now
            self.effort_since[name] = since
            if since is not None and now - since >= 1 - 1e-9:
                raise ValueError(f"{name}: overload risk; PWM={pwm[name]} limit={self.pwm_limits[name]} "
                                 f"error_deg={error:.2f} duration={now - since:.2f}s")
        self.effort_pwm, self.last_effort_time = pwm, now

    def _body_command(self, target, current, elapsed, now):
        tracking, since = self.tracking, self.aligned_since
        if not tracking and now >= self.alignment_deadline:
            raise ValueError(f"{self.label}: alignment deadline exceeded; current={current}, "
                             f"target={target}, command={self.command}")
        if not tracking and (self.last_alignment_report is None or now - self.last_alignment_report >= 1):
            actual_joint = max(self.active, key=lambda n: abs(current[n] - target[n]))
            command_joint = max(self.active, key=lambda n: abs(self.command[n] - target[n]))
            present_pwm = self.effort_pwm.get(actual_joint)  # the gripper (teacher mode) has no effort sample
            pwm_limit = self.pwm_limits.get(actual_joint)
            print(f"{self.label}: phase=aligning; actual_joint={actual_joint} actual={current[actual_joint]} "
                  f"target={target[actual_joint]} error_deg={abs(current[actual_joint] - target[actual_joint]) / TICKS_PER_DEGREE:.2f} "
                  f"Present_PWM={present_pwm} PWM_Limit={pwm_limit}; "
                  f"command_joint={command_joint} command={self.command[command_joint]} target={target[command_joint]} "
                  f"error_deg={abs(self.command[command_joint] - target[command_joint]) / TICKS_PER_DEGREE:.2f}", flush=True)
            self.last_alignment_report = now
        if not tracking:
            aligned = all(abs(target[n] - current[n]) <= 2.5 * TICKS_PER_DEGREE
                          and abs(target[n] - self.command[n]) <= 0.5 * TICKS_PER_DEGREE for n in self.active)
            since = (now if since is None else since) if aligned else None
            tracking = since is not None and now - since >= 0.5 - 1e-9
        acceleration = 10 * TICKS_PER_DEGREE
        limit = (10 if tracking else 1) * TICKS_PER_DEGREE
        command, velocity = {}, {}
        for name in self.active:
            error = target[name] - self.command[name]
            # Leave enough distance for this step and subsequent braking; moving targets may still be passed.
            brake = math.sqrt((acceleration * elapsed) ** 2 + 2 * acceleration * abs(error)) - acceleration * elapsed
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
        if (self.failed or not 0 <= now - prepared["started"] <= MAX_GAP_S
                or (self.last_time is not None and not 0 <= now - self.last_time <= MAX_GAP_S)):
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
            self.alignment_deadline = prepared["alignment_deadline"]
            self.last_time = self.clock()
            return normalized(self.follower, self.command)
        goals = {n: int(v) for n, v in prepared["command"].items()}
        self.follower.sync_write("Goal_Position", goals, normalize=False)
        self.command = prepared["command"]
        self.last_time = prepared["time"]
        if "body_state" in prepared:
            was_tracking = self.tracking
            self.velocity, self.tracking, self.aligned_since = prepared["body_state"]
            if self.tracking and not was_tracking:
                print(f"{self.label}: aligned; body tracking limit 10 deg/s, acceleration 10 deg/s^2", flush=True)
        return normalized(self.follower, goals)

    def _seed(self, current, target, started):
        """Seed at the present pose; one tick of readback jitter around a fixed origin is the same pose.

        2026-10-23 device probe: with torque OFF, a written Goal_Position is replaced by the servo's
        own Present_Position within 50 ms (write 2097, read back 2092, then 2091 while the pose read
        2091). Exact goal/present equality is therefore not reachable on a joint that drifts a tick,
        and the previous exact check aborted `align` before any motion. The write is kept so a
        register left far away is still caught, and a gap above one tick still refuses the seed.
        """
        origin = dict(current)
        for _ in range(3):
            self.follower.sync_write("Goal_Position", current, normalize=False)
            goals = self.follower.sync_read("Goal_Position", motors=list(self.active), normalize=False)
            fresh = self.follower.sync_read("Present_Position", motors=list(self.active), normalize=False)
            detail = f"initial goal readback mismatch: expected={current}, readback={goals}, fresh={fresh}"
            finite_values(goals, self.active)
            finite_values(fresh, self.active)
            for name in self.active:
                calibration = self.follower.calibration[name]
                if not calibration.range_min <= fresh[name] <= calibration.range_max:
                    raise ValueError(f"{name}: seed outside calibrated range; {detail}")
                if abs(target[name] - fresh[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
                    raise ValueError(f"{name}: seed difference >=100 degrees; {detail}")
                if self.follower.read("Hardware_Error_Status", name) or self.follower.read("Torque_Enable", name):
                    raise ValueError(f"{name}: seed hardware error or torque ON; {detail}")
            if not 0 <= self.clock() - started <= MAX_GAP_S:
                raise ValueError(f"stale seed transaction (>0.5 seconds); {detail}")
            if any(abs(goals[n] - origin[n]) > SEED_TOLERANCE_TICKS
                   or abs(fresh[n] - origin[n]) > SEED_TOLERANCE_TICKS for n in self.active):
                raise ValueError(detail)
            if all(abs(goals[n] - fresh[n]) <= SEED_TOLERANCE_TICKS for n in self.active):
                return goals
            current = fresh
        raise ValueError(detail)


def run_native(module, follower_type, leader_type, *, body_only=False, teacher=False):
    """Keep native factories/recording; replace only hardware lifecycle and action guard."""
    devices = []
    if body_only and hasattr(module, "record"):
        raise ValueError("body-only mode is manual teleoperation only")
    if teacher and not hasattr(module, "record"):
        raise ValueError("teacher mode is a recording")
    shared = {}
    original_robot = module.make_robot_from_config
    original_teleop = module.make_teleoperator_from_config

    class Follower(follower_type):
        def connect(self, calibrate=True):
            connect_passive(self, follower=True)

        def send_action(self, action):
            if "motion" not in shared:
                from motor_health import MotorHealth
                shared["motion"] = NativeJointMotion(self.bus, None if teacher else shared["leader"].bus,
                                                     body_only=body_only, teacher=teacher, monitor=MotorHealth())
            sent = shared["motion"].send(action)
            shared["sent"] = sent
            return sent

        def disconnect(self):
            close_device(self)

    class Leader(leader_type):
        def connect(self, calibrate=True):
            connect_passive(self, follower=False)

        def disconnect(self):
            close_device(self)

    def robot_factory(config):
        device = original_robot(config)
        if not isinstance(device, follower_type) or getattr(config, "use_degrees", False):
            raise ValueError("guard supports only normalized OMX follower manual control")
        device.__class__ = Follower
        devices.append(device)
        return device

    def teleop_factory(config):
        device = original_teleop(config)
        if teacher:
            if isinstance(device, leader_type):
                raise ValueError("teacher mode replays a trajectory, not a leader")
            return device  # no motor bus: LeRobot's own disconnect is enough
        if not isinstance(device, leader_type):
            raise ValueError("guard requires OMX leader")
        device.__class__ = Leader
        devices.append(device)
        shared["leader"] = device
        return device

    module.make_robot_from_config = robot_factory
    module.make_teleoperator_from_config = teleop_factory
    original_frame = getattr(module, "build_dataset_frame", None)
    if original_frame is not None:
        def frame(features, values, prefix):
            if prefix == module.ACTION:
                values = shared["sent"]
            return original_frame(features, values, prefix=prefix)
        module.build_dataset_frame = frame
    fault = None
    try:
        return module.main()
    except BaseException as exc:
        fault = exc
        raise
    finally:
        errors = []
        for device in reversed(devices):
            try:
                close_device(device)
            except Exception as exc:
                errors.append(exc)
        module.make_robot_from_config, module.make_teleoperator_from_config = original_robot, original_teleop
        if original_frame is not None:
            module.build_dataset_frame = original_frame
        motion = shared.get("motion")
        if fault is not None and motion is not None and not motion.failed:
            motion.report_fault(fault)
        if motion is not None and motion.monitor is not None:
            try:
                motion.monitor.end()
            except BaseException:
                pass  # OFF already attempted; parent finalizes the same bound session snapshot.
        if errors:
            raise RuntimeError(f"native cleanup failed: {errors}")


def main():
    mode = sys.argv.pop(1)
    teacher = "--teacher" in sys.argv
    if teacher:
        sys.argv.remove("--teacher")
        if mode != "record":
            raise SystemExit("teacher mode is a recording")
    body_only = "--body-only" in sys.argv
    if body_only:
        sys.argv.remove("--body-only")
        if mode != "teleoperate":
            raise SystemExit("body-only mode is manual teleoperation only")
    if mode not in ("record", "teleoperate"):
        raise SystemExit("expected record or teleoperate")
    from lerobot.robots.omx_follower.omx_follower import OmxFollower
    from lerobot.teleoperators.omx_leader.omx_leader import OmxLeader
    module = importlib.import_module("lerobot.scripts.lerobot_" + mode)
    run_native(module, OmxFollower, OmxLeader, body_only=body_only, teacher=teacher)


if __name__ == "__main__":
    main()
