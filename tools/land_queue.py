"""Landing queue for tools/land.py: sessions of one clone land one at a time, first come first served.

On 2026-10-18 ``fix/fleet-network-load-v2`` needed four land rounds (~2.5 h): every round passed, but
another session had landed on ``main`` meanwhile, so the next round merged the new ``main`` and tested
again. Every worktree of a clone shares the git common dir, so the queue lives there:
``<git-common-dir>/rosy-land-queue/<start ns>-<pid>.json``, one ticket per waiting or landing run.
File names sort in arrival order. A ticket is written under a dot name and renamed into place, so a
reader never sees half of one. The first live ticket may test and land; the rest wait, then merge
``main`` once. A ticket is stale, and the next reader removes it, when its holder's PID is gone on
this host or it was not refreshed for ``STALE_AFTER`` (the holder refreshes it every poll and round).
``leave`` runs from land.py's ``finally`` and from ``atexit`` (Ctrl-C included); a killed process
leaves a ticket the PID check reclaims. Standard library only.
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import time

import land_events  # rosy-land-events.jsonl (queue and turn lines)
from pathlib import Path

QUEUE = "rosy-land-queue"
STALE_AFTER = 3 * 3600  # seconds without a refresh; one FULL round takes 30-90 min, the holder refreshes per round
POLL = 10.0
REPORT_EVERY = 300.0  # seconds between unchanged position lines
_held: list[Path] = []


class QueueError(Exception):
    """Waiting for the queue failed; the message says why. land.py exits 1."""


def pid_alive(pid: int) -> bool:
    """Whether a process with this id exists. Never signals it (os.kill on Windows would end it).

    Same as tools/release/publish_payload_release.pid_alive (not imported: that module pulls in signing).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def queue_dir(wt: Path) -> Path:
    common = subprocess.run(["git", "-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return Path(common.stdout.strip()) / QUEUE


def take(qdir: Path, branch: str, worktree: str = "", status: str = "waiting") -> Path:
    """Write this process's ticket at the end of the queue and return its path.

    ``status``: ``pending`` (waiting for a preparation slot) or ``preparing`` (tests outside the lock: keeps its
    place, blocks no one; ``land_prepare.py``), ``waiting``,
    or ``turn`` (merging, testing, landing). A ticket without one (an older land.py) counts as waiting."""
    qdir.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    while (qdir / f"{stamp:020d}-{os.getpid()}.json").exists():  # one process, one clock tick (Windows)
        stamp += 1
    name = f"{stamp:020d}-{os.getpid()}.json"
    info = {"pid": os.getpid(), "host": socket.gethostname(), "start": time.time(), "branch": branch,
            "worktree": worktree, "status": status}
    tmp = qdir / f".{name}.tmp"
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, qdir / name)
    return qdir / name


def _stale(info: dict | None, age: float) -> str | None:
    if age > STALE_AFTER:
        return f"not refreshed for {age / 60:.0f} min"
    if info and info.get("host") == socket.gethostname() and not pid_alive(int(info.get("pid") or 0)):
        return f"pid {info.get('pid')} is gone"
    # shortcut: a reused PID looks alive; STALE_AFTER still reclaims it.
    return None


def set_status(ticket: Path, status: str, **fields) -> None:
    """Rewrite a held ticket's status (and ``fields``, e.g. ``batch``) by rename (also refreshes it)."""
    info = json.loads(ticket.read_text(encoding="utf-8"))
    tmp = ticket.with_name(f".{ticket.name}.tmp")
    tmp.write_text(json.dumps({**info, **fields, "status": status}), encoding="utf-8")
    os.replace(tmp, ticket)


def blockers(qdir: Path, ticket: Path, now: float | None = None) -> list[dict]:
    """Who keeps ``ticket`` from its turn: any ticket in its turn, every earlier one not preparing, and a
    batch leader (``land_batch.py``) whose ``batch`` names this ticket's branch, wherever it stands.

    A FULL tier in the lock held every lander behind it for 40+ min (2026-10-26); a preparing ticket now
    runs it outside the lock and keeps its place."""
    rows = ahead(qdir, Path("~"), now)  # every live ticket ("~" sorts after the digits)
    mine = next((r.get("branch") for r in rows if r["ticket"] == ticket.name), None)
    return [r for r in rows if r["ticket"] != ticket.name and (
        r.get("status") == "turn" or (mine is not None and mine in (r.get("batch") or []))
        or (r["ticket"] < ticket.name and r.get("status") not in ("preparing", "pending")))]


def ahead(qdir: Path, ticket: Path, now: float | None = None) -> list[dict]:
    """Live tickets before ``ticket``, oldest first; stale ones on the way are removed."""
    now = time.time() if now is None else now
    found = []
    for path in sorted(qdir.glob("[0-9]*.json")):
        if path.name >= ticket.name:
            break
        try:
            age = now - path.stat().st_mtime
            info = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue  # its holder left meanwhile
        except (OSError, ValueError):
            info = None  # unreadable: live until STALE_AFTER
        why = _stale(info, age)
        if why:
            path.unlink(missing_ok=True)
            print(f"[queue] removed stale ticket {path.name} ({(info or {}).get('branch', '?')}): {why}", flush=True)
            continue
        found.append({**(info or {}), "ticket": path.name, "age": now - (info or {}).get("start", now)})
    return found


def describe(rows: list[dict]) -> str:
    return ", ".join(f"{r.get('branch', '?')} ({r.get('status', 'waiting')}, pid {r.get('pid', '?')} on "
                     f"{r.get('host', '?')}, {r['age'] / 60:.0f} min)" for r in rows)


def touch(ticket: Path | None = None) -> None:
    """Refresh a held ticket so others do not reclaim it while its holder still waits or tests."""
    for path in [ticket] if ticket else list(_held):
        try:
            os.utime(path)
        except OSError:
            pass


def wait(qdir: Path, ticket: Path, timeout: float, clock=time.time, sleep=time.sleep, check=None,
         done=None, form=None) -> str | None:
    """Mark ``ticket`` waiting; return None once nothing blocks it (``blockers``), marked as in its turn;
    QueueError after ``timeout`` seconds (0: no limit), or as soon as ``check()`` names a reason to stop.
    ``"landed"`` as soon as ``done()`` is true (a batch landed this branch), ``"batch"`` when ``form(rows)``
    made this ticket a batch leader while ``rows`` blocked it (``land_batch.py``)."""
    set_status(ticket, "waiting")
    began, said, last = clock(), None, 0.0
    while True:
        if done and done():
            return "landed"
        rows = blockers(qdir, ticket, clock())
        if not rows:
            if said is not None:
                print(f"[queue] first in line after {(clock() - began) / 60:.0f} min", flush=True)
            land_events.emit("turn", waited_s=round(clock() - began))
            set_status(ticket, "turn")
            return None
        if form and form(rows):
            return "batch"
        if len(rows) != said or clock() - last >= REPORT_EVERY:
            print(f"[queue] position {len(rows) + 1}; ahead: {describe(rows)}", flush=True)
            said, last = len(rows), clock()
        if check and (why := check()):
            raise QueueError(f"{why}. Nothing was merged or tested; fix it on the branch and run land.py again")
        if timeout and clock() - began >= timeout:
            raise QueueError(f"waited {timeout / 60:.0f} min in the landing queue ({qdir}), {len(rows)} still"
                             f" ahead: {describe(rows)}. Nothing was merged or tested. Run land.py again later;"
                             " during an incident, --no-queue lands without waiting")
        touch(ticket)
        sleep(POLL)


def enter(wt: Path, branch: str, status: str = "waiting") -> tuple[Path, Path]:
    """Take a ticket (its place in the queue) and release it at exit whatever happens; (queue dir, ticket)."""
    qdir = queue_dir(wt)
    ticket = take(qdir, branch, str(wt), status)
    _held.append(ticket)
    atexit.register(leave)
    print(f"[queue] ticket {ticket.name} in {qdir}", flush=True)
    land_events.emit("queue", ticket=ticket.name, position=len(ahead(qdir, ticket)) + 1)
    return qdir, ticket


def join(wt: Path, branch: str, timeout: float) -> Path:
    """Take a ticket, release it at exit whatever happens, and wait until it is first."""
    qdir, ticket = enter(wt, branch)
    wait(qdir, ticket, timeout)
    return ticket


def leave() -> None:
    """Remove every ticket this process holds. Safe to call twice."""
    while _held:
        _held.pop().unlink(missing_ok=True)
