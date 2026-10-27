"""Speculative prepare (D-889 addendum 3): run the turn's main-delta selection before the turn, on the tree the
turn will most likely test, outside the lock.

On 2026-10-27 a landing took 2.6 turns: a prepare took 15-60 min, two to four landings moved main meanwhile, and
the turn's selection of main's delta outgrew the turn cap, so the ticket prepared again and main moved again.
After its own prepare a ticket predicts main as main plus each waiting ticket ahead of it (their land_full
candidates, in queue order), merges itself on top (``land.merge``, so the records are resolved as at a turn) and
runs ``select(<its FULL main>, head=<predicted main>, landed=True)`` there: the selection its turn would run. The
predicted tree is kept in its land_full record. At the turn, when the merged candidate's tree equals it up to the
records ``land_merge.resolver`` regenerates, that selection already passed on this tree: the turn runs only the
root test/ part (the guards read those records) and lands. Otherwise the turn runs as before, never worse.

A chain stops at a ticket without a land_full record, a carried (main-red) one, or a safety-path one (D-889 6: those
run serial and alone; nobody stacks on them); a still-preparing ticket is skipped (it most likely lands later).
A FULL ticket stays in the chain: it passed FULL on its candidate, and this test runs on the merged tree anyway.
Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

from land_merge import resolver
from land_selection import SAFETY_TRIGGER, _affected

KEY = "spec"


def _record(land, wt: Path, branch: str) -> dict | None:
    try:
        record = json.loads(land.land_full._path(wt, branch).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def chain(land, wt: Path, python: str, qdir: Path, ticket: Path) -> list[str]:
    """Candidates of the waiting tickets ahead, in queue order, up to the first that nobody stacks on."""
    found = []
    for row in land.land_queue.ahead(qdir, ticket):
        if row.get("status") in ("preparing", "pending"):
            continue
        record = _record(land, wt, str(row.get("branch", "")))
        if not record or record.get("tier") not in ("full", "affected") or not (record.get("candidate")
                                                                               and record.get("main")):
            break
        selected = _affected(land, wt, python, record["main"], record["candidate"])
        if any(e.endswith(SAFETY_TRIGGER) for e in selected.get("escalations", [])):
            break
        found.append(record["candidate"])
    return found


def prepare(land, wt: Path, branch: str, args, python: str, qdir: Path | None, ticket: Path | None) -> None:
    """After the prepare: test the predicted turn and keep its tree in the land_full record. Never stops the landing."""
    record = _record(land, wt, branch)
    if ticket is None or not record or record.get("tier") not in ("full", "affected"):
        return
    links = chain(land, wt, python, qdir, ticket)
    if not links:
        land.land_events.emit("speculation", stage="prepare", chain=[], ran=False)
        return
    main_sha, head = land.out(wt, "rev-parse", "main"), land.out(wt, "rev-parse", "HEAD")
    stacked, spec = [], None
    # a main-red carry judged on this speculative tree must not mark this landing's own turn
    carried, passes = list(land.land_mainred.CARRIED), list(land.land_mainred.PASSES)
    try:
        land.git(wt, "checkout", "-q", "--detach", main_sha)
        for candidate in links:
            try:
                land.merge(wt, candidate, branch, python, False)
            except land.Stop:
                break  # a conflict outside the records: the chain ends before this ticket
            stacked.append(candidate)
        if stacked:
            predicted = land.out(wt, "rev-parse", "HEAD")
            land.merge(wt, head, branch, python, False)
            invocations, note = land.select(wt, record["main"], python, head=predicted, landed=True)
            land.run_tests(wt, args, invocations, land.tmp_dir(branch), "spec")
            spec = {"tree": land.out(wt, "rev-parse", "HEAD^{tree}"), "sha": land.out(wt, "rev-parse", "HEAD"),
                    "base": record["main"], "candidate": record["candidate"], "chain": stacked, "main": main_sha,
                    "invocations": invocations, "full": bool(note)}
    except (land.Stop, land.subprocess.CalledProcessError) as error:  # a NEW failure here is the turn's to judge
        print(f"[land] speculative prepare abandoned: {str(error).splitlines()[0] if str(error) else error!r}",
              flush=True)
    finally:
        land.land_mainred.CARRIED[:], land.land_mainred.PASSES[:] = carried, passes
        land.git(wt, "merge", "--abort", check=False)
        land.git(wt, "checkout", "-q", branch)
    if land.out(wt, "rev-parse", "HEAD") != head:
        raise land.Stop(f"speculative prepare left HEAD off {head[:10]}; check the worktree")
    if spec:
        land.land_full._path(wt, branch).write_text(json.dumps({**record, KEY: spec}), encoding="utf-8")
    land.land_events.emit("speculation", stage="prepare", chain=stacked, ran=spec is not None)


def held(land, wt: Path, branch: str, full_main: str, candidate: str) -> list[list[str]] | None:
    """At the turn: the root test/ part of the speculated selection when this candidate's tree is the speculated
    one up to the records (the guard set when that part is empty); None when the prediction broke."""
    record = _record(land, wt, branch)
    spec = (record or {}).get(KEY)
    if not isinstance(spec, dict) or spec.get("base") != full_main or spec.get("candidate") != record.get("candidate"):
        land.land_events.emit("speculation", stage="turn", held=False, why="none" if not spec else "stale")
        return None
    differ = land.lines(wt, "diff", "--name-only", spec["tree"], f"{candidate}^{{tree}}")
    if not all(map(resolver, differ)):
        # which bet failed: a chained ticket not landed (bounced or still behind), or landings outside the chain
        landed = [c for c in spec["chain"] if land.git(wt, "merge-base", "--is-ancestor", c, "main",
                                                        check=False).returncode == 0]
        moved = len(land.lines(wt, "rev-list", "--first-parent", "main", f"^{spec['main']}")) if spec.get("main") else None
        land.land_events.emit("speculation", stage="turn", held=False, why="tree", differ=differ[:20],
                              missing=[c for c in spec["chain"] if c not in landed],
                              outside=None if moved is None else max(0, moved - len(landed)))
        return None
    root = [kept for kept in ([p for p in inv if p.startswith("test/") or p == "test"] for inv in spec["invocations"])
            if kept]
    land.land_events.emit("speculation", stage="turn", held=True, differ=differ[:20])
    guards = [g for g in land.land_guards.GUARDS if (wt / g).exists()]
    return root or ([guards] if guards else [])  # never an empty invocation: bare pytest would collect anything


def with_spec(land, wt: Path, branch: str, prepared: dict | None) -> dict | None:
    """``prepared`` for the land record of a held turn: its tier, plus the speculated selection (it passed on this
    tree up to the records). The record's base stays the turn's main, an ancestor of the landed commit."""
    spec = ((_record(land, wt, branch) or {}).get(KEY) or {})
    return {**prepared, "invocations": prepared["invocations"] + spec.get("invocations", [])} if prepared else None
