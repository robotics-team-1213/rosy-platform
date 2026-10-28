"""What tools/land.py did, as one JSON line per event in ``<git-common-dir>/rosy-land-events.jsonl``.

Until 2026-10-26 a landing's screen output was its only record, so queue waits and failure rates were
guessed from file times. Each line has ``t`` (epoch s), ``event``, ``pid``, ``branch`` and the event's own
fields; one ``os.write`` on an ``O_APPEND`` descriptor per line, so concurrent landers never interleave.

  queue    entered the queue: ticket, position (live tickets ahead + 1)
  turn     first in line: waited_s
  round    a round began: round, main
  tests    one invocation judged: round, argv, verdict (pass, flaky, new, unusable, cancelled), seconds
           (its batch's wall time)
  landed   main fast-forwarded: sha, rounds
  stop     the run ended without landing: reason (first line)
  skip     --tests none on the user's words: reason (--skip-reason)

``tools/land_stats.py`` turns the file into the daily numbers. Writing never stops a landing.
Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

EVENTS = "rosy-land-events.jsonl"
_where: dict[str, object] = {}


def bind(wt: Path, branch: str) -> None:
    """Where this run's events go, and the branch they belong to (land.main calls it once)."""
    common = subprocess.run(["git", "-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if common.returncode == 0:
        _where.update(path=Path(common.stdout.strip()) / EVENTS, branch=branch)


LAST = [time.monotonic()]  # the latest sign of progress, for land_watchdog


def beat() -> None:
    LAST[0] = time.monotonic()


def emit(event: str, **fields) -> None:
    beat()
    path = _where.get("path")
    if path is None:
        return
    line = json.dumps({"t": round(time.time(), 3), "event": event, "pid": os.getpid(),
                       "branch": _where["branch"], **fields}, ensure_ascii=False, default=str) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # a record we could not write must not cost the landing


def read(path: Path) -> list[dict]:
    """Every readable line, oldest first; a torn or foreign line is skipped."""
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("event"), str) and isinstance(row.get("t"), (int, float)):
            rows.append(row)
    return rows
