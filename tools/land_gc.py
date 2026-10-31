"""Clean up after stopped or landed land_async landings (hidden trees under <git-common-dir>/rosy-land-wt).

land_async keeps a stopped landing's hidden worktree, snapshot branch, `.stopped` marker, script copy and logs for its
owner; nothing removed them, and by 2026-11-01 there were 122 markers and as many land/... branches. A hidden landing
is removed only when nothing is lost: no live queue ticket references it, its log is at least an hour old, its tree
is clean, and its commits are all in main or in a live ticket's branch. Anything else is kept and reported.

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

HOLDER, QUEUE, PREFIX = "rosy-land-wt", "rosy-land-queue", "land/"
QUIET_S = 3600  # the 1 h wait worktree_rules gives landed worktrees
FILES = (".stopped", ".land_async.py", ".resume.log")
SNAPSHOT = re.compile(r"-\d{14}(-batch\d+-k\d+)?$")  # land_async.snapshot_name, plus land_batch's batch branches


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def live(common: Path) -> tuple[set[str], set[str]]:
    """(branches, worktree paths) that live queue tickets name, batches included."""
    branches, trees = set(), set()
    for path in (common / QUEUE).glob("[0-9]*.json"):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if land_queue.pid_alive(int(info.get("pid") or 0)):
            branches.update([info.get("branch", ""), *(info.get("batch") or [])])
            trees.add(str(Path(info.get("worktree") or ".").resolve()))
    return branches - {""}, trees


def plan(repo: Path, now: float, log_days: float) -> list[tuple[str, str, Path | None, list[str]]]:
    """(action, reason, hidden tree or None, branches) per leftover; action is remove, keep or log."""
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder = common / HOLDER
    names, trees = live(common)
    refs = [b for b in git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{PREFIX}").splitlines()
            if SNAPSHOT.search(b)]  # only land_async snapshots; a hand-made land/... branch is not ours
    by_name: dict[str, list[str]] = {}
    for ref in refs:
        by_name.setdefault(ref.split("-batch")[0].replace("/", "-"), []).append(ref)
    keys = {p.name for p in holder.iterdir() if p.is_dir()} if holder.is_dir() else set()
    keys |= {p.name[:-len(s)] for s in FILES for p in holder.glob(f"*{s}")} if holder.is_dir() else set()
    keys |= set(by_name)
    out = []
    for name in sorted(keys):
        tree, branches = holder / name, by_name.get(name, [])
        log = holder / f"{name}.log"
        if any(b in names for b in branches) or str(tree.resolve()) in trees:
            out.append(("keep", "live ticket", tree if tree.is_dir() else None, branches))
            continue
        if log.exists() and now - log.stat().st_mtime < QUIET_S:
            out.append(("keep", "log written in the last hour", tree if tree.is_dir() else None, branches))
            continue
        heads = branches + ([git(tree, "rev-parse", "HEAD")] if tree.is_dir() else [])
        unique = git(repo, "rev-list", "--count", "--no-merges", *[h for h in heads if h], "^main",
                     *[f"^{b}" for b in names if git(repo, "rev-parse", "-q", "--verify", b)]) if heads else "0"
        if unique not in ("", "0"):
            out.append(("keep", f"unlanded work ({unique} commit(s) not in main)", tree if tree.is_dir() else None,
                        branches))
        elif tree.is_dir() and git(tree, "status", "--porcelain", "--untracked-files=no"):
            out.append(("keep", "dirty tree", tree, branches))
        else:
            out.append(("remove", "landed or nothing unique", tree if tree.is_dir() else None, branches))
    if holder.is_dir():  # a landing's log outlives it by log_days, for its owner to read the STOP
        for log in holder.glob("*.log"):
            stem = log.name[:-len(".resume.log")] if log.name.endswith(".resume.log") else log.stem
            if not (holder / stem).is_dir() and now - log.stat().st_mtime > log_days * 86400:
                out.append(("log", f"older than {log_days:g} days", None, [str(log)]))
    return out


def apply(repo: Path, rows) -> list[str]:
    """Do the removals; one problem line per step that failed."""
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder, problems = common / HOLDER, []
    for action, _, tree, items in rows:
        if action == "log":
            Path(items[0]).unlink(missing_ok=True)
            continue
        if action != "remove":
            continue
        if tree is not None:
            result = subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)],
                                    capture_output=True, text=True)
            if result.returncode:
                problems.append(f"{tree.name}: {result.stderr.strip()[:120]}")
                continue
            name = tree.name
        else:
            name = items[0].split("-batch")[0].replace("/", "-") if items else ""
        for branch in items:
            git(repo, "branch", "-D", branch)
        for suffix in FILES:
            (holder / f"{name}{suffix}").unlink(missing_ok=True)
    git(repo, "worktree", "prune")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove; without it only print the plan")
    parser.add_argument("--log-days", type=float, default=7, help="delete logs of gone landings older than this")
    args = parser.parse_args(argv)
    repo = Path.cwd()
    rows = plan(repo, time.time(), args.log_days)
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
    for line in apply(repo, rows):
        print(f"[land-gc] FAIL {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
