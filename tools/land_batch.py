"""Batch landing for tools/land.py: while a turn runs, two or more waiting landings prepare and land as one.

On 2026-10-28 sixteen landings queued. Each turn merged main, tested main's delta and fast-forwarded, so the
last one waited for fifteen serial turns, and every one of them moved main under everyone behind it. Now the
earliest waiting ticket that may batch, while another ticket blocks it, leads a batch of at least ``BATCH_MIN``
tickets (itself included, at most ``kopt(p)`` of the rolling NEW rate ``rate``) that touch no safety-tagged path
and are not FULL-class (D-889 3/6: those, and ``--tests`` other than auto, land alone). Members are waiting
tickets (a green affected prepared tier) and ``pending`` ones still queued for a pretest slot (their selection
from the fork point is affected): on 2026-10-28 sixteen of 23 tickets sat ``pending`` behind three pretest
slots while batching only looked at the prepared few, and a FULL-class head of the waiting list kept everyone
behind it from leading. Its ticket names the members (``batch``), so they wait behind it
(``land_queue.blockers``) and a pending member does not take a pretest slot (``land_prepare.slot``). In its own worktree it merges each member's
tip into a new branch ``<leader>-batch<HHMMSS>-k<k>`` (``land.merge``: the records auto-resolve; a member with any
other conflict is left out and lands alone), merges main, lands alone if that selects FULL, prepares the
branch outside the lock (``land_prepare``), and
lands it through the ordinary rounds: one turn, one fast-forward for all. A member sees its tip in main and
ends as landed. If the batch stops (a NEW failure, a conflict, the size ratchet, the queue), the leader goes
back to its own branch, which the batch never touched, and bisects by halving: it keeps the first half of the
group in ``batch`` and tries again, the second half is released to form its own batch, until a half is one
landing that goes alone.
Never resets or force-deletes: a stopped batch branch is kept for its log; a landed one goes with ``-d``.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import land_events
import land_full
import land_prepare
import land_queue

BATCH_MIN = 2  # waiting tickets, the leader included, that make a batch
# D-889 addendum 4: k from the rolling NEW rate p, by expected landings per turn under halving bisect
# (p 0.25: k2 0.80 vs k1 0.75; p 0.05: k6 2.29). p above the bound -> k; else KMAX. Unknown p -> 2.
KOPT = ((0.2, 2), (0.12, 3), (0.07, 4))
KMAX = 6
KFULL = 3  # a FULL batch costs a whole FULL run per try: at most this many, and never more than kopt(p)
WINDOW_S, WINDOW_RUNS = 24 * 3600, 50  # the last 24 h, widened to the last 50 runs when it holds fewer


def rate(path: Path, now: float | None = None) -> tuple[float | None, int]:
    """(p, runs): landing runs (pid, branch) that prepared or met a NEW, and the share that met a NEW."""
    runs: dict[tuple, list] = {}
    for row in land_events.read(path):
        new = row["event"] == "tests" and row.get("verdict") == "new"
        if row["event"] == "prepared" or new:
            run = runs.setdefault((row.get("pid"), row.get("branch")), [0.0, False])
            run[0], run[1] = max(run[0], row["t"]), run[1] or new
    ordered = sorted(runs.values(), key=lambda run: run[0], reverse=True)
    now = time.time() if now is None else now
    recent = [run for run in ordered if run[0] >= now - WINDOW_S]
    if len(recent) < WINDOW_RUNS:
        recent = ordered[:WINDOW_RUNS]
    return (sum(run[1] for run in recent) / len(recent) if recent else None), len(recent)


def kopt(p: float | None) -> int:
    return 2 if p is None else next((k for bound, k in KOPT if p > bound), KMAX)


def in_main(land, wt: Path, branch: str) -> bool:
    return land.git(wt, "merge-base", "--is-ancestor", f"refs/heads/{branch}", "main", check=False).returncode == 0


def safety(land, wt: Path, branch: str) -> bool:
    """D-889 3: a branch that touches a safety-tagged path (D-430 5) lands alone, never in a batch."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "harness"))
        import safety_review  # PyYAML, as the safety_review step land.py already runs
        manifest = safety_review._manifest(land.out(wt, "rev-parse", "main"))
    except Exception:  # noqa: BLE001 - no manifest reading: treat it as safety, it lands alone
        return True
    paths = land.lines(wt, "diff", "--name-only", f"main...refs/heads/{branch}")
    return any(safety_review._is_safety_in(path, manifest) for path in paths)


