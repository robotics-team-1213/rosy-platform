#!/usr/bin/env python3
"""Why the landing queue stands still: a read-only diagnosis of the stalls found on 2026-10-31.

  python tools/land_stall.py [--minutes 60]

When local main has not moved for ``--minutes`` while tickets wait, prints each known cause with the tickets and
the safe remedy, and exits 1; otherwise exits 0. It only reads the queue tickets, the event log and each
landing's log tail; it never stops or changes anything (land.py does not use it). Causes, each of which held
main still for an hour or more on 2026-10-31 and was found only by a manual hourly check:

  turn-host-room   the turn holder's job waits for host room behind other landings' prepare jobs (75 min)
  batch-deadlock   an earlier 'waiting' member and the later leader carrying it wait on each other (2 h 15 min)
  carried-member   a 'waiting' member holds every later ticket while its leader still prepares
  turn-bounce      turns go back to preparing (the 10-min turn cap) again and again
  old-code         a ticket entered before main's last landing-code change: it runs the old rules

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_events  # noqa: E402
import land_queue  # noqa: E402  (pid_alive only; ahead() would delete stale tickets)

LOG_IDLE_S = 15 * 60  # a turn holder's log quiet this long while waiting for host room counts as stuck
BOUNCE_WINDOW_S = 3 * 3600
LANDING_CODE = ("tools/land*.py", "tools/remote")


def tickets(qdir: Path) -> list[dict]:
    """Live-or-not queue tickets, oldest first; unlike land_queue.ahead this never removes a stale one."""
    rows = []
    for path in sorted(qdir.glob("[0-9]*.json")):
        try:
            rows.append({**json.loads(path.read_text(encoding="utf-8")), "ticket": path.name})
        except (OSError, ValueError):
            continue
    return rows


def bounces(events: list[dict], now: float) -> dict[str, int]:
    """Per branch: turns in the last BOUNCE_WINDOW_S followed by another prepare instead of landed or stop."""
    out: dict[str, int] = {}
    mine = sorted((e for e in events if e["t"] >= now - BOUNCE_WINDOW_S), key=lambda e: e["t"])
    for i, e in enumerate(mine):
        if e.get("event") != "turn":
            continue
        nxt = next((x for x in mine[i + 1:] if x.get("branch") == e.get("branch")
                    and x.get("event") in ("landed", "stop", "prepared", "turn")), None)
        if nxt is not None and nxt["event"] in ("prepared", "turn"):
            out[e["branch"]] = out.get(e["branch"], 0) + 1
    return out


def diagnose(rows: list[dict], events: list[dict], logs: dict[str, tuple[str, float]], code_t: float,
             now: float) -> list[str]:
    """Causes with the tickets they name; ``logs`` maps a worktree path to (log tail, log mtime)."""
    found = []
    carried = {name: r for r in rows for name in (r.get("batch") or [])}
    by_branch = {r.get("branch"): r for r in rows}
    for r in rows:
        tail, mtime = logs.get(r.get("worktree", ""), ("", now))
        waiting = tail.rfind("waiting for host room") > tail.rfind("host room after waiting")
        if r.get("status") == "turn" and waiting and now - mtime > LOG_IDLE_S:
            found.append(f"turn-host-room: {r['branch']} holds the turn and its job waits for host room "
                         f"({(now - mtime) / 60:.0f} min quiet); remedy: if it is yours, stop its land.py and "
                         "resume it; otherwise tell its owner")
    for name, leader in carried.items():
        member = by_branch.get(name)
        if member is None or member.get("status") != "waiting":
            continue
        if leader.get("alive") is False:  # 2026-10-31: a member was stopped "to ride" with a leader already gone
            found.append(f"orphaned-member: {name} is carried by {leader['branch']}, whose land.py is gone; remedy: "
                         "do NOT stop the member, it must land on its own (or resume the leader)")
            continue
        if member["ticket"] < leader["ticket"] and leader.get("status") == "waiting":
            found.append(f"batch-deadlock: member {name} (earlier, waiting) and leader {leader['branch']} wait on "
                         f"each other; remedy: stop member's land.py (pid {member.get('pid')}); its commits ride in "
                         "the leader's batch")
        elif leader.get("status") in ("preparing", "pending") and any(
                x["ticket"] > member["ticket"] and x.get("status") == "waiting" for x in rows):
            found.append(f"carried-member: {name} waits for its preparing leader {leader['branch']} and holds every "
                         f"later ticket; remedy: stop member's land.py (pid {member.get('pid')}); its commits ride "
                         "in the leader's batch")
    for branch, n in sorted(bounces(events, now).items()):
        if n >= 2:
            found.append(f"turn-bounce: {branch} went back to preparing after {n} turns in "
                         f"{BOUNCE_WINDOW_S // 3600} h (turn cap); remedy: look for slow turn tests (host room)")
    old = [r["branch"] for r in rows if r.get("start", now) < code_t]
    if old:
        found.append(f"old-code: {len(old)} ticket(s) entered before main's last landing-code change and run the "
                     f"old rules: {', '.join(old)}; remedy: restart pending ones (land_async --supervise on the "
                     "same snapshot)")
    return found


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def _tail(path: Path, size: int = 4096) -> tuple[str, float]:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - size))
            return handle.read().decode("utf-8", "replace"), path.stat().st_mtime
    except OSError:
        return "", time.time()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=60, help="main still this long with tickets = stalled")
    args = parser.parse_args(argv)
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    now = time.time()
    rows = [{**r, "alive": land_queue.pid_alive(int(r.get("pid") or 0))} for r in tickets(common / "rosy-land-queue")]
    main_t = float(_git("log", "-1", "--format=%ct", "main") or now)
    idle = (now - main_t) / 60
    if not rows or idle < args.minutes:
        print(f"[land-stall] not stalled: main moved {idle:.0f} min ago, {len(rows)} ticket(s)")
        return 0
    code_t = float(_git("log", "-1", "--format=%ct", "main", "--", *LANDING_CODE) or 0)
    logs = {r.get("worktree", ""): _tail(Path(r.get("worktree", "") + ".log")) for r in rows}  # land_async's log
    found = diagnose(rows, land_events.read(common / land_events.EVENTS), logs, code_t, now)
    print(f"[land-stall] STALLED: main still {idle:.0f} min with {len(rows)} ticket(s)")
    for line in found or ["no known cause: read the turn holder's log and the waiting tickets"]:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
