"""One unattended pass over the landing backlog, every 10 minutes from the main checkout (scheduled task RosyLandTick).

Every step already existed, but each ran only when some session or a running landing happened to call it, so the
backlog grew while nobody looked (11-13/14: ~20 landings stopped on one red main for hours, 270 unlanded branches,
4.2 GB of leftovers, 243 rollup tries that found nothing). In order, each step on its own (one failing never skips
the next), never deleting work:

1. main-red recheck: when main moved since the last tick and ids are open, run them on main (``land_mainred
   recheck``); ids that pass close, which is what lets the landings stopped on them go again.
2. resume: orphaned landings and MAIN-RED stops main has cleared (``land_async.orphans``); resumed together they
   gather and roll up as one landing (``land_prepare.gather``).
3. rollup: ``land_rollup apply --auto`` for pending landings that fit together.
4. cleanup: ``land_gc`` (lossless) and the branch sweep (merged branches go, idle unlanded ones to refs/archive/).
5. report: ``<git-common-dir>/rosy-land-backlog.txt``, the queue, stops by kind and open main-red ids with age and
   owner. An unowned main-red id older than ALERT_S is the line a person or agent acts on.

    python tools/land_tick.py [--report]        # --report: step 5 only
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_async  # noqa: E402
import land_gc  # noqa: E402
import land_mainred  # noqa: E402
import land_queue  # noqa: E402
import worktree_rules  # noqa: E402

ALERT_S = 30 * 60  # a main-red id open this long with no owner is called out
SHOWN = 10  # the oldest open main-red ids the report names
RECHECK_STAMP, LOG, REPORT, LOCK = ("rosy-land-tick.recheck", "rosy-land-tick.log", "rosy-land-backlog.txt",
                                     "rosy-land-tick.lock")


def _run(repo: Path, *argv: str, timeout: float) -> str:
    done = subprocess.run([sys.executable, "-X", "utf8", *argv], cwd=repo, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    lines = (done.stdout + done.stderr).strip().splitlines()
    return lines[-1] if lines else f"exit {done.returncode}"


def recheck(repo: Path, common: Path) -> str:
    main = land_async.git(repo, "rev-parse", "main")
    stamp = common / RECHECK_STAMP
    if not land_mainred.state(repo) or (stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == main):
        return "nothing to recheck"
    said = _run(repo, "tools/land_mainred.py", "recheck", timeout=45 * 60)
    stamp.write_text(main, encoding="utf-8")
    return said


def resume(repo: Path) -> str:
    names = land_async.orphans(repo)
    for name in names:
        try:
            land_async.resume(repo, name, [], land_async.detach, wait=0)
        except SystemExit as exc:
            print(f"[tick] resume {name}: {exc}", flush=True)
    return f"resumed {len(names)}: {', '.join(names)}" if names else "nothing to resume"


def cleanup(repo: Path) -> str:
    rows = land_gc.plan(repo, time.time(), 7)
    problems = land_gc.apply(repo, rows)
    worktree_rules.sweep_branches(repo, time.time(), True, say=lambda line: None, quiet=True)
    return f"land_gc removed {sum(r[0] != 'keep' for r in rows) - len(problems)}, kept {len(problems)} changed"


def report(repo: Path, common: Path, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    rows = land_queue.ahead(land_queue.queue_dir(repo), Path("~"))
    place = land_async.holder(repo)
    stops = sorted(place.glob("*.stopped")) if place.is_dir() else []
    red = [s for s in stops if land_async.main_red_stop(place, s.name[:-len(".stopped")])]
    lines = [f"[backlog] {time.strftime('%m-%d %H:%M', time.localtime(now))} main {land_async.git(repo, 'rev-parse', '--short=10', 'main')}",
             "[backlog] queue: " + (", ".join(f"{s} {sum(r.get('status') == s for r in rows)}"
                                              for s in ("pending", "preparing", "waiting", "turn")) if rows else "empty"),
             f"[backlog] stopped: {len(stops)} ({len(red)} on MAIN-RED, wait for main; {len(stops) - len(red)} for owners)"]
    opened = sorted(land_mainred.state(repo).items(), key=lambda kv: kv[1]["since"] or now)
    alerts = [nodeid for nodeid, s in opened if now - (s["since"] or now) > ALERT_S and not s["owner"]]
    lines.append(f"[backlog] main-red open: {len(opened)}, {len(alerts)} unowned over {ALERT_S // 60} min"
                 + (" (ALERT)" if alerts else ""))
    for nodeid, s in opened[:SHOWN]:  # 11-14: 160 open ids, most never rechecked after main healed them
        lines.append(f"[backlog]   {nodeid} open {(now - (s['since'] or now)) / 60:.0f} min, owner {s['owner'] or 'none'}")
    (common / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo = Path(land_async.git(Path.cwd(), "rev-parse", "--show-toplevel"))
    common = Path(land_async.git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    steps = [] if "--report" in argv else [("recheck", lambda: recheck(repo, common)), ("resume", lambda: resume(repo)),
                                           ("rollup", lambda: _run(repo, "tools/land_rollup.py", "apply", "--auto",
                                                                   timeout=20 * 60)),
                                           ("cleanup", lambda: cleanup(repo))]
    try:
        with land_async.locked(common / LOCK):  # one tick at a time; a long recheck makes the next ones skip
            for name, step in steps:
                try:
                    print(f"[tick] {name}: {step()}", flush=True)
                except Exception as exc:  # noqa: BLE001  each step on its own
                    print(f"[tick] {name} failed: {exc}", flush=True)
            print("\n".join(report(repo, common)), flush=True)
    except land_async.Busy:
        print("[tick] another tick is running; skipped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
