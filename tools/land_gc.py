"""Clean up after stopped or landed land_async landings (hidden trees under <git-common-dir>/rosy-land-wt).

land_async keeps a stopped landing's hidden worktree, snapshot branch, `.stopped` marker, script copy and logs for its
owner; nothing removed them, and by 2026-11-01 there were 122 markers and as many land/... branches. A hidden landing
is removed only when nothing is lost: no live queue ticket references it, its log is at least an hour old, its tree
is clean, and its commits are all in main. Anything else is kept and reported, including redundant snapshots.

    python tools/land_gc.py [--apply] [--log-days 7]      # dry run without --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_queue  # noqa: E402  (pid_alive)
import land_async  # noqa: E402  (supervisor ownership before the queue ticket)
import worktrees  # noqa: E402  (lossless status, including ignored user data)

HOLDER, QUEUE, PREFIX = "rosy-land-wt", "rosy-land-queue", "land/"
QUIET_S = 3600  # the 1 h wait worktree_rules gives landed worktrees
FILES = (".stopped", ".land_async.py", ".resume.log")
SNAPSHOT = re.compile(r"-\d{14}(-batch\d+-k\d+)?$")  # land_async.snapshot_name, plus land_batch's batch branches


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout.strip()


class Plan(list):
    """Rows and the exact identities checked before offering their removal."""

    def __init__(self, log_days):
        super().__init__()
        self.log_days = log_days
        self.states = {}


def live(common: Path) -> tuple[set[str], set[str]]:
    """(branches, worktree paths) that live queue tickets name, batches included."""
    branches, trees = set(), set()
    for path in (common / QUEUE).glob("[0-9]*.json"):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"unreadable queue ticket: {path.name}") from exc
        if land_queue.pid_alive(int(info.get("pid") or 0)):
            branches.update([info.get("branch", ""), *(info.get("batch") or [])])
            trees.add(str(Path(info.get("worktree") or ".").resolve()))
    return branches - {""}, trees


def plan(repo: Path, now: float, log_days: float, *, only: str | None = None) -> Plan:
    """(action, reason, hidden tree or None, branches) per leftover; action is remove, keep or log."""
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder = common / HOLDER
    names, trees = live(common)
    listing = git(repo, "worktree", "list", "--porcelain")
    registered = {str(Path(line[9:]).resolve()) for line in listing.splitlines()
                  if line.startswith("worktree ")}
    attached = {line[7:]: str(Path(block.splitlines()[0][9:]).resolve()) for block in listing.split("\n\n")
                for line in block.splitlines() if line.startswith("branch ")}
    refs = [b for b in git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{PREFIX}").splitlines()
            if SNAPSHOT.search(b)]  # only land_async snapshots; a hand-made land/... branch is not ours
    by_name: dict[str, list[str]] = {}
    for ref in refs:
        by_name.setdefault(ref.split("-batch")[0].replace("/", "-"), []).append(ref)
    keys = {p.name for p in holder.iterdir() if p.is_dir()} if holder.is_dir() else set()
    keys |= {p.name[:-len(s)] for s in FILES for p in holder.glob(f"*{s}")} if holder.is_dir() else set()
    keys |= set(by_name)
    if only is not None:
        keys &= {only}
    out = Plan(log_days)
    for name in sorted(keys):
        tree, branches = holder / name, by_name.get(name, [])
        log = holder / f"{name}.log"
        if any(b in names for b in branches) or str(tree.resolve()) in trees:
            out.append(("keep", "live ticket", tree if tree.is_dir() else None, branches))
            continue
        if land_async.running(tree):
            out.append(("keep", "live supervisor", tree if tree.is_dir() else None, branches))
            continue
        if log.exists() and now - log.stat().st_mtime < QUIET_S:
            out.append(("keep", "log written in the last hour", tree if tree.is_dir() else None, branches))
            continue
        if tree.is_dir() and (tree.is_symlink() or str(tree.resolve()) not in registered):
            out.append(("keep", "unregistered directory", tree, branches))
            continue
        if any(attached.get(f"refs/heads/{b}", str(tree.resolve())) != str(tree.resolve()) for b in branches):
            out.append(("keep", "snapshot checked out elsewhere", tree if tree.is_dir() else None, branches))
            continue
        refs = [(branch, git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")) for branch in branches]
        head = (git(tree, "rev-parse", "HEAD"), git(tree, "rev-parse", "--symbolic-full-name", "HEAD")) if tree.is_dir() else ()
        heads = [sha for _, sha in refs] + list(head[:1])
        unique = git(repo, "rev-list", "--count", *heads, "^main") if heads else "0"
        if unique != "0":
            out.append(("keep", f"unlanded work ({unique} commit(s) not in main)", tree if tree.is_dir() else None,
                        branches))
        else:
            status = worktrees._status(tree) if tree.is_dir() else ([], [])
            if status is None or any(status):
                out.append(("keep", "dirty tree or ignored data", tree, branches))
            else:
                row = ("remove", "landed or nothing unique", tree, branches)
                out.append(row)
                out.states[(row[2], tuple(branches))] = (refs, head)
    if holder.is_dir():  # a landing's log outlives it by log_days, for its owner to read the STOP
        for log in holder.glob("*.log"):
            stem = log.name[:-len(".resume.log")] if log.name.endswith(".resume.log") else log.stem
            if only is not None and stem != only:
                continue
            if (not (holder / stem).is_dir() and str((holder / stem).resolve()) not in trees
                    and not any(b.replace("/", "-").split("-batch")[0] == stem for b in names)
                    and now - log.stat().st_mtime > log_days * 86400):
                out.append(("log", f"older than {log_days:g} days", None, [str(log)]))
                out.states[(None, (str(log),))] = log.stat()
    return out


def apply(repo: Path, rows) -> list[str]:
    """Do the removals; one problem line per step that failed."""
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder, problems = common / HOLDER, []
    if not isinstance(rows, Plan):
        return ["removal requires an unchanged plan from this process"]
    for row in rows:
        action, _, tree, items = row
        if action not in ("remove", "log"):
            continue
        key = (tree, tuple(items))
        try:
            name = tree.name if tree else Path(items[0]).name.removesuffix(".resume.log").removesuffix(".log")
            fresh = plan(repo, time.time(), rows.log_days, only=name)
            if row not in fresh or rows.states[key] != fresh.states.get(key):
                problems.append(f"{tree or items}: state changed; kept")
                continue
            if action == "log":
                Path(items[0]).unlink()
                continue
            with land_async.locked(tree.parent / (tree.name + ".supervisor.lock")):
                if tree.is_dir():
                    git(repo, "worktree", "remove", str(tree))
                for branch, sha in rows.states[key][0]:
                    git(repo, "update-ref", "-d", f"refs/heads/{branch}", sha)
                for suffix in FILES:
                    (holder / f"{name}{suffix}").unlink(missing_ok=True)
        except (subprocess.CalledProcessError, OSError, RuntimeError, ValueError, land_async.Busy) as exc:
            detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            problems.append(f"{tree or items}: {detail.strip()[:120]}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove; without it only print the plan")
    parser.add_argument("--log-days", type=float, default=7, help="delete logs of gone landings older than this")
    args = parser.parse_args(argv)
    repo = Path.cwd()
    try:
        rows = plan(repo, time.time(), args.log_days)
    except (subprocess.CalledProcessError, OSError, RuntimeError, ValueError) as exc:
        print(f"[land-gc] FAIL cannot establish safe plan: {exc}")
        return 1
    counts: dict[str, int] = {}
    for action, reason, tree, items in rows:
        counts[f"{action}: {reason.split(' (')[0]}"] = counts.get(f"{action}: {reason.split(' (')[0]}", 0) + 1
        if action == "keep" and reason.startswith("unlanded"):
            print(f"KEEP {tree.name if tree else items[0]}: {reason}")
    for key, n in sorted(counts.items()):
        print(f"[land-gc] {n:4d} {key}")
    if not args.apply:
        print("[land-gc] dry run; --apply removes the 'remove' and 'log' rows")
        return 0
    problems = apply(repo, rows)
    for line in problems:
        print(f"[land-gc] FAIL {line}")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main())
