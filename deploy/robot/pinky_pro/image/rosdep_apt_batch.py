#!/usr/bin/env python3
"""Turn `rosdep install --simulate` output into one apt package list.

rosdep runs one `apt-get install` per key (22 runs, ~4.5 min of a 6.5 min
payload build on 2026-10-01). build-native-payload.sh installs this list in a
single transaction with rosdep's own flags, then lets rosdep confirm that
nothing is left. Non-apt installers (pip) are left to that rosdep run.
Reads stdin, prints sorted unique package names, one per line.
"""

from __future__ import annotations

import re
import sys

APT_LINE = re.compile(r"^\s*(?:sudo\s+(?:-H\s+)?)?apt-get\s+install\s+-y\s+(.+?)\s*$")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")


def main() -> int:
    packages: set[str] = set()
    for line in sys.stdin:
        match = APT_LINE.match(line)
        if not match:
            continue
        for name in match.group(1).split():
            if not PACKAGE.fullmatch(name):
                print(f"rosdep_apt_batch: refusing {name!r}", file=sys.stderr)
                return 2
            packages.add(name)
    for name in sorted(packages):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
