#!/usr/bin/env python3
"""Judge Command Parser & Queue Dispatcher for `chunk_runner` (`chunk_runner_commands.py`).

Single Responsibility:
  - Parses and validates judge commands (`checked`, `stop`, `episode`, `splice`, `run [rel]`,
    `jog`, `goto`, `park`, `chain`, `grip`, `retreat`, `load`, `state`) and mutates `Runner`'s
    queue/target/library state atomically.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import uuid

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)

from omx_adapter.chunk_library import GUARD_UNITS_PER_S, NAMES, load_library, park_path, transit_path  # noqa: E402
from omx_adapter.motion_profile import retime  # noqa: E402
from cell_envelope import digest  # noqa: E402
import cell_params as prm  # noqa: E402
from chunk_policy_playback import active_jaw_gate, check_runner_jaw_gate, halt_policy_gate, read_present_or_hold  # noqa: E402
from chunk_runner_guards import (  # noqa: E402
    JOG_MAX,
    REL_MAX,
    SETTLE_TOL,
    build_chain_segments,
    build_jog_target,
    build_splice_frames,
    library_gripper_closed,
    library_transit_speed,
    parse_transit,
    policy_requires_jaw_gate,
    safe_stderr,
)

EMPTY_MARGIN = 2.0


def _clear_trailing_gate(runner, *, stop_motion: bool = True) -> None:
    if getattr(runner, "_trailing_jaw_gate", None) is None:
        return
    if stop_motion:
        stop = getattr(getattr(getattr(runner, "robot", None), "motion", None), "stop_streaming", None)
        if callable(stop):
            stop()
    runner._trailing_jaw_gate = None


def _begin_release(runner, target_grip: float | None, present=None) -> None:
    from chunk_runner_settle import begin_grip_release

    begin_grip_release(runner, target_grip, EMPTY_MARGIN, present)


def _arm_release(runner, frames, *, force: bool = False) -> bool:
    from chunk_runner_settle import arm_queue_release

    return arm_queue_release(runner, frames, force=force, empty_margin=EMPTY_MARGIN)


def _latch_status_write_error(runner, present, command: str, reason: str | None, error: OSError) -> None:
    if not runner.human_hold_latched:
        pose = present if present is not None else getattr(runner, "last_present", None)
        if pose is None and getattr(runner, "target", None) is not None:
            pose = list(runner.target)
        msg = f"status write failed ({reason})" if reason else "status write failed"
        if pose is not None:
            runner.hold(pose, msg, human=True)
        else:
            runner.human_hold_latched = True
            runner.fault = msg
    safe_stderr({"command": command, **({"error": reason} if reason else {}),
                 "status_write_failed": str(error)[:300]})


def dispatch_runner_command(runner, line: str) -> bool:
    """Apply one judge command to `runner`; False means stop."""
    words = line.split()
    if not words:
        return True
    verb = words[0]
    expected_library = None
    if verb not in ("state", "stop", "park"):
        runner.home_since = None
    try:
        ep_words = words[3:] if verb == "checked" and len(words) >= 4 else words
        is_episode_close = ep_words[:1] == ["episode"] and ep_words[1:2] in (["fail"], ["drop"])
        if runner.human_hold_latched and verb not in ("state", "human-hold") and not is_episode_close:
            raise ValueError("human hold latched: only state or human-hold")
        if verb == "human-hold":
            if len(words) != 1:
                raise ValueError("human-hold takes no arguments")
            try:
                pose = runner.present()
            except Exception:  # noqa: BLE001  an unread pose holds the last known one, never ends in torque OFF
                pose = list(getattr(runner, "last_present", None) or runner.target)
            runner.hold(pose, "human hold", human=True)
            return True
        if verb not in ("checked", "state", "stop") and runner.operating_context:
            runner.operating_context = {**runner.operating_context, "session_id": uuid.uuid4().hex}
        if verb == "checked":
            if len(words) < 4:
                raise ValueError("checked requires session, library digest and command")
            session, expected_library, words = words[1], words[2], words[3:]
            line, verb = " ".join(words), words[0]
            if not runner.operating_context or runner.operating_context.get("session_id") != session:
                raise ValueError("checked command targets another session")
            if verb != "load" and runner._library_digest() != expected_library:
                raise ValueError("checked command targets another library")
        runner.grip_from = runner.grip_from if verb in ("state", "grip", "episode") else None
        runner.jog_path = runner.jog_path if verb in ("jog", "state", "episode") else []
        if verb == "stop":
            fold_on_stop = words[1:] == ["fold"] or (
                words[1:] != ["now"]
                and prm.get(
                    runner.params,
                    "runner.fold_on_stop",
                    bool(runner.operating_context and runner.operating_context.get("scope") == "hardware"),
                )
            )
            home = runner.library.get("chunks", {}).get("home") if fold_on_stop else None
            held = getattr(getattr(runner.robot, "motion", None), "held", None)
            hard_fault = bool(runner.fault and not runner.fault.startswith("contact"))
            present, at_home = None, False
            if fold_on_stop or getattr(runner, "_release_until", None) is not None:
                if getattr(runner, "_stop_after_park", None):
                    return True
                try:
                    present = runner.present()
                except Exception:  # noqa: BLE001
                    present = None
                at_home = (
                    bool(home)
                    and runner.target is not None
                    and present is not None
                    and max(
                        max(abs(a - b) for a, b in zip(runner.target[:5], home[-1][:5])),
                        max(abs(a - b) for a, b in zip(present[:5], home[-1][:5])),
                    ) <= SETTLE_TOL
                    and not getattr(runner, "jitter", {}).get("shaking")
                    and getattr(runner, "_release_until", None) is None
                )
                if not at_home:
                    if home and runner.target is not None and present is not None and not held and not hard_fault and getattr(runner, "_release_until", None) is None:
                        transit = parse_transit(runner.library)
                        grip_park = runner.target[5] if not runner.holding else library_gripper_closed(runner.library)
                        frames = park_path(list(present[:5]) + [runner.target[5]], home[-1], grip_park, runner.fps, transit,
                                           library_transit_speed(runner.library))
                        halt_policy_gate(runner)
                        runner.queue = frames
                        runner.chunk, runner.settle_since, runner.played = "park", None, []
                        runner.trend, runner.pace_floor, runner._stop_after_park = [], 0.0, line
                        return True
                    why = (
                        "unconfirmed grip release" if getattr(runner, "_release_until", None) is not None
                        else "no home chunk" if not home
                        else "no target pose" if runner.target is None
                        else "pose unreadable" if present is None
                        else f"guard hold {held}" if held
                        else f"fault {runner.fault}" if hard_fault
                        else "arm shaking at home"
                    )
                    hold_pose = present if present is not None else getattr(runner, "last_present", None) or getattr(runner, "target", None)
                    if hold_pose is not None:
                        if hasattr(runner, "hold"):
                            runner.hold(hold_pose, why, human=True)
                        else:
                            runner.human_hold_latched, runner.fault = True, why
                        try:
                            runner.report(
                                command=line, ok=False, folded=False, hold=True,
                                person_needed=True, error=f"{why}; torque stays ON", present=hold_pose,
                            )
                        except OSError as write_error:
                            _latch_status_write_error(runner, hold_pose, line, why, write_error)
                    else:
                        runner.human_hold_latched, runner.fault = True, why
                        safe_stderr({"command": line, "ok": False, "folded": False, "hold": True,
                                     "person_needed": True, "error": f"{why}; torque stays ON"})
                    return True
            try:
                runner.report(command=line, ok=True, **({"present": present} if fold_on_stop else {}))
            except OSError as write_error:
                _latch_status_write_error(runner, present if fold_on_stop else None, line, None, write_error)
            return bool(runner.human_hold_latched)
        if verb == "episode":
            from episode_recorder import dispatch_episode_command
            dispatch_episode_command(runner, words, line, _latch_status_write_error)
            return True
        if runner.chunk is not None and verb != "splice":
            raise ValueError(f"chunk {runner.chunk} is still running")
        if getattr(getattr(runner.robot, "motion", None), "held", None) and verb != "state":
            raise ValueError("the guard holds an overloaded joint: the runner is shedding its load first")
        soft = (runner.fault or "").startswith("contact")
        if runner.fault and verb not in ("park", "state") and not (soft and verb in ("retreat", "jog", "grip")):
            raise ValueError(
                f"fault ({runner.fault}): only park, state or stop"
                + (", or retreat/jog/grip after a contact" if soft else "")
            )
        if verb in ("run", "goto", "park", "chain", "splice", "retreat"):
            runner._damp_cooldown = 0
        if verb == "splice" and len(words) in (2, 3) and words[2:] in ([], ["rel"]):
            if (runner.policy_playback is not None or getattr(runner, "jaw_gate", None) is not None
                    or (words[1] == "policy" and ("policy_playback" in runner.library or "jaw_gate" in runner.library
                                                  or policy_requires_jaw_gate(runner)))):
                raise ValueError("cannot splice a timed or jaw-gated policy chunk")
            spliced = build_splice_frames(runner.library, words[1], words[2:] == ["rel"], runner.queue, runner.target, runner.fps)
            if not _arm_release(runner, spliced, force=words[1].startswith("release")):
                return True
            halt_policy_gate(runner)
            runner.queue = spliced
            runner.chunk = words[1] if runner.chunk is None else f"{runner.chunk} -> {words[1]}"
            runner.settle_since, runner.contact_ticks, runner.contact_start = None, 0, None
            return True
        if verb == "run" and len(words) in (2, 3) and words[2:] in ([], ["rel"]):
            frames = runner.library["chunks"].get(words[1])
            if frames is None:
                raise ValueError(f"unknown chunk {words[1]}")
            start = frames[0]
            offset = [0.0] * 6
            if words[2:] == ["rel"]:
                offset = [t - s for t, s in zip(runner.target[:5], start[:5])] + [0.0]
                if max(abs(v) for v in offset) > REL_MAX:
                    raise ValueError(f"relative offset {max(abs(v) for v in offset):.1f} exceeds {REL_MAX}")
            gap = max(abs(a + o - b) for a, o, b in zip(start[:5], offset, runner.target[:5]))
            if gap > JOG_MAX * 2:
                raise ValueError(f"chunk {words[1]} starts {gap:.1f} away from the held target")
            new_play, new_gate = None, None
            if words[1] == "policy" and "policy_playback" in runner.library:
                from chunk_policy_playback import start

                if len(words) != 2:
                    raise ValueError("timed policy frames cannot be shifted")
                new_play = start(runner)
                new_gate = new_play.jaw_gate
            elif words[1] == "policy" and "jaw_gate" in runner.library:
                from chunk_policy_playback import start_jaw_gate

                if len(words) != 2:
                    raise ValueError("jaw-gated policy frames cannot be shifted")
                new_gate = start_jaw_gate(runner, runner.library["jaw_gate"])
            if words[1] == "policy" and new_gate is None and policy_requires_jaw_gate(runner):
                raise ValueError("policy chunk requires jaw_gate when grasp_pick or rim height is configured")
            queued = [[max(-100.0, min(100.0, v + o)) for v, o in zip(f, offset)] for f in frames]
            if not _arm_release(runner, queued, force=words[1].startswith("release")):
                return True
            if words[1] == "policy":
                same_gate = new_gate is not None and new_gate.same_as(getattr(runner, "_trailing_jaw_gate", None))
                _clear_trailing_gate(runner, stop_motion=not same_gate)
            else:
                halt_policy_gate(runner)
            runner.policy_playback = new_play
            runner.jaw_gate = None if new_play is not None else new_gate
            runner.queue = queued
            runner.chunk, runner.settle_since, runner.played, runner.contact_ticks = words[1], None, [], 0
            runner.contact_start, runner.trend, runner.pace_floor = None, [], 0.0
            return True
        if verb == "jog" and len(words) >= 3 and len(words) % 2 == 1:
            present, ok = read_present_or_hold(runner, "encoder read failed")
            if not ok:
                return True
            moved = build_jog_target(words, present, runner.target)
            play = runner.policy_playback if runner.chunk == "policy" else None
            gate = None if runner.human_hold_latched else active_jaw_gate(runner, play)
            if gate is not None and not check_runner_jaw_gate(runner, gate, moved, play.receipt() if play else None):
                return True
            halt_policy_gate(runner)
            if getattr(runner, "_committed_grip", None) is None and moved[5] != runner.target[5]:
                runner._committed_grip = (runner.target[5], runner.holding)
            if moved[5] > runner.target[5]:
                _begin_release(runner, moved[5], present)
            runner.jog_path, runner.target = (runner.jog_path or [list(runner.target)]) + [list(moved)], moved
        elif verb == "goto" and len(words) == 2:
            if words[1] == "policy" and ("policy_playback" in runner.library or "jaw_gate" in runner.library
                                          or policy_requires_jaw_gate(runner)):
                raise ValueError("cannot goto a timed or jaw-gated policy chunk")
            frames = runner.library["chunks"].get(words[1])
            if frames is None:
                raise ValueError(f"unknown chunk {words[1]}")
            path = transit_path(
                runner.target, frames[0], library_gripper_closed(runner.library),
                runner.fps, parse_transit(runner.library), library_transit_speed(runner.library),
            )
            if not _arm_release(runner, path):
                return True
            halt_policy_gate(runner)
            runner.queue = path
            runner.chunk, runner.settle_since, runner.played = f"goto {words[1]}", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "park" and len(words) == 1:
            home = runner.library["chunks"].get("home")
            if not home:
                raise ValueError("park needs a home chunk in the library")
            path = park_path(
                runner.target, home[-1], library_gripper_closed(runner.library),
                runner.fps, parse_transit(runner.library), library_transit_speed(runner.library),
            )
            if not _arm_release(runner, path):
                return True
            halt_policy_gate(runner)
            runner.queue = path
            runner.chunk, runner.settle_since, runner.played = "park", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "chain" and len(words) >= 2:
            path, label, release = build_chain_segments(
                runner.library, words, runner.target, runner.fps, require_policy_gate=policy_requires_jaw_gate(runner)
            )
            if not _arm_release(runner, path, force=release is not None):
                return True
            halt_policy_gate(runner)
            runner.queue, runner.chunk = path, label
            runner.settle_since, runner.played, runner.contact_ticks, runner.contact_start = None, [], 0, None
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "grip" and len(words) == 2:
            raw_grip = float(words[1])
            if not math.isfinite(raw_grip):
                raise ValueError("grip target must be finite")
            to = max(library_gripper_closed(runner.library), min(100.0, raw_grip))
            play = runner.policy_playback if runner.chunk == "policy" else None
            gate = None if runner.human_hold_latched else active_jaw_gate(runner, play)
            if to != runner.target[5] or gate is not None or runner.holding or getattr(runner, "_release_until", None) is not None:
                present, ok = read_present_or_hold(runner, "encoder read failed")
                if not ok:
                    return True
            else:
                present = None
            if gate is not None and not check_runner_jaw_gate(
                runner, gate, [*runner.target[:5], to], play.receipt() if play else None
            ):
                return True
            if getattr(runner, "_committed_grip", None) is None and to != runner.target[5]:
                runner._committed_grip = (runner.target[5], runner.holding)
            if to > runner.target[5]:
                _begin_release(runner, to, present)
            free = present is not None and abs(present[5] - runner.target[5]) <= EMPTY_MARGIN
            runner.grip_from, runner.target[5] = (runner.target[5] if free else None), to
        elif verb == "retreat" and len(words) == 1:
            if not runner.retreat_frames:
                raise ValueError("nothing to retreat along")
            keep_open = runner.target[5] > library_gripper_closed(runner.library) + EMPTY_MARGIN
            raw = [f[:5] + [runner.target[5]] for f in runner.retreat_frames] if keep_open else list(runner.retreat_frames)
            if runner.target is not None and raw:
                if len(raw) > 2:
                    best_i = min(
                        range(min(len(raw) - 1, 20)),
                        key=lambda i: max(abs(a - b) for a, b in zip(raw[i][:5], runner.target[:5])),
                    )
                    raw = raw[best_i:]
                hold = [list(runner.target)] * 4
                raw = hold + retime(raw, runner.fps, 0.25 * GUARD_UNITS_PER_S, start=runner.target)
            if not _arm_release(runner, raw):
                return True
            halt_policy_gate(runner)
            runner.queue = raw
            runner.retreat_frames = []
            runner.chunk, runner.settle_since, runner.played = "retreat", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "load" and len(words) == 2:
            try:
                library = load_library(Path(words[1]))
            except (SystemExit, OSError, OverflowError, TypeError) as exc:
                raise ValueError(str(exc)) from None
            if library["fps"] != runner.fps:
                raise ValueError(f"library fps {library['fps']} differs from the runner fps {runner.fps}")
            lib_digest = digest(library)
            if expected_library is not None and lib_digest != expected_library:
                raise ValueError("checked load content differs from the reviewed library")
            runner.plan_check(library)
            runner.library = library
            runner._lib_digest_cache = (id(library), lib_digest)
            if library.get("holding") is True:
                runner.holding = True
        elif verb != "state":
            raise ValueError(
                "commands: run <chunk> [rel] | jog <joint> <delta> [...] | grip <value> | goto <chunk> | load <library> | park | human-hold | state | stop"
            )
        try:
            runner.report(command=line, ok=True, present=locals().get("present"))
        except OSError as write_error:
            _latch_status_write_error(runner, locals().get("present"), line, None, write_error)
    except ValueError as error:
        try:
            runner.report(command=line, ok=False, error=str(error), present=locals().get("present"))
        except OSError as write_error:
            _latch_status_write_error(runner, locals().get("present"), line, str(error), write_error)
    return True
