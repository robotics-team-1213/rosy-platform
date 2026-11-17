#!/usr/bin/env python3
"""Hardware Error, Body PWM Effort Sampling, Overload-Hold & Pose Seeding for `NativeJointMotion` (`guarded_native_effort.py`).

Single Responsibility:
  - Read follower hardware errors (`check_hardware_errors`) and body PWM effort (`read_body_pwm`).
  - Evaluate 0.2 s effort saturation, single-use overload-hold (`check_effort`), and held-joint thermal/timeout watch (`watch_hold`).
  - Seed initial follower goal position with 3-attempt readback verification before enabling torque (`seed_follower_pose`).
"""
from __future__ import annotations

from guarded_device import (
    BODY,
    HOLD_S,
    HOLD_TEMP_RISE_C,
    MAX_GAP_S,
    NAMES,
    READ_RETRY,
    SEED_TOLERANCE_TICKS,
    TICKS_PER_DEGREE,
    finite_values,
    normalized,
)


def check_hardware_errors(motion) -> None:
    if "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table"):
        errors = motion.follower.sync_read("Hardware_Error_Status", list(NAMES), normalize=False, num_retry=READ_RETRY)
        for name in NAMES:
            if errors[name]:
                raise ValueError(f"{name}: hardware error")
        return
    for name in NAMES:
        if motion.follower.read("Hardware_Error_Status", name):
            raise ValueError(f"{name}: hardware error")


def read_body_pwm(motion) -> dict:
    if "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table"):
        return motion.follower.sync_read("Present_PWM", list(BODY), normalize=False, num_retry=READ_RETRY)
    return {name: motion.follower.read("Present_PWM", name) for name in BODY}


def watch_hold(motion, name: str, saturated: bool, pwm: float, now: float) -> None:
    """A held joint: at the cap for HOLD_S in a row, or warming, ends the session. It never frees itself."""
    hold = motion.held[name]
    rise = motion.follower.read("Present_Temperature", name) - hold["temp"]
    if rise >= HOLD_TEMP_RISE_C:
        raise ValueError(
            f"{name}: overload risk; held joint warmed {rise} C at PWM={pwm} limit={motion.pwm_limits[name]} "
            f"duration={now - hold['since']:.2f}s"
        )
    if not saturated:
        hold["saturated_since"] = None
        return
    if hold["saturated_since"] is None:
        hold["saturated_since"] = now
    if now - hold["saturated_since"] >= HOLD_S - 1e-9:
        raise ValueError(
            f"{name}: overload risk; hold timed out at PWM={pwm} limit={motion.pwm_limits[name]} "
            f"duration={now - hold['since']:.2f}s"
        )


def check_effort(motion, current: dict, started: float) -> None:
    before = motion.clock()
    if motion.last_effort_time is not None and before - motion.last_effort_time < 0.2 - 1e-9:
        return
    pwm = motion._read_body_pwm()
    finite_values(pwm, BODY)
    if motion.monitor is not None:
        motion.monitor.sample(motion, current, pwm, motion.clock())
    now = motion.clock()
    if (
        not 0 <= now - started <= MAX_GAP_S
        or not 0 <= now - motion.last_time <= MAX_GAP_S
        or (motion.last_effort_time is not None and not 0 <= now - motion.last_effort_time <= MAX_GAP_S)
    ):
        raise ValueError("stale effort sample (>0.5 seconds)")
    for name in BODY:
        saturated = abs(pwm[name]) >= 0.9 * motion.pwm_limits[name]
        if name in motion.held:
            motion._watch_hold(name, saturated, pwm[name], now)
            continue
        error = abs(current[name] - int(motion.command[name])) / TICKS_PER_DEGREE
        loaded = error > 2 and saturated
        since = motion.effort_since[name] if loaded else None
        if loaded and since is None:
            since = now
        motion.effort_since[name] = since
        if since is not None and now - since >= 1 - 1e-9:
            detail = (
                f"{name}: overload risk; PWM={pwm[name]} limit={motion.pwm_limits[name]} "
                f"error_deg={error:.2f} duration={now - since:.2f}s"
            )
            if name in motion.held_once:
                raise ValueError(f"{detail}; second overload on this joint")
            motion.command[name] = current[name]
            if name in motion.velocity:
                motion.velocity[name] = 0.0
            motion.held[name] = {
                "since": now,
                "saturated_since": now,
                "temp": motion.follower.read("Present_Temperature", name),
            }
            motion.held_once.add(name)
            motion.effort_since[name] = None
            print(
                f"{motion.label}: overload-hold {detail}; goal set to present, torque on, "
                f"hold watch {HOLD_S:.0f} s",
                flush=True,
            )
    motion.effort_pwm, motion.last_effort_time = pwm, now


def seed_follower_pose(motion, current: dict, target: dict, started: float) -> dict:
    """Seed at the present pose; one tick of readback jitter around a fixed origin is the same pose."""
    use_sync = "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table")
    origin = dict(current)
    for _ in range(3):
        motion.follower.sync_write("Goal_Position", current, normalize=False)
        goals = motion.follower.sync_read("Goal_Position", motors=list(motion.active), normalize=False)
        fresh = motion.follower.sync_read("Present_Position", motors=list(motion.active), normalize=False)
        detail = f"initial goal readback mismatch: expected={current}, readback={goals}, fresh={fresh}"
        finite_values(goals, motion.active)
        finite_values(fresh, motion.active)
        hw_errs = (
            motion.follower.sync_read("Hardware_Error_Status", list(motion.active), normalize=False, num_retry=READ_RETRY)
            if use_sync
            else None
        )
        torques = (
            motion.follower.sync_read("Torque_Enable", list(motion.active), normalize=False, num_retry=READ_RETRY)
            if use_sync
            else None
        )
        for name in motion.active:
            calibration = motion.follower.calibration[name]
            if not calibration.range_min <= fresh[name] <= calibration.range_max:
                raise ValueError(f"{name}: seed outside calibrated range; {detail}")
            if abs(target[name] - fresh[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
                raise ValueError(f"{name}: seed difference >=100 degrees; {detail}")
            err = hw_errs[name] if hw_errs is not None else motion.follower.read("Hardware_Error_Status", name)
            tq = torques[name] if torques is not None else motion.follower.read("Torque_Enable", name)
            if err or tq:
                raise ValueError(f"{name}: seed hardware error or torque ON; {detail}")
        if not 0 <= motion.clock() - started <= MAX_GAP_S:
            raise ValueError(f"stale seed transaction (>0.5 seconds); {detail}")
        if any(
            abs(goals[n] - origin[n]) > SEED_TOLERANCE_TICKS or abs(fresh[n] - origin[n]) > SEED_TOLERANCE_TICKS
            for n in motion.active
        ):
            raise ValueError(detail)
        if all(abs(goals[n] - fresh[n]) <= SEED_TOLERANCE_TICKS for n in motion.active):
            motion.last_present = normalized(motion.follower, fresh)
            return goals
        current = fresh
    raise ValueError(detail)
