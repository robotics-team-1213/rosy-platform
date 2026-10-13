"""Green land.py results, kept per landed commit so pre-push can reuse them (D-553 addendum 3).

tools/land.py writes one record when it fast-forwards main: the landed commit, the main
commit it was tested against (base) and the pytest invocations that passed there (NEW
failures stop a landing; known ones were compared by test/known_failures.py). Records
live in the shared git directory (`<git-common-dir>/rosy-land/<sha>.json`), so every
worktree and the main checkout see the same ones.

pre-push asks `owed`: starting at the pushed commit, follow record -> its base -> that
base's record until a base is already on the upstream (origin/main). If the chain
reaches it, every commit being pushed was landed by land.py with its affected tier
green, and only the fast suites no record ran are owed. A missing record (a commit
landed by hand, a --tests none landing) breaks the chain and pre-push runs as before.

    python tools/hooks/land_record.py owed --head <sha> --upstream origin/main -- <fast suites>
    exit 0 + owed suites (one per line, maybe none) | exit 3 = not covered, run the full gate
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}")
MAX_CHAIN = 200


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def folder(repo: Path) -> Path:
    common = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    return (common if common.is_absolute() else repo / common) / "rosy-land"


def write(repo: Path, sha: str, base: str, invocations: list[list[str]], logs: list[str]) -> Path:
    if not (SHA.fullmatch(sha) and SHA.fullmatch(base)):
        raise ValueError("land record needs full commit ids")
    target = folder(repo)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{sha}.json"
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps({
        "sha": sha, "base": base, "invocations": invocations, "logs": logs,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read(repo: Path, sha: str) -> dict | None:
    path = folder(repo) / f"{sha}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if record.get("sha") != sha or not SHA.fullmatch(str(record.get("base", ""))):
        return None
    return record


def owed(repo: Path, head: str, upstream: str, fast_suites: list[str]) -> list[str] | None:
    """Fast suites still owed when land records cover upstream..head; None when they do not."""
    upstream_sha = _git(repo, "rev-parse", "--verify", "-q", f"{upstream}^{{commit}}", check=False).stdout.strip()
    if not upstream_sha:
        return None
    ran: set[str] = set()
    sha = head
    for _ in range(MAX_CHAIN):
        if _git(repo, "merge-base", "--is-ancestor", sha, upstream_sha, check=False).returncode == 0:
            break  # already on the upstream: nothing left to cover
        record = read(repo, sha)
        if record is None:
            return None
        if _git(repo, "merge-base", "--is-ancestor", record["base"], sha, check=False).returncode != 0:
            return None
        ran.update(arg for inv in record["invocations"] for arg in inv)
        sha = record["base"]
    else:
        return None
    if sha == head:
        return None  # nothing past upstream: the gate runs as before
    return [suite for suite in fast_suites if suite not in ran]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("owed")
    check.add_argument("--head", required=True)
    check.add_argument("--upstream", default="origin/main")
    check.add_argument("suites", nargs="*")
    args = parser.parse_args(argv)
    repo = Path.cwd()
    head = _git(repo, "rev-parse", "--verify", f"{args.head}^{{commit}}").stdout.strip()
    result = owed(repo, head, args.upstream, args.suites)
    if result is None:
        return 3
    for suite in result:
        print(suite)
    return 0


if __name__ == "__main__":
    sys.exit(main())
