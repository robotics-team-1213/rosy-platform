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


def again(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, invocations, note) -> str | None:
    """Mid-turn work too long for the lock (a FULL delta, or the turn's time cap): prepare it outside, wait again,
    and give back the main it now passed over."""
    prepare(land, wt, branch, args, python, qdir, ticket, invocations, note)
    land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=watch(land, wt))
    return land.land_full.restore(wt, branch)


def watch(land, wt: Path):
    """For ``land_queue.wait``: each time main moves, preview the merge (``git merge-tree``, the tree untouched)
    and name a conflict land.py cannot resolve, so it stops now instead of at its turn (2026-10-26: a landing
    waited 121 min, then stopped on a conflict main had made during the wait)."""
    seen = [None]

    def check() -> str | None:
        main = land.out(wt, "rev-parse", "main")
        if main == seen[0]:
            return None
        seen[0] = main
        tree = land.git(wt, "merge-tree", "--write-tree", "--no-messages", "HEAD", main, check=False)
        if tree.returncode != 1:
            return None
        manual = land.plan(wt, land.conflict_stages(tree.stdout))[1]
        return f"main {main[:10]} conflicts with this branch outside the auto-resolved records: {manual}" if manual else None
    return check


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
    explicit = args.tests == "full"
    env = None
    if explicit:
        args._full_witness = None
        invocations, note, env = land.land_selection.required(land, wt, main_sha, python)
    elif invocations is None:
        invocations, note = land.select(wt, main_sha, python)
        if not note and not (wt / "tools/harness/affected_tests.py").is_file():
            return  # main's delta stands in for an affected tier only where the D-436 selector maps it
    print(f"[land] {'FULL' if note else 'affected'} tier before the turn, ticket preparing (main {main_sha[:10]})",
          flush=True)
    logdir, began = land.tmp_dir(branch), time.monotonic()
    guard_args = land.argparse.Namespace(**{**vars(args), "no_cache": True}) if explicit else args
    guarded = land.land_guards.first(wt, guard_args, invocations, logdir, "pre", land.run_tests, isolated=True)  # alone runs: here only
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest guards; retry the landing from {candidate[:10]}")
    land.land_selection.require_eligible(land, args, land.land_selection.eligible(land, guarded))
    tested = land.run_tests(wt, args, invocations, logdir, "pre")
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest; {candidate[:10]} was tested; retry the landing")
    clean = land.land_selection.eligible(land, guarded + tested)
    land.land_selection.require_eligible(land, args, clean)
    tier = ("full" if note else "affected") if clean else None
    land.land_full.save(wt, branch, candidate, main_sha, tier, invocations)
    if explicit:
        args._full_witness = dict(candidate=candidate, main=main_sha, invocations=[list(i) for i in invocations], env=env)
    land.land_events.emit("prepared", tier=tier, seconds=round(time.monotonic() - began))
