"""Roll waiting landings into one branch with one queue ticket (D-889 addendum 11, a bors-style rollup).

Ticket-level auto batching (addenda 4/6) let a leader carry members that kept their own tickets; their interplay
deadlocked the queue and it was turned off (addendum 9). A rollup instead merges the members' snapshots into one
branch, queues that branch once with land_async, and then stops the members' land.py, so no ticket waits on another.
On 2026-11-01 seven paused landings were rolled up by hand this way.

    python tools/land_rollup.py plan                # read-only: which pending landings would roll up
    python tools/land_rollup.py apply               # build land rollup branch, check, queue it, stop the members
    python tools/land_rollup.py apply --auto        # the watchdog's run: every compatible waiting landing
    python tools/land_rollup.py apply --urgent "<the user's words>"   # the rollup jumps the queue (D-889 5)
    python tools/land_rollup.py split <rollup>      # after a failed rollup: its members as two halves (or alone)

Members: 'pending' land_async tickets on this host, not urgent, not explicit ('alone': FULL, checks, --no-cache), not
carried and not leading a batch, whose hidden tree is at the snapshot tip. At most ROLLUP_MAX members; a member that
does not merge cleanly (land_merge's record auto-resolve aside) is left to land on its own.

D-889 addendum 33 (user, 2026-11-09: "대기하는것들을 하나로 합쳐서 하면 더이상 문제가 없잖아"): a FULL waiter
('preparing' with ``full_wait``, it runs no test) is a member too, and tiers mix: one FULL run covers every member,
safety tests included, instead of one FULL per landing. A rollup is never re-rolled. A stopped rollup is split by
land_async's supervisor (halves, a half of one lands alone with its own STOP). ROSY_ROLLUP_MIXED=0 restores the
addendum 23/32 rules: preparing tickets stay out, one tier per rollup, safety and (with --auto) FULL land alone.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land  # noqa: E402  (merge, checks, Stop)
import land_async  # noqa: E402
import land_batch  # noqa: E402
import land_merge  # noqa: E402
import land_queue  # noqa: E402
import land_selection  # noqa: E402

ROLLUP_MAX = int(os.environ.get("ROSY_ROLLUP_MAX", "12"))
MIXED = os.environ.get("ROSY_ROLLUP_MIXED", "1") != "0"  # D-889 addendum 33's revert switch


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def tier(repo: Path, branch: str) -> str | None:
    """'affected' or 'full' for main..branch, or None when it touches a safety path (it lands alone)."""
    sel = land_selection._affected(land, repo, sys.executable, "main", branch)
    if any(e.endswith(land_selection.SAFETY_TRIGGER) for e in sel.get("escalations") or ()):
        return None
    return sel["mode"]


def affected(repo: Path, branch: str) -> str | None:
    """``tier`` for the unattended rollup: a FULL-tier landing lands alone like a safety one."""
    return "affected" if tier(repo, branch) == "affected" else None


def candidates(rows: list[dict], repo: Path, host: str | None = None, mixed: bool | None = None) -> list[dict]:
    """Queue rows (oldest first) a rollup may take."""
    mixed = MIXED if mixed is None else mixed
    host = host or socket.gethostname()
    carried = land_batch.taken(rows)
    found = []
    for r in rows:
        tree = Path(r.get("worktree") or "")
        # 2026-11-03: a --tests full --no-cache landing for publish evidence was rolled up and ran auto (alone)
        idle = (r.get("status") in ("pending", "waiting")
                or (mixed and r.get("status") == "preparing" and r.get("full_wait")))  # a FULL waiter runs no test
        if (not idle or land_async.HOLDER not in tree.parts or r.get("urgent")
                or (mixed and land_async.ROLLUP.fullmatch(r.get("branch") or ""))
                or r.get("alone")
                or r.get("host") != host or r.get("batch") or r.get("branch") in carried or not tree.is_dir()):
            continue
        tip = git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{r['branch']}", check=False).stdout.strip()
        if tip and tip == git(tree, "rev-parse", "HEAD", check=False).stdout.strip():
            found.append(r)
    return found


def reach(repo: Path, branch: str) -> list[list[str]]:
    """The pytest invocations main..branch selects: what a fellow member must not overlap (D-889 23)."""
    sel = land_selection._affected(land, repo, sys.executable, "main", branch)
    return sel["local_invocations"] if sel["mode"] == "full" else sel["invocations"]


def plan(repo: Path, rows: list[dict], tier_of=tier, reach_of=reach, mixed: bool | None = None) -> list[dict]:
    """Members, in queue order, merging together onto main; fewer than two means no rollup. Unmixed: one tier,
    no safety member. Mixed (addendum 33): any tier; with a FULL or safety member the rollup runs FULL, which
    covers every member, so suite overlap no longer matters."""
    mixed = MIXED if mixed is None else mixed
    cur, kind, members, reached = git(repo, "rev-parse", "main").stdout.strip(), None, [], []
    guards = getattr(getattr(land, "land_guards", None), "GUARDS", ())
    tiers = {r["branch"]: tier_of(repo, r["branch"]) for r in rows}
    whole = mixed and any(t != "affected" for t in tiers.values())
    for r in rows:
        if len(members) >= ROLLUP_MAX:
            break
        t = tiers[r["branch"]]
        if not mixed and (t is None or (kind and t != kind)):
            continue
        # D-889 23: members whose suites overlap would each have to rerun the others'; such a member lands alone
        mine = [] if whole else reach_of(repo, r["branch"])
        if any(land_selection.overlaps(other, mine, guards) for other in reached):
            continue
        res = git(repo, "merge-tree", "--write-tree", "--no-messages", cur, r["branch"], check=False)
        if res.returncode == 1:
            _, manual = land_merge.plan(repo, land_merge.conflict_stages(res.stdout), (cur, r["branch"]))
            if manual:
                continue
            # shortcut: an auto-resolvable member is not folded into ``cur``, so a later clash with it is found
            # only by apply's real merge (which then leaves that later member out); fold it in if that bites.
        elif res.returncode == 0:
            tree = res.stdout.split()[0]
            cur = git(repo, "commit-tree", tree, "-p", cur, "-p", r["branch"], "-m", "rollup plan").stdout.strip()
        else:
            continue
        kind = kind or t
        members.append(r)
        reached.append(mine)
    return members if len(members) >= 2 else []


def member_metadata(place: Path, member: dict, ancestors=()) -> dict:
    """Keep direct owners, embedding frozen child metadata before their sidecars can be collected."""
    data = {k: member[k] for k in ("branch", "worktree", "candidate", "ticket", "members_error") if k in member}
    branch = data["branch"]
    if not land_async.ROLLUP.fullmatch(branch):
        if "members" in member:
            data["members_error"] = "nested metadata on a non-carrier"
        return data
    if data.get("members_error"):
        return data
    try:
        if branch in ancestors:
            raise ValueError("cyclic nested membership")
        children = member["members"] if "members" in member else json.loads(
            (place / (branch.replace("/", "-") + ".members")).read_text(encoding="utf-8"))
        if not isinstance(children, list) or not children or any(
                not isinstance(m, dict) or not isinstance(m.get("branch"), str) or not m["branch"] for m in children):
            raise ValueError("invalid nested members")
        data["members"] = [member_metadata(place, m, (*ancestors, branch)) for m in children]
    except (OSError, ValueError, RecursionError):
        data["members_error"] = "unavailable nested membership"
    return data


def build(repo: Path, members: list[dict], now: datetime, python: str = sys.executable,
          start=land_async.start, urgent: str = "") -> tuple[str, list[dict]] | None:
    """Merge members into a fresh branch from main, run the stage-0 checks, queue it; (snapshot, merged members)."""
    if len({r["branch"] for r in members}) != len(members):
        raise land.Stop("duplicate rollup member branch; preserve the competing tickets for review")
    stamp = f"{now:%Y%m%d%H%M%S}"
    branch, wt = f"fix/land-rollup-{stamp}", land_async.holder(repo) / f"rollup-build-{stamp}"
    git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
    try:
        merged = []
        for r in members:
            try:
                candidate = git(repo, "rev-parse", r["branch"]).stdout.strip()
                land.merge(wt, candidate, branch, python, False, source=r["branch"])
                metadata = member_metadata(land_async.holder(repo), {**r, "candidate": candidate})
                merged.append({**r, **metadata})
            except land.Stop as exc:
                print(f"[rollup] {r['branch']} left out: {str(exc).splitlines()[0]}", flush=True)
        if len(merged) < 2:
            print("[rollup] fewer than two members merged: no rollup", flush=True)
            return None
        land.safety_review(wt, "main", "HEAD", python)
        land.size_check(wt, "main", "HEAD", python)
        if (wt / land.HARNESS).is_file():
            land.step(wt, [python, land.HARNESS, "lint"], None, "lint")
        first = members[0].get("ticket")  # D-889 23: the rollup takes its first member's place in the queue
        if first:
            os.environ[land_queue.TICKET_ENV] = str(land_queue.queue_dir(repo) / first)
        try:
            snap, log = start(wt, ["--tests", "auto", *(["--urgent", urgent] if urgent else [])], now,
                              land_async.detach)
        finally:
            os.environ.pop(land_queue.TICKET_ENV, None)
        (log.parent / (log.name.removesuffix(".log") + ".members")).write_text(
            json.dumps([{k: r[k] for k in ("branch", "worktree", "candidate", "ticket", "members", "members_error")
                         if k in r}
                        for r in merged], indent=1),
            encoding="utf-8")
        return snap, merged
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)


def adopted(qdir: Path, first: dict, wait: float = 180, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Wait until the rollup's land.py owns the first member's ticket (its pid changed), so stopping the member
    cannot leave a dead ticket that a peer's ``blockers`` removes before the rollup adopts it."""
    path, until = qdir / str(first.get("ticket") or ""), clock() + wait
    while first.get("ticket") and clock() < until:
        try:
            if int(json.loads(path.read_text(encoding="utf-8")).get("pid") or 0) != int(first["pid"]):
                return True
        except (OSError, ValueError):
            return False
        sleep(3)
    return False


