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
    LEAD_DEG,
    STALL_PROGRESS_DEG,
    STALL_RELEASE_DEG,
    STALL_S,
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
        if motion.follower.read("Hardware_Error_Status", name, num_retry=READ_RETRY):
            raise ValueError(f"{name}: hardware error")


def read_body_pwm(motion) -> dict:
    if "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table"):
        return motion.follower.sync_read("Present_PWM", list(BODY), normalize=False, num_retry=READ_RETRY)
    return {name: motion.follower.read("Present_PWM", name, num_retry=READ_RETRY) for name in BODY}


def watch_hold(motion, name: str, saturated: bool, pwm: float, now: float, hold: dict | None = None) -> None:
    """A held joint (or a squeezing gripper, its own hold dict): at the cap for HOLD_S in a row, or warming, ends the session. It never frees itself."""
    hold = motion.held[name] if hold is None else hold
    rise = motion.follower.read("Present_Temperature", name, num_retry=READ_RETRY) - hold["temp"]
    if rise >= HOLD_TEMP_RISE_C:
        raise ValueError(
            f"{name}: overload risk; held joint warmed {rise} C at PWM={pwm} limit={motion.pwm_limits.get(name, 'gripper current mode')} "
            f"duration={now - hold['since']:.2f}s"
        )
    if not saturated:
        hold["saturated_since"] = None
        return
    if hold["saturated_since"] is None:
        hold["saturated_since"] = now
    if now - hold["saturated_since"] >= HOLD_S - 1e-9:
        raise ValueError(
            f"{name}: overload risk; hold timed out at PWM={pwm} limit={motion.pwm_limits.get(name, 'gripper current mode')} "
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
                f"{name}: overload risk; PWM={pwm[name]} limit={motion.pwm_limits.get(name, 'gripper current mode')} "
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
                "temp": motion.follower.read("Present_Temperature", name, num_retry=READ_RETRY),
            }
            motion.held_once.add(name)
            motion.effort_since[name] = None
            print(
                f"{motion.label}: overload-hold {detail}; goal set to present, torque on, "
                f"hold watch {HOLD_S:.0f} s",
                flush=True,
            )
    if "gripper" in motion.active:  # a gripper that squeezes (its command leads it: blocked by the box) keeps its bounded lead; it is NEVER frozen or cut for it
        if motion.grip_way is None and abs(motion.command["gripper"] - current["gripper"]) >= (LEAD_DEG - 0.5) * TICKS_PER_DEGREE:
            squeeze = motion.squeeze.setdefault("gripper", {"saturated_since": None})
            grip_pwm = motion.follower.read("Present_PWM", "gripper", num_retry=READ_RETRY)
            if abs(grip_pwm) < 0.9 * motion.follower.read("PWM_Limit", "gripper", num_retry=READ_RETRY):
                squeeze["saturated_since"] = None
            elif squeeze["saturated_since"] is None:
                squeeze["saturated_since"] = now
            elif now - squeeze["saturated_since"] >= HOLD_S - 1e-9:
                relax_squeeze(motion, current)
        else:
            motion.squeeze.pop("gripper", None)
    motion.effort_pwm, motion.last_effort_time = pwm, now


def relax_squeeze(motion, current: dict) -> None:
    """The jaws held the box at the PWM cap for HOLD_S: the command drops its lead and equals the present position (the motor stops pushing, the jaws stay,
    no torque write anywhere: a firm hold must not drop the box, nor the other arm of a bimanual session). The squeeze lead is not applied again until the
    trigger target has moved at least STALL_RELEASE_DEG to the open side of the jaws (guarded_native_track). Reported once."""
    motion.grip_way = 1 if motion.command["gripper"] > current["gripper"] else -1
    motion.command["gripper"], motion.velocity["gripper"] = current["gripper"], 0.0
    motion.squeeze.pop("gripper", None)
    print(f"{motion.label}: gripper squeeze relaxed: PWM at the cap for {HOLD_S:g} s, command set to the present position; "
          f"re-armed when the trigger moves {STALL_RELEASE_DEG} degrees to the open side of the jaws", flush=True)


def seed_follower_pose(motion, current: dict, target: dict, started: float, raw: dict | None = None) -> dict:
    """Seed at the present pose; one tick of readback jitter around a fixed origin is the same pose."""
    use_sync = "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table")
    origin = dict(current)
    for _ in range(3):
        motion.follower.sync_write("Goal_Position", current, normalize=False)
        goals = motion.follower.sync_read("Goal_Position", motors=list(motion.active), normalize=False, num_retry=READ_RETRY)
        fresh = motion.follower.sync_read("Present_Position", motors=list(motion.active), normalize=False, num_retry=READ_RETRY)
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
            if max(abs(target[name] - fresh[name]), abs((raw or target).get(name, target[name]) - fresh[name])) >= 100 * TICKS_PER_DEGREE - 1e-9:
                raise ValueError(f"{name}: seed difference >=100 degrees (raw Leader target and floored target both judged); {detail}")
            err = hw_errs[name] if hw_errs is not None else motion.follower.read("Hardware_Error_Status", name, num_retry=READ_RETRY)
            tq = torques[name] if torques is not None else motion.follower.read("Torque_Enable", name, num_retry=READ_RETRY)
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


