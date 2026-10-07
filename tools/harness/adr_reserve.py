"""Claim the next ADR number atomically with a git ref (D-508).

Usage (from any worktree of the repository)::

    python tools/harness/adr_reserve.py next "<topic>"   # prints D-nnn
    python tools/harness/adr_reserve.py list
    python tools/harness/adr_reserve.py release D-nnn

``next`` takes one more than the highest number seen in: ``docs/adr`` files and
added Log rows or gap lines in the history of every local branch, the same
files in every worktree (untracked included), and existing ``refs/adr/D-*``. It then
creates ``refs/adr/D-nnn`` with ``git update-ref <ref> <sha> 0{40}``, which
fails if the ref already exists. All worktrees share one ref store, so two
sessions cannot both create the same ref; the loser tries the next number.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LOG = "docs/reference/ROSY ADR Log.md"
GAPS = "tools/harness/adr_gaps.txt"
CONFIG = "tools/harness/harness.yaml"
ZERO = "0" * 40
# Log rows "| D-n |", gap lines "D-n reason", harness.yaml gaps "  D-n:".
NUMBERED_LINE = re.compile(r"^(?:\| |  )?D-(\d+)\b", re.MULTILINE)
ADR_FILE = re.compile(r"(?:^|docs/adr/)D-(\d+)[-.]", re.MULTILINE)
ADDED_LINE = re.compile(r"^\+(?:\| |  )?D-(\d+)", re.MULTILINE)
ATTEMPTS = 50


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def reserved() -> dict[str, str]:
    out = git("for-each-ref", "--format=%(refname:lstrip=2) %(objectname)", "refs/adr").stdout
    return dict(line.split() for line in out.splitlines() if line.strip())


def used_numbers() -> set[int]:
    numbers = {int(name[2:]) for name in reserved() if name[2:].isdigit()}
    # History of all local branches, two processes total (723 branches on 2026-10-07:
    # a per-branch ls-tree or a multi-tree git grep took 14 s and nears the argv limit).
    names = git("log", "--branches", "--name-only", "--format=", "--", "docs/adr").stdout
    numbers |= {int(n) for n in ADR_FILE.findall(names)}
    added = git("log", "--branches", "--no-merges", "--format=", "-p", "-U0",
                "--", LOG, GAPS, CONFIG).stdout
    numbers |= {int(n) for n in ADDED_LINE.findall(added)}
    porcelain = git("worktree", "list", "--porcelain").stdout
    for line in porcelain.splitlines():
        if not line.startswith("worktree "):
            continue
        tree = Path(line[len("worktree "):])
        adr_dir = tree / "docs" / "adr"
        if adr_dir.is_dir():
            numbers |= {int(n) for p in adr_dir.glob("D-*") for n in ADR_FILE.findall(p.name)}
        for rel in (LOG, GAPS, CONFIG):
            path = tree / rel
            if path.is_file():
                numbers |= {int(n) for n in NUMBERED_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace"))}
    return numbers


def cmd_next(reason: str) -> int:
    head = git("rev-parse", "HEAD").stdout.strip()
    number = max(used_numbers(), default=0) + 1
    for _ in range(ATTEMPTS):
        ref = f"refs/adr/D-{number}"
        if git("update-ref", "--create-reflog", "-m", reason, ref, head, ZERO, check=False).returncode == 0:
            print(f"D-{number}")
            return 0
        number += 1  # a peer created this ref between our scan and our claim
    print(f"no free number after {ATTEMPTS} attempts", file=sys.stderr)
    return 1


def cmd_list() -> int:
    for name, sha in sorted(reserved().items(), key=lambda kv: int(kv[0][2:]) if kv[0][2:].isdigit() else 0):
        reason = git("reflog", "show", "-1", "--format=%gs", f"refs/adr/{name}", check=False).stdout.strip()
        print(f"{name}\t{sha[:9]}\t{reason}")
    return 0


def cmd_release(adr_id: str) -> int:
    sha = reserved().get(adr_id)
    if sha is None:
        print(f"{adr_id}: not reserved", file=sys.stderr)
        return 1
    git("update-ref", "-d", f"refs/adr/{adr_id}", sha)
    print(f"released {adr_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next").add_argument("reason")
    sub.add_parser("list")
    sub.add_parser("release").add_argument("adr_id")
    args = parser.parse_args(argv)
    if args.command == "next":
        return cmd_next(args.reason)
    if args.command == "list":
        return cmd_list()
    if not re.fullmatch(r"D-\d+", args.adr_id):
        parser.error("adr_id must look like D-123")
    return cmd_release(args.adr_id)


if __name__ == "__main__":
    sys.exit(main())
