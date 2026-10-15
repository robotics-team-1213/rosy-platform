"""Claim the next API reference version atomically with a git ref (D-510 for versions).

Usage (from any worktree of the repository)::

    python tools/harness/api_reserve.py next "<topic>"    # prints v1.NNN
    python tools/harness/api_reserve.py list
    python tools/harness/api_reserve.py release v1.NNN --reason "<topic>"   # or --force
    python tools/harness/api_reserve.py bump v1.NNN       # move every live-version pin here

``next`` takes one more than the highest minor seen in the ``**Version:**`` header
and ``### v1.NNN`` changelog rows of ``docs/reference/ROSY API & Protocol
Reference.md``: lines added in the history of every local branch and remote-
tracking ref, the file in every worktree (uncommitted included), and existing
``refs/api/v1.*``. It then creates ``refs/api/v1.NNN`` create-only, exactly as
``adr_reserve.py`` does for ADR numbers (same helpers, same CAP guard).

``bump`` rewrites, in this worktree's tracked files, only the lines that pin the
live version: ``**Version:** v1.N`` (reference header and tests),
``ROSY-API-REF-001 v1.N`` / ``(v1.N)`` (core_api_web app.py) and the
``"v1.N" in header`` test pin. Changelog rows and logs are history and stay;
rename your own ``### v1.N`` row by hand. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import adr_reserve as shared

REF = "docs/reference/ROSY API & Protocol Reference.md"
NS = "refs/api"
VERSION_LINE = re.compile(r"^(?:\*\*Version:\*\* |### )v1\.(\d+)\b", re.MULTILINE)
ADDED_LINE = re.compile(r"^\+(?:\*\*Version:\*\* |### )v1\.(\d+)\b")
HEADER = re.compile(r"^\*\*Version:\*\* (v1\.\d+)\b", re.MULTILINE)
NAME = re.compile(r"v1\.(\d+)")


def label(n: int) -> str:
    return f"v1.{n}"


def pin_pattern(version: str) -> re.Pattern:
    v = re.escape(version)
    return re.compile(rf"(?:\*\*Version:\*\* |ROSY-API-REF-001 \(?){v}\b|\"{v}\" in header")


def used_numbers() -> dict[int, str]:
    """Minor -> where it was seen (for the report)."""
    numbers: dict[int, str] = {}
    for name in shared.reserved(NS):
        if match := NAME.fullmatch(name):
            shared._note(numbers, int(match.group(1)), f"{NS}/{name}")
    shared._from_history(numbers, ADDED_LINE, "--no-merges", "-p", "-U0", "--", REF)
    for line in shared.git("worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]) / REF
            if path.is_file():
                for n in VERSION_LINE.findall(path.read_text(encoding="utf-8-sig", errors="replace")):
                    shared._note(numbers, int(n), str(path))
    return numbers


def main_highest() -> int | None:
    if shared.git("rev-parse", "--verify", "-q", "refs/heads/main", check=False).returncode != 0:
        return None
    text = shared.git("show", f"main:{REF}", check=False).stdout
    return max((int(n) for n in VERSION_LINE.findall(text)), default=0)


def cmd_bump(target: str) -> int:
    root = Path(shared.git("rev-parse", "--show-toplevel").stdout.strip())
    header = HEADER.search((root / REF).read_text(encoding="utf-8"))
    if header is None:
        print(f"no **Version:** header in {REF}", file=sys.stderr)
        return 1
    current = header.group(1)
    if current == target:
        print(f"already {target}")
        return 0
    if target not in shared.reserved(NS):
        print(f"warning: {target} is not reserved here; run `next` first", file=sys.stderr)
    pin = pin_pattern(current)
    files = shared.git("-C", str(root), "grep", "-l", "-I", "-F", "-e", current, check=False).stdout
    changed = 0
    for rel in files.splitlines():
        path = root / rel
        with path.open(encoding="utf-8", newline="") as f:
            text = f.read()
        new, count = pin.subn(lambda m: m.group(0).replace(current, target), text)
        if count:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(new)
            print(f"{rel}: {count}")
            changed += count
        if rel.endswith(".py"):
            for number, line in enumerate(new.splitlines(), 1):
                if re.search(rf"{re.escape(current)}\b", line):
                    print(f"warning: {rel}:{number} still names {current}: {line.strip()[:80]}",
                          file=sys.stderr)
    print(f"{current} -> {target}: {changed} pins; rename your own `### {current}` row by hand")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next").add_argument("reason")
    sub.add_parser("list")
    release = sub.add_parser("release")
    release.add_argument("version")
    release.add_argument("--reason", help="the reservation's reason, as `list` shows it")
    release.add_argument("--force", action="store_true", help="release someone else's reservation")
    sub.add_parser("bump").add_argument("version")
    args = parser.parse_args(argv)
    if args.command == "next":
        return shared.claim(used_numbers(), main_highest(), args.reason, NS, label)
    if args.command == "list":
        return shared.cmd_list(NS)
    if not NAME.fullmatch(args.version):
        parser.error("version must look like v1.123")
    if args.command == "bump":
        return cmd_bump(args.version)
    return shared.cmd_release(args.version, args.reason, args.force, NS)


if __name__ == "__main__":
    sys.exit(main())
