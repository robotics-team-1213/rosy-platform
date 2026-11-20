"""Merge queue: retest only what changed since the pull request's green CI run (D-1059).

A pull_request run tests the merge of the PR head into the base of that moment and, when green, leaves
that merge commit in a notice on its ``ci-result`` check. The queue's commit differs from it only by what
entered the base since. A selected test those changes cannot reach has the inputs it passed with, so the
queue run leaves it out. Whatever this module cannot show keeps the whole selection.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import urllib.request
from pathlib import Path

from affected_pack import SelectionError
from affected_repo import _git, _under

ENV = "ROSY_QUEUE_TESTED"  # the commit the pull_request run tested; ci.yml sets it on merge_group
NOTICE = "rosy-tested-commit"  # title of the notice ci.yml's ci-result leaves on a green pull_request run


def narrowed(repo, sel, tested: str | None = None):
    """`sel` for the queue's commit, without the tests untouched since `tested`; `sel` itself when unset."""
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
    """(selection, reason) for `git diff --name-status --no-renames <tested> HEAD` output."""
    import affected_narrow
    import affected_tests as at  # here, not at the top: affected_tests imports affected_ci, which imports this
    rows = [line.split("\t", 1) for line in status.splitlines() if "\t" in line]
    delta = [path for _, path in rows]
    if sel.mode != "affected" or sel.escalations:
        return sel, "whole selection: the pull request's own selection is the full tier"
    if any(kind.startswith("D") for kind, _ in rows):
        return sel, "whole selection: a file was removed since the tested commit"
    if affected_narrow.HARNESS_YAML in delta:
        return sel, f"whole selection: {affected_narrow.HARNESS_YAML} changed since the tested commit"
    since = at.select(repo, delta)
    if since.mode != "affected" or since.escalations or since.narrowed or since.unmapped:
        # A narrowed tier names only the known readers of a change (D-436 2026-11-09): not enough to rule a test out.
        return sel, "whole selection: the changes since the tested commit are outside the plain affected tier"
    keep = sorted(p for p in sel.reasons if any(_under(p, q) or _under(q, p) for q in since.reasons))
    out = dataclasses.replace(sel, reasons={p: sel.reasons[p] for p in keep})
    out.invocations = out.local_invocations = at.pack(repo, keep)
    return out, (f"{len(keep)} of {len(sel.reasons)} selected paths are reached by the "
                 f"{len(delta)} file(s) changed since the tested commit")


def tested_commit(api: str, repository: str, head: str, token: str, get=None) -> str:
    """The merge commit a green pull_request ci run tested for PR head `head`; "" when no such run left one."""
    def fetch(url: str):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    get = get or fetch
    runs = get(f"{api}/repos/{repository}/commits/{head}/check-runs?check_name=ci-result&per_page=100")["check_runs"]
    for run in sorted(runs, key=lambda r: r.get("completed_at") or "", reverse=True):
        if run.get("conclusion") != "success" or (run.get("app") or {}).get("slug") != "github-actions":
            continue
        for note in get(f"{api}/repos/{repository}/check-runs/{run['id']}/annotations"):
            sha = (note.get("message") or "").strip()
            if note.get("title") == NOTICE and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
                return sha
    return ""


def main() -> int:
    """Print the tested commit for the merge queue commit at HEAD, fetched and checked; nothing when unknown."""
    root = Path.cwd()
    try:
        head = _git(root, "rev-parse", "HEAD^2").strip()  # the queue merges the PR head into its base
        sha = tested_commit(os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                            os.environ["GITHUB_REPOSITORY"], head, os.environ["GH_TOKEN"])
        if not sha:
            raise SelectionError(f"no green pull_request run left a {NOTICE} notice for {head}")
        _git(root, "fetch", "--quiet", "origin", sha)
        if _git(root, "rev-parse", f"{sha}^2").strip() != head:
            raise SelectionError(f"{sha} is not a merge of {head}")
    except Exception as exc:  # noqa: BLE001 - any doubt keeps the whole selection, never fails the run
        print(f"[queue] whole selection: {exc}", file=sys.stderr)
        return 0
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
