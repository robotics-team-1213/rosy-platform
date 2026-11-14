"""tools/land.py's tests outside the lock (D-889 A'): a landing prepares before its turn, then the turn runs only main's delta.

The queue ticket is ``preparing`` meanwhile: it keeps its place and blocks no one (``land_queue.blockers``). The
tier that passed is recorded (``land_full.save``), and the turn selects main's delta since that main on the
candidate, so a delta that touches this branch's paths reruns their suites and one that does not runs the
guards only. Until 2026-10-26 only a FULL tier prepared, and only with someone ahead: a FULL lander first in
line held everyone 40+ min, and every affected tier ran inside the lock (4-13 min a turn).

At most ``MAX_PREPARING`` landings prepare at once. It was 3 while each lab PC took one invocation at a time; since
2026-10-28 each PC admits jobs only within its own free cores and GB (remote_job.ADMIT), so the hosts, not this
count, hold the load. On 10-30..31 landings waited p50 52 / p90 239 min for one of 3 slots (prepare itself p50 23
min, the turn p50 6 min) while the model and AI PCs ran at load ~2-3 of 24 cores. ``land`` is the calling ``land`` module (run as a script it is ``__main__``),
passed in so its ``Stop`` is the one the caller catches.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import land_queue

MAX_PREPARING = 6
POLL = 15.0
# 2026-11-04 05:42: five FULL pretests shared the two lab PCs at once, so none finished for 45 min and main stood
# still with nothing ready. FULL pretests beyond this many wait (oldest first), so one finishes and takes the turn.
MAX_FULL = 2
GATHER_S = 90.0  # gather(): a new ticket waits this long as pending for a rollup to take it
ROLL_POLLS = 40  # D-889 34: a FULL waiter starts a rollup again every 40 polls (10 min) while it waits
# D-889 28: speculation (addendum 3) ran 9.8 h of test-PC time in 6 h on 11-03 and its tree was held at 3 of 34
# turns, while the ticket stayed "preparing" behind it. It runs only when this is "1".
SPECULATE_ENV = "ROSY_LAND_SPECULATE"


def rules() -> str | None:
    """main's landing code: its tools/land*.py and tools/remote/*.py blob ids, or None when git cannot tell."""
    try:
        top = subprocess.run(["git", "ls-tree", "main", "tools/"], capture_output=True, text=True, check=True).stdout
        if not any(line.endswith("\ttools/land.py") for line in top.splitlines()):
            return None
        remote = subprocess.run(["git", "ls-tree", "-r", "main", "tools/remote/"], capture_output=True, text=True,
                                check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return "".join(line for line in top.splitlines(True) if "\ttools/land" in line) + remote


STARTED = rules()  # the rules this process runs: a landing loads main's copy once (land_checks.landed_copy)


def relaunch(land, qdir: Path, ticket: Path, run=None) -> int | None:
    """While waiting: when main's landing code changed since this process started, run main's land.py on the same
    ticket and return its exit code. This process stays alive, so the ticket's pid holds its place.

    2026-10-31: fixes to the queue (batch deadlock, turn priority) never reached landers already waiting; they
    deadlocked and bounced until each was restarted by hand in queue order."""
    if STARTED is None or rules() in (None, STARTED):
        return None
    rows = land_queue.ahead(qdir, Path("~"))
    me = next((r for r in rows if r["ticket"] == ticket.name), {})
    if me.get("batch") or any(me.get("branch") in (r.get("batch") or []) for r in rows):
        return None  # a live batch keeps its loaded rules through preparation, landing and switch-back
    print("[land] main's landing code changed while this landing waited: continuing with it", flush=True)
    argv = [sys.executable, "-X", "utf8", str(qdir.parent.parent / "tools" / "land.py"), *sys.argv[1:]]
    env = {**land.ENV, land_queue.TICKET_ENV: str(ticket), land.land_checks.OWN_COPY: "1"}
    run = run or (lambda a, e: land.remote_pytest.remote_job.step(a, env=e).returncode)  # beats for the watchdog
    return run(argv, env)


def slot(qdir: Path, ticket: Path, sleep=time.sleep, held=None, changed=None, roll=None) -> None:
    """Wait for a preparation slot, reserving capacity for older pending tickets, and while ``held()`` (a batch
    carries this branch, ``land_batch.carried``: its pretest covers this one). A carried pending ticket reserves
    no capacity: it never prepares on its own. An urgent ticket (D-889 addendum 5) reserves nothing for older
    pending ones: behind their reservations an urgent landing still waited hours for a slot (2026-10-31)."""
    land_queue.set_status(ticket, "pending")

    def busy() -> int:
        rows = land_queue.ahead(qdir, Path("~"))
        carried = {name for r in rows for name in (r.get("batch") or [])}
        urgent = any(r["ticket"] == ticket.name and r.get("urgent") for r in rows)
        return sum((r.get("status") == "preparing" and not r.get("full_wait"))
                   or (r.get("status") == "pending" and r["ticket"] < ticket.name
                       and r.get("branch") not in carried and not urgent)
                   for r in rows if r["ticket"] != ticket.name)
    while (held and held()) or busy() >= MAX_PREPARING:
        land_queue.touch(ticket)
        if changed and (code := changed()) is not None:
            raise SystemExit(code)  # main's land.py ran this landing to its end on this ticket
        sleep(POLL)
    gather(ticket, sleep, roll)
    land_queue.set_status(ticket, "preparing")


def gather(ticket: Path, sleep=time.sleep, roll=None, clock=time.monotonic) -> None:
    """Stay ``pending`` for GATHER_S, then start a rollup: landings queued close together (20 MAIN-RED stops resumed
    at once) go as one candidate with one pretest. 11-10..11-14 the rollup found "fewer than two pending" 243 times
    in a row: with 6 slots a ticket was pending for one poll, and only the turn holder rolled, every 10 min, while
    each landing ran its own ~46 min pretest. A rollup that takes this ticket stops this lander (``land_rollup``)."""
    try:
        row = json.loads(ticket.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    # only land_async snapshots (land_rollup.candidates' rule): a land.py run from a worktree is never rolled
    if (roll is None or row.get("urgent") or row.get("alone") or land_async_rollup(row.get("branch") or "")
            or "rosy-land-wt" not in Path(row.get("worktree") or "").parts):
        return
    end = clock() + GATHER_S
    while clock() < end:
        land_queue.touch(ticket)
        sleep(min(POLL, max(end - clock(), 0)))
    try:
        roll()
    except Exception:  # noqa: BLE001  a rollup that cannot start never costs the landing
        pass


def land_async_rollup(branch: str) -> bool:
    return branch.startswith("land/fix/land-rollup-")  # a rollup itself never waits to be rolled again


def full_slot(qdir: Path, ticket: Path, sleep=time.sleep, changed=None, roll=None) -> None:
    """Mark this preparing ticket FULL and wait while MAX_FULL older FULL pretests run; an urgent one never waits.
    A waiter runs no test, so ``full_wait`` frees its preparation slot (2026-11-07: two waiters held 2 of 6 slots
    while a one-file landing stood pending); MAX_FULL and each host's admission still hold the load.
    On starting to wait it calls ``roll`` (D-889 addendum 34): the rollup takes this waiter with every other waiter
    and any rollup whose FULL has not started, so one combined FULL candidate waits (11-09 22:40: five did, with no
    turn holder to run the scheduled rollup)."""
    land_queue.set_status(ticket, "preparing", tier="full")
    if json.loads(ticket.read_text(encoding="utf-8")).get("urgent"):
        return
    said = False
    def older() -> int:
        return sum(r.get("status") == "preparing" and r.get("tier") == "full" for r in land_queue.ahead(qdir, ticket))
    polls = 0
    while older() >= MAX_FULL:
        if roll and said and (polls := polls + 1) % ROLL_POLLS == 0:
            try:  # a waiter that came while another apply held its lock was left out of that one
                roll()
            except Exception:  # noqa: BLE001
                pass
        if not said:
            print(f"[land] FULL pretest waits for {MAX_FULL} older FULL pretest(s) to finish", flush=True)
            said = True
            land_queue.set_status(ticket, "preparing", full_wait=True)
            try:
                roll and roll()
            except Exception:  # noqa: BLE001  a rollup that cannot start never costs the landing
                pass
        land_queue.touch(ticket)
        if changed and (code := changed()) is not None:
            raise SystemExit(code)
        sleep(POLL)
    if said:
        land_queue.set_status(ticket, "preparing", full_wait=False)


def again(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, invocations, note) -> str | None:
    """Mid-turn work too long for the lock (a FULL delta, or the turn's time cap): prepare it outside, wait again,
    and give back the main it now passed over."""
    # The lock's end, so a turn's real length is measurable (turn -> released), not turn -> landed/stop (2026-10-31).
    land_queue.release(ticket, note)
    prepare(land, wt, branch, args, python, qdir, ticket, invocations, note)
    land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=watch(land, wt),
                    tested=land.land_full.restore(wt, branch), changed=lambda: relaunch(land, qdir, ticket))
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
        tree = land.git(wt, "merge-tree", "--write-tree", "--no-messages", *land.RENORMALIZE, "HEAD", main, check=False)
        if tree.returncode == 0:
            return size(tree.stdout.split()[0], main)
        if tree.returncode != 1:
            return None
        manual = land.plan(wt, land.conflict_stages(tree.stdout), ("HEAD", main))[1]
        return f"main {main[:10]} conflicts with this branch outside the auto-resolved records: {manual}" if manual else None
    return check


def prepare(land, wt: Path, branch: str, args, python: str, qdir: Path | None, ticket: Path | None,
            invocations: list[list[str]] | None = None, note: str | None = None) -> None:
    """Merge main, run this branch's selection (or the given FULL ``invocations`` of main's delta), record it.

    A NEW failure stops here, before the turn; the ticket is released by ``land.main``. One exception (D-889 14):
    a failure main already had at the merged base, when main has moved since, prepares once more on the new main.
    11-01: two landings stopped on a MAIN-RED test that main had fixed during their 66 min pretest."""
    try:
        _prepare(land, wt, branch, args, python, qdir, ticket, invocations, note)
    except land.Stop as stop:
        if (invocations is not None or "MAIN-RED" not in str(stop) or getattr(args, "_main_red_retry", False)
                or land.out(wt, "rev-parse", "main") == land.land_mainred.merged_main(wt)):
            raise
        args._main_red_retry = True
        print(f"[land] {stop}\n[land] main moved since that base: preparing once more on the new main", flush=True)
        _prepare(land, wt, branch, args, python, qdir, None, None, None)


def _prepare(land, wt: Path, branch: str, args, python: str, qdir: Path | None, ticket: Path | None,
             invocations: list[list[str]] | None, note: str | None) -> None:
    if ticket is not None:
        landed = lambda: land.land_batch.in_main(land, wt, branch)  # noqa: E731
        slot(qdir, ticket, held=lambda: not landed() and land.land_batch.carried(qdir, branch),
             changed=lambda: relaunch(land, qdir, ticket), roll=lambda: land.land_watchdog.rollup(qdir.parent))
        if landed():
            return  # a batch landed this branch while it waited for a slot: the turn's wait ends it as landed
    main_sha = land.out(wt, "rev-parse", "main")
    if land.git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
        land.merge(wt, main_sha, branch, python, False)
    candidate = land.out(wt, "rev-parse", "HEAD")
    land.size_check(wt, main_sha, candidate, python)  # before the hosts, not at the turn after them
    explicit = args.tests == "full"
    env = None
    if explicit:
        args._full_witness = None
        invocations, note, env = land.land_selection.required(land, wt, main_sha, python)
    elif invocations is None:
        invocations, note = land.select(wt, main_sha, python)
        if not note and not (wt / "tools/harness/affected_tests.py").is_file():
            return  # main's delta stands in for an affected tier only where the D-436 selector maps it
    delta = bool(note) and note.startswith(land.land_selection.DELTA_NOTE) and not explicit
    full = bool(note) and not delta
    print(f"[land] {'FULL' if full else 'delta' if delta else 'affected'} tier before the turn, ticket preparing"
          f" (main {main_sha[:10]})", flush=True)
    if ticket is not None:
        if full:
            full_slot(qdir, ticket, changed=lambda: relaunch(land, qdir, ticket),
                      roll=lambda: land.land_watchdog.rollup(qdir.parent))
        else:
            land_queue.set_status(ticket, "preparing", tier="")
    # Cache log hashes outlive this preparation; later preparations must keep its raw bytes intact.
    logdir = Path(tempfile.mkdtemp(prefix=f"prepare-{candidate[:10]}-", dir=land.tmp_dir(branch)))
    began = time.monotonic()
    guard_args = land.argparse.Namespace(**{**vars(args), "no_cache": True}) if explicit else args
    # The guard round (with land_isolation's alone runs: here only) beside the selection, not before it: on
    # 2026-10-27 it took 150-870 s and every pretest waited for it while holding one of MAX_PREPARING slots.
    # Each is its own remote_pytest.run (own queue, threads, run dir); a Stop from either stops the landing.
    raised: list[BaseException] = []
    guarded: list[str] = []

    def guards() -> None:
        nonlocal guarded
        try:
            guarded = land.land_guards.first(wt, guard_args, invocations, logdir, "pre", land.run_tests,
                                             isolated=not delta)
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller's thread below
            raised.append(error)
    side = threading.Thread(target=guards, name="pretest-guards", daemon=True)
    side.start()
    tested = land.run_tests(wt, args, invocations, logdir, "pre")  # a Stop or Ctrl-C here does not wait for the guards
    side.join()
    if raised:
        raise raised[0]
    if land.out(wt, "rev-parse", "HEAD") != candidate:
        raise land.Stop(f"HEAD changed during pretest; {candidate[:10]} was tested; retry the landing")
    clean = land.land_selection.eligible(land, guarded + tested, args)
    land.land_selection.require_eligible(land, args, clean, guarded + tested)
    # D-970 4: a LOAD-FLAKY id no longer voids the whole pretest; the record keeps it and the turn reruns it.
    # An explicit FULL witness stays strict, and so does a summary whose LOAD-FLAKY line cannot be read.
    relax = not explicit and not full  # a FULL tier (explicit or escalated) stays strict
    flaky = land.land_selection.load_flaky_ids(guarded + tested) if relax else None
    # D-970 4: a pass reused from another tree (land_cache NARROW) names the tier for the queue too; the record is
    # marked "reused" so land.py writes no land record from it and pre-push still reruns (11-03: 9 of 20 had none).
    reused = relax and any(land.land_cache.NARROW in line for line in guarded + tested)
    # D-970 3: an explicit FULL keeps no "reused" mark; publish_evidence recomputes each cross-tree pass itself.
    drop = (("LOAD-FLAKY",) if flaky else ()) + ((land.land_cache.NARROW,) if reused or explicit else ())
    judged = [line for line in guarded + tested if not any(d in line for d in drop)]
    tier = land.land_selection.tier(land, judged, full)  # carried: restore() refuses it
    anchor = None
    if delta:
        # D-889 27: main's delta suites passed here outside the lock. They extend the earlier tier over the new
        # main ("delta"), never stand in for it; with no clean earlier tier the record stays as it was.
        base = land.land_full.prepared(wt, branch, land.land_full.restore(wt, branch))
        if tier is not None and base is not None:
            try:
                combined = land.land_record.plan(invocations, base,
                                                  available=(wt / land.land_record.TARGET).is_file())
            except ValueError as exc:
                raise land.Stop(f"invalid delta preparation plan: {exc}") from exc
            land.land_full.save(wt, branch, candidate, main_sha, "delta", combined,
                                base_tier=base["tier"], flaky=land.land_full.flaky(wt, branch) + (flaky or []),
                                yields=int(base.get("yields") or 0) + 1, reused=reused or bool(base.get("reused")))
        elif base is not None:
            # A delta pretest with no tier saves nothing, yet its yield counts toward MAX_DELTA_YIELDS: 11-03
            # 23:20-23:35 one ticket yielded again and again on an unchanged record (D-970 1).
            land.land_full.count_yield(wt, branch)
        tier = "delta" if tier is not None and base is not None else None
    # Keeping an older base with --no-cache would repeat overtime on every turn.
    elif tier == "affected" and not args.no_cache:
        anchor_main = land.land_full.restore(wt, branch)
        anchor = land.land_full.prepared(wt, branch, anchor_main)
    keep_full = (anchor and anchor["tier"] == "full" and anchor["invocations"]
                 and all(isinstance(inv, list) and inv
                         and all(isinstance(word, str) and word for word in inv)
                         for inv in anchor["invocations"]))
    if keep_full:
        # A delta cannot replace a FULL origin; retain its exact base and invocations.
        print(f"[land] retained FULL preparation {anchor['candidate'][:10]} over {anchor['main'][:10]}", flush=True)
    elif not delta:
        land.land_full.save(wt, branch, candidate, main_sha, tier, invocations, flaky=flaky, reused=reused,
                            env=env if explicit else None)
    if explicit:
        args._full_witness = dict(candidate=candidate, main=main_sha, invocations=[list(i) for i in invocations], env=env)
    if ticket is not None:
        land_queue.set_status(ticket, "preparing", tested=land.land_full.restore(wt, branch) or "")
    land.land_events.emit("prepared", tier=tier, seconds=round(time.monotonic() - began))
    if os.environ.get(SPECULATE_ENV) == "1":
        land.land_speculate.prepare(land, wt, branch, args, python, qdir, ticket)
