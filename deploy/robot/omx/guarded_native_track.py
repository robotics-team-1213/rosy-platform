"""Alignment and tracking command generation of `NativeJointMotion` (`guarded_native_track.py`).

Aligns at 1 deg/s until the actual and commanded poses settle on the target, then tracks at the mode's limit with the
acceleration limit; a held joint stays put. Split out of guarded_native.py, which keeps the prepare/commit transaction.
"""
from __future__ import annotations

import math

from guarded_device import BODY, LEAD_DEG, STALL_RELEASE_DEG, TICKS_PER_DEGREE
from guarded_native_probe import safe_print
from teleop_speed import ACC_DEG_S2_PER_RAW, STAGES


def body_command(self, target, current, elapsed, now, staged=None):
    tracking, since = self.tracking, self.aligned_since
    full = not (self.teacher or self.body_only)  # full-arm Leader teleop and recording
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
        safe_print(
            f"{self.label}: phase=aligning; actual_joint={actual_joint} actual={current[actual_joint]} "
            f"target={target[actual_joint]} error_deg={abs(current[actual_joint] - target[actual_joint]) / TICKS_PER_DEGREE:.2f} "
            f"Present_PWM={present_pwm} PWM_Limit={pwm_limit}; "
            f"command_joint={command_joint} command={self.command[command_joint]} target={target[command_joint]} "
            f"error_deg={abs(self.command[command_joint] - target[command_joint]) / TICKS_PER_DEGREE:.2f}"
        )
        self.last_alignment_report = now
    if not tracking:
        aligned = all(
            abs(target[n] - current[n]) <= 2.5 * TICKS_PER_DEGREE
            and abs(target[n] - self.command[n]) <= 0.5 * TICKS_PER_DEGREE
            for n in (self.active if self.teacher else BODY)  # full mode: the gripper may rest on a box
        )
        since = (now if since is None else since) if aligned else None
        tracking = since is not None and now - since >= 0.5 - 1e-9
    if not tracking:
        self.grip_ready = False
    elif full and not self.grip_ready and abs(target["gripper"] - self.command["gripper"]) <= 0.5 * TICKS_PER_DEGREE:
        self.grip_ready = True  # the gripper's own command reached its target once: it may use the tracking limit
    acceleration = self.accel_deg_s2 * TICKS_PER_DEGREE
    staged_full = bool(full and self.stage)
    decel = (min(0.5 * self.brake_deg_s2, STAGES[self.stage]["profile_acc"] * ACC_DEG_S2_PER_RAW) * TICKS_PER_DEGREE
             if staged_full else acceleration)
    limit = (self.track_deg_s if tracking else self.align_deg_s) * TICKS_PER_DEGREE
    command, velocity = {}, {}
    frozen = self.frozen(staged) if staged else self.frozen()
    for name in self.active:
        if name == "gripper" and self.grip_way is not None:  # a relaxed squeeze: no lead while the trigger stays on the squeeze side of the jaws
            if self.grip_way * (target[name] - current[name]) < -STALL_RELEASE_DEG * TICKS_PER_DEGREE:
                self.grip_way = None  # the trigger moved to the open side: re-armed, normal tracking below
            else:
                command[name], velocity[name] = current[name], 0.0
                continue
        if name in frozen:
            command[name] = staged[name]["goal"] if staged and name in staged else self.command[name]
            velocity[name] = 0.0
            continue
        error = target[name] - self.command[name]
        brake = math.sqrt((decel * elapsed) ** 2 + 2 * decel * abs(error)) - decel * elapsed
        v_ff_raw = ((target[name] - self.prev_target[name]) / elapsed
                    if self.prev_target is not None and elapsed > 0 else 0.0)
        if (self.teacher or staged_full) and name in BODY and abs(v_ff_raw) <= 1e-6 and abs(self.v_ff_ema[name]) > 1.0 and abs(error) > 1.0 and error * self.v_ff_ema[name] > 0:
            v_ff = 0.55 * self.v_ff_ema[name]
        else:
            v_ff = v_ff_raw
        v_ff = max(-limit, min(limit, v_ff))
        if (self.teacher or staged_full) and name in BODY:
            self.v_ff_ema[name] = v_ff
        if (self.teacher or staged_full) and tracking and self.prev_target is not None and elapsed > 0:
            if error * v_ff > 0:
                reach = min(
                    abs(error) / elapsed,
                    math.sqrt(min(limit, abs(v_ff)) ** 2 + 2 * decel * abs(error)),
                )
                brake = max(brake, reach)
        lim = limit if name != "gripper" or not full or self.grip_ready else (self.align_deg_s if staged_full else 1.0) * TICKS_PER_DEGREE
        desired = math.copysign(min(lim, brake), error)
        if full and (desired * self.velocity[name] < 0 or abs(desired) < abs(self.velocity[name])):  # slowing or reversing: brake harder
            step = self.brake_deg_s2 * TICKS_PER_DEGREE * elapsed  # toward zero (reversal) or the smaller desired speed, never past it
            change = max(-step, min(step, (0.0 if desired * self.velocity[name] < 0 else desired) - self.velocity[name]))
        else:
            change = max(-acceleration * elapsed, min(acceleration * elapsed, desired - self.velocity[name]))
        velocity[name] = self.velocity[name] + change
        if full:  # never carry more speed than the remaining distance can be braked at the acceleration limit
            stop = math.sqrt(2 * decel * abs(error))
            velocity[name] = max(-stop, min(stop, velocity[name]))
        command[name] = self.command[name] + velocity[name] * elapsed
        if full:  # one-sided: only this tick's advance is cut to present + LEAD_DEG in the direction of travel. The command is never
            # pulled toward the arm beyond the stage limit, so drift, sag or a push stays visible to the 5 degree check, and it never moves faster than permitted.
            lead, step = LEAD_DEG * TICKS_PER_DEGREE, command[name] - self.command[name]
            retracted, moving_hold = False, False
            if self.lag is not None:
                lead = self.lag.lead_ticks(name, LEAD_DEG)  # free motion at v lags by v * tau; a blocked joint measures 0 and keeps the 3 degrees
                delta = self.lag.delta.get(name, 0)
                max_step = lim * elapsed
                if command[name] > current[name] and delta == 0:
                    cap = current[name] + lead
                    held_in = min(command[name], max(cap, self.command[name] - max_step))
                    retracted = held_in < self.command[name]
                elif command[name] > current[name] and delta > 0:
                    cap = current[name] + lead
                    held_in = min(command[name], max(cap, self.command[name]))
                    moving_hold = held_in == self.command[name] and held_in < command[name]
                elif command[name] < current[name] and delta == 0:
                    cap = current[name] - lead
                    held_in = max(command[name], min(cap, self.command[name] + max_step))
                    retracted = held_in > self.command[name]
                elif command[name] < current[name] and delta < 0:
                    cap = current[name] - lead
                    held_in = max(command[name], min(cap, self.command[name]))
                    moving_hold = held_in == self.command[name] and held_in > command[name]
                else:
                    held_in = (min(command[name], max(current[name] + lead, self.command[name])) if step > 0
                               else max(command[name], min(current[name] - lead, self.command[name])) if step < 0 else command[name])
            else:
                held_in = (min(command[name], max(current[name] + lead, self.command[name])) if step > 0
                           else max(command[name], min(current[name] - lead, self.command[name])) if step < 0 else command[name])
            if held_in != command[name] and elapsed > 0:
                if retracted:
                    velocity[name] = 0.0
                elif moving_hold:  # cap <= self.command on a still-moving tick: bleed momentum at accel rate instead of snapping velocity to 0
                    decay = self.accel_deg_s2 * TICKS_PER_DEGREE * elapsed
                    prev_v = self.velocity[name]
                    velocity[name] = math.copysign(max(0.0, abs(prev_v) - decay), prev_v) if prev_v else 0.0
                else:
                    velocity[name] = max(-lim, min(lim, (held_in - self.command[name]) / elapsed))
            command[name] = held_in
        calibration = self.follower.calibration[name]
        if full and not calibration.range_min <= command[name] <= calibration.range_max:  # an overrun at the range end: held there, never a cut
            command[name], velocity[name] = min(max(command[name], calibration.range_min), calibration.range_max), 0.0
        if not calibration.range_min <= command[name] <= calibration.range_max:
            raise ValueError(f"{name}: streamed command outside calibrated range")
    return command, (velocity, tracking, since)
