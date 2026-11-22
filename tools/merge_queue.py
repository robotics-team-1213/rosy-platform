"""Inspect the GitHub merge queue and dequeue a PR with a recorded reason (#258).

Usage::

    python tools/merge_queue.py list
    python tools/merge_queue.py status <PR>
    python tools/merge_queue.py dequeue <PR> --reason "<why>"

Every session shares one GitHub account (#258), so ``list`` also shows the
``Session:`` line pr_land.py puts at the bottom of each PR body, and
``dequeue`` appends who ran it and why to ``<git-common-dir>/rosy-queue-audit.jsonl``.
``status`` prints one PR's merge state and the one next step (D-1055).

``list`` reads both the queue's entries and the open PRs' own ``isInMergeQueue`` (11-21 21:05 KST: PR #432 was
in the queue at position 2 while ``list`` printed "empty"), and the repository is the checkout this file is in,
not the shell's working directory.
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

REPO = Path(__file__).resolve().parents[1]  # this checkout, whatever the shell's working directory is

LIST_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    mergeQueue(branch: "main") {
      entries(first: 100) { nodes {
        position state enqueuedAt pullRequest { number title body }
      } }
    }
    pullRequests(states: OPEN, baseRefName: "main", first: 100) { nodes {
      number title body isInMergeQueue mergeQueueEntry { position state enqueuedAt }
    } }
  }
}"""

STATUS_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    number state mergeStateStatus mergeable isInMergeQueue mergeQueueEntry { position state }
    commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
      __typename ... on CheckRun { name conclusion } ... on StatusContext { context state }
    } } } } } }
  } }
}"""

FAILED = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}

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
    owner, _, name = run_gh(repo, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip().partition("/")
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
    data = graphql(repo, LIST_QUERY, owner=owner, name=name).get("repository") or {}
    queue = data.get("mergeQueue")
    nodes = list(((queue or {}).get("entries") or {}).get("nodes") or [])
    listed = {(entry.get("pullRequest") or {}).get("number") for entry in nodes}
    for pr in ((data.get("pullRequests") or {}).get("nodes") or []):  # a queued PR the entries list missed
        entry = pr.get("mergeQueueEntry")
        if pr.get("isInMergeQueue") and entry and pr.get("number") not in listed:
            nodes.append({**entry, "pullRequest": pr, "seen": "PR state only"})
    if not nodes:
        print(f"[merge-queue] {owner}/{name} main: empty" if queue is not None else
              f"[merge-queue] {owner}/{name} main: no merge queue visible and no open PR in one")
        return 0
    for entry in sorted(nodes, key=lambda e: e.get("position") or 0):
        pr = entry.get("pullRequest") or {}
        session = SESSION_LINE.search(pr.get("body") or "")
        print(f"{entry['position']} {entry['state']} PR #{pr.get('number')} {pr.get('title', '')} "
              f"enqueued={entry['enqueuedAt']} session={session.group(1).strip() if session else 'unknown'}"
              + (f" ({entry['seen']})" if entry.get("seen") else ""))
    return 0


def next_step(pr: dict) -> str:
    """One line: what the PR's owner does now (D-1055: merge origin/main only when DIRTY, never for BEHIND)."""
    contexts = (((pr.get("commits") or {}).get("nodes") or [{}])[-1].get("commit") or {}).get("statusCheckRollup") or {}
    failed = sorted({c.get("name") or c.get("context") for c in (contexts.get("contexts") or {}).get("nodes") or []
                     if (c.get("conclusion") or c.get("state")) in FAILED})
    status, mergeable, entry = pr.get("mergeStateStatus"), pr.get("mergeable"), pr.get("mergeQueueEntry") or {}
    if pr.get("state") != "OPEN":
        return f"{pr.get('state', '?').lower()}: nothing to do"
    if pr.get("isInMergeQueue"):
        return f"in the merge queue (position {entry.get('position')}, {entry.get('state')}): wait"
    if status == "DIRTY" or mergeable == "CONFLICTING":
        return ("DIRTY: in your worktree run git fetch origin && git merge origin/main, resolve with the"
                " resolve-merge-conflicts skill (D-1067), commit, then python tools/pr_land.py --evidence again:"
                " the tree changed, so lab evidence reruns")
    if failed:
        return f"{status}: failing checks {', '.join(failed)}: fix them on the branch"
    if status == "BEHIND":
        return "BEHIND: do not touch it; the merge queue tests it on top of main"
    if mergeable == "UNKNOWN" or status == "UNKNOWN":
        return "UNKNOWN: GitHub is still computing; run status again in a minute"
    if status == "BLOCKED":
        return "BLOCKED: checks still running or a required review is missing; wait or read gh pr checks"
    return f"{status}: not in the queue; python tools/pr_land.py from its worktree queues it"


def cmd_status(repo: Path, number: int) -> int:
    owner, name = repo_slug(repo)
    pr = graphql(repo, STATUS_QUERY, owner=owner, name=name, number=number).get("repository", {}).get("pullRequest")
    if not pr:
        raise SystemExit(f"merge-queue: PR #{number} not found on {owner}/{name}")
    print(f"PR #{number} {pr.get('state')} mergeStateStatus={pr.get('mergeStateStatus')} "
          f"mergeable={pr.get('mergeable')} inQueue={'yes' if pr.get('isInMergeQueue') else 'no'}")
    print(f"next: {next_step(pr)}")
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
    status = sub.add_parser("status", help="one PR's merge state and the next step")
    status.add_argument("pr", type=int, metavar="PR")
    dequeue = sub.add_parser("dequeue", help="dequeuePullRequest and record the run locally")
    dequeue.add_argument("pr", type=int, metavar="PR")
    dequeue.add_argument("--reason", required=True, metavar="WHY", help="why this PR leaves the queue")
    args = parser.parse_args(argv)
    cwd = (repo or REPO).resolve()
    if args.command == "list":
        return cmd_list(cwd)
    if args.command == "status":
        return cmd_status(cwd, args.pr)
    return cmd_dequeue(cwd, args.pr, args.reason)


if __name__ == "__main__":
    sys.exit(main())
