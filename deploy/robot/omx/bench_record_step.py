"""What the bench is waiting for between pressing Start/Home and the first recorded frame (status.json "starting_step").

Values: follower_home, leader_align (state "step"), then from the recorder's own log: starting_recorder (no log yet),
connecting_cameras (lerobot up, "Recording episode" not printed), aligning (guard phase=aligning; "starting_deg_left" is the
largest remaining joint error). None once the guard tracks. "starting_arm" is the arm whose step is shown (arm_ab homes one after the other). The step never goes
backwards within one start (the furthest one reached is kept), and is cleared when the start ends. Also: the home-skip test of go_home.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import time


ORDER = ("follower_home", "leader_align", "starting_recorder", "connecting_cameras", "aligning", "done")


def _raw_step(state, tail_bytes):
    status = state.get("status")
    if status == "homing":
        return state.get("step"), None
    if status not in ("handing_over", "recording") or not state.get("folder"):
        return None, None
    log = Path(state["folder"]) / "bench.log"
    try:
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - tail_bytes))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ("starting_recorder" if status == "handing_over" else "done"), None
    if "Recording episode" not in text:
        return ("connecting_cameras" if "Using video codec" in text else "starting_recorder"), None
    last_aligning, last_aligned = text.rfind("phase=aligning"), text.rfind(": aligned;")
    if last_aligning > last_aligned:
        found = re.findall(r"error_deg=([0-9.]+)", text[last_aligning:].split("\n", 1)[0])
        return "aligning", (max(map(float, found)) if found else None)
    return "done", None


def starting_step(state, memory=None, tail_bytes=60000):
    """memory: a dict the caller keeps between polls; with it the step never goes back within one start."""
    memory = {} if memory is None else memory
    step, degrees = _raw_step(state, tail_bytes)
    if state.get("status") not in ("homing", "handing_over", "recording"):
        memory.clear()  # the start has ended
        return {"starting_step": None, "starting_deg_left": None, "starting_arm": None}
    key = (state.get("name"), state.get("step_arm"), state.get("folder"))
    if memory.get("key") != key:
        memory.clear()
        memory["key"] = key
    if step in ORDER and ORDER.index(step) < memory.get("rank", -1):
        step, degrees = ORDER[memory["rank"]], None  # an earlier phrase fell out of the log tail: keep the furthest step
    elif step in ORDER:
        memory["rank"] = ORDER.index(step)
    return {"starting_step": None if step == "done" else step, "starting_deg_left": degrees, "starting_arm": state.get("step_arm")}


HOME_SKIP_UNITS = 1.0  # normalized units (200 per calibrated range, about 1.8 degrees on a full range): inside 2 degrees


def at_home(live_path, library_path, since, now=time.time, units=HOME_SKIP_UNITS):
    """True when the runner's live body pose (read from a file the running recorder already writes: no extra bus
    process) is within `units` of the library home the real home uses (its last frame) on all five body joints. Written after
    `since` (this request began) and at most 3 s ago. Any doubt (stale, missing) is False."""
    try:
        written = Path(live_path).stat().st_mtime
        if written <= since or not 0 <= now() - written <= 3.0:
            return False
        live = json.loads(Path(live_path).read_text(encoding="utf-8"))["state"]
        home = json.loads(Path(library_path).read_text(encoding="utf-8"))["chunks"]["home"][-1]
        return len(live) >= 5 and len(home) >= 5 and all(
            isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= units for a, b in zip(live[:5], home[:5]))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return False
