#!/usr/bin/env python3
"""Hardware Error, Body PWM Effort Sampling, Overload-Hold & Pose Seeding for `NativeJointMotion` (`guarded_native_effort.py`).

Single Responsibility:
  - Read follower hardware errors (`check_hardware_errors`) and body PWM effort (`read_body_pwm`).
  - Evaluate 0.2 s effort saturation, single-use overload-hold (`check_effort`), held-joint thermal/timeout watch
    (`watch_hold`), and gripper/joint stall watch (`relax_squeeze`, `stall_watch`, `restart_after_pause`).
  - Seed initial follower goal position with 3-attempt readback verification before enabling torque (`seed_follower_pose`).
"""
from __future__ import annotations

import math

from guarded_device import (
    BODY,
    HOLD_S,
    HOLD_TEMP_RISE_C,
    LEAD_DEG,
    MAX_GAP_S,
    NAMES,
    READ_RETRY,
    SEED_TOLERANCE_TICKS,
    STALL_PROGRESS_DEG,
    STALL_RELEASE_DEG,
    STALL_S,
    TICKS_PER_DEGREE,
    finite_values,
    normalized,
)
from guarded_native_probe import (  # noqa: E402,F401
    TelemetryReadError,
    check_hold_deadlines,
    check_hold_health,
    check_sync_hw_status,
    check_temp_limit,
    drain_rx,
    enforce_temperatures,
    is_hardware_fault,
    is_valid_hw_status,
    probe_hardware_errors,
    probe_held_overload,
    probe_runner_limits,
    safe_print,
)


def check_hardware_errors(motion) -> None:
    if "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table"):
        errors = motion.follower.sync_read("Hardware_Error_Status", list(NAMES), normalize=False, num_retry=READ_RETRY)
        check_sync_hw_status(motion.follower, errors, READ_RETRY)
        return
    first_err = None
    for name in NAMES:
        val = motion.follower.read("Hardware_Error_Status", name, num_retry=READ_RETRY)
        if is_hardware_fault(val):
            raise ValueError(f"{name}: hardware error ({val})")
        if not is_valid_hw_status(val):
            drain_rx(motion.follower)
            first_err = first_err or TelemetryReadError(f"{name}: invalid hardware status {val}")
    if first_err is not None:
        raise first_err


def read_body_pwm(motion) -> dict:
    if "read" not in vars(motion.follower) and hasattr(motion.follower, "model_ctrl_table"):
        return motion.follower.sync_read("Present_PWM", list(BODY), normalize=False, num_retry=READ_RETRY)
    return {name: motion.follower.read("Present_PWM", name, num_retry=READ_RETRY) for name in BODY}


def watch_hold(motion, name: str, saturated: bool, pwm: float, read_started: float, hold: dict | None = None) -> None:
    """A held joint (or a squeezing gripper, its own hold dict): at the cap for HOLD_S in a row, or warming, ends the session. It never frees itself."""
    hold = motion.held[name] if hold is None else hold
    temp = motion.follower.read("Present_Temperature", name, num_retry=READ_RETRY)
    now = motion.clock()
    if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp):
        raise OSError(f"{name}: invalid held temperature {temp}")
    check_temp_limit(motion, name, temp)
    rise = temp - hold["temp"]
    if rise >= HOLD_TEMP_RISE_C:
        raise ValueError(
            f"{name}: overload risk; held joint warmed {rise} C at PWM={pwm} limit={motion.pwm_limits.get(name, 'gripper current mode')} "
            f"duration={now - hold['since']:.2f}s"
        )
    check_hold_deadlines(motion, name, hold, now, pwm=pwm)
    if not 0 <= now - read_started <= MAX_GAP_S:
        raise OSError(f"{name}: stale held telemetry read (>0.5 seconds)")
    hold["last_telemetry_at"] = read_started
    if not saturated:
        hold["saturated_since"] = None
        return
    if hold["saturated_since"] is None:
        hold["saturated_since"] = read_started


