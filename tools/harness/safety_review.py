"""D-430 §5: commits that touch safety-tagged paths carry a ``Safety-Review:`` trailer.

Usage: python tools/harness/safety_review.py BASE HEAD [--warn-only]

Checks the commits in BASE..HEAD, minus ancestors of BASELINE (history from
before this check landed) and the reviewed ``EXEMPT`` list. CI passes exactly the
event's range: the PR base for ``pull_request``, ``before`` for ``push``. When
BASE is empty, all zeros (a new branch) or unreachable (a force push), only
HEAD itself is checked (HEAD^..HEAD), never the whole history, so one old
untrailered commit cannot keep CI red. Needs full history (``fetch-depth: 0``).

What is safety-tagged comes from ``tools/harness/platform_parts.yaml``: files under
a ``concern: safety`` root (deepest root wins) and the ``safety_modules`` list. A
path counts when the manifest at HEAD, at BASE, at the commit, or at its parent
tags it, so a branch forked before a path was tagged is still checked. A commit needs the
trailer when it

- changes such a path (a ``git mv`` changes both the old and the new path, so wave
  3/4 moves of safety roots or modules need the trailer), or
- stops tagging a root, module or ``safety_anchors`` entry that its parent tagged.

A non-merge commit is checked on its diff to its parent. A merge is checked only
on the paths it changes against every parent (``diff-tree --cc``: conflict
resolutions and evil-merge edits); what it brings in is checked on the merged
commits themselves.

``--warn-only`` prints the same report and exits 0. CI's ``scope`` job, ``tools/land.py`` (the commits a
landing adds) and ``tools/hooks/pre-push`` (``origin/main..`` the pushed sha) enforce it (D-762 stage 0).
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

#: main when this check landed (D-430 wave 0). Its ancestors are never checked.
BASELINE = "5496c22dc81e1efd20a14d05419bb8d4e25658bd"  # git commit revision
#: Reviewed historical commits after BASELINE that touch safety paths without a
#: trailer: ``[{"commit": <full SHA>, "reason": ...}]`` in EXEMPT_FILE beside this file.
#: Add only with an independent review.
EXEMPT_FILE = Path(__file__).with_name("safety_review_exempt.json")


def load_exempt(path: Path = EXEMPT_FILE) -> dict[str, str]:
    """Commit -> reason. Missing, unreadable or malformed exits 1: never read as "nothing exempt"."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        table = {row["commit"]: row["reason"] for row in rows}
        ok = (isinstance(rows, list) and len(table) == len(rows)
              and all(re.fullmatch(r"[0-9a-f]{40}", c) and isinstance(r, str) and r.strip() for c, r in table.items()))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SystemExit(f"[safety-review] cannot load {path.name}: {exc!r}") from exc
    if not ok:
        raise SystemExit(f"[safety-review] {path.name}: each row needs a unique full 40-hex `commit` and a reason")
    return table


