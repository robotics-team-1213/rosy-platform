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
from harness import affected_exclusive

RECORDS = "rosy-land-full"


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _path(wt: Path, branch: str) -> Path:
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common) / RECORDS / (branch.replace("/", "-") + ".json")


def save(wt: Path, branch: str, candidate: str, main: str, tier: str | None = None,
         invocations: list[list[str]] | None = None, base_tier: str | None = None,
         flaky: list[list[str]] | None = None, yields: int = 0, reused: bool = False,
         env: str | None = None) -> None:
    path = _path(wt, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"candidate": candidate, "main": main, "tier": tier, "invocations": invocations}
    extra = {**({"base_tier": base_tier} if base_tier else {}), **({"flaky": flaky} if flaky else {}),
             **({"yields": yields} if yields else {}), **({"reused": True} if reused else {}),
             **({"env": env} if env else {})}
    path.write_text(json.dumps({**record, **extra}), encoding="utf-8")


def count_yield(wt: Path, branch: str) -> None:
    """One more delta yield on the saved record (land_selection.MAX_DELTA_YIELDS), its tier and evidence unchanged."""
    path = _path(wt, branch)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(record, dict):
        record["yields"] = int(record.get("yields") or 0) + 1
        path.write_text(json.dumps(record), encoding="utf-8")


def flaky(wt: Path, branch: str) -> list[list[str]]:
    """D-970 4: invocations of node ids the saved pretest passed only when rerun alone (LOAD-FLAKY); the turn runs
    them again."""
    try:
        runs = json.loads(_path(wt, branch).read_text(encoding="utf-8")).get("flaky") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in runs if isinstance(r, list) and r and all(isinstance(w, str) and w for w in r)]


def prepared(wt: Path, branch: str, main: str | None) -> dict | None:
    """The saved tier over ``main`` (tier, invocations, candidate, main) for the land record, or None.

    A "delta" record (D-889 27: main's delta suites run before the turn on top of an earlier tier) reports that
    earlier tier, so a land record never calls it FULL unless the tier under it was."""
    try:
        record = json.loads(_path(wt, branch).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(record, dict) and record.get("tier") == "delta":
        record = {**record, "tier": record.get("base_tier")}
    ok = isinstance(record, dict) and main and record.get("main") == main and record.get("tier") in ("full", "affected")
    return record if ok and isinstance(record.get("invocations"), list) else None


def forget(wt: Path, branch: str) -> None:
    _path(wt, branch).unlink(missing_ok=True)


def restore(wt: Path, branch: str) -> str | None:
    """The main an earlier run's FULL tier passed over, if HEAD still carries only that change."""
    try:
        record = json.loads(_path(wt, branch).read_text(encoding="utf-8"))
        candidate, main = record["candidate"], record["main"]
        tier = record.get("base_tier") if record.get("tier") == "delta" else record.get("tier")
        if (tier == "full"
                and _git(wt, "cat-file", "-e", "main:tools/harness/affected_exclusive.py").returncode == 0
                and not affected_exclusive.canonical_full(record.get("invocations", []))):
            return None  # Old FULL plans require a fresh prepare once main owns the strict timing plan.
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if record.get("tier") == "carried":
        return None  # a main-red carry (land_mainred) is never green: the next run tests it again
    return main if bridge(wt, candidate, main, "HEAD", "main") else None


def bridge(wt: Path, candidate: str, tested_main: str, head: str, main: str) -> bool:
    """Only merges of main and permitted record resolutions connect candidate to head."""
    ancestor = lambda a, b: _git(wt, "merge-base", "--is-ancestor", a, b).returncode == 0  # noqa: E731
    if not (ancestor(candidate, head) and ancestor(tested_main, main)):
        return False
    if _git(wt, "rev-list", "--no-merges", head, f"^{candidate}", f"^{main}").stdout.strip():
        return False  # a commit of the branch's own since the FULL tier: test it all again
    for line in _git(wt, "rev-list", "--merges", "--parents", head, f"^{candidate}", f"^{main}").stdout.splitlines():
        sha, first, *others = line.split()
        if len(others) != 1 or not ancestor(others[0], main):
            return False  # something other than main was merged in
        tree = _git(wt, "merge-tree", "--write-tree", "--no-messages", "-X", "renormalize", first, others[0])  # as land.merge
        if tree.returncode == 0:
            # land.merge regenerates index.md and drops landed gap lines in the merge commit itself
            edited = _git(wt, "diff", "--name-only", tree.stdout.split()[0], sha).stdout.splitlines()
            if not all(map(resolver, edited)):
                return False  # the merge commit changed more than git's own merge and those records
        elif tree.returncode != 1 or not all(map(resolver, conflict_stages(tree.stdout))):
            return False  # a conflict outside land.py's auto-resolved records was settled by hand
    return True
