"""Publish local main to origin as a merge-commit PR (D-868 2), dry run unless --apply.

    python tools/publish_main.py [--min-hours 6] [--force-blocked "<reason>"] [--apply]
    python tools/publish_main.py --merge-when-green <PR> [--apply]

Publish mode:
1. ``git fetch origin``. If origin/main is not an ancestor of local main, ``git merge-tree`` (no checkout
   is touched) decides: conflicts only in ``SYNC_RECORDS`` (content conflicts) -> exit 4 and the sync
   landing to run; anything else (code, add/add, rename/delete) -> exit 3 "sync needs robot-4d". This
   version never performs the sync landing itself.
2. Publish SHA: the newest commit of ``--ancestry-path origin/main..main`` (contains origin/main, is in
   local main) with a green FULL land record. **Green FULL** = ``tools/hooks/land_record.py`` holds a
   record for exactly that SHA (land.py writes one only after a fast-forward of that very candidate with
   0 NEW, no LOAD-FLAKY and no pass borrowed from another tree), its base is an ancestor of the SHA, and
   one invocation is exactly ``["test"]`` (root test/ whole: only ``lab_full_invocations``, the FULL tier,
   runs it; the affected tier names root test files one by one). Records do not say FULL themselves.
   Not ``--first-parent``: a land.py landing is a merge with the topic branch as first parent, so the
   main tips that hold records sit on second parents.
3. Due when the last publish (newest ``origin/publish/main-YYYYMMDD[-HH]`` by name; with --apply also
   merged ``publish/main-`` PRs from gh) is older than --min-hours, or ``--force-blocked`` names a waiting PR.
4. --apply: refuse if a publish PR is open; push ``<sha>:refs/heads/publish/main-YYYYMMDD-HH`` (UTC) from
   a temporary detached worktree at that SHA under ``<git-common-dir>/rosy-publish/`` so pre-push selects
   from the pushed tree (it reads the working tree), never --no-verify or force; ``gh pr create``; remove
   the worktree.

Merge mode (``--merge-when-green``): the PR must be an open ``publish/main-`` PR whose head still has a
green FULL record, ``mergeable`` MERGEABLE, ``mergeStateStatus`` not DIRTY/BEHIND, and check ``ci-result``
SUCCESS; --apply then runs ``gh pr merge --merge --match-head-commit <head>``. PRs are never closed,
reopened or force-pushed.

Exit codes: 0 done, planned (dry run), nothing to publish or not due | 1 git/gh failure, ci-result
failed or a refusal (branch exists, PR not a publish PR) | 2 usage | 3 sync needs robot-4d |
4 clean sync landing needed first | 5 not ready yet (ci-result pending, mergeable UNKNOWN) |
6 PR not mergeable: sync needed | 7 a publish PR is already open.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
import land_record  # noqa: E402  (green land.py results per landed commit)

SYNC_RECORDS = frozenset({"docs/logs.md", "docs/index.md", "tools/harness/adr_gaps.txt"})
PREFIX = "publish/main-"
STAMP = re.compile(r"publish/main-(\d{8})(?:-(\d{2}))?")


class Stop(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise Stop(1, f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}")
    return result


def run_gh(repo: Path, *args: str) -> str:
    result = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise Stop(1, f"gh {' '.join(args[:3])} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def ancestor(repo: Path, a: str, b: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def sync_conflicts(repo: Path) -> list[str] | None:
    """None when origin/main merges into main with only SYNC_RECORDS content conflicts, else what blocks."""
    tree = git(repo, "merge-tree", "--write-tree", "--name-only", "main", "origin/main", check=False)
    if tree.returncode not in (0, 1):
        raise Stop(1, f"git merge-tree failed ({tree.returncode}): {tree.stderr.strip()}")
    files, _, messages = tree.stdout.partition("\n\n")
    blocking = [p for p in files.splitlines()[1:] if p not in SYNC_RECORDS]
    for line in messages.splitlines():
        content = re.fullmatch(r"CONFLICT \(content\): Merge conflict in (.+)", line)
        if line.startswith("CONFLICT") and not (content and content[1] in SYNC_RECORDS):
            blocking.append(line)
    return sorted(set(blocking)) or None


def green_full(repo: Path, sha: str) -> bool:
    record = land_record.read(repo, sha)
    return bool(record) and ["test"] in record.get("invocations", []) and ancestor(repo, record["base"], sha)


def publish_sha(repo: Path) -> str | None:
    for sha in git(repo, "rev-list", "--topo-order", "--ancestry-path", "origin/main..main").stdout.split():
        if green_full(repo, sha):
            return sha
    return None


def _stamp(name: str) -> datetime | None:
    match = STAMP.search(name)
    if not match:
        return None
    return datetime.strptime(match[1] + (match[2] or "00"), "%Y%m%d%H").replace(tzinfo=timezone.utc)


def last_publish(repo: Path, apply: bool) -> datetime | None:
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/remotes/origin/{PREFIX}*").stdout
    times = [t for t in map(_stamp, refs.split()) if t]
    if apply:
        merged = json.loads(run_gh(repo, "pr", "list", "--state", "merged", "--search", f"head:{PREFIX}",
                                   "--json", "headRefName,mergedAt", "--limit", "20") or "[]")
        times += [datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")) for pr in merged if pr.get("mergedAt")]
    return max(times, default=None)


def publish(repo: Path, args: argparse.Namespace, now: datetime) -> str:
    git(repo, "fetch", "origin")
    if not ancestor(repo, "origin/main", "main"):
        blocking = sync_conflicts(repo)
        if blocking:
            raise Stop(3, "sync needs robot-4d: " + ", ".join(blocking))
        raise Stop(4, "origin/main is not in local main; the merge is clean or records-only. From a worktree:"
                      " git merge origin/main, then python tools/land.py --tests auto")
    sha = publish_sha(repo)
    if sha is None:
        return "nothing to publish: no commit past origin/main has a green FULL land record"
    last = last_publish(repo, args.apply)
    due = last is None or now - last >= timedelta(hours=args.min_hours)
    when = last.isoformat(timespec="minutes") if last else "never"
    if not due and not args.force_blocked:
        return f"not due: last publish {when}, --min-hours {args.min_hours}; would publish {sha[:10]}"
    branch = PREFIX + now.strftime("%Y%m%d-%H")
    why = f"forced: {args.force_blocked}" if args.force_blocked else f"last publish {when}"
    if not args.apply:
        return f"dry run: would push {sha} to {branch} and open a PR ({why}); rerun with --apply"
    if json.loads(run_gh(repo, "pr", "list", "--state", "open", "--search", f"head:{PREFIX}",
                         "--json", "number") or "[]"):
        raise Stop(7, "a publish PR is already open: use --merge-when-green <PR>")
    if git(repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", check=False).returncode == 0:
        raise Stop(1, f"origin already has {branch}; never force-pushed, try next hour")
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    temp = common / "rosy-publish" / branch.replace("/", "-")
    git(repo, "worktree", "add", "--detach", str(temp), sha)
    try:
        push = git(temp, "push", "origin", f"{sha}:refs/heads/{branch}", check=False)
        if push.returncode != 0:
            raise Stop(1, f"push refused (pre-push or remote):\n{push.stdout}{push.stderr}".rstrip())
    finally:
        git(repo, "worktree", "remove", "--force", str(temp), check=False)
    url = run_gh(repo, "pr", "create", "--base", "main", "--head", branch,
                 "--title", f"publish: local main {sha[:10]} ({now:%Y-%m-%d %H} UTC)",
                 "--body", f"D-868 publish of local main `{sha}` (green FULL land record; {why}).\n"
                           "Merge with a merge commit only: `python tools/publish_main.py --merge-when-green"
                           " <PR> --apply`.").strip()
    return f"pushed {sha} to {branch}; PR {url}"


def merge_when_green(repo: Path, pr: str, apply: bool) -> str:
    view = json.loads(run_gh(repo, "pr", "view", pr, "--json",
                             "state,headRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup"))
    head = view["headRefOid"]
    if view["state"] != "OPEN" or not view["headRefName"].startswith(PREFIX):
        raise Stop(1, f"PR {pr} is not an open {PREFIX} PR ({view['state']} {view['headRefName']})")
    if not green_full(repo, head):
        raise Stop(1, f"PR {pr} head {head[:10]} has no green FULL land record here; not merging")
    if view["mergeable"] == "CONFLICTING" or view["mergeStateStatus"] in ("DIRTY", "BEHIND"):
        raise Stop(6, f"sync needed: PR {pr} is {view['mergeable']}/{view['mergeStateStatus']}")
    if view["mergeable"] != "MERGEABLE":
        raise Stop(5, f"PR {pr} mergeable is {view['mergeable']}; retry later")
    checks = [c for c in view.get("statusCheckRollup") or [] if c.get("name") == "ci-result"]
    state = (checks[0].get("conclusion") or checks[0].get("status") or "") if checks else "MISSING"
    if state != "SUCCESS":
        if state in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            raise Stop(1, f"ci-result {state} on PR {pr}; not merging")
        raise Stop(5, f"ci-result is {state} on PR {pr}; retry later")
    if not apply:
        return f"dry run: PR {pr} is mergeable and ci-result is green; would merge {head[:10]} with --apply"
    run_gh(repo, "pr", "merge", pr, "--merge", "--match-head-commit", head)
    return (f"merged PR {pr} at {head[:10]} (merge commit). Next, in the main checkout:"
            " git fetch origin && git merge --ff-only origin/main")


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="push/open the PR or merge (default: dry run)")
    parser.add_argument("--min-hours", type=float, default=6.0)
    parser.add_argument("--force-blocked", metavar="REASON", help="publish now: a teammate PR waits on it")
    parser.add_argument("--merge-when-green", metavar="PR")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.merge_when_green:
            message = merge_when_green(args.repo, args.merge_when_green, args.apply)
        else:
            message = publish(args.repo, args, now or datetime.now(timezone.utc))
    except Stop as stop:
        print(f"[publish] {stop}", file=sys.stderr)
        return stop.code
    print(f"[publish] {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
