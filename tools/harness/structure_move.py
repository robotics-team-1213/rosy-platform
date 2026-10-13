"""D-625: preview one holder move; --apply moves files only, never references.

python tools/harness/structure_move.py drive-nav2
python tools/harness/structure_move.py drive-nav2 --apply --expected-head <SHA>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d427_move as legacy


MANIFEST = Path(__file__).with_name("platform_structure_moves.json")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], encoding="utf-8").rstrip("\n")


def checked_path(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if (not relative or any(p.lower() in ("", ".", "..", ".git", ".worktrees") for p in parts)
            or any(any(c in p for c in '<>:"\\|?*\0') for p in parts)):
        raise ValueError(f"invalid repository path: {relative!r}")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink() or (candidate.exists() and
                getattr(candidate.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError(f"linked path refused: {relative}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path escapes repository: {relative}")
    return candidate


def overlaps(a: str, b: str) -> bool:
    return legacy.under(a, b) or legacy.under(b, a)


def preview(root: Path, unit: dict) -> dict:
    source, target = unit["source"], unit["target"]
    if not source.startswith("middleware/") or not target.startswith("middleware/") or overlaps(source, target):
        raise ValueError("move must name two disjoint middleware holders")
    src, dst = checked_path(root, source), checked_path(root, target)
    if not src.is_dir():
        raise ValueError(f"source directory missing: {source}")
    if dst.exists():
        raise ValueError(f"target already exists: {target}")
    tracked = git(root, "ls-files", "-z").split("\0")
    tracked = [p for p in tracked if p]
    files = [p for p in tracked if legacy.under(p, source)]
    if not files:
        raise ValueError("source has no tracked files")
    actual = set()
    for path in src.rglob("*"):
        rel = path.relative_to(root).as_posix()
        checked_path(root, rel)
        if path.is_file():
            actual.add(rel)
    if actual != set(files):
        raise ValueError("source contains untracked/ignored or missing tracked files")
    parts_path = checked_path(root, "tools/harness/platform_parts.yaml")
    if not parts_path.is_file():
        raise ValueError("platform_parts.yaml missing; cannot verify Safety")
    parts = yaml.safe_load(parts_path.read_text(encoding="utf-8"))
    if not isinstance(parts, dict) or not isinstance(parts.get("roots"), list) or not isinstance(parts.get("safety_modules"), list):
        raise ValueError("invalid Safety manifest")
    if (any(not isinstance(p, str) for p in parts["safety_modules"])
            or any(not isinstance(r, dict) or not isinstance(r.get("path"), str) for r in parts["roots"])):
        raise ValueError("invalid Safety paths")
    safety = list(parts["safety_modules"])
    safety.extend(r["path"] for r in parts["roots"] if r.get("concern") == "safety")
    safety_hits = [p for p in safety if overlaps(source, p)]
    scanner = legacy.LegacyScan({source: target})
    references = []
    skipped = []
    for path in tracked:
        if path in legacy.FROZEN_BYTES or path.startswith(legacy.HISTORY_DIRS) or PurePosixPath(path).name in legacy.HISTORY_NAMES:
            continue
        # Read-only scanning must not follow a consumer symlink outside the tree.
        try:
            candidate = checked_path(root, path)
        except ValueError:
            skipped.append(path)
            continue
        content = legacy.read(candidate)
        if content is None:
            skipped.append(path)
            continue
        references.extend({"path": path, "form": form, "reference": text}
                          for form, text, _ in scanner.findings(path, content))
    return {"head": git(root, "rev-parse", "HEAD"), **unit, "tracked_files": files,
            "references": references, "unscanned_files": skipped, "safety_paths": safety_hits,
            "references_updated": False, "state": "preview",
            "apply_allowed": not (unit["manual_safety"] or safety_hits),
            "limits": "Variable/f-string paths and install/import closure require manual review."}


def move(root: Path, report: dict, expected_head: str | None) -> None:
    if not expected_head:
        raise ValueError("--apply requires --expected-head from the reviewed preview")
    if report["head"] != expected_head:
        raise ValueError("stale HEAD; create and review a new preview")
    common = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    holder = common.parent / ".worktrees"
    registered = [Path(line[9:]).resolve() for line in git(root, "worktree", "list", "--porcelain").splitlines()
                  if line.startswith("worktree ")]
    if (root not in registered or not root.is_relative_to(holder) or root.parent != holder
            or not (root / ".git").is_file()):
        raise ValueError("apply requires a registered <repo>/.worktrees/<topic> worktree")
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch == "main":
        raise ValueError("main worktree refused")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("worktree/index not clean; preserve changes before migration")
    if not report["apply_allowed"]:
        raise ValueError("Safety move requires independent review and manual migration")
    # Recheck paths immediately before the one mutation; no cleanup or auto commit.
    src = checked_path(root, report["source"])
    dst = checked_path(root, report["target"])
    if dst.exists():
        raise ValueError("target already exists")
    if git(root, "rev-parse", "HEAD") != expected_head:
        raise ValueError("stale HEAD")
    dst.parent.mkdir(parents=True, exist_ok=True)
    git(root, "mv", "--", src.relative_to(root).as_posix(), dst.relative_to(root).as_posix())
    report["state"] = "moved_needs_reference_edits"


def main() -> int:
    units = json.loads(MANIFEST.read_text(encoding="utf-8"))["units"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit", choices=units)
    parser.add_argument("--apply", action="store_true", help="move files only; references remain a manual follow-up")
    parser.add_argument("--expected-head", help="full SHA from reviewed preview, required for --apply")
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
        report = preview(root, units[args.unit])
        report["unit"] = args.unit
        if args.apply:
            move(root, report, args.expected_head)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print(f"structure move refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
