"""A landing that shows no progress for LIMIT_S stops by itself, with every thread's stack on file.

2026-10-28: a landing's re-prepare (pid 100908) finished its 25 pretest invocations at 07:52 and then sat for
76 min with no child process, no event and its ticket "preparing", until a person killed it at 09:10; the stdout
file's last lines were still in Python's buffer, so where it hung was lost. Progress is any land event, any queue
touch (``land_events.beat``) or any remote job poll (``remote_job.LAST_POLL``, every POLL_S while a job runs).
Past LIMIT_S without one, the watchdog writes ``faulthandler`` stacks of all threads to ``<logdir>/watchdog-<pid>.txt``,
records a ``stop`` event, removes the process's tickets and exits 3. It never writes to stdout or stderr: a blocked
stream must not block it too. LIMIT_S is above the longest single step (venv setup, 3,600 s). Standard library only.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time
from pathlib import Path

LIMIT_S = float(os.environ.get("ROSY_LAND_WATCHDOG_MIN", "90")) * 60
CHECK_S = 60.0


def idle(land_events, remote_job, clock=time.monotonic) -> float:
    return clock() - max(land_events.LAST[0], getattr(remote_job, "LAST_POLL", 0.0))


def start(logdir: Path, land_events, land_queue, remote_job, limit: float = LIMIT_S, check: float = CHECK_S,
          clock=time.monotonic, sleep=time.sleep, exit_=os._exit) -> threading.Thread:
    def watch() -> None:
        while True:
            sleep(check)
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
