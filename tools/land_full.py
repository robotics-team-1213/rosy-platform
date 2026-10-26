"""Keep a branch's green FULL tier across tools/land.py runs (D-762 stage 0, D-803 6).

Within one run, a FULL landing whose ``main`` moved reruns only the selection of main's delta since the
FULL-tested main (``land.py`` ``full_main``). On 2026-10-18 runs also ended between rounds (test hosts
lost for over 600 s, exit 255), and the next run started with a FULL tier again. ``save`` records the
FULL-tested candidate and main under ``<git-common-dir>/rosy-land-full/``; ``restore`` gives that main
back only while the branch still holds exactly the tested change: the candidate is HEAD or an ancestor,
the recorded main is still in ``main``, and the branch added nothing after it but merges of ``main``
whose result is git's own merge (or differs only in the records ``land_merge`` auto-resolves). Anything
else (a fix commit, a hand-edited merge, a rewritten branch) means a FULL tier again. Standard library only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from land_merge import conflict_stages, resolver

RECORDS = "rosy-land-full"


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _path(wt: Path, branch: str) -> Path:
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common) / RECORDS / (branch.replace("/", "-") + ".json")


def save(wt: Path, branch: str, candidate: str, main: str) -> None:
    path = _path(wt, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidate": candidate, "main": main}), encoding="utf-8")


def forget(wt: Path, branch: str) -> None:
    _path(wt, branch).unlink(missing_ok=True)


def restore(wt: Path, branch: str) -> str | None:
    """The main an earlier run's FULL tier passed over, if HEAD still carries only that change."""
    try:
        record = json.loads(_path(wt, branch).read_text(encoding="utf-8"))
        candidate, main = record["candidate"], record["main"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    ancestor = lambda a, b: _git(wt, "merge-base", "--is-ancestor", a, b).returncode == 0  # noqa: E731
    if not (ancestor(candidate, "HEAD") and ancestor(main, "main")):
        return None
    if _git(wt, "rev-list", "--no-merges", "HEAD", f"^{candidate}", "^main").stdout.strip():
        return None  # a commit of the branch's own since the FULL tier: test it all again
    for line in _git(wt, "rev-list", "--merges", "--parents", "HEAD", f"^{candidate}", "^main").stdout.splitlines():
        sha, first, *others = line.split()
        if len(others) != 1 or not ancestor(others[0], "main"):
            return None  # something other than main was merged in
        tree = _git(wt, "merge-tree", "--write-tree", "--no-messages", first, others[0])
        if tree.returncode == 0:
            # land.merge regenerates index.md and drops landed gap lines in the merge commit itself
            edited = _git(wt, "diff", "--name-only", tree.stdout.split()[0], sha).stdout.split()
            if not all(map(resolver, edited)):
                return None  # the merge commit changed more than git's own merge and those records
        elif tree.returncode != 1 or not all(map(resolver, conflict_stages(tree.stdout))):
            return None  # a conflict outside land.py's auto-resolved records was settled by hand
    return main