EXEMPT = load_exempt()
MANIFEST = "tools/harness/platform_parts.yaml"
TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)
ZERO = re.compile(r"^0*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _exists(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _manifest(commit: str) -> dict:
    """Manifest at ``commit``; empty before it existed. Read-only: the dict is shared across commits."""
    return _manifest_at(commit) if re.fullmatch(r"[0-9a-f]{40}", commit) else _manifest_at.__wrapped__(commit)


@functools.cache  # full SHAs only: a ref such as HEAD moves
def _manifest_at(commit: str) -> dict:
    entry = _git("ls-tree", "-z", commit, "--", MANIFEST)
    return _parse(entry.split()[2]) if entry else {}


@functools.cache
def _parse(oid: str) -> dict:
    # 2026-10-27: yaml.safe_load was 738 of 1,150 s on a 1,878-commit publish range; the blob rarely changes.
    return yaml.safe_load(_git("cat-file", "blob", oid)) or {}


def is_safety(path: str, roots: list[dict], modules: set[str]) -> bool:
    if path in modules:
        return True
    owner = max((root for root in roots if _under(path, root["path"])),
                key=lambda root: len(root["path"]), default=None)
    return owner is not None and owner.get("concern") == "safety"


def _is_safety_in(path: str, manifest: dict) -> bool:
    return is_safety(path, manifest.get("roots") or [], set(manifest.get("safety_modules") or ()))


def tagged(manifest: dict) -> set[str]:
    """Every safety tag: roots, modules and anchors (removing any is a safety change)."""
    anchors = {f"anchor:{anchor.get('symbol') or anchor.get('in', '') + '.' + anchor.get('string', '')}"
               for anchor in manifest.get("safety_anchors") or ()}
    return ({f"root:{root['path']}" for root in manifest.get("roots") or () if root.get("concern") == "safety"}
            | {f"module:{path}" for path in manifest.get("safety_modules") or ()} | anchors)


def _parents(commit: str) -> list[str]:
    return _git("rev-list", "--parents", "-n", "1", commit).split()[1:]


def needs_review(commit: str, range_manifests: tuple[dict, ...], parents: list[str] | None = None) -> list[str]:
    """Why ``commit`` needs a trailer (empty when it does not)."""
    parents = _parents(commit) if parents is None else parents
    if len(parents) > 1:
        changed = _git("diff-tree", "--cc", "--no-commit-id", "--name-only", commit).split()
    else:
        changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "--root", commit).split()
    own = _manifest(commit)
    parent_manifests = [_manifest(parent) for parent in parents]
    manifests = (*range_manifests, own, *parent_manifests[:1])
    reasons = [f"touches {path}" for path in changed if any(_is_safety_in(path, m) for m in manifests)]
    # A merge untags only what every parent tagged; a branch's own removal is
    # reported on that branch's commit.
    kept = set.intersection(*(tagged(m) for m in parent_manifests)) if parent_manifests else set()
    reasons += [f"untags {entry}" for entry in sorted(kept - tagged(own))]
    return reasons


def resolve_base(base: str, head: str) -> str:
    if not base or ZERO.match(base) or not _exists(base):
        return f"{head}^"  # new branch or force push: the pushed tip only
    return base


def commits(base: str, head: str) -> list[str]:
    return list(_with_parents(base, head))


def _with_parents(base: str, head: str) -> dict[str, list[str]]:
    """Commits of the range, oldest first, each with its parents (one rev-list for the whole range)."""
    rows = _git("rev-list", "--reverse", "--parents", head, "^" + base, "^" + BASELINE).splitlines()
    return {row.split()[0]: row.split()[1:] for row in rows if row and row.split()[0] not in EXEMPT}


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    args = [arg for arg in argv if arg != "--warn-only"]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base, head = args
    if not _exists(BASELINE):
        print(f"[safety-review] baseline {BASELINE} is not in this clone; fetch full history "
              "(actions/checkout fetch-depth: 0)", file=sys.stderr)
        return 0 if warn_only else 1
    base = resolve_base(base, head)
    range_manifests = (_manifest(head), _manifest(base))
    missing = []
    checked = _with_parents(base, head)
    for commit, parents in checked.items():
        reasons = needs_review(commit, range_manifests, parents)
        if reasons and not TRAILER.search(_git("log", "-1", "--format=%B", commit)):
            subject = _git("log", "-1", "--format=%h %s (author %an)", commit).strip()
            missing.append(f"{subject}\n    " + "\n    ".join(reasons))
    print(f"[safety-review] {len(checked)} commit(s) checked after baseline {BASELINE[:9]}")
    if not missing:
        return 0
    print("[safety-review] safety-tagged changes without a `Safety-Review: <reviewer/lane> <evidence>` "
          "trailer (D-430 section 5):\n" + "\n".join(missing), file=sys.stderr)
    return 0 if warn_only else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
