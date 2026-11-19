"""What tools/land.py did, as one JSON line per event in ``<git-common-dir>/rosy-land-events.jsonl``.

Until 2026-10-26 a landing's screen output was its only record, so queue waits and failure rates were
guessed from file times. Each line has ``t`` (epoch s), ``event``, ``pid``, ``branch`` and the event's own
fields; one ``os.write`` on an ``O_APPEND`` descriptor per line, so concurrent landers never interleave.

  queue    entered the queue: ticket, position (live tickets ahead + 1), apps (the branch's apps, below)
  turn     first in line: waited_s
  round    a round began: round, main
  merged   the round's merge of main ended: round, seconds, resolved (auto-resolved paths)
  async    land_async queued a snapshot (its own branch field): source, behind (commits of main not in HEAD)
  tests    one invocation judged: round, argv, verdict (pass, flaky, new, unusable, cancelled), seconds
           (its batch's wall time)
  landed   main fast-forwarded: sha, rounds, apps
  stop     the run ended without landing: reason (first line)
  skip     --tests none on the user's words: reason (--skip-reason)

``tools/land_stats.py`` turns the file into the daily numbers. Writing never stops a landing.
Standard library only, except ``apps``: ``affected_repo.landing_apps`` of ``main...HEAD`` at bind (2026-11-19, so a
week of data can decide per-app parallel turns); it needs PyYAML and is left out when it cannot be read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

EVENTS = "rosy-land-events.jsonl"
APPS_ON = ("queue", "landed")  # events that carry the branch's apps
_where: dict[str, object] = {}


def bind(wt: Path, branch: str) -> None:
    """Where this run's events go, and the branch they belong to (land.main calls it once)."""
    common = subprocess.run(["git", "-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if common.returncode == 0:
        _where.update(path=Path(common.stdout.strip()) / EVENTS, branch=branch, apps=landing_apps(wt))


def landing_apps(wt: Path) -> list[str] | None:
    """The apps of this branch's own delta (``main...HEAD``); None when git or the manifest cannot say."""
    try:
        harness = str(Path(__file__).resolve().parent / "harness")
        if harness not in sys.path:
            sys.path.insert(0, harness)
        import affected_repo
        import yaml
        delta = subprocess.run(["git", "-C", str(wt), "diff", "--name-only", "main...HEAD"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", check=True).stdout.splitlines()
        parts = yaml.safe_load((wt / "tools/harness/platform_parts.yaml").read_text(encoding="utf-8"))
        return affected_repo.landing_apps(delta, parts)
    except Exception:  # noqa: BLE001  (a record we could not compute must not cost the landing)
        return None


LAST = [time.monotonic()]  # the latest sign of progress, for land_watchdog


def beat() -> None:
    LAST[0] = time.monotonic()


def emit(event: str, **fields) -> None:
    beat()
    path = _where.get("path")
    if path is None:
        return
    line = json.dumps({"t": round(time.time(), 3), "event": event, "pid": os.getpid(),
                       "branch": _where["branch"], **({"apps": _where.get("apps")} if event in APPS_ON else {}),
                       **fields}, ensure_ascii=False, default=str) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # a record we could not write must not cost the landing


def landed(sha: str, *, main_move: bool = True) -> None:
    """One actual completion event, retaining pinned rollup members when available.

    A missing/invalid sidecar must never hide a successful FF. The goal reader can recover late sidecars
    and reports incomplete membership separately from the actual main move.
    """
    fields = {"sha": sha, "main_move": main_move}
    path = _where.get("path")
    if path is not None:
        sidecar = Path(path).parent / "rosy-land-wt" / (str(_where.get("branch", "")).replace("/", "-") + ".members")
        try:
            if sidecar.exists():
                fields["members"] = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fields["members_error"] = "unreadable sidecar"
    emit("landed", **fields)


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
