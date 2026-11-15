"""The cheap landing gates, run by land_async.py before it creates a snapshot or a ticket (2026-11-09 bottleneck report).

safety review, size ratchet, lint (ADR gaps included) and the secret scan took 67 + 18 stops that only showed up
inside the queued supervisor, after the owner had left. Here they fail fast in the owner's own terminal. The branch is
not touched: when main is not yet in it lint is advisory (the supervisor re-lints after merging main).

First of all, a branch that changes landing-gate tools or safety paths together with product paths is refused (report
item 6, D-889 addendum 32): such a change runs FULL and holds the product change behind it, and a broken gate stops
every landing after it. ``--mixed "<the user's words>"`` lets one through.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

# the landing gates themselves; secret_scan.py is the scanner land.secret_scan runs
GATE = ("tools/land", "tools/remote/", "deploy/robot/pinky_pro/release/secret_scan.py")
MANIFEST = "tools/harness/platform_parts.yaml"


def mixed(paths: list[str], is_safety) -> tuple[list[str], list[str]]:
    """(gate-tool or safety paths, product paths); docs, Markdown and tests go with either side."""
    held, product = [], []
    for path in paths:
        parts = PurePosixPath(path).parts
        if path.startswith("docs/") or path.endswith(".md") or {"test", "tests"} & set(parts) \
                or parts[-1].startswith("test_"):
            continue
        (held if path.startswith(GATE) or is_safety(path) else product).append(path)
    return held, product


def safety_of(wt: Path):
    """``safety_review.is_safety`` over this tree's manifest, or nothing is safety when the harness is absent."""
    if not (wt / MANIFEST).is_file():
        return lambda path: False
    sys.path.insert(0, str(wt / "tools" / "harness"))
    import safety_review
    manifest = safety_review.yaml.safe_load((wt / MANIFEST).read_text(encoding="utf-8")) or {}
    roots, modules = manifest.get("roots") or [], set(manifest.get("safety_modules") or ())
    return lambda path: safety_review.is_safety(path, roots, modules)


def crlf_added(land, wt: Path, base: str, changed: list[str]) -> list[str]:
    """Changed text files whose HEAD copy has CRLF lines that the merge base's copy did not.

    tools/land_mainred.py was committed CRLF (fd9019f795) past core.autocrlf; every branch that stored it LF then
    stopped on a whole-file conflict (2026-11-09). ``-text`` files keep their bytes and are not checked."""
    if not changed:
        return []

    def with_cr(rev: str) -> set[str]:  # whole tree (<1 s), no path list on the command line; -I skips binary
        found = land.git(wt, "grep", "-lI", "-e", "\r$", rev, check=False).stdout  # exit 1: no match
        return {line.split(":", 1)[1] for line in found.splitlines() if ":" in line}

    paths = sorted(with_cr("HEAD") & set(changed) - with_cr(land.out(wt, "merge-base", base, "HEAD")))
    if not paths:
        return []
    attrs = land.lines(wt, "check-attr", "text", "--", *paths)  # "<path>: text: set|unset|auto|unspecified"
    return [path for path, attr in zip(paths, attrs) if not attr.endswith(": unset")]


