"""Merge queue and main push: repeat the guard set alone on a tree a green run already tested (D-1059, D-1064).

A pull_request run tests the merge of the PR head into the base of that moment and, when green, leaves
that merge commit in a notice on its ``ci-result`` check. The queue's commit differs from it only by what
entered the base since. When nothing did, the queue's tree is the tree that run passed, and the queue run
repeats the guard set alone. Any difference, or any doubt, keeps the whole selection.

The push run on main is the same case one step later (D-1064): when the push is exactly the one queue entry
whose queue run passed on this very commit, the two runs select the same tests on the same tree.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import urllib.request
from pathlib import Path

from affected_pack import SelectionError
from affected_repo import _git

ENV = "ROSY_QUEUE_TESTED"  # the commit the pull_request run tested; ci.yml sets it on merge_group
NOTICE = "rosy-tested-commit"  # title of the notice ci.yml's ci-result leaves on a green pull_request run


def narrowed(repo, sel, tested: str | None = None):
    """`sel` for the queue's commit, cut to the guard set when its tree is `tested`'s; `sel` itself when unset."""
    tested = os.environ.get(ENV, "") if tested is None else tested
    if not tested:
        return sel
    try:
        out, why = narrow(repo, sel, _git(repo.root, "diff", "--name-status", "--no-renames", tested, "HEAD"))
    except SelectionError as exc:
        out, why = sel, f"whole selection: cannot diff against {tested}: {exc}"
    print(f"[queue] {why}", file=sys.stderr)
    return out


def narrow(repo, sel, status: str):
    """(selection, reason) for `git diff --name-status --no-renames <tested> HEAD` output.

    Only an empty difference narrows: the queue's tree is then the tree the pull_request run passed, and the
    guard set alone runs again. Narrowing on what the changed files reach was reviewed and dropped on
    2026-11-21: tests reach other modules by running scripts, read ADRs by glob and import fixtures from
    other test files, none of which the selector sees (D-1059)."""
    import affected_tests as at  # here, not at the top: affected_tests imports affected_ci, which imports this
    rows = [line.split("\t", 1) for line in status.splitlines() if "\t" in line]
    if sel.mode != "affected" or sel.escalations:
        return sel, "whole selection: the pull request's own selection is the full tier"
    if rows:
        return sel, f"whole selection: {len(rows)} file(s) changed since the tested commit ({rows[0][1]}, ...)"
    guards = at.select(repo, []).reasons
    keep = sorted(p for p in sel.reasons if p in guards)
    out = dataclasses.replace(sel, reasons={p: sel.reasons[p] for p in keep})
    out.invocations = out.local_invocations = at.pack(repo, keep)
    return out, f"same tree as the tested commit: the guard set alone, {len(keep)} of {len(sel.reasons)} selected paths"


def _reader(token: str):
    def fetch(url: str):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    return fetch


def tested_commit(api: str, repository: str, head: str, token: str, get=None) -> str:
    """The merge commit a green pull_request ci run tested for PR head `head`; "" when no such run left one."""
    get = get or _reader(token)
    runs = get(f"{api}/repos/{repository}/commits/{head}/check-runs?check_name=ci-result&per_page=100")["check_runs"]
    for run in sorted(runs, key=lambda r: r.get("completed_at") or "", reverse=True):
        if run.get("conclusion") != "success" or (run.get("app") or {}).get("slug") != "github-actions":
            continue
        for note in get(f"{api}/repos/{repository}/check-runs/{run['id']}/annotations"):
            sha = (note.get("message") or "").strip()
            if note.get("title") == NOTICE and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
                return sha
    return ""


def queue_passed(api: str, repository: str, sha: str, parent: str, token: str, get=None) -> bool:
    """True when a merge queue run of ci.yml passed on exactly `sha`, built on `parent` (D-1064).

    The queue names its ref ``gh-readonly-queue/<branch>/pr-N-<base sha>``; the run selected its tests against
    that base, so it must be the push's own previous tip for the two selections to be the same."""
    get = get or _reader(token)
    runs = get(f"{api}/repos/{repository}/actions/runs?head_sha={sha}&event=merge_group&per_page=50")["workflow_runs"]
    return any(run.get("head_sha") == sha and run.get("conclusion") == "success"
               and str(run.get("head_branch") or "").endswith("-" + parent)
               and str(run.get("path") or "").split("@")[0].endswith(".github/workflows/ci.yml") for run in runs)


def pushed(parent: str, before: str, passed) -> None:
    """Raise unless this push is the one queue entry a green queue run already tested (D-1064).

    The queue run of the tip tests the tip's own pull request against the entry before it. A push that carries
    several entries is selected over all of them on the final tree, which no queue run did."""
    if not before or parent != before:
        raise SelectionError("the push holds more than the last merge queue entry (HEAD^1 is not the previous tip)")
    if not passed():
        raise SelectionError("no green merge queue run of ci.yml on this commit")


def main(argv: list[str] | None = None) -> int:
    """Print the commit whose green run already tested HEAD's tree (fetched and checked); nothing when unknown.

    No argument: HEAD is a merge queue commit (D-1059). ``--pushed <before>``: HEAD is the new main tip (D-1064)."""
    argv = sys.argv[1:] if argv is None else argv
    root = Path.cwd()
    api, repository, token = (os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                              os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", ""))
    try:
        if argv[:1] == ["--pushed"]:
            sha, parent = _git(root, "rev-parse", "HEAD").strip(), _git(root, "rev-parse", "HEAD^1").strip()
            pushed(parent, argv[1] if len(argv) > 1 else "", lambda: queue_passed(api, repository, sha, parent, token))
        else:
            head = _git(root, "rev-parse", "HEAD^2").strip()  # the queue merges the PR head into its base
            sha = tested_commit(api, repository, head, token)
            if not sha:
                raise SelectionError(f"no green pull_request run left a {NOTICE} notice for {head}")
            _git(root, "fetch", "--quiet", "origin", sha)
            if _git(root, "rev-parse", f"{sha}^2").strip() != head:
                raise SelectionError(f"{sha} is not a merge of {head}")
            # The same base, not only the same tree: the tests were selected against it. With a base that moved
            # and came back to an equal tree, the two runs would select different tests (review, 2026-11-21).
            if _git(root, "rev-parse", f"{sha}^1").strip() != _git(root, "rev-parse", "HEAD^1").strip():
                raise SelectionError(f"{sha} was tested on another base than this queue entry")
    except Exception as exc:  # noqa: BLE001 - any doubt keeps the whole selection, never fails the run
        print(f"[queue] whole selection: {exc}", file=sys.stderr)
        return 0
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
