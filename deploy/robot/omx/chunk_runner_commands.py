#!/usr/bin/env python3
"""Judge Command Parser & Queue Dispatcher for `chunk_runner` (`chunk_runner_commands.py`).

Single Responsibility:
  - Parses and validates judge commands (`checked`, `stop`, `episode`, `splice`, `run [rel]`,
    `jog`, `goto`, `park`, `chain`, `grip`, `retreat`, `load`, `state`) and mutates `Runner`'s
    queue/target/library state atomically.
"""
from __future__ import annotations

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
from chunk_runner_guards import (  # noqa: E402
    JOG_MAX,
    REL_MAX,
    build_chain_segments,
    build_jog_target,
    build_splice_frames,
)

EMPTY_MARGIN = 2.0


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
            runner.report(command=line, ok=True)
            return False
        if verb == "episode":
            runner.report(command=line, ok=True, **runner.recorder.command(words[1:]))
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
        if verb == "splice" and len(words) in (2, 3) and words[2:] in ([], ["rel"]):
            runner.queue = build_splice_frames(
                runner.library, words[1], words[2:] == ["rel"], runner.queue, runner.target, runner.fps
            )
            if words[1].startswith("release"):
                runner.holding = False
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
            runner.queue = [[max(-100.0, min(100.0, v + o)) for v, o in zip(f, offset)] for f in frames]
            if words[1].startswith("release"):
                runner.holding = False
            runner.chunk, runner.settle_since, runner.played, runner.contact_ticks = words[1], None, [], 0
            runner.contact_start, runner.trend, runner.pace_floor = None, [], 0.0
            return True
        if verb == "jog" and len(words) >= 3 and len(words) % 2 == 1:
            present = runner.present()
            moved = build_jog_target(words, present, runner.target)
            runner.jog_path, runner.target = (runner.jog_path or [list(runner.target)]) + [list(moved)], moved
        elif verb == "goto" and len(words) == 2:
            frames = runner.library["chunks"].get(words[1])
            if frames is None:
                raise ValueError(f"unknown chunk {words[1]}")
            transit = {NAMES.index(k): float(v) for k, v in runner.library.get("transit", {}).items()} or None
            runner.queue = transit_path(
                runner.target,
                frames[0],
                runner.library["gripper_closed"],
                runner.fps,
                transit,
                runner.library.get("transit_speed", 0.85),
            )
            runner.chunk, runner.settle_since, runner.played = f"goto {words[1]}", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "park" and len(words) == 1:
            home = runner.library["chunks"].get("home")
            if not home:
                raise ValueError("park needs a home chunk in the library")
            transit = {NAMES.index(k): float(v) for k, v in runner.library.get("transit", {}).items()} or None
            runner.queue = park_path(
                runner.target,
                home[-1],
                runner.library["gripper_closed"],
                runner.fps,
                transit,
                runner.library.get("transit_speed", 0.85),
            )
            runner.chunk, runner.settle_since, runner.played = "park", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "chain" and len(words) >= 2:
            runner.queue, runner.chunk, release = build_chain_segments(runner.library, words, runner.target, runner.fps)
            if release:
                runner.holding = False
            runner.settle_since, runner.played, runner.contact_ticks, runner.contact_start = None, [], 0, None
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "grip" and len(words) == 2:
            to = max(float(runner.library["gripper_closed"]), min(100.0, float(words[1])))
            if to > runner.target[5]:
                runner.holding = False
            present = runner.present() if to < runner.target[5] else None
            free = present is not None and abs(present[5] - runner.target[5]) <= EMPTY_MARGIN
            runner.grip_from, runner.target[5] = (runner.target[5] if free else None), to
        elif verb == "retreat" and len(words) == 1:
            if not runner.retreat_frames:
                raise ValueError("nothing to retreat along")
            keep_open = runner.target[5] > float(runner.library["gripper_closed"]) + EMPTY_MARGIN
            raw = [f[:5] + [runner.target[5]] for f in runner.retreat_frames] if keep_open else list(runner.retreat_frames)
            if len(raw) > 25 and runner.target is not None:
                best_i = min(
                    range(min(len(raw) - 1, 20)),
                    key=lambda i: max(abs(a - b) for a, b in zip(raw[i][:5], runner.target[:5])),
                )
                raw = retime(raw[best_i:], runner.fps, 0.65 * GUARD_UNITS_PER_S, start=runner.target)
            runner.queue = raw
            runner.retreat_frames = []
            runner.chunk, runner.settle_since, runner.played = "retreat", None, []
            runner.trend, runner.pace_floor = [], 0.0
            return True
        elif verb == "load" and len(words) == 2:
            try:
                library = load_library(Path(words[1]))
            except (SystemExit, OSError) as exc:
                raise ValueError(str(exc)) from None
            if library["fps"] != runner.fps:
                raise ValueError(f"library fps {library['fps']} differs from the runner fps {runner.fps}")
            lib_digest = digest(library)
            if expected_library is not None and lib_digest != expected_library:
                raise ValueError("checked load content differs from the reviewed library")
            runner.plan_check(library)
            runner.library = library
            runner._lib_digest_cache = (id(library), lib_digest)
        elif verb != "state":
            raise ValueError(
                "commands: run <chunk> [rel] | jog <joint> <delta> [...] | grip <value> | goto <chunk> | load <library> | park | state | stop"
            )
        runner.report(command=line, ok=True, present=locals().get("present"))
    except ValueError as error:
        runner.report(command=line, ok=False, error=str(error), present=locals().get("present"))
    return True
