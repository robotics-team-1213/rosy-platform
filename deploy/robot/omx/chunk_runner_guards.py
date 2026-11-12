#!/usr/bin/env python3
"""Guarded trajectory builder, adaptive contact guard, and motor health/thermal helpers (`chunk_runner_guards.py`).

Split from `chunk_runner_run.py` (D-766 2) so the real-time tick loop (`chunk_runner_run.py`) and
guarded trajectory/contact/thermal helpers (`chunk_runner_guards.py`) each stay well below 430 lines.
"""
from __future__ import annotations

from typing import Any

from omx_adapter.chunk_library import (
    GUARD_UNITS_PER_S,
    NAMES,
     chain_path,
    park_path,
    receding_horizon_splice,
    transit_path,
)
import cell_params as prm

JOG_MAX = 5.0
SETTLE_TOL = 3.0
REL_MAX = 20.0
CONTACT_LAG, CONTACT_TICKS = prm.default("runner.contact_lag"), prm.default("runner.contact_ticks")
TEMP_STOP = 65
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
MOTORS = [n.split(".")[0] for n in NAMES]


def contact_limits(start_lags: list, params=None) -> list:
    base = prm.get(params, "runner.contact_lag", CONTACT_LAG)
    rise, top = prm.get(params, "runner.contact_rise"), prm.get(params, "runner.contact_loaded_max")
    return [max(base, min(s + rise, top)) for s in start_lags]


def evaluate_adaptive_contact_guard(
    lags: list[float],
    contact_start: list[float] | None,
    contact_ticks: int,
    params=None,
    *,
    step_delta_units: float = 0.0,
) -> tuple[list[float], int, bool, float]:
    """Evaluate per-joint contact lag against `contact_limits`, with optional velocity-aware transient allowance
    (`step_delta_units`) to prevent false contact trips during smooth descent acceleration while catching real stops."""
    if contact_start is None:
        contact_start = contact_limits(lags, params)
    vel_allowance = min(1.2, max(0.0, float(step_delta_units) * 0.15))
    lag = max(lags) if lags else 0.0
    over = any(v > (limit + vel_allowance) for v, limit in zip(lags, contact_start))
    new_ticks = contact_ticks + 1 if over else 0
    tripped = new_ticks >= prm.get(params, "runner.contact_ticks", CONTACT_TICKS)
    return contact_start, new_ticks, tripped, lag


def read_motor_health(robot) -> dict[str, list[int]] | None:
    """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
    bus = getattr(robot, "bus", None)
    if bus is None:
        return None

    def signed(v):
        return int(v) - 65536 if int(v) > 32767 else int(v)

    kw = {"normalize": False, "num_retry": 2} if "read" not in vars(bus) and hasattr(bus, "model_ctrl_table") else {}
    pwm, current, temp = (
        bus.sync_read(name, **kw) for name in ("Present_PWM", "Present_Current", "Present_Temperature")
    )
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


def build_chain_segments(
    library: dict[str, Any],
    words: list[str],
    target: list[float],
    fps: int,
) -> tuple[list[list[float]], str, bool]:
    """Validate and chain multi-step `chain <step> ; <step> ...` trajectories."""
    parts = [part.strip().split() for part in " ".join(words[1:]).split(";") if part.strip()]
    if not parts:
        raise ValueError("chain requires at least one step")
    cursor, segments, release = list(target), [], False
    transit = {NAMES.index(k): float(v) for k, v in library.get("transit", {}).items()} or None
    speed = library.get("transit_speed", 0.85)
    closed = library["gripper_closed"]
    for step in parts:
        if step[0] == "run" and len(step) == 2:
            frames = library["chunks"].get(step[1])
            if frames is None:
                raise ValueError(f"unknown chunk {step[1]}")
            gap = max(abs(a - b) for a, b in zip(frames[0][:5], cursor[:5]))
            if gap > JOG_MAX * 2:
                raise ValueError(f"chunk {step[1]} starts {gap:.1f} away from the held target")
            seg = [list(f) for f in frames]
            if step[1].startswith("release"):
                release = True
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
