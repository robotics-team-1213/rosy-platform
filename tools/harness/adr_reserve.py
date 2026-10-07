"""Claim the next ADR number atomically with a git ref (D-508).

Usage (from any worktree of the repository)::

    python tools/harness/adr_reserve.py next "<topic>"    # prints D-nnn
    python tools/harness/adr_reserve.py list
    python tools/harness/adr_reserve.py release D-nnn --reason "<topic>"   # or --force

``next`` takes one more than the highest number seen in: ``docs/adr`` files and
added Log rows or gap lines in the history of every local branch and remote-
tracking ref, the same files in every worktree (untracked included), and
existing ``refs/adr/D-*``. Numbers more than ``CAP`` above main's highest are
ignored with a warning (a typo such as D-5080 would otherwise move everyone).
It then creates ``refs/adr/D-nnn`` with ``git update-ref <ref> <sha> 0{40}``,
which fails if the ref already exists. All worktrees share one ref store, so
two sessions cannot both create the same ref; the loser tries the next number.
The refs are local: they are not pushed and CI does not see them.
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
ADDED_LINE = re.compile(r"^\+(?:\| |  )?D-(\d+)\b")
ADR_FILE = re.compile(r"(?:^|docs/adr/)D-(\d+)[-.]")
ATTEMPTS = 50
CAP = 20


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def reserved() -> dict[str, str]:
    out = git("for-each-ref", "--format=%(refname:lstrip=2) %(objectname)", "refs/adr").stdout
    return dict(line.split() for line in out.splitlines() if line.strip())


def reason_of(adr_id: str) -> str:
    return git("reflog", "show", "-1", "--format=%gs", f"refs/adr/{adr_id}", check=False).stdout.strip()


def _note(numbers: dict[int, str], number: int, source: str) -> None:
    numbers.setdefault(number, source)


def _from_history(numbers: dict[int, str], pattern: re.Pattern, *args: str) -> None:
    # --source labels each commit with the ref that reached it ("@<ref>" lines).
    source = "?"
    for line in git("log", "--branches", "--remotes", "--source", "--format=@%S", *args).stdout.splitlines():
        if line.startswith("@"):
            source = line[1:]
        elif match := pattern.search(line):
            _note(numbers, int(match.group(1)), f"{source}: {line.lstrip('+')[:60]}")


def main_highest() -> int | None:
    if git("rev-parse", "--verify", "-q", "refs/heads/main", check=False).returncode != 0:
        return None
    names = git("ls-tree", "--name-only", "main", "docs/adr/").stdout
    log = git("show", f"main:{LOG}", check=False).stdout
    found = [int(m.group(1)) for line in names.splitlines() if (m := ADR_FILE.search(line))]
    found += [int(n) for n in NUMBERED_LINE.findall(log)]
    return max(found, default=0)


def used_numbers() -> dict[int, str]:
    """Number -> where it was seen (for the report)."""
    numbers: dict[int, str] = {}
    for name in reserved():
        if name[2:].isdigit():
            _note(numbers, int(name[2:]), f"refs/adr/{name}")
    # Two processes over all branch history (723 branches on 2026-10-07: a
    # per-branch ls-tree or a multi-tree git grep took 14 s and neared the argv limit).
    _from_history(numbers, ADR_FILE, "--name-only", "--", "docs/adr")
    _from_history(numbers, ADDED_LINE, "--no-merges", "-p", "-U0", "--", LOG, GAPS, CONFIG)
    for line in git("worktree", "list", "--porcelain").stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        tree = Path(line[len("worktree "):])
        adr_dir = tree / "docs" / "adr"
        if adr_dir.is_dir():
            for p in adr_dir.glob("D-*"):
                if match := ADR_FILE.search(p.name):
                    _note(numbers, int(match.group(1)), str(p))
        for rel in (LOG, GAPS, CONFIG):
            path = tree / rel
            if path.is_file():
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                for n in NUMBERED_LINE.findall(text):
                    _note(numbers, int(n), str(path))
    return numbers


def cmd_next(reason: str) -> int:
    head = git("rev-parse", "HEAD").stdout.strip()
    numbers = used_numbers()
    ceiling = main_highest()
    if ceiling is not None:
        for n in sorted(k for k in numbers if k > ceiling + CAP):
            print(f"warning: ignoring D-{n} (more than {CAP} above main's D-{ceiling}) from {numbers.pop(n)}",
                  file=sys.stderr)
    highest = max(numbers, default=0)
    if numbers:
        print(f"highest in use: D-{highest} from {numbers[highest]}", file=sys.stderr)
    number = highest + 1
    for _ in range(ATTEMPTS):
        ref = f"refs/adr/D-{number}"
        result = git("update-ref", "--create-reflog", "-m", reason, ref, head, ZERO, check=False)
        if result.returncode == 0:
            print(f"D-{number}")
            return 0
        if git("rev-parse", "--verify", "-q", ref, check=False).returncode != 0:
            print(f"git update-ref {ref} failed: {result.stderr.strip()}", file=sys.stderr)
            return 1
        number += 1  # a peer created this ref between our scan and our claim
    print(f"no free number after {ATTEMPTS} attempts", file=sys.stderr)
    return 1


def cmd_list() -> int:
    for name, sha in sorted(reserved().items(), key=lambda kv: int(kv[0][2:]) if kv[0][2:].isdigit() else 0):
        print(f"{name}\t{sha[:9]}\t{reason_of(name)}")
    return 0


def cmd_release(adr_id: str, reason: str | None, force: bool) -> int:
    sha = reserved().get(adr_id)
    if sha is None:
        print(f"{adr_id}: not reserved", file=sys.stderr)
        return 1
    recorded = reason_of(adr_id)
    if not force and reason != recorded:
        print(f"{adr_id} was reserved for {recorded!r}; pass --reason with that text, or --force",
              file=sys.stderr)
        return 1
    git("update-ref", "-d", f"refs/adr/{adr_id}", sha)
    print(f"released {adr_id} ({recorded})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next").add_argument("reason")
    sub.add_parser("list")
    release = sub.add_parser("release")
    release.add_argument("adr_id")
    release.add_argument("--reason", help="the reservation's reason, as `list` shows it")
    release.add_argument("--force", action="store_true", help="release someone else's reservation")
    args = parser.parse_args(argv)
    if args.command == "next":
        return cmd_next(args.reason)
    if args.command == "list":
        return cmd_list()
    if not re.fullmatch(r"D-\d+", args.adr_id):
        parser.error("adr_id must look like D-123")
    return cmd_release(args.adr_id, args.reason, args.force)


if __name__ == "__main__":
    sys.exit(main())