_BATCHABLE: dict[tuple[str, str], str | None] = {}  # (branch, tip) -> group or None; a tip never changes


def batchable(land, wt: Path, other: Path, name: str, tip: str) -> str | None:
    """The batch group, "affected" or "full", or None for a safety-tagged branch (alone, D-889 3). A prepared
    tier says which; a ticket still ``pending`` (no pretest yet) gets its selection from its fork point, so it
    may join without a pretest of its own."""
    if land_full.restore(other, name) is not None:  # read each time: a pretest may record its tier later
        return None if safety(land, wt, name) else group_of(other, name)
    key = (name, tip)
    if key not in _BATCHABLE:
        if safety(land, wt, name):
            _BATCHABLE[key] = None
        else:
            fork = land.out(other, "merge-base", "main", "HEAD")
            try:
                _BATCHABLE[key] = "affected" if land.select(other, fork, sys.executable)[1] is None else "full"
            except Exception:  # noqa: BLE001 - a selection that cannot run says nothing: alone
                _BATCHABLE[key] = None
    return _BATCHABLE[key]


def plain_auto(args, extra) -> bool:
    """Explicit checks or freshness requests run alone; only plain auto opts into batching."""
    return (args.tests == "auto" and not extra and not getattr(args, "node", False)
            and not getattr(args, "no_cache", False))


def taken(tickets: list[dict]) -> set[str]:
    """Branches a live batch already carries (its leaders' ``batch`` lists): no second batch may take them."""
    return {name for r in tickets for name in (r.get("batch") or [])}


def eligible(land, wt: Path, row: dict, kind: str = "affected", carried_now: set[str] = frozenset()) -> bool:
    """A waiting or pending ticket another landing may carry: this host, a clean branch at its worktree's HEAD."""
    other, name = Path(row.get("worktree") or "."), row.get("branch") or ""
    if (row.get("batch_auto") is not True or row.get("status") not in ("waiting", "pending")
            or row.get("host") != socket.gethostname()):
        return False
    if (row.get("batch") or name in carried_now or name in ("", "main", "HEAD") or not other.is_dir()
            or other.resolve() == wt.resolve()):
        return False
    if in_main(land, wt, name):
        return False
    head = land.git(other, "rev-parse", "HEAD", check=False).stdout.strip()
    tip = land.git(wt, "rev-parse", f"refs/heads/{name}", check=False).stdout.strip()
    return bool(head) and head == tip and batchable(land, wt, other, name, tip) == kind


def carried(qdir: Path, branch: str) -> bool:
    """Whether a live batch leader's ticket names ``branch`` (``land_prepare.slot`` holds such a member)."""
    return any(branch in (r.get("batch") or []) for r in land_queue.ahead(qdir, Path("~")))


def group_of(wt: Path, branch: str) -> str | None:
    """The green prepared tier, "affected" or "full": the batch group this landing may lead or join. FULL-class
    landings batch only with each other and run one FULL on the merged tree (D-889 addendum 6)."""
    record = land_full.prepared(wt, branch, land_full.restore(wt, branch))
    return record["tier"] if record is not None and record["tier"] in ("affected", "full") else None