def precheck(land, wt: Path, python: str, mixed_ok: str = "") -> None:
    """``land`` is tools/land.py (its Stop, gates and git helpers); raises land.Stop on the first failing gate."""
    before = land.out(wt, "rev-parse", "main")
    changed = land.lines(wt, "diff", "--name-only", "--diff-filter=AM", f"{before}...HEAD")  # a rename: its base copy is under the old name
    if crlf := crlf_added(land, wt, before, changed):
        listed = " ".join(f'"{path}"' for path in crlf)
        raise land.Stop(f"this branch adds CRLF line endings to {len(crlf)} text file(s): {', '.join(crlf[:5])}. Main"
                        " stores text LF, and a CRLF copy conflicts as a whole file with every branch that edits it."
                        f" Fix: git add --renormalize -- {listed} && git commit -m \"chore: LF line endings\"")
    held, product = mixed(land.lines(wt, "diff", "--name-only", f"{before}...HEAD"), safety_of(wt))
    if held and product and not mixed_ok.strip():
        raise land.Stop(f"this branch changes landing-gate tools or safety paths ({len(held)}: {', '.join(held[:5])})"
                        f" together with product paths ({len(product)}: {', '.join(product[:5])}). Split them into"
                        " separate branches (a gate or safety change runs FULL and holds the product change behind"
                        ' it), or pass --mixed "<the user\'s words>" (D-889 addendum 32)')
    land.safety_review(wt, before, "HEAD", python)
    land.size_check(wt, before, "HEAD", python)
    merged = land.git(wt, "merge-base", "--is-ancestor", before, "HEAD", check=False).returncode == 0
    if (wt / land.HARNESS).is_file():
        try:
            land.step(wt, [python, land.HARNESS, "lint"], None, "lint")
        except land.Stop as exc:
            if merged:
                raise
            print(f"[precheck] lint fails before main is merged (the supervisor re-lints after the merge): {exc}")
    land.secret_scan(wt, before)
    print("[precheck] safety review, size ratchet, lint and secret scan passed", flush=True)


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        raise SystemExit(f"[land-async] git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def pop_opt(argv: list[str], name: str, hint: str) -> tuple[str | None, list[str]]:
    """Extract ``--name value`` or ``--name=value`` from ``argv``; return ``(value, rest)``."""
    value, rest, i = None, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == name:
            if i + 1 >= len(argv) or not argv[i + 1].strip() or argv[i + 1].startswith("--"):
                raise SystemExit(f"[land-async] {name} needs {hint}")
            if value is not None:
                raise SystemExit(f"[land-async] {name} may only be passed once")
            value, i = argv[i + 1], i + 2
        elif arg.startswith(name + "="):
            val = arg.split("=", 1)[1]
            if not val.strip() or val.startswith("--"):
                raise SystemExit(f"[land-async] {name} needs {hint}")
            if value is not None:
                raise SystemExit(f"[land-async] {name} may only be passed once")
            value, i = val, i + 1
        else:
            rest.append(arg)
            i += 1
    return value, rest


def _checked_out_worktrees(cwd: Path, branch: str) -> list[Path]:
    listing = _git(cwd, "worktree", "list", "--porcelain")
    target, paths = f"refs/heads/{branch}", []
    for block in listing.split("\n\n"):
        lines = block.splitlines()
        wt = next((line[9:] for line in lines if line.startswith("worktree ")), None)
        ref = next((line[7:] for line in lines if line.startswith("branch ")), None)
        if wt and ref == target:
            paths.append(Path(wt))
    return paths


def resolve_branch(cwd: Path, branch: str | None, prefix: str = "land/") -> tuple[str, str]:
    """Return ``(branch_name, ref)`` for HEAD or an explicit local topic branch."""
    if branch is None:
        name = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        if name in ("HEAD", "main") or name.startswith(prefix):
            raise SystemExit(f"[land-async] run it from a topic branch's worktree, not {name!r}")
        if _git(cwd, "status", "--porcelain"):
            raise SystemExit("[land-async] uncommitted changes: commit them first (a landing takes only commits)")
        return name, "HEAD"
    name = branch.removeprefix("refs/heads/")
    if name in ("HEAD", "main") or name.startswith(prefix):
        raise SystemExit(f"[land-async] pass a topic branch name, not {name!r}")
    if subprocess.run(["git", "-C", str(cwd), "show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
                      capture_output=True).returncode != 0:
        raise SystemExit(f"[land-async] local branch not found: {name!r}")
    for wt in _checked_out_worktrees(cwd, name):
        if _git(wt, "status", "--porcelain"):
            raise SystemExit(f"[land-async] {name} has uncommitted changes in {wt}: commit them first"
                             " (a landing takes only commits)")
    return name, f"refs/heads/{name}"


def precheck_branch(cwd: Path, branch: str, words: list[str], place: Path, fallback_land: Path) -> int:
    """Run land.py --precheck on ``branch`` from a temporary hidden checkout under ``place``."""
    place.mkdir(exist_ok=True)
    wt = place / f"precheck-{branch.replace('/', '-')}-{os.getpid()}"
    _git(cwd, "worktree", "remove", "--force", str(wt), check=False)
    _git(cwd, "worktree", "add", "--detach", "-q", str(wt), f"refs/heads/{branch}")
    try:
        land_py = wt / "tools" / "land.py"
        if not land_py.is_file():
            land_py = fallback_land
        return subprocess.call([sys.executable, str(land_py), "--precheck", *words], cwd=wt)
    finally:
        _git(cwd, "worktree", "remove", "--force", str(wt), check=False)
