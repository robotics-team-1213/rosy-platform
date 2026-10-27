"""Batch landing for tools/land.py: while a turn runs, two or more waiting landings prepare and land as one.

On 2026-10-28 sixteen landings queued. Each turn merged main, tested main's delta and fast-forwarded, so the
last one waited for fifteen serial turns, and every one of them moved main under everyone behind it. Now the
earliest waiting ticket, while another ticket blocks it, leads a batch when at least ``BATCH_MIN`` waiting
tickets (itself included) hold a green prepared tier (``land_full.restore``). Its ticket names the members
(``batch``), so they wait behind it (``land_queue.blockers``). In its own worktree it merges each member's
tip into a new branch ``<leader>-batch<HHMMSS>`` (``land.merge``: the records auto-resolve; a member with any
other conflict is left out and lands alone), prepares that branch outside the lock (``land_prepare``), and
lands it through the ordinary rounds: one turn, one fast-forward for all. A member sees its tip in main and
ends as landed. If the batch stops (a NEW failure, a conflict, the size ratchet, the queue), the leader goes
back to its own branch, which the batch never touched, clears ``batch`` and lands alone; so do the members.
Never resets or force-deletes: a stopped batch branch is kept for its log; a landed one goes with ``-d``.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import land_events
import land_full
import land_prepare
import land_queue

BATCH_MIN = 2  # waiting tickets, the leader included, that make a batch


def in_main(land, wt: Path, branch: str) -> bool:
    return land.git(wt, "merge-base", "--is-ancestor", f"refs/heads/{branch}", "main", check=False).returncode == 0


def eligible(land, wt: Path, row: dict) -> bool:
    """A waiting ticket another landing may carry: this host, a clean prepared branch at its worktree's HEAD."""
    other, name = Path(row.get("worktree") or "."), row.get("branch") or ""
    if row.get("host") != socket.gethostname() or row.get("batch") or name in ("", "main", "HEAD"):
        return False
    if not other.is_dir() or other.resolve() == wt.resolve() or in_main(land, wt, name):
        return False
    head = land.git(other, "rev-parse", "HEAD", check=False).stdout.strip()
    tip = land.git(wt, "rev-parse", f"refs/heads/{name}", check=False).stdout.strip()
    return bool(head) and head == tip and land_full.restore(other, name) is not None


def former(land, wt: Path, qdir: Path, ticket: Path):
    """``form`` for ``land_queue.wait`` and the list it fills with the members it chose."""
    chosen: list[dict] = []

    def form(rows: list[dict]) -> bool:
        tickets = land_queue.ahead(qdir, Path("~"))
        if any(r.get("batch") for r in tickets):
            return False  # one batch at a time
        waiting = [r for r in tickets if r.get("status") == "waiting"]
        if len(waiting) < BATCH_MIN or waiting[0]["ticket"] != ticket.name:
            return False
        joined = [r for r in waiting[1:] if eligible(land, wt, r)]
        if len(joined) + 1 < BATCH_MIN:
            return False
        land_queue.set_status(ticket, "preparing", batch=[r["branch"] for r in joined])
        chosen[:] = joined
        return True
    return form, chosen


def queue(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path) -> int | None:
    """Wait for the turn. 0 when a batch landed this branch; None when it lands alone (``land.rounds``)."""
    form, chosen = former(land, wt, qdir, ticket)
    form = form if args.tests == "auto" else None  # a batch is tested; a skipped or hand-picked run never leads one
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
        if (code := lead(land, wt, branch, args, python, qdir, ticket, main_co, chosen)) is not None:
            return code
        form = None  # once stopped, this landing goes alone


def lead(land, wt: Path, branch: str, args, python: str, qdir: Path, ticket: Path, main_co: Path,
         joined: list[dict]) -> int | None:
    """Merge, prepare and land the batch; None after a stop, back on ``branch`` with ``batch`` cleared."""
    name, took = f"{branch}-batch{time.strftime('%H%M%S')}", []
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
        land_events.emit("batch", branch=name, members=took)
        land_prepare.prepare(land, wt, name, args, python, qdir, ticket)
        land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=land_prepare.watch(land, wt))
        code = land.rounds(args, wt, name, main_co, python, qdir, ticket)
    except (land.Stop, land_queue.QueueError) as stop:
        land_full.forget(wt, name)
        back = land.git(wt, "switch", branch, check=False)
        if back.returncode != 0:
            raise land.Stop(f"batch {name} stopped ({stop}); switching back to {branch} failed, worktree left"
                            f" as is:\n{back.stdout}{back.stderr}") from stop
        land_queue.set_status(ticket, "waiting", batch=[])
        print(f"[batch] {name} stopped, kept for its log; {branch} and the members land alone: {stop}", flush=True)
        return None
    land.git(wt, "switch", branch)
    land.git(wt, "merge", "--ff-only", "main")  # the branch is in main: its worktree reads as landed
    land.git(wt, "branch", "-d", name, check=False)
    land_full.forget(wt, name)
    land_full.forget(wt, branch)
    return code
