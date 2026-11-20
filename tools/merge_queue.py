"""Inspect the GitHub merge queue and dequeue a PR with a recorded reason (#258).

Usage::

    python tools/merge_queue.py list
    python tools/merge_queue.py dequeue <PR> --reason "<why>"

Every session shares one GitHub account (#258), so ``list`` also shows the
``Session:`` line pr_land.py puts at the bottom of each PR body, and
``dequeue`` appends who ran it and why to ``<git-common-dir>/rosy-queue-audit.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SESSION_LINE = re.compile(r"(?m)^Session:\s*(.+)$")

LIST_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    mergeQueue {
      entries(first: 100) { nodes {
        position state enqueuedAt pullRequest { number title body }
      } }
    }
  }
}"""

PR_ID_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { id } }
}"""

DEQUEUE_MUTATION = """mutation($id: ID!) {
  dequeuePullRequest(input: {id: $id}) { mergeQueueEntry { pullRequest { number } } }
}"""


def session_name() -> str:
    return os.environ.get("ROSY_SESSION_NAME") or os.environ.get("CLAUDE_SESSION_NAME") or "unknown"


def run_gh(repo: Path, *args: str) -> str:
    result = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"merge-queue: gh {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout


def repo_slug(repo: Path) -> tuple[str, str]:
    owner, _, name = run_gh(repo, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").partition("/")
    if not name:
        raise SystemExit("merge-queue: could not resolve owner/name; run inside the repository checkout")
    return owner, name


def graphql(repo: Path, query: str, **fields: str | int) -> dict:
    cmd = ["api", "graphql", "-f", f"query={query}"]
    for key, value in fields.items():
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    return json.loads(run_gh(repo, *cmd))["data"]


def cmd_list(repo: Path) -> int:
    owner, name = repo_slug(repo)
    queue = graphql(repo, LIST_QUERY, owner=owner, name=name).get("repository", {}).get("mergeQueue") or {}
    nodes = list((queue.get("entries") or {}).get("nodes") or [])
    if not nodes:
        print("[merge-queue] empty (or merge queue not configured)")
        return 0
    for entry in nodes:
        pr = entry.get("pullRequest") or {}
        session = SESSION_LINE.search(pr.get("body") or "")
        print(f"{entry['position']} {entry['state']} PR #{pr.get('number')} {pr.get('title', '')} "
              f"enqueued={entry['enqueuedAt']} session={session.group(1).strip() if session else 'unknown'}")
    return 0


def audit_path(repo: Path) -> Path:
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    return Path(common) / "rosy-queue-audit.jsonl"


def cmd_dequeue(repo: Path, pr: int, reason: str) -> int:
    owner, name = repo_slug(repo)
    found = graphql(repo, PR_ID_QUERY, owner=owner, name=name, number=pr).get("repository", {}).get("pullRequest") or {}
    if not found.get("id"):
        raise SystemExit(f"merge-queue: PR #{pr} not found on {owner}/{name}")
    graphql(repo, DEQUEUE_MUTATION, id=found["id"])
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": "dequeue",
        "pr": pr,
        "reason": reason,
        "session": session_name(),
    }
    with audit_path(repo).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[merge-queue] dequeued PR #{pr} ({reason})")
    return 0


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print position, state, PR, title, enqueuedAt, body Session line")
    dequeue = sub.add_parser("dequeue", help="dequeuePullRequest and record the run locally")
    dequeue.add_argument("pr", type=int, metavar="PR")
    dequeue.add_argument("--reason", required=True, metavar="WHY", help="why this PR leaves the queue")
    args = parser.parse_args(argv)
    cwd = (repo or Path.cwd()).resolve()
    if args.command == "list":
        return cmd_list(cwd)
    return cmd_dequeue(cwd, args.pr, args.reason)


if __name__ == "__main__":
    sys.exit(main())
