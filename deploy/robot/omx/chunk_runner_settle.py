#!/usr/bin/env python3
"""Chunk Settlement, Grasp Holding Detection & Idle Auto-Park Lifecycle (`chunk_runner_settle.py`).

Single Responsibility:
  - Evaluate chunk completion settlement and grasp holding (`check_chunk_settled`).
  - Manage idle timeout auto-park and torque-OFF session termination (`check_runner_idle`).
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cell_params as prm  # noqa: E402
from chunk_policy_playback import absorb_telemetry_error  # noqa: E402
from chunk_runner_commands import EMPTY_MARGIN  # noqa: E402
from chunk_runner_guards import SETTLE_TOL, safe_stderr  # noqa: E402
from chunk_runner_interrupt import folded, interrupt_step, interrupt_tick  # noqa: E402

SETTLE_S = 3.0
IDLE_PARK_S, IDLE_STOP_S, IDLE_RETRY_S = (prm.default(f"runner.idle_{k}_s") for k in ("park", "stop", "retry"))


def note_sent_grip(runner, sent) -> None:
    """Track the last written gripper goal across retimed sends while release confirmation is pending."""
    saved = getattr(runner, "_committed_grip", None)
    sent_grip = float(sent["gripper.pos"]) if isinstance(sent, dict) and "gripper.pos" in sent else None
    if getattr(runner, "_release_until", None) is not None:
        if sent_grip is not None:
            runner._committed_grip = (sent_grip, True if saved is None else saved[1])
        return
    if saved is None or sent_grip is None or abs(sent_grip - saved[0]) > 0.25 or (
        getattr(runner, "target", None) is not None and len(runner.target) >= 6 and abs(sent_grip - runner.target[5]) <= 0.25
    ):
        runner._committed_grip = None


def begin_grip_release(runner, target_grip: float | None, empty_margin: float, present=None) -> None:
    """Arm release protection against both commanded target and measured held jaw position."""
    prev, prev_floor = getattr(runner, "_release_until", None), getattr(runner, "_release_floor", None)
    if runner.holding or prev is not None:
        if getattr(runner, "_committed_grip", None) is None and getattr(runner, "target", None) is not None and len(runner.target) >= 6:
            runner._committed_grip = (float(runner.target[5]), True)
        if target_grip is not None:
            runner._release_until = float(target_grip) if prev is None else max(float(target_grip), prev)
        pose = present if present is not None else getattr(runner, "last_present", None)
        if pose is None and hasattr(runner, "present"):
            try:
                pose = runner.present()
            except Exception:  # noqa: BLE001
                pose = None
        if pose is not None and len(pose) >= 6 and (runner.holding or prev_floor is None):
            floor = float(pose[5]) + empty_margin
            runner._release_floor = floor if prev_floor is None else max(prev_floor, floor)
        elif runner.holding and prev_floor is None:
            runner._release_floor = float("inf")
    runner.holding = False


def arm_queue_release(runner, frames, *, force: bool = False, empty_margin: float = EMPTY_MARGIN) -> bool:
    """Read live jaw pose and arm release confirmation whenever a queued path opens a held jaw."""
    if not (runner.holding or getattr(runner, "_release_until", None) is not None) or not frames:
        return True
    prev = float(runner.target[5]) if getattr(runner, "target", None) is not None and len(runner.target) >= 6 else float(frames[0][5])
    peak = max(float(f[5]) for f in frames) if force else None
    for g in () if force else (float(f[5]) for f in frames):
        if g > prev + 1e-6:
            peak = g if peak is None or g > peak else peak
        else:
            prev = min(prev, g)
    if peak is None:
        return True
    from chunk_policy_playback import read_present_or_hold
    present, ok = read_present_or_hold(runner, "encoder read failed")
    if not ok:
        return False
    begin_grip_release(runner, peak, empty_margin, present)
    return True


def confirm_grip_release(runner, sent, present, *, committed: bool, empty_margin: float) -> None:
    """Track mid-trajectory held-jaw openings and drop release HOLD only after confirmed jaw opening."""
    if not committed or not getattr(runner, "_fresh_present", False) or present is None or len(present) < 6:
        return
    sent_grip = float(sent["gripper.pos"]) if isinstance(sent, dict) and "gripper.pos" in sent else None
    if sent_grip is None:
        return
    prev_sent, held_jaw = getattr(runner, "_last_sent_grip", None), getattr(runner, "_held_jaw", None)
    runner._last_sent_grip = sent_grip
    release_at = getattr(runner, "_release_until", None)
    if release_at is None:
        if held_jaw is not None and prev_sent is not None and sent_grip > prev_sent + 1e-6 and not runner.human_hold_latched:
            future = [sent_grip, *(float(f[5]) for f in (getattr(runner, "queue", None) or ()))]
            if getattr(runner, "target", None) is not None and len(runner.target) >= 6:
                future.append(float(runner.target[5]))
            release_at = runner._release_until = max(future)
            runner._release_floor = float(held_jaw) + empty_margin
            if getattr(runner, "_committed_grip", None) is None:
                runner._committed_grip = (prev_sent, True)
            runner._held_jaw = None
        else:
            runner._held_jaw = float(present[5]) if float(present[5]) > sent_grip + empty_margin else None
            return
    if runner.human_hold_latched:
        return
    floor = getattr(runner, "_release_floor", None)
    need = release_at - empty_margin if floor is None else max(release_at - empty_margin, float(floor))
    if sent_grip >= need and float(present[5]) >= need:
        runner._release_until = runner._release_floor = runner._committed_grip = runner._held_jaw = None


def confirm_post_write_present(runner, sent, committed: bool, read_fn, empty_margin: float):
    """Discard pre-write guard observation caches before sampling hardware to confirm release."""
    motion = getattr(getattr(runner, "robot", None), "motion", None)
    prev_sent, held_jaw = getattr(runner, "_last_sent_grip", None), getattr(runner, "_held_jaw", None)
    opening = held_jaw is not None and isinstance(sent, dict) and "gripper.pos" in sent and prev_sent is not None and float(sent["gripper.pos"]) > prev_sent + 1e-6
    if committed and motion is not None and (getattr(runner, "_release_until", None) is not None or opening):
        motion.last_present = None
    runner._fresh_present = False
    present, ok = read_fn(runner, "encoder read failed")
    confirm_grip_release(runner, sent, present, committed=committed, empty_margin=empty_margin)
    return present, ok


def check_chunk_settled(runner, present: list[float], error: float, now: float, cr_attr) -> None:
    """Evaluate whether the active chunk has finished its queue and settled within tolerance or timeout."""
    if runner.chunk is None or runner.queue:
        return
    runner.settle_since = runner.settle_since if runner.settle_since is not None else now
    grasp = runner.chunk.startswith("grasp")
    release = runner.chunk.startswith("release")
    gripper_still = runner.last_grip is not None and abs(present[5] - runner.last_grip) < 0.3
    runner.last_grip = present[5]
    settle_tol = cr_attr("SETTLE_TOL", SETTLE_TOL)
    settle_s = cr_attr("SETTLE_S", SETTLE_S)
    empty_margin = cr_attr("EMPTY_MARGIN", EMPTY_MARGIN)
    body_still = (
        runner.last_body is not None
        and max(abs(a - b) for a, b in zip(present[:5], runner.last_body)) < 0.08
        and error <= settle_tol + min(runner.pace_floor, 0.8)
    )
    runner.last_body = list(present[:5])
    aerial = (runner.chunk.startswith("goto ") or runner.chunk in ("above_pick", "above_place", "standby"))
    no_contact = not getattr(runner, "contact", False) and not (runner.fault or "").startswith("contact")
    if aerial and no_contact and not runner.jitter.get("shaking"):
        settled = error <= settle_tol * 1.15 or body_still or now - runner.settle_since >= settle_s
    else:
        settled = (error <= settle_tol or body_still) and not runner.jitter["shaking"]
    jaws_ready = (
        gripper_still
        if grasp
        else (
            abs(present[5] - runner.target[5]) <= 0.25
            or (gripper_still and now - runner.settle_since >= 0.4)
        )
        if release
        else True
    )
    if (settled and jaws_ready) or now - runner.settle_since >= settle_s:
        fields = dict(
            command=f"run {runner.chunk}",
            ok=True,
            settled=settled,
            paced_ticks=runner.paced_ticks,
            peak_lag=round(runner.peak_lag, 2),
            over_ticks=runner.over_ticks,
            **({"damped_ticks": runner.damped_ticks} if runner.damped_ticks else {}),
            **({"sway": runner.sway_peak} if getattr(runner, "sway_peak", None) else {}),
            **({"speed_low": round(runner.speed_low, 2)} if getattr(runner, "speed_low", 1.0) < 1.0 else {}),
        )
        runner.sway_peak, runner.speed_low = {}, 1.0
        runner.paced_ticks, runner.pace_floor, runner.peak_lag, runner.over_ticks, runner.damped_ticks = 0, 0.0, 0.0, 0, 0
        if (runner.chunk == "park" or runner.chunk.endswith("; park")) and settled and getattr(runner, "_release_until", None) is None:
            runner.home_since = now
        backed_out = runner.chunk == "retreat" and settled
        if (runner.chunk == "park" or runner.chunk.endswith("; park") or backed_out) and (
            runner.fault or ""
        ).startswith("contact"):
            runner.fault = None
        if grasp:
            by_position = present[5] > runner.target[5] + empty_margin
            fields["holding"] = by_position
            health = runner.read_health()
            if health:
                runner.health = health
                current = abs(health["current_ma"][5])
                fields["gripper_current_ma"] = current
                threshold = runner.library.get("hold_current_ma")
                if threshold is not None:
                    fields["holding"] = by_position and current >= threshold
            runner.holding = bool(fields["holding"])
        elif runner.holding and (
            runner.chunk in ("lift_pick", "park", "goto above_place", "descend_place")
            or runner.chunk.startswith(("lift_pick", "goto above_place", "descend_place"))
        ):
            runner.holding = present[5] > runner.target[5] + empty_margin
            fields["holding"] = runner.holding
        runner.chunk, runner.last_grip, runner.last_body = None, None, None
        unconfirmed_release = getattr(runner, "_release_until", None) is not None
        if unconfirmed_release:
            fields.update(ok=False, holding=True, error="release not confirmed by jaw feedback")
        stop_cmd = getattr(runner, "_stop_after_park", None)
        if stop_cmd and getattr(runner, "_interrupt", None) is None:
            runner._stop_after_park = None
            home_frames = runner.library.get("chunks", {}).get("home")
            home = home_frames[-1] if home_frames else None
            if settled and folded(present, home) and not unconfirmed_release:
                runner._stopped, runner._park_settled = True, True
                runner.report(**fields, present=present)
                runner.report(command=stop_cmd, ok=True, folded=True, reason="folded home before stop, torque goes OFF", present=present)
            else:
                runner._stopped, runner._park_settled = False, False
                why = "unconfirmed grip release" if unconfirmed_release else f"{stop_cmd} ended unsettled or short of home"
                if hasattr(runner, "hold"):
                    runner.hold(present, why, human=True)
                else:
                    runner.human_hold_latched, runner.fault = True, why
                stop_row = dict(command=stop_cmd, ok=False, folded=False, hold=True, person_needed=True, error=f"{why}; torque stays ON")
                for row in (fields, stop_row):
                    try:
                        runner.report(**row, present=present)
                    except OSError as error:
                        safe_stderr({"command": row["command"], "status_write_failed": str(error)[:300]})
            return
        runner.report(**fields, present=present)
        if stop_cmd:
            runner._stop_after_park = None
            runner._stopped, runner._park_settled = True, settled and not unconfirmed_release
            if not unconfirmed_release:
                runner.report(command=stop_cmd, ok=True, folded=settled, reason="folded home before stop, torque goes OFF", present=present)


def check_runner_idle(runner, cr_attr) -> bool:
    """Fold home, then end the session (True), when no command has come for a while."""
    if runner.chunk is not None or runner.queue or runner.pending or getattr(runner, "_release_until", None) is not None:
        return False
    quiet = runner.clock() - runner.last_input
    idle_retry_s = cr_attr("IDLE_RETRY_S", IDLE_RETRY_S)
    idle_park_s = cr_attr("IDLE_PARK_S", IDLE_PARK_S)
    idle_stop_s = cr_attr("IDLE_STOP_S", IDLE_STOP_S)
    if runner.home_since is None:
        if runner.idle_parks >= 2:
            if runner.idle_parks == 2:
                runner.idle_parks, runner.fault = 3, f"idle fold held twice ({runner.fault}): a person must free the arm"
                runner.report(command="park", ok=False, error=runner.fault, person_needed=True)
            return False
        wait = prm.get(runner.params, "runner.idle_retry_s", idle_retry_s) if runner.idle_parks else prm.get(runner.params, "runner.idle_park_s", idle_park_s)
        if quiet >= wait:
            runner.last_input = runner.clock()
            runner.idle_parks += 1
            runner.command("park")
        return False
    pushed = (runner.fault or "").startswith("pushing at rest")
    if pushed or min(quiet, runner.clock() - runner.home_since) >= prm.get(runner.params, "runner.idle_stop_s", idle_stop_s):
        runner.report(command="stop", ok=True, reason=f"{runner.fault if pushed else f'no command for {quiet:.0f} s'}; folded home, torque goes OFF")
        return True
    return False


def tick_or_report(runner, command_label: str) -> None:
    """Run one control tick, emitting a structured terminal fault status if it raises."""
    try:
        runner.tick()
    except Exception as error:
        try:
            runner.status(
                {
                    "command": command_label,
                    "ok": False,
                    "fault": f"session ended: {type(error).__name__}: {error}"[:1000],
                    "t": round(time.time(), 3),
                }
            )
        except Exception:  # noqa: BLE001
            pass
        raise


def wait_aligned_before_start(runner, lines, period: float) -> bool:
    """Wait for the guard's stationary initial alignment before admitting chunks; False stops early."""
    motion = getattr(runner.robot, "motion", None)
    while motion is not None and not getattr(motion, "tracking", True):
        if getattr(runner, "signals", None):  # interrupted before the guard tracks: folded ends, else HOLD (no motion)
            return not interrupt_step(runner, may_move=False)
        started = runner.clock()
        try:
            arrived = lines()
        except OSError as error:
            if not absorb_telemetry_error(runner, getattr(runner, "last_present", None), "command intake failed", error):
                raise
            arrived = []
        if arrived and not getattr(runner, "signals", None):  # an interrupt (checked first) drops FIFO commands
            runner.pending += arrived
            if "human-hold" in runner.pending:
                runner.pending.clear()
                runner.command("human-hold")
            stop = next(
                (i for i, cmd in enumerate(runner.pending) if cmd.strip() in ("stop", "stop now", "stop fold")),
                None,
            )
            if stop is not None and all(cmd.strip() == "state" for cmd in runner.pending[:stop]) and not getattr(
                    runner, "signals", None):
                prefix, raw_stop = list(runner.pending[:stop]), runner.pending[stop]
                for cmd in prefix:
                    if runner.human_hold_latched or getattr(runner, "signals", None):
                        break
                    runner.command(cmd)
                if not runner.human_hold_latched and not getattr(runner, "signals", None):
                    stop_cmd = raw_stop.strip()
                    fold_on_stop = stop_cmd == "stop fold" or (
                        stop_cmd != "stop now"
                        and prm.get(
                            runner.params,
                            "runner.fold_on_stop",
                            bool(runner.operating_context and runner.operating_context.get("scope") == "hardware"),
                        )
                    )
                    if not fold_on_stop and getattr(runner, "_release_until", None) is None:
                        runner.report(command=raw_stop, ok=True, present=runner.target)
                        return False
                    try:
                        present = runner.present()
                    except Exception:  # noqa: BLE001
                        present = None
                    home = runner.library.get("chunks", {}).get("home")
                    at_home = (
                        bool(home)
                        and runner.target is not None
                        and present is not None
                        and folded(present, home[-1])
                        and folded(runner.target, home[-1])
                        and not getattr(runner, "jitter", {}).get("shaking")
                        and getattr(runner, "_release_until", None) is None
                    )
                    if at_home:
                        try:
                            runner.report(command=raw_stop, ok=True, folded=True, present=present)
                            return False
                        except OSError as error:
                            safe_stderr({"command": raw_stop, "status_write_failed": str(error)[:300]})
                            runner.pending.clear()
                            if hasattr(runner, "hold"):
                                runner.hold(present, "status write failed", human=True)
                            else:
                                runner.human_hold_latched, runner.fault = True, "status write failed"
                    else:
                        runner.pending.clear()
                        why = (
                            "unconfirmed grip release"
                            if getattr(runner, "_release_until", None) is not None
                            else f"{stop_cmd} cannot fold (" + (
                                "no home chunk" if not home
                                else "no target pose" if runner.target is None
                                else "pose unreadable" if present is None
                                else "guard not tracking yet"
                            ) + ")"
                        )
                        hold_pose = present if present is not None else getattr(runner, "last_present", None) or runner.target
                        if hold_pose is not None and hasattr(runner, "hold"):
                            runner.hold(hold_pose, why, human=True)
                        else:
                            runner.human_hold_latched, runner.fault = True, why
                        row = dict(command=raw_stop, ok=False, folded=False, hold=True,
                                   person_needed=True, error=f"{why}; torque stays ON")
                        if hold_pose is not None:
                            try:
                                runner.report(**row, present=hold_pose)
                            except OSError as error:
                                safe_stderr({**row, "status_write_failed": str(error)[:300]})
                        else:
                            safe_stderr(row)
        if interrupt_tick(runner, "start", tick_or_report):
            return False
        if runner.human_hold_latched or runner.fault or getattr(motion, "held", None):
            try:
                runner.report(
                    command="start",
                    ok=False,
                    error=runner.fault or ("human hold latched" if runner.human_hold_latched else "guard hold active"),
                    present=runner.target,
                )
            except OSError as error:
                if not runner.human_hold_latched:
                    raise
                safe_stderr({"command": "start", "status_write_failed": str(error)[:300]})
            return True
        runner.sleep(max(0.0, period - (runner.clock() - started)))
    runner.report(command="start", ok=True, present=runner.target)
    return True