def _sampled_gripper_effort(motion, sample_time: float | None):
    mon = getattr(motion, "monitor", None)
    motions = getattr(mon, "motions", None)
    key_fn = getattr(mon, "key", None)
    if not isinstance(motions, dict) or not callable(key_fn):
        return None, None
    state = motions.get(key_fn(motion))
    if not isinstance(state, dict):
        return None, None
    grip_lim = ((state.get("limits") or {}).get("gripper") or {}).get("pwm_limit")
    grip_pwm = None
    last = state.get("last")
    if sample_time is not None and isinstance(last, dict) and last.get("sample_time") == sample_time:
        for entry in last.get("motors") or ():
            if entry.get("joint") == "gripper" and isinstance(entry.get("pwm"), (int, float)) and not isinstance(entry.get("pwm"), bool):
                grip_pwm = entry["pwm"]
                break
    return grip_pwm, grip_lim


def check_effort(motion, current: dict, started: float, *, allow_stale_hold: bool = False) -> dict:
    before = motion.clock()
    if motion.last_effort_time is not None and before - motion.last_effort_time < 0.2 - 1e-9:
        return {}
    pwm = motion._read_body_pwm()
    finite_values(pwm, BODY)
    monitor_io_error = None
    monitor_started = None
    if motion.monitor is not None:
        try:
            if allow_stale_hold and getattr(motion.monitor, "supports_hold_gap", False):
                monitor_started = motion.clock()
                motion.monitor.sample(motion, current, pwm, monitor_started, allow_gap=True)
            else:
                monitor_started = motion.clock()
                motion.monitor.sample(motion, current, pwm, monitor_started)
        except (OSError, ValueError) as exc:
            if not allow_stale_hold or (isinstance(exc, ValueError) and not getattr(exc, "recoverable_telemetry", False)):
                raise
            monitor_io_error = exc
    now = motion.clock()
    max_gap = math.inf if allow_stale_hold else MAX_GAP_S
    if (
        not 0 <= now - started <= MAX_GAP_S
        or not 0 <= now - motion.last_time <= max_gap
        or (motion.last_effort_time is not None and not 0 <= now - motion.last_effort_time <= max_gap)
    ):
        def ms(seconds):
            return "n/a" if seconds is None else f"{seconds * 1000:.1f}"

        last_tick_age = None if motion.last_time is None else now - motion.last_time
        last_effort_age = None if motion.last_effort_time is None else now - motion.last_effort_time
        pwm_age = (now if monitor_started is None else monitor_started) - before
        monitor_age = None if monitor_started is None else now - monitor_started
        raise ValueError(
            "stale effort sample (>0.5 seconds): "
            f"tick_ms={ms(now - started)} last_tick_ms={ms(last_tick_age)} "
            f"last_effort_ms={ms(last_effort_age)} pwm_ms={ms(pwm_age)} monitor_ms={ms(monitor_age)}"
        )
    staged = {}
    for name in BODY:
        saturated = abs(pwm[name]) >= 0.9 * motion.pwm_limits[name]
        if name in motion.held:
            motion._watch_hold(name, saturated, pwm[name], before)
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
            try:
                temp = motion.follower.read("Present_Temperature", name, num_retry=READ_RETRY)
                if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp):
                    raise OSError(f"{name}: invalid held temperature {temp}")
            except (OSError, TimeoutError, ConnectionError):
                fail_now = motion.clock()
                if not 0 <= fail_now - since < 1.0 + HOLD_S - 1e-9:
                    raise ValueError(f"{detail}; hold temperature unreadable past {HOLD_S:.1f}s cap") from None
                raise
            check_temp_limit(motion, name, temp)
            temp_now = motion.clock()
            entry = min(temp_now, since + 1.0)
            if not 0 <= temp_now - entry < HOLD_S - 1e-9:
                raise ValueError(f"{detail}; overload hold deadline exceeded")
            staged[name] = {
                "goal": current[name],
                "hold": {
                    "since": entry,
                    "saturated_since": entry,
                    "temp": temp,
                    "last_telemetry_at": before,
                },
                "detail": detail,
            }
    if monitor_io_error is not None:
        raise monitor_io_error
    if "gripper" in motion.active:  # a gripper that squeezes (its command leads it: blocked by the box) keeps its bounded lead; it is NEVER frozen or cut for it
        if motion.grip_way is None and abs(motion.command["gripper"] - current["gripper"]) >= (LEAD_DEG - 0.5) * TICKS_PER_DEGREE:
            squeeze = motion.squeeze.setdefault("gripper", {"saturated_since": None})
            grip_pwm, grip_lim = _sampled_gripper_effort(motion, monitor_started)
            if grip_pwm is None:
                grip_pwm = motion.follower.read("Present_PWM", "gripper", num_retry=READ_RETRY)
            if grip_lim is None:
                grip_lim = motion.follower.read("PWM_Limit", "gripper", num_retry=READ_RETRY)
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (grip_pwm, grip_lim)):
                raise TelemetryReadError(f"gripper: invalid squeeze telemetry ({grip_pwm}, {grip_lim})")
            if abs(grip_pwm) < 0.9 * grip_lim:
                squeeze["saturated_since"] = None
            elif squeeze["saturated_since"] is None:
                squeeze["saturated_since"] = now
            elif now - squeeze["saturated_since"] >= HOLD_S - 1e-9:
                relax_squeeze(motion, current)
        else:
            motion.squeeze.pop("gripper", None)
    motion.effort_pwm = pwm
    if not staged:
        if motion.last_effort_time is not None and not 0 <= now - motion.last_effort_time <= MAX_GAP_S:
            motion.last_effort_gap_at = now
        motion.last_effort_time = now
    return staged


