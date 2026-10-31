"""Roll waiting landings into one branch with one queue ticket (D-889 addendum 11, a bors-style rollup).

Ticket-level auto batching (addenda 4/6) let a leader carry members that kept their own tickets; their interplay
deadlocked the queue and it was turned off (addendum 9). A rollup instead merges the members' snapshots into one
branch, queues that branch once with land_async, and then stops the members' land.py, so no ticket waits on another.
On 2026-11-01 seven paused landings were rolled up by hand this way.

    python tools/land_rollup.py plan                # read-only: which pending landings would roll up
    python tools/land_rollup.py apply               # build land rollup branch, check, queue it, stop the members
    python tools/land_rollup.py split <rollup>      # after a failed rollup: its members as two halves (or alone)

Members: 'pending' land_async tickets on this host, not urgent, not carried and not leading a batch, whose hidden
tree is at the snapshot tip. A landing that touches a safety path lands alone. Affected-tier and FULL-tier landings
never share a rollup. At most ROLLUP_MAX members; a member that does not merge cleanly (land_merge's record
auto-resolve aside) is left to land on its own.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land  # noqa: E402  (merge, checks, Stop)
import land_async  # noqa: E402
import land_batch  # noqa: E402
import land_merge  # noqa: E402
import land_queue  # noqa: E402
import land_selection  # noqa: E402

ROLLUP_MAX = int(os.environ.get("ROSY_ROLLUP_MAX", "6"))


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def tier(repo: Path, branch: str) -> str | None:
    """'affected' or 'full' for main..branch, or None when it touches a safety path (it lands alone)."""
    sel = land_selection._affected(land, repo, sys.executable, "main", branch)
    if any(e.endswith(land_selection.SAFETY_TRIGGER) for e in sel.get("escalations") or ()):
        return None
    return sel["mode"]


def candidates(rows: list[dict], repo: Path, host: str | None = None) -> list[dict]:
    """Queue rows (oldest first) a rollup may take."""
    host = host or socket.gethostname()
    carried = land_batch.taken(rows)
    found = []
    for r in rows:
        tree = Path(r.get("worktree") or "")
        if (r.get("status") != "pending" or land_async.HOLDER not in tree.parts or r.get("urgent")
                or r.get("host") != host or r.get("batch") or r.get("branch") in carried or not tree.is_dir()):
            continue
        tip = git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{r['branch']}", check=False).stdout.strip()
        if tip and tip == git(tree, "rev-parse", "HEAD", check=False).stdout.strip():
            found.append(r)
    return found


def plan(repo: Path, rows: list[dict], tier_of=tier) -> list[dict]:
    """Members, in queue order: one tier, merging together onto main; fewer than two means no rollup."""
    cur, kind, members = git(repo, "rev-parse", "main").stdout.strip(), None, []
    for r in rows:
        if len(members) >= ROLLUP_MAX:
            break
        t = tier_of(repo, r["branch"])
        if t is None or (kind and t != kind):
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
    return members if len(members) >= 2 else []


def build(repo: Path, members: list[dict], now: datetime, python: str = sys.executable,
          start=land_async.start) -> tuple[str, list[dict]] | None:
    """Merge members into a fresh branch from main, run the stage-0 checks, queue it; (snapshot, merged members)."""
    stamp = f"{now:%Y%m%d%H%M%S}"
    branch, wt = f"fix/land-rollup-{stamp}", land_async.holder(repo) / f"rollup-build-{stamp}"
    git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
    try:
        merged = []
        for r in members:
            try:
                land.merge(wt, git(repo, "rev-parse", r["branch"]).stdout.strip(), branch, python, False,
                           source=r["branch"])
                merged.append(r)
            except land.Stop as exc:
                print(f"[rollup] {r['branch']} left out: {str(exc).splitlines()[0]}", flush=True)
        if len(merged) < 2:
            print("[rollup] fewer than two members merged: no rollup", flush=True)
            return None
        land.safety_review(wt, "main", "HEAD", python)
        land.size_check(wt, "main", "HEAD", python)
        if (wt / land.HARNESS).is_file():
            land.step(wt, [python, land.HARNESS, "lint"], None, "lint")
        snap, log = start(wt, ["--tests", "auto"], now, land_async.detach)
        (log.parent / (log.name.removesuffix(".log") + ".members")).write_text(
            json.dumps([{"branch": r["branch"], "worktree": r["worktree"]} for r in merged], indent=1),
            encoding="utf-8")
        return snap, merged
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)


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
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    qdir = land_queue.queue_dir(repo)
    now = datetime.now(timezone.utc)
    if argv[:1] == ["split"] and len(argv) == 2:
        split(repo, argv[1], now)
        return 0
    members = plan(repo, candidates(land_queue.ahead(qdir, Path("~")), repo))
    if not members:
        print("[rollup] no rollup: fewer than two pending landings fit together")
        return 0
    print("[rollup] members: " + ", ".join(r["branch"] for r in members))
    if argv[:1] != ["apply"]:
        return 0
    built = build(repo, members, now)
    if built is None:
        return 1
    snap, merged = built
    for r in merged:  # only now: the rollup ticket exists, so the members' commits are still queued
        stop(int(r["pid"]))
    print(f"[rollup] queued {snap}; stopped {len(merged)} member landing(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