def alignment_deadline(started: float, target: dict, current: dict) -> float:
    return started + min(105, max(5, max(abs(target[n] - current[n]) for n in BODY) / TICKS_PER_DEGREE + 5))


def restart_after_pause(motion, started: float) -> None:
    """lerobot paused between two record loops (save and encode, 29 s on 2026-11-21) and the arm kept holding its last
    command. Only the clocks and the alignment phase start over; the command and offsets stay, so the same tick still runs
    the 5 degree following-error, 100 degree, range and effort checks, and Goal_Position cannot jump. The loop's saturation
    clocks (effort load timers, held and squeezing joints' saturated-since) start fresh: the pause neither extends nor
    shortens the loop's own HOLD_S rule, which is unchanged while the loop runs; the boundary watch judges the pause alone."""
    motion.last_time, motion.last_effort_time, motion.prev_target = started, None, None
    motion.effort_since = dict.fromkeys(motion.effort_since)
    for hold in (*motion.held.values(), *motion.squeeze.values()):
        hold["saturated_since"] = None
    motion.velocity = dict.fromkeys(motion.active, 0.0)
    motion.tracking, motion.aligned_since, motion.last_alignment_report = False, None, None
    motion.resuming = True
    motion.stall.clear()
    resume = getattr(motion.monitor, "resume", None)
    if resume is not None:  # the monitor's own sample-age check starts over too; an undeclared delay still stops
        resume(motion)


def over_100(mapped: dict, target: dict, current: dict):
    """The first body joint whose raw or floored Leader target is 100 degrees or more from the arm, else None (the guard's own comparison)."""
    return next((n for n in BODY if max(abs(mapped[n] - current[n]), abs(target[n] - current[n])) >= 100 * TICKS_PER_DEGREE - 1e-9), None)


def stall_watch(motion, target: dict, current: dict, now: float, mapped: dict | None = None) -> None:
    """Full-arm teleop. A joint whose command leads the arm by the full LEAD_DEG toward a target further away, while the arm does
    not advance STALL_PROGRESS_DEG for STALL_S, is held: command frozen at present, torque ON, one log line. The hold ends when the
    target is back within STALL_RELEASE_DEG of the arm; tracking then restarts from alignment. The PWM watch of a hold stays."""
    ticks = TICKS_PER_DEGREE
    releasing = [n for n, hold in motion.held.items() if hold.get("stall") and abs(target[n] - current[n]) <= STALL_RELEASE_DEG * ticks]
    far = over_100(mapped if mapped is not None else target, target, current) if releasing else None
    if far is not None:  # the 100 degree test is skipped while held; on the tick that would release, it runs first: the hold stays, no cut
        if getattr(motion, "hold_kept_for", None) != far:
            print(f"{motion.label}: stall-hold kept: {far} is 100 degrees or more from the Leader; bring it back before the hold can release", flush=True)
        motion.hold_kept_for, releasing = far, []
    else:
        motion.hold_kept_for = None
    for name in releasing:
        del motion.held[name]
        if name in motion.effort_since:
            motion.effort_since[name] = None  # the next overload judgement starts fresh
        print(f"{motion.label}: stall-hold released on {name}: target back within {STALL_RELEASE_DEG} degrees", flush=True)
        if not motion.held:
            motion.tracking, motion.aligned_since, motion.resuming = False, None, True
    if motion.held:
        return
    for name in BODY:  # the gripper never stall-holds: a squeeze on a box keeps its bounded lead (check_effort watches its PWM and temperature)
        way = 1 if target[name] > current[name] else -1
        if not (way * (motion.command[name] - current[name]) >= (LEAD_DEG - 0.5) * ticks
                and abs(target[name] - current[name]) > LEAD_DEG * ticks):
            motion.stall.pop(name, None)
            continue
        ref = motion.stall.get(name)
        if ref is None or way * (current[name] - ref[0]) >= STALL_PROGRESS_DEG * ticks:
            motion.stall[name] = (current[name], now)
        elif now - ref[1] >= STALL_S:
            motion.command[name] = current[name]
            motion.velocity[name] = 0.0
            motion.held[name] = {"since": now, "saturated_since": now, "temp": motion.follower.read("Present_Temperature", name, num_retry=READ_RETRY),
                                 "stall": True}
            motion.stall.pop(name)
            print(f"{motion.label}: stall-hold on {name}: command frozen at present, torque stays ON "
                  f"(less than {STALL_PROGRESS_DEG} deg toward the target in {STALL_S:g} s: slow real progress holds too)", flush=True)
            return