def commit_holds(motion, staged: dict | None, now: float) -> None:
    """Publish staged overload holds only after Goal_Position sync_write succeeds."""
    if not staged:
        return
    if motion.last_effort_time is not None and not 0 <= now - motion.last_effort_time <= MAX_GAP_S:
        motion.last_effort_gap_at = now
    motion.last_effort_time = now
    for name, item in staged.items():
        if name in motion.velocity:
            motion.velocity[name] = 0.0
        motion.held[name] = item["hold"]
        motion.held_once.add(name)
        motion.effort_since[name] = None
        safe_print(
            f"{motion.label}: overload-hold {item['detail']}; goal set to present, torque on, "
            f"hold watch {HOLD_S:.0f} s"
        )


def relax_squeeze(motion, current: dict) -> None:
    """The jaws held the box at the PWM cap for HOLD_S: the command drops its lead and equals the present position (the motor stops pushing, the jaws stay,
    no torque write anywhere: a firm hold must not drop the box, nor the other arm of a bimanual session). The squeeze lead is not applied again until the
    trigger target has moved at least STALL_RELEASE_DEG to the open side of the jaws (guarded_native_track). Reported once."""
    motion.grip_way = 1 if motion.command["gripper"] > current["gripper"] else -1
    motion.command["gripper"], motion.velocity["gripper"] = current["gripper"], 0.0
    motion.squeeze.pop("gripper", None)
    safe_print(f"{motion.label}: gripper squeeze relaxed: PWM at the cap for {HOLD_S:g} s, command set to the present position; "
               f"re-armed when the trigger moves {STALL_RELEASE_DEG} degrees to the open side of the jaws")


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
    motion.prev_mapped = None
    if hasattr(motion, "clamped"):
        motion.clamped.clear()
    motion.last_effort_gap_at = None
    motion.effort_since = dict.fromkeys(motion.effort_since)
    for hold in motion.held.values():
        hold["last_telemetry_at"] = started
    for hold in (*motion.held.values(), *motion.squeeze.values()):
        hold["saturated_since"] = None
    motion.velocity = dict.fromkeys(motion.active, 0.0)
    motion.tracking, motion.aligned_since, motion.last_alignment_report = False, None, None
    motion.resuming = True
    motion.stall.clear()
    if motion.lag is not None:
        motion.lag.speed.clear()
        motion.lag.delta.clear()
        motion.lag.blocked_since.clear()
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
