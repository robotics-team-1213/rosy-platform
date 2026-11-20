"""The FIFO place a land_async supervisor holds before land.py starts (11-19: 792 of 958 STOPs were "queue full").

Only the oldest live waiter in each queue lane (<tree>.roomwait, first request time in <tree>.requested) may reserve, under
land_queue.reserve()'s lock; the marker is kept in ``taken`` until land_async hands it to land.py.
Lives beside land_async (its copy runs beside the log) and is imported from main's tools/ after land_async._queue().
"""
from __future__ import annotations

import time
import os
from pathlib import Path

def note_stop(row: dict, why: str) -> None:
    """Before ending a landing on purpose (taskkill /F: exit 1, nothing logged): its supervisor reports `why`."""
    if wt := row.get("worktree"):
        tree = Path(wt)
        (tree.parent / (tree.name + ".killed")).write_text(why + "\n", encoding="utf-8")


def stopped_text(tree: Path, log: Path, code: int) -> str:
    """The .stopped note; a note_stop reason (ended on purpose) goes into it and, appended, into the .log."""
    note = tree.parent / (tree.name + ".killed")
    why = note.read_text(encoding="utf-8").strip() if note.is_file() else ""
    note.unlink(missing_ok=True)
    if why:
        with open(log, "a", encoding="utf-8") as out:
            out.write(f"[land-async] land.py was ended on purpose: {why}\n")
    return f"land.py exit {code}{f' (ended on purpose: {why})' if why else ''}; read {tree.name}.log\n"


taken: dict[str, Path] = {}  # tree -> the reservation reserve_now took for it


def reserve_now(tree: Path, land_queue, mine: Path, start: str) -> bool:
    """One FIFO poll for this lane, with reserve() enforcing its capacity under lock."""
    mine.write_text(start, "utf-8")  # rewritten each poll: a waiter silent for 5 min is not in line
    lane = land_queue.lane_of(tree)
    now = time.time()
    try:
        for waiter in mine.parent.glob("*.roomwait"):
            if waiter == mine or now - waiter.stat().st_mtime >= 300:
                continue
            if (waiter.read_text("utf-8"), waiter.name) < (start, mine.name):
                waiting_tree = waiter.with_name(waiter.name.removesuffix(".roomwait"))
                if land_queue.lane_of(waiting_tree) == lane:
                    return False
    except OSError:
        return False
    try:
        taken[str(tree)] = land_queue.reserve(land_queue.queue_dir(tree), tree.name, lane)
    except land_queue.QueueError:
        return False  # still full: stay first in line
    mine.unlink(missing_ok=True)  # no longer waiting: it must not block the next in line
    return True


def place(tree: Path) -> tuple[Path, str]:
    """The waiter file and the first request time (written once, never reset)."""
    mine = tree.parent / (tree.name + ".roomwait")
    requested = tree.parent / (tree.name + ".requested")
    if not requested.exists():
        requested.write_text(str(time.time_ns()), "utf-8")
    return mine, requested.read_text("utf-8").strip()


def wait_for_room(tree: Path, deadline: float, land_queue) -> bool:
    mine, start = place(tree)
    while time.monotonic() < deadline:
        if reserve_now(tree, land_queue, mine, start):
            return True
        time.sleep(60)
    return False


def gate(tree: Path, land_queue, room, deadline: float, window: float) -> tuple[float, Path | None]:
    """(deadline, marker) before land.py starts: reserve at once as FIFO head, else wait via room (wait_drain).
    Deadline 0.0: no place in the window. Marker None: a room check that reserved nothing (land.py reserves itself);
    a marker is handed to land.py in RESERVED_ENV."""
    if str(tree) not in taken and not reserve_now(tree, land_queue, *place(tree)):
        deadline = land_queue.wait_drain(tree, room, deadline, window)
        if not deadline:
            return 0.0, None
    marker = taken.pop(str(tree), None)
    if marker is not None:
        os.environ[land_queue.RESERVED_ENV] = str(marker)
    return deadline, marker


def release(land_queue, marker: Path) -> None:
    """After land.py: drop the env and any marker it did not consume at enter()."""
    os.environ.pop(land_queue.RESERVED_ENV, None)
    land_queue.unreserve(marker)
