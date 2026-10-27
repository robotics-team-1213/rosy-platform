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

import sys
import threading
import time
from pathlib import Path

import land_queue

MAX_PREPARING = 3
POLL = 15.0
# D-889 7: the test PCs clean up at 05:30 and reboot at 06:00; a pretest started in between dies (2026-10-27 06:00,
# exit 143). Minutes after midnight, local time: no pretest starts inside, it waits for the hosts to come back.
REBOOT = (5 * 60 + 15, 6 * 60 + 10)


def after_reboot(ticket: Path | None, sleep=time.sleep, clock=time.localtime) -> None:
    """Wait (ticket kept fresh) while the lab PCs' nightly cleanup and reboot window is on."""
    told = False
    while REBOOT[0] <= (now := clock()).tm_hour * 60 + now.tm_min < REBOOT[1]:
        if not told:
            print(f"[land] test PCs reboot at 06:00: the pretest starts after {REBOOT[1] // 60:02d}:{REBOOT[1] % 60:02d}",
                  flush=True)
            told = True
        if ticket is not None:
            land_queue.touch(ticket)
        sleep(POLL)


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
    waited 121 min, then stopped on a conflict main had made during the wait). A clean merge also gets the size
    ratchet on an unreferenced preview commit: main growing the same unit stopped two landings at their turns,
    392 min after they started (2026-10-26)."""
    seen = [None]

    def size(tree: str, main: str) -> str | None:
        try:
            preview = land.out(wt, "commit-tree", tree, "-p", "HEAD", "-p", main, "-m", "land.py size preview")
            land.size_check(wt, main, preview, sys.executable)
        except land.Stop as stop:
            return f"main {main[:10]} merged with this branch fails the size ratchet: {str(stop).splitlines()[0]}"
        except Exception:  # noqa: BLE001 - a preview only; the turn's own size check still decides
            return None
        return None

    def check() -> str | None:
        main = land.out(wt, "rev-parse", "main")
        if main == seen[0]:
            return None
        seen[0] = main
        tree = land.git(wt, "merge-tree", "--write-tree", "--no-messages", "HEAD", main, check=False)
        if tree.returncode == 0:
            return size(tree.stdout.split()[0], main)
        if tree.returncode != 1:
            return None
        manual = land.plan(wt, land.conflict_stages(tree.stdout))[1]
        return f"main {main[:10]} conflicts with this branch outside the auto-resolved records: {manual}" if manual else None
    return check


def prepare(land, wt: Path, branch: str, args, python: str, qdir: Path | None, ticket: Path | None,
            invocations: list[list[str]] | None = None, note: str | None = None) -> None:
    """Merge main, run this branch's selection (or the given FULL ``invocations`` of main's delta), record it.

    A NEW failure stops here, before the turn; the ticket is released by ``land.main``."""
    after_reboot(ticket)
    if ticket is not None:
        slot(qdir, ticket)
    main_sha = land.out(wt, "rev-parse", "main")
    if land.git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
        land.merge(wt, main_sha, branch, python, False)
    candidate = land.out(wt, "rev-parse", "HEAD")
    land.size_check(wt, main_sha, candidate, python)  # before the hosts, not at the turn after them
    if invocations is None:
        invocations, note = land.select(wt, main_sha, python)
        if not note and not (wt / "tools/harness/affected_tests.py").is_file():
            return  # main's delta stands in for an affected tier only where the D-436 selector maps it
    print(f"[land] {'FULL' if note else 'affected'} tier before the turn, ticket preparing (main {main_sha[:10]})",
          flush=True)
    logdir, began = land.tmp_dir(branch), time.monotonic()
    # The guard round (with land_isolation's alone runs: here only) beside the selection, not before it: on
    # 2026-10-27 it took 150-870 s and every pretest waited for it while holding one of MAX_PREPARING slots.
    # Each is its own remote_pytest.run (own queue, threads, run dir); a Stop from either stops the landing.
    raised: list[BaseException] = []

    def guards() -> None:
        try:
            land.land_guards.first(wt, args, invocations, logdir, "pre", land.run_tests, isolated=True)
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller's thread below
            raised.append(error)
    side = threading.Thread(target=guards, name="pretest-guards", daemon=True)
    side.start()
    land.run_tests(wt, args, invocations, logdir, "pre")  # a Stop or Ctrl-C here does not wait for the guards
    side.join()
    if raised:
        raise raised[0]
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest; {candidate[:10]} was tested; retry the landing")
    tier = "carried" if land.land_mainred.CARRIED else "full" if note else "affected"  # carried: restore() refuses it
    anchor = None
    # Keeping an older base with --no-cache would repeat overtime on every turn.
    if tier == "affected" and not args.no_cache:
        anchor_main = land.land_full.restore(wt, branch)
        anchor = land.land_full.prepared(wt, branch, anchor_main)
    keep_full = (anchor and anchor["tier"] == "full" and anchor["invocations"]
                 and all(isinstance(inv, list) and inv
                         and all(isinstance(word, str) and word for word in inv)
                         for inv in anchor["invocations"]))
    if keep_full:
        # A delta cannot replace a FULL origin; retain its exact base and invocations.
        print(f"[land] retained FULL preparation {anchor['candidate'][:10]} over {anchor['main'][:10]}", flush=True)
    else:
        land.land_full.save(wt, branch, candidate, main_sha, tier, invocations)
    land.land_events.emit("prepared", tier=tier, seconds=round(time.monotonic() - began))