def former(land, wt: Path, qdir: Path, ticket: Path, kind: str = "affected"):
    """``form`` for ``land_queue.wait``, the list it fills with the members it chose, and its ``p``."""
    chosen: list[dict] = []
    measured: dict = {}

    def form(rows: list[dict]) -> bool:
        tickets = land_queue.ahead(qdir, Path("~"))
        busy = taken(tickets)
        me = next((r for r in tickets if r["ticket"] == ticket.name), {})
        if me.get("branch") in busy:
            return False  # another batch carries this landing
        # The earliest waiting ticket that may batch leads; a safety or FULL-class head no longer stops the rest.
        earlier = [r for r in tickets if r.get("status") == "waiting" and r["ticket"] < ticket.name]
        if any(eligible(land, wt, r, kind, busy) for r in earlier):
            return False
        joined = []
        for row in tickets:  # waiting and pending, in arrival order: a pending member skips its own pretest
            if row["ticket"] != ticket.name and len(joined) < KMAX - 1 and eligible(land, wt, row, kind, busy):
                joined.append(row)
        if len(joined) + 1 < BATCH_MIN:
            return False
        p, runs = rate(qdir.parent / land_events.EVENTS)  # recomputed at every formation
        joined = joined[:(kopt(p) if kind == "affected" else min(kopt(p), KFULL)) - 1]
        land_queue.set_status(ticket, "preparing", batch=[r["branch"] for r in joined])
        chosen[:] = joined
        measured.update(p=None if p is None else round(p, 3), runs=runs)
        return True
    return form, chosen, measured


def queue(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path) -> int | None:
    """Wait for the turn. 0 when a batch landed this branch; None when it lands alone (``land.rounds``)."""
    kind = group_of(wt, branch)
    form, chosen, measured = former(land, wt, qdir, ticket, kind or "affected")
    if not plain_auto(args, land.EXTRA) or safety(land, wt, branch) or kind is None:
        form = None  # a batch is tested; safety branches and explicit --tests land alone (D-889 3)
    while True:
        got = land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=land_prepare.watch(land, wt),
                              done=lambda: in_main(land, wt, branch), form=form)
        if got == "landed":
            land_full.forget(wt, branch)
            print(f"== landed in a batch (not pushed): main {land.out(wt, 'rev-parse', 'main')[:10]} holds {branch}\n"
                  f"[land] this worktree is now removable. After leaving it, from the main checkout {main_co}:\n"
                  f"  {land.worktrees.SWEEP}")
            return 0
        if got != "batch":
            return None
        if (code := run(land, wt, branch, args, python, qdir, ticket, main_co, chosen[:], measured, kind)) is not None:
            return code
        form = None  # once its half is down to itself, this landing goes alone


