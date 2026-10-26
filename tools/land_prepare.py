"""tools/land.py's tests outside the lock (D-889 A'): a landing prepares before its turn, then the turn runs only main's delta.

The queue ticket is ``preparing`` meanwhile: it keeps its place and blocks no one (``land_queue.blockers``). The
tier that passed is recorded (``land_full.save``), and the turn selects main's delta since that main on the
candidate, so a delta that touches this branch's paths reruns their suites and one that does not runs the
guards only. Until 2026-10-26 only a FULL tier prepared, and only with someone ahead: a FULL lander first in
line held everyone 40+ min, and every affected tier ran inside the lock (4-13 min a turn).

At most ``MAX_PREPARING`` landings prepare at once: the model and AI PCs take one invocation each, and timing
tests fail falsely under load. ``land`` is the calling ``land`` module (run as a script it is ``__main__``),
passed in so its ``Stop`` is the one the caller catches.
"""

from __future__ import annotations

import time
from pathlib import Path

import land_queue

MAX_PREPARING = 3
POLL = 15.0


def slot(qdir: Path, ticket: Path, sleep=time.sleep) -> None:
    """Wait (``pending``: blocks no one) until fewer than ``MAX_PREPARING`` other tickets are preparing."""
    land_queue.set_status(ticket, "pending")
    while sum(r.get("status") == "preparing" for r in land_queue.ahead(qdir, Path("~"))
              if r["ticket"] != ticket.name) >= MAX_PREPARING:
        land_queue.touch(ticket)
        sleep(POLL)
    land_queue.set_status(ticket, "preparing")


def prepare(land, wt: Path, branch: str, args, python: str, qdir: Path | None, ticket: Path | None,
            invocations: list[list[str]] | None = None, note: str | None = None) -> None:
    """Merge main, run this branch's selection (or the given FULL ``invocations`` of main's delta), record it.

    A NEW failure stops here, before the turn; the ticket is released by ``land.main``."""
    if ticket is not None:
        slot(qdir, ticket)
    main_sha = land.out(wt, "rev-parse", "main")
    if land.git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
        land.merge(wt, main_sha, branch, python, False)
    candidate = land.out(wt, "rev-parse", "HEAD")
    if invocations is None:
        invocations, note = land.select(wt, main_sha, python)
        if not note and not (wt / "tools/harness/affected_tests.py").is_file():
            return  # main's delta stands in for an affected tier only where the D-436 selector maps it
    print(f"[land] {'FULL' if note else 'affected'} tier before the turn, ticket preparing (main {main_sha[:10]})",
          flush=True)
    logdir = land.tmp_dir(branch)
    land.land_guards.first(wt, args, invocations, logdir, "pre", land.run_tests)
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest guards; retry the landing from {candidate[:10]}")
    land.run_tests(wt, args, invocations, logdir, "pre")
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest; {candidate[:10]} was tested; retry the landing")
    land.land_full.save(wt, branch, candidate, main_sha)
