"""A landing that shows no progress for LIMIT_S stops by itself, with every thread's stack on file.

2026-10-28: a landing's re-prepare (pid 100908) finished its 25 pretest invocations at 07:52 and then sat for
76 min with no child process, no event and its ticket "preparing", until a person killed it at 09:10; the stdout
file's last lines were still in Python's buffer, so where it hung was lost. Progress is any land event, any queue
touch (``land_events.beat``) or any remote job poll (``remote_job.LAST_POLL``, every POLL_S while a job runs).
Long silent steps beat too: land.step (lint, size_range, safety_review) and remote_pytest.remote (ship, venv
setup up to 3,600 s) run through ``remote_job.step``, which marks LAST_POLL every POLL_S while the child runs.
Past LIMIT_S without one, the watchdog writes ``faulthandler`` stacks of all threads to ``<logdir>/watchdog-<pid>.txt``,
records a ``stop`` event, removes the process's tickets and exits 3. It never writes to stdout or stderr: a blocked
stream must not block it too. Standard library only.

The same check loop is the half-hourly rollup schedule (D-889 addendum 23 item 6, addendum 32): the process holding the
turn starts ``land_rollup.py apply --auto`` from the main checkout once per ROLLUP_EVERY_S (a stamp in the git common
dir), output appended to ``<git-common-dir>/rosy-land-rollup.log``. Only the turn holder: it is never a rollup member,
so the rollup's stop of its members cannot reach the child.
"""

from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

LIMIT_S = 30 * 60.0
CHECK_S = 60.0
ROLLUP_EVERY_S = 30 * 60.0
STAMP, ROLLUP_LOG = "rosy-land-rollup.stamp", "rosy-land-rollup.log"


def rollup_due(land_events, land_queue, now=time.time) -> Path | None:
    """The git common dir when this process holds the turn and no rollup started for ROLLUP_EVERY_S (claims it)."""
    path = land_events._where.get("path")
    if path is None or not any(land_queue.owns_turn(t) for t in list(land_queue._held)):
        return None
    stamp = Path(path).parent / STAMP
    try:
        if now() - stamp.stat().st_mtime < ROLLUP_EVERY_S:
            return None
    except FileNotFoundError:
        pass
    stamp.touch()
    os.utime(stamp)
    return stamp.parent


def rollup(common: Path, popen=subprocess.Popen):
    """``land_rollup.py apply --auto`` from main's checkout (land code runs from main), detached from our stdout."""
    main = common.parent
    # shortcut: a --replace of the turn holder (taskkill /T) also ends this child mid-build; detach fully if seen.
    with open(common / ROLLUP_LOG, "a", encoding="utf-8") as out:
        return popen([sys.executable, "-X", "utf8", str(main / "tools" / "land_rollup.py"), "apply", "--auto"],
                     cwd=main, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=0x08000000 if os.name == "nt" else 0)  # CREATE_NO_WINDOW


def idle(land_events, remote_job, clock=time.monotonic) -> float:
    return clock() - max(land_events.LAST[0], getattr(remote_job, "LAST_POLL", 0.0))


def start(logdir: Path, land_events, land_queue, remote_job, limit: float = LIMIT_S, check: float = CHECK_S,
          clock=time.monotonic, sleep=time.sleep, exit_=os._exit) -> threading.Thread:
    def watch() -> None:
        while True:
            sleep(check)
            try:
                if common := rollup_due(land_events, land_queue):
                    rollup(common)
            except (OSError, ValueError):
                pass  # a rollup that cannot start never costs the landing
            quiet = idle(land_events, remote_job, clock)
            if quiet <= limit:
                continue
            dump = Path(logdir) / f"watchdog-{os.getpid()}.txt"
            try:
                dump.parent.mkdir(parents=True, exist_ok=True)
                with dump.open("w", encoding="utf-8") as out:
                    faulthandler.dump_traceback(file=out, all_threads=True)
            except OSError:
                dump = None
            land_events.emit("stop", reason=f"watchdog: no progress for {quiet / 60:.0f} min (no event, queue touch"
                                            f" or remote poll); thread stacks in {dump}")
            land_queue.leave()
            exit_(3)
            return
    thread = threading.Thread(target=watch, name="land-watchdog", daemon=True)
    thread.start()
    return thread