def run(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path,
        members: list[dict], measured: dict, kind: str, after: str = "waiting") -> int | None:
    """Lead ``members``, bisecting by halving on a stop; 0 once landed, None when this landing is left alone."""
    while members:
        code, took = lead(land, wt, branch, args, python, qdir, ticket, main_co, members, measured, kind)
        if code is not None:
            return code
        group = [branch, *took]
        keep = [r for r in members if r["branch"] in took][:(len(group) + 1) // 2 - 1]  # the first half
        land_queue.set_status(ticket, after, batch=[r["branch"] for r in keep])
        land_events.emit("train", branches=group, k=len(group), **measured, result="stopped",
                         bisect=f"keeps {len(keep) + 1} of {len(group)}, the rest re-form or go alone")
        members = keep
    return None


def early(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path) -> int | None:
    """At the start, before a pretest of its own: lead the waiting and pending tickets of this landing's group,
    so they share one pretest. On 2026-10-28 every waiting ticket was FULL-class or unprepared, so the pending
    affected ones never found a leader and each waited for a pretest slot of its own. 0 when the batch landed
    this branch; None to go on alone (its own pretest, then ``queue``)."""
    if ticket is None or args.tests != "auto":
        return None  # a skipped or explicit run never leads
    tickets = land_queue.ahead(qdir, Path("~"))
    busy = taken(tickets)
    if branch in busy or not any(
            r["ticket"] != ticket.name and r.get("status") in ("waiting", "pending") for r in tickets):
        return None  # another batch carries it; nobody to carry
    if land_full.restore(wt, branch) is not None:
        return None  # a prepared landing leads from its wait (``former``)
    kind = batchable(land, wt, wt, branch, land.out(wt, "rev-parse", "HEAD"))
    if kind is None:
        return None  # safety lands alone
    joined = [r for r in tickets if r["ticket"] != ticket.name and eligible(land, wt, r, kind, busy)]
    if not joined:
        return None
    p, runs = rate(qdir.parent / land_events.EVENTS)
    joined = joined[:(kopt(p) if kind == "affected" else min(kopt(p), KFULL)) - 1]
    land_queue.set_status(ticket, "pending", batch=[r["branch"] for r in joined])
    mine = {branch, *(r["branch"] for r in joined)}
    rivals = [r for r in land_queue.ahead(qdir, Path("~")) if r["ticket"] < ticket.name and r.get("batch")
              and mine & {r.get("branch"), *r["batch"]}]
    if rivals:  # an earlier ticket took one of these in the same moment: it leads, this one goes alone
        land_queue.set_status(ticket, "pending", batch=[])
        return None
    measured = {"p": None if p is None else round(p, 3), "runs": runs}
    code = run(land, wt, branch, args, python, qdir, ticket, main_co, joined, measured, kind, after="pending")
    if code is None:
        land_queue.set_status(ticket, "preparing", batch=[])
    return code


def lead(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path,
         joined: list[dict], measured: dict, kind: str = "affected") -> tuple[int | None, list[str]]:
    """Merge, prepare and land the batch: (code, merged members); code None after a stop, back on ``branch``."""
    name, took = f"{branch}-batch{time.strftime('%H%M%S')}-k{len(joined) + 1}", []  # a halved retry gets its own
    try:
        land.git(wt, "switch", "-c", name)
        for row in joined:
            tip = land.out(wt, "rev-parse", f"refs/heads/{row['branch']}")
            try:
                land.merge(wt, tip, name, python, False, source=row["branch"])
                took.append(row["branch"])
            except land.Stop as stop:
                print(f"[batch] {row['branch']} left out, it lands alone: {str(stop).splitlines()[0]}", flush=True)
        if not took:
            raise land.Stop("no member merged without a conflict")
        land_queue.set_status(ticket, "preparing", batch=took)
        print(f"[batch] {name}: {branch} + {', '.join(took)}", flush=True)
        land_events.emit("train", branches=[branch, *took], k=len(took) + 1, **measured, group=kind, result="formed")
        main_sha = land.out(wt, "rev-parse", "main")
        land.merge(wt, main_sha, name, python, False)
        if kind == "affected" and land.select(wt, main_sha, python)[1]:
            raise land.Stop("the affected batch selects the FULL tier: it re-forms by group (D-889 addendum 6)")
        land_prepare.prepare(land, wt, name, args, python, qdir, ticket)
        land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=land_prepare.watch(land, wt))
        code = land.rounds(args, wt, name, main_co, python, qdir, ticket)
    except (land.Stop, land_queue.QueueError) as stop:
        land_full.forget(wt, name)
        back = land.git(wt, "switch", branch, check=False)
        if back.returncode != 0:
            raise land.Stop(f"batch {name} stopped ({stop}); switching back to {branch} failed, worktree left"
                            f" as is:\n{back.stdout}{back.stderr}") from stop
        print(f"[batch] {name} stopped, kept for its log; it bisects: {stop}", flush=True)
        return None, took
    land.git(wt, "switch", branch)
    land.git(wt, "merge", "--ff-only", "main")  # the branch is in main: its worktree reads as landed
    land.git(wt, "branch", "-d", name, check=False)
    land_full.forget(wt, name)
    land_full.forget(wt, branch)
    land_events.emit("train", branches=[branch, *took], k=len(took) + 1, **measured, result="landed")
    return code, took
