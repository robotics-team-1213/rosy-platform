#!/usr/bin/env python3
"""Guarded trajectory builder, adaptive contact guard, and motor health/thermal helpers (`chunk_runner_guards.py`).

Split from `chunk_runner_run.py` (D-766 2) so the real-time tick loop (`chunk_runner_run.py`) and
guarded trajectory/contact/thermal helpers (`chunk_runner_guards.py`) each stay well below 430 lines.
"""
from __future__ import annotations

import json
import math
import sys
from typing import Any

from omx_adapter.chunk_library import (
    GUARD_UNITS_PER_S, NAMES, chain_path, park_path, receding_horizon_splice, transit_path,
)
import cell_params as prm

JOG_MAX = 5.0
SETTLE_TOL = 3.0
REL_MAX = 20.0
CONTACT_LAG, CONTACT_TICKS = prm.default("runner.contact_lag"), prm.default("runner.contact_ticks")
TEMP_STOP = 65
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
MOTORS = [n.split(".")[0] for n in NAMES]


def safe_stderr(row: dict) -> None:
    """Best-effort stderr JSON diagnostic: closed or broken stderr must never exit a powered HOLD loop."""
    try:
        print(json.dumps(row, default=str), file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


def hold_runner(runner, present, reason, *, human: bool, empty_margin: float) -> None:
    """Freeze at the measured body pose; human hold also latches the command path."""
    saved, runner._committed_grip = getattr(runner, "_committed_grip", None), None
    if saved is not None and runner.target is not None and len(runner.target) >= 6:
        runner.target[5], runner.holding = saved
    chunk, jogging = runner.chunk, bool(runner.jog_path)
    runner.queue, runner.retreat_frames = [], (runner.played or runner.jog_path[:-1])[::-1]
    runner.target = list(present[:5]) + [runner.target[5]]
    runner.fault, runner.holding = reason, bool(runner.holding and present[5] > runner.target[5] + empty_margin)
    runner.chunk, runner.played, runner.jog_path = None, [], []
    runner.pace_floor, runner.paced, runner.pace_last, runner.trend = 0.0, 0, None, []
    # stop exactly where the arm is (no leftover wrist nudge); the failed chunk keeps its own sway record
    runner.pitch_hold, sway, runner.sway_peak, runner.speed_low = 0.0, runner.sway_peak, {}, 1.0
    gated = False
    fold_park = not human and bool(getattr(runner, "_stop_after_park", None))
    fold_abort = fold_park and getattr(runner, "_interrupt", None) is None
    if human or fold_abort:
        if not runner.human_hold_latched:
            runner._human_hold_release_from = len(getattr(runner, "signals", None) or ())
        runner.human_hold_latched = True
        runner.policy_playback = runner.jaw_gate = runner._trailing_jaw_gate = None
        stop = getattr(getattr(getattr(runner, "robot", None), "motion", None), "stop_streaming", None)
        if callable(stop):
            stop()
        runner.torque_hold_commanded = False
        runner._human_hold_ack_pending = True
        runner.pending.clear()
        runner.retreat_frames = []
        runner.grip_from = runner._release_until = runner._release_floor = runner._held_jaw = None
        runner._stop_after_park, runner._stopped, runner.home_since = None, False, None
    elif (getattr(runner, "policy_playback", None) is not None
          or getattr(runner, "jaw_gate", None) is not None
          or getattr(runner, "_trailing_jaw_gate", None) is not None):
        from chunk_policy_playback import halt_policy_gate
        gated = halt_policy_gate(runner)
    if chunk == "park":
        runner.last_input = runner.clock()
        runner._stop_after_park = None
    if not human:
        fields = dict(
            command=f"run {chunk or 'jog'}" if chunk or jogging else "fault",
            ok=False, error=runner.fault, contact=True, **({"sway": sway} if sway else {}),
            **({"hold": True, "folded": False, "person_needed": True} if fold_abort else {}),
        )
        if gated or fold_park:
            from chunk_policy_playback import report_policy_halt
            report_policy_halt(runner, present, True, **fields)
        else:
            runner.report(present=present, **fields)


def halt_thermal_or_stall(runner, present, reason: str, *, empty_margin: float) -> None:
    """Freeze on motor overtemp/stall; latch human HOLD if a direct stop fold was active."""
    from chunk_policy_playback import halt_policy_gate, report_policy_halt

    chunk, sway = runner.chunk, runner.sway_peak
    stop_cmd = getattr(runner, "_stop_after_park", None)
    already_held = bool(runner.human_hold_latched)
    fold_abort = bool(stop_cmd) and getattr(runner, "_interrupt", None) is None
    if already_held:
        runner.fault, runner._stop_after_park = reason, None
    elif fold_abort:
        hold_runner(runner, present, reason, human=True, empty_margin=empty_margin)
    else:
        runner.fault, runner.queue, runner.target = reason, [], present[:5] + [runner.target[5]]
        runner.chunk, runner.pitch_hold, runner.sway_peak, runner.speed_low = None, 0.0, {}, 1.0
        runner._stop_after_park = None
    gated = already_held or halt_policy_gate(runner) or bool(stop_cmd)
    extra = dict(hold=True, folded=False, person_needed=True) if (fold_abort or already_held) else {}
    report_policy_halt(runner, present, gated, command=f"run {chunk}" if chunk else "fault",
                       ok=False, error=reason, **({"sway": sway} if sway else {}), **extra)


def human_hold_overload(runner, present) -> None:
    """A guard overload while a human hold is latched: report once that a person is needed."""
    if not getattr(runner, "_human_hold_overload_reported", False):
        runner._human_hold_overload_reported, runner._human_hold_ack_pending = True, False
        try:
            runner.report(command="human-hold", ok=False, error="guard overload during human hold; person needed",
                          person_needed=True, present=present)
        except OSError as error:
            safe_stderr({"command": "human-hold", "status_write_failed": str(error)[:300]})


def shed_interrupt_hold(runner, sent, present, *, fresh: bool = True) -> None:
    """While HOLD sees a native overload hold, keep bounded XL430 relief, pin held joints, and poll release."""
    motion = getattr(runner.robot, "motion", None)
    held = getattr(motion, "held", None) or {}
    if not held or present is None:
        runner._shed_seen_at = None
        return
    if getattr(runner, "human_hold_latched", False):
        human_hold_overload(runner, present)
    now, et = runner.clock(), getattr(motion, "last_effort_time", False)
    if not fresh or (et is not False and (et is None or not 0 <= now - et <= 0.5)):
        runner.shed_clear = runner._shed_seen_at = None
        return
    prev, gap_at, shed_clear = getattr(runner, "_shed_seen_at", None), getattr(motion, "last_effort_gap_at", None), getattr(runner, "shed_clear", None)
    if shed_clear is not None and ((prev is not None and not 0 <= now - prev <= 0.5) or (gap_at is not None and gap_at > shed_clear)):
        runner.shed_clear = None
    runner._shed_seen_at = now
    import runner_strain

    home = (runner.library.get("chunks") or {}).get("home") if isinstance(getattr(runner, "library", None), dict) else None
    if home:
        runner.target = runner_strain.shed(runner.target, present, sent if isinstance(sent, dict) else {}, home[-1],
                                           0.5 * GUARD_UNITS_PER_S / runner.fps)
    for i, name in enumerate(MOTORS[:5]):
        if name in held:
            runner.target[i] = float(present[i])
    runner_strain.release_when_clear(runner, motion, held, now)


def human_hold_ack(runner, present, *, hold_sent: bool = True) -> None:
    """The first tick after a human hold: torque is now commanded, report it once."""
    if not hold_sent or not runner._human_hold_ack_pending:
        return
    runner._human_hold_ack_pending, runner.torque_hold_commanded = False, True
    try:
        runner.report(command="human-hold", ok=True, person_needed=True, present=present)
    except OSError as error:
        safe_stderr({"command": "human-hold", "status_write_failed": str(error)[:300]})


def contact_limits(start_lags: list, params=None) -> list:
    base = prm.get(params, "runner.contact_lag", CONTACT_LAG)
    rise, top = prm.get(params, "runner.contact_rise"), prm.get(params, "runner.contact_loaded_max")
    return [max(base, min(s + rise, top)) for s in start_lags]


def evaluate_adaptive_contact_guard(
    lags: list[float], contact_start: list[float] | None, contact_ticks: int, params=None, *, step_delta_units: float = 0.0,
) -> tuple[list[float], int, bool, float]:
    """Evaluate per-joint contact lag against `contact_limits`, with optional velocity-aware transient allowance
    (`step_delta_units`) to prevent false contact trips during smooth descent acceleration while catching real stops."""
    if contact_start is None:
        contact_start = contact_limits(lags, params)
    vel_allowance = min(1.2, max(0.0, float(step_delta_units) * 0.15))
    lag = max(lags) if lags else 0.0
    # Bound real-arm loaded limits (<= 2.35) to 2.35 units (4.23 deg) so coasting stays below the 5 deg hard stop.
    over = any(v > (min(limit + vel_allowance, 2.35) if limit <= 2.35 else limit + vel_allowance)
               for v, limit in zip(lags, contact_start))
    new_ticks = contact_ticks + 1 if over else 0
    tripped = new_ticks >= prm.get(params, "runner.contact_ticks", CONTACT_TICKS)
    return contact_start, new_ticks, tripped, lag


def read_motor_health(robot) -> dict[str, list[int]] | None:
    """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
    bus = getattr(robot, "bus", None)
    if bus is None:
        return None
    signed = lambda v: int(v) - 65536 if int(v) > 32767 else int(v)
    kw = {"normalize": False, "num_retry": 2} if "read" not in vars(bus) and hasattr(bus, "model_ctrl_table") else {}
    pwm, current, temp = (bus.sync_read(n, **kw) for n in ("Present_PWM", "Present_Current", "Present_Temperature"))
    if isinstance(temp, dict):
        from guarded_native_effort import enforce_temperatures

        enforce_temperatures(getattr(robot, "motion", None), temp)
    return {
        "pwm": [signed(pwm[m]) for m in MOTORS],
        "current_ma": [signed(current[m]) for m in MOTORS],
        "temp_c": [int(temp[m]) for m in MOTORS],
    }


def check_motor_thermal_and_stall(
    health: dict[str, Any],
    target: list[float],
    present: list[float],
    health_present: list[float] | None,
    overload_since: float | None,
    now: float,
) -> tuple[str | None, list[float], float | None]:
    """Check motor temperatures and load-bearing joint PWM stall windows."""
    hot = max(health["temp_c"])
    moved = health_present or present
    stalled = [
        i
        for i in range(4)
        if abs(health["pwm"][i]) >= PWM_STOP
        and abs(target[i] - present[i]) > STALL_GAP
        and abs(present[i] - moved[i]) < STALL_MOVE
    ]
    new_overload_since = None if not stalled else (now if overload_since is None else overload_since)
    pushing = max((abs(health["pwm"][i]) for i in stalled), default=0)
    reason = (
        f"temperature {hot} C"
        if hot >= TEMP_STOP
        else f"load-bearing joint stalled at PWM {pushing} for {PWM_STOP_S} s"
        if new_overload_since is not None and now - new_overload_since >= PWM_STOP_S
        else None
    )
    return reason, present, new_overload_since


def build_splice_frames(
    library: dict[str, Any],
    chunk_name: str,
    rel: bool,
    queue: list[list[float]],
    target: list[float],
    fps: int,
) -> list[list[float]]:
    """Build receding-horizon spliced trajectory frames for `splice <chunk> [rel]`."""
    frames = library["chunks"].get(chunk_name)
    if frames is None:
        raise ValueError(f"unknown chunk {chunk_name}")
    window = max(1, min(len(queue), round(0.25 * fps))) if queue else 0
    anchor = queue[window - 1] if window else target
    offset = [0.0] * 6
    if rel:
        offset = [t - s for t, s in zip(anchor[:5], frames[0][:5])] + [0.0]
        if max(abs(v) for v in offset) > REL_MAX:
            raise ValueError(f"relative offset {max(abs(v) for v in offset):.1f} exceeds {REL_MAX}")
    next_frames = [[max(-100.0, min(100.0, v + o)) for v, o in zip(f, offset)] for f in frames]
    gap = max(abs(a - b) for a, b in zip(next_frames[0][:5], anchor[:5]))
    if gap > JOG_MAX * 2:
        raise ValueError(f"chunk {chunk_name} starts {gap:.1f} away from the splice anchor")
    return receding_horizon_splice(queue, target, next_frames, fps, blend_s=0.25, vmax=GUARD_UNITS_PER_S)


def build_jog_target(words: list[str], present: list[float], target: list[float]) -> list[float]:
    """Validate and compute the coordinated target for `jog <joint> <delta> [...]`."""
    moved = list(target)
    pairs = list(zip(words[1::2], words[2::2]))
    if len({name for name, _ in pairs}) != len(pairs) or any(name not in NAMES for name, _ in pairs):
        raise ValueError("jog takes distinct follower joint names")
    for name, value in pairs:
        delta, index = float(value), NAMES.index(name)
        if not abs(delta) <= JOG_MAX:
            raise ValueError(f"jog is limited to {JOG_MAX}")
        moved[index] = max(-100.0, min(100.0, moved[index] + delta))
        if abs(moved[index] - present[index]) > JOG_MAX + SETTLE_TOL:
            raise ValueError(f"jog would put the target more than {JOG_MAX + SETTLE_TOL} from the joint")
    return moved


def runner_has_configured_rim(runner) -> bool:
    if getattr(runner, "rim_z_m", None) is not None:
        return True
    params = getattr(runner, "params", None)
    if not isinstance(params, dict) or "policy.source_rim_z_m" not in params:
        return False
    raw = params["policy.source_rim_z_m"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return True
    try:
        val = float(raw)
    except OverflowError:
        return True
    return (not math.isfinite(val)) or val != 0.0


def policy_requires_jaw_gate(runner, library: dict | None = None) -> bool:
    lib = runner.library if library is None else library
    if ("grasp_pick" in (lib.get("chunks") or {}) or runner_has_configured_rim(runner)
            or getattr(runner, "trusted_grasp", None) is not None):
        return True
    src = lib.get("source")
    if src is not None and not isinstance(src, dict):
        return True
    pick = src.get("pick") if isinstance(src, dict) else None
    if pick is not None and not isinstance(pick, dict):
        return True
    return any(isinstance(m, dict) and (m.get("rim_z_m") is not None or m.get("rim_z") is not None) for m in (src, pick))


def library_gripper_closed(library: dict) -> float:
    raw = library.get("gripper_closed")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("invalid gripper_closed")
    try:
        val = float(raw)
    except OverflowError:
        raise ValueError("invalid gripper_closed") from None
    if not math.isfinite(val) or not -100.0 <= val <= 100.0:
        raise ValueError("invalid gripper_closed")
    return val


def library_transit_speed(library: dict) -> float:
    raw = library.get("transit_speed", 0.85)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("invalid transit_speed")
    try:
        val = float(raw)
    except OverflowError:
        raise ValueError("invalid transit_speed") from None
    if not math.isfinite(val) or not 0.1 <= val <= 0.85:
        raise ValueError("invalid transit_speed")
    return val


def parse_transit(library: dict) -> dict[int, float] | None:
    raw = library.get("transit")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid transit")
    out = {}
    for name, value in raw.items():
        idx = NAMES.index(name) if name in NAMES else (int(name) if type(name) is str and name in tuple("012345") else -1)
        if idx < 0 or idx in out or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid transit")
        try:
            val = float(value)
        except OverflowError:
            raise ValueError("invalid transit") from None
        if not math.isfinite(val) or not -100.0 <= val <= 100.0:
            raise ValueError("invalid transit")
        out[idx] = val
    return out or None


def build_chain_segments(
    library: dict[str, Any],
    words: list[str],
    target: list[float],
    fps: int,
    *,
    require_policy_gate: bool = False,
) -> tuple[list[list[float]], str, float | None]:
    """Validate and chain multi-step `chain <step> ; <step> ...` trajectories."""
    parts = [part.strip().split() for part in " ".join(words[1:]).split(";") if part.strip()]
    if not parts:
        raise ValueError("chain requires at least one step")
    cursor, segments, release = list(target), [], None
    transit = parse_transit(library)
    speed = library_transit_speed(library)
    closed = library_gripper_closed(library)
    for step in parts:
        if (step[0] in ("run", "goto") and len(step) >= 2 and step[1] == "policy"
                and ("policy_playback" in library or "jaw_gate" in library
                     or "grasp_pick" in (library.get("chunks") or {}) or require_policy_gate)):
            raise ValueError("cannot chain a timed or jaw-gated policy chunk")
        if step[0] == "run" and len(step) == 2:
            frames = library["chunks"].get(step[1])
            if frames is None:
                raise ValueError(f"unknown chunk {step[1]}")
            gap = max(abs(a - b) for a, b in zip(frames[0][:5], cursor[:5]))
            if gap > JOG_MAX * 2:
                raise ValueError(f"chunk {step[1]} starts {gap:.1f} away from the held target")
            seg = [list(f) for f in frames]
            if step[1].startswith("release"):
                peak = max((float(f[5]) for f in seg), default=float(cursor[5]))
                release = peak if release is None else max(release, peak)
        elif step[0] == "goto" and len(step) == 2:
            frames = library["chunks"].get(step[1])
            if frames is None:
                raise ValueError(f"unknown chunk {step[1]}")
            seg = transit_path(cursor, frames[0], closed, fps, transit, speed)
        elif step == ["park"]:
            home = library["chunks"].get("home")
            if not home:
                raise ValueError("park needs a home chunk in the library")
            seg = park_path(cursor, home[-1], closed, fps, transit, speed)
        else:
            raise ValueError(f"chain step {step!r} must be 'run <chunk>', 'goto <chunk>' or 'park'")
        segments.append(seg)
        cursor = list(seg[-1])
    chunk_label = " ; ".join(" ".join(s) for s in parts)
    return chain_path(segments, fps), chunk_label, release