def stop(pid: int) -> None:
    """End a member's land.py; its supervisor keeps the snapshot and hidden tree (land_async)."""
    # shortcut: the member's remote jobs already running finish on their own; kill them too if hosts stay full.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def resume(member: dict) -> None:
    """Queue one member again on its own snapshot (the restart land_async --supervise does)."""
    tree = Path(member["worktree"])
    script = tree.parent / (tree.name + ".land_async.py")
    script.write_bytes((Path(__file__).resolve().parent / "land_async.py").read_bytes())
    (tree.parent / (tree.name + ".stopped")).unlink(missing_ok=True)
    land_async.detach([sys.executable, "-X", "utf8", str(script), "--supervise", str(tree), member["branch"],
                       "--tests", "auto"], tree.parent / (tree.name + ".resume.log"))


def split(repo: Path, rollup: str, now: datetime, builder=build, resumer=resume) -> list:
    """One level of bisection after a failed rollup: a merge conflict sends every member back alone, a NEW
    failure re-rolls each half (a half of one lands alone)."""
    holder = land_async.holder(repo)
    members = json.loads((holder / f"{rollup}.members").read_text(encoding="utf-8"))
    log = holder / f"{rollup}.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if "conflicts with this branch" in text or "merge aborted" in text:
        halves = [[m] for m in members]
    else:
        halves = [members[: len(members) // 2], members[len(members) // 2:]]
    done = []
    for half in (h for h in halves if h):
        done.append(resumer(half[0]) if len(half) == 1 else builder(repo, half, now))
    return done


def main(argv: list[str]) -> int:
    # this file's checkout, not the cwd: land_async's supervisor runs ``split`` from the hidden holder (.git/...)
    repo = Path(git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").stdout.strip())
    qdir = land_queue.queue_dir(repo)
    now = datetime.now(timezone.utc)
    if argv[:1] == ["split"] and len(argv) == 2:
        split(repo, argv[1], now)
        return 0
    auto = "--auto" in argv  # D-889 23 item 6 / 32: unattended; unmixed, FULL-tier (and safety) landings stay alone
    urgent = argv[argv.index("--urgent") + 1] if "--urgent" in argv[:-1] else ""
    members = plan(repo, candidates(land_queue.ahead(qdir, Path("~")), repo),
                   tier_of=affected if auto and not MIXED else tier)
    if not members:
        print("[rollup] no rollup: fewer than two pending landings fit together")
        return 0
    print("[rollup] members: " + ", ".join(r["branch"] for r in members))
    if argv[:1] != ["apply"]:
        return 0
    built = build(repo, members, now, urgent=urgent)
    if built is None:
        return 1
    snap, merged = built
    adopted(land_queue.queue_dir(repo), merged[0])
    for r in merged:  # only now: the rollup ticket exists, so the members' commits are still queued
        stop(int(r["pid"]))
    print(f"[rollup] queued {snap}; stopped {len(merged)} member landing(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
