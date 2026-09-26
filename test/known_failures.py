"""Compare a pytest run against test/known_failures.txt.

Usage (from the repo root):

    python -m pytest <paths> -q -rfE -p no:cacheprovider > run.txt
    python test/known_failures.py run.txt        # or pipe the output on stdin

Exit 0: every FAILED/ERROR line is a listed pre-existing failure.
Exit 1: at least one failure is not listed (the branch introduced it, or the list is stale).
A listed id that did not fail is printed as "not failing here" (fixed, or not selected).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

LIST = Path(__file__).with_name("known_failures.txt")
SUMMARY = re.compile(r"^(?:FAILED|ERROR) (?P<nodeid>\S.*?)(?: - .*)?$")


def load_known(text: str) -> dict[str, str]:
    known: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nodeid, _, reason = line.partition("  # ")
        known[nodeid.strip()] = reason.strip()
    return known


def failed_ids(report: str) -> list[str]:
    ids = []
    for line in report.splitlines():
        match = SUMMARY.match(line.strip())
        if match:
            ids.append(match.group("nodeid").replace("\\", "/"))
    return ids


def _matches(failed: str, known: str) -> bool:
    # A run started inside a module (cd src/runtime/gateway) prints a shorter
    # node id; accept it when it is a path-boundary suffix of the listed id.
    return failed == known or known.endswith("/" + failed)


def compare(report: str, known: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Return (new failures, listed failures seen, listed ids not failing)."""
    new, seen = [], []
    for failed in failed_ids(report):
        hit = next((k for k in known if _matches(failed, k)), None)
        if hit is None:
            new.append(failed)
        elif hit not in seen:
            seen.append(hit)
    quiet = [k for k in known if k not in seen]
    return new, seen, quiet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", nargs="?", help="saved pytest output (default: stdin)")
    args = parser.parse_args(argv)
    report = Path(args.report).read_text(encoding="utf-8", errors="replace") if args.report else sys.stdin.read()
    new, seen, quiet = compare(report, load_known(LIST.read_text(encoding="utf-8")))
    for nodeid in seen:
        print(f"known     {nodeid}")
    for nodeid in quiet:
        print(f"not failing here  {nodeid}")
    for nodeid in new:
        print(f"NEW       {nodeid}")
    print(f"{len(new)} new, {len(seen)} known, {len(quiet)} listed but not failing")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
