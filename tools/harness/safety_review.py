"""D-430 §5: commits that touch safety-tagged paths carry a ``Safety-Review:`` trailer.

Usage: python tools/harness/safety_review.py BASE HEAD [--warn-only]

Checks every non-merge commit in BASE..HEAD that is not already in BASELINE, so
history from before this check landed is exempt. BASE may be empty or all zeros
(a new branch push); then only BASELINE bounds the range. Needs full history
(CI checks out with ``fetch-depth: 0``).

Safety-tagged paths are read from ``tools/harness/platform_parts.yaml`` at each
commit and at its parent: files under a ``concern: safety`` root (deepest root
wins) and the ``safety_modules`` list. A commit needs the trailer when it changes
such a file, or when the manifest stops tagging something that was tagged
(removing a safety tag is a safety change too).

``--warn-only`` prints the same report and exits 0; ``tools/hooks/pre-push`` uses it
as an opt-in early warning. The CI step is the enforcement.
"""

from __future__ import annotations

import re
import subprocess
import sys

import yaml

#: main when this check landed (D-430 wave 0). Older commits are never checked.
BASELINE = "e0f53ce79beb695142907bcedda2fdd99994bb63"
MANIFEST = "tools/harness/platform_parts.yaml"
TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _rules(commit: str) -> tuple[list[dict], set[str]]:
    """(roots, safety_modules) of the manifest at ``commit``; empty before it existed."""
    try:
        text = _git("show", f"{commit}:{MANIFEST}")
    except subprocess.CalledProcessError:
        return [], set()
    manifest = yaml.safe_load(text) or {}
    return manifest.get("roots") or [], set(manifest.get("safety_modules") or ())


def is_safety(path: str, roots: list[dict], modules: set[str]) -> bool:
    if path in modules:
        return True
    owner = max((root for root in roots if _under(path, root["path"])),
                key=lambda root: len(root["path"]), default=None)
    return owner is not None and owner.get("concern") == "safety"


def _tagged(roots: list[dict], modules: set[str]) -> set[str]:
    return {f"root:{root['path']}" for root in roots if root.get("concern") == "safety"} | {
        f"module:{path}" for path in modules}


def needs_review(commit: str) -> list[str]:
    """Why ``commit`` needs a trailer (empty when it does not)."""
    parent = f"{commit}^"
    new_roots, new_modules = _rules(commit)
    old_roots, old_modules = _rules(parent)
    changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", parent, commit).split()
    reasons = [f"touches {path}" for path in changed
               if is_safety(path, new_roots, new_modules) or is_safety(path, old_roots, old_modules)]
    reasons += [f"untags {entry}" for entry in sorted(
        _tagged(old_roots, old_modules) - _tagged(new_roots, new_modules))]
    return reasons


def _exists(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0


def commits(base: str, head: str) -> list[str]:
    excluded = ["^" + BASELINE]
    if base and set(base) != {"0"} and _exists(base):
        excluded.append("^" + base)  # a force-pushed-away BASE falls back to BASELINE alone
    return _git("rev-list", "--no-merges", "--reverse", head, *excluded).split()


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
    missing = []
    checked = commits(base, head)
    for commit in checked:
        reasons = needs_review(commit)
        if reasons and not TRAILER.search(_git("log", "-1", "--format=%B", commit)):
            subject = _git("log", "-1", "--format=%h %s", commit).strip()
            missing.append(f"{subject}\n    " + "\n    ".join(reasons))
    print(f"[safety-review] {len(checked)} commit(s) checked after baseline {BASELINE[:9]}")
    if not missing:
        return 0
    print("[safety-review] safety-tagged changes without a `Safety-Review: <reviewer/lane> <evidence>` "
          "trailer (D-430 §5):\n" + "\n".join(missing), file=sys.stderr)
    return 0 if warn_only else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
