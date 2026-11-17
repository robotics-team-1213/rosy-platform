"""D-889 addendum 36: a commit that changes the landing pipeline cites its numbers and what it removes.

``Metrics: before=...`` for any commit touching tools/land*.py or tools/land_*/; ``Removes: ...`` as well when it adds
a timer/trigger constant (*_S, *_EVERY*, *_POLLS) or a call that builds a rollup. ``size_range.py`` applies it to every
non-merge commit of a range, so it runs in the landing precheck and the turn, where main is the local main.
"""

from __future__ import annotations

import datetime as dt
import re

#: Only commits committed at or after this are checked: branches already in flight on 2026-11-17 are not blocked
#: retroactively.
RULE_SINCE = dt.datetime.fromisoformat("2026-11-17T18:00:00+09:00")
PIPELINE = re.compile(r"^tools/(land[^/]*\.py|land_[^/]+/)")
TRIGGER = re.compile(r"^\+[A-Z][A-Z0-9_]*(?:_S|_POLLS|_EVERY[A-Z0-9_]*)\s*=|"
                     r"^\+.*(?:land_rollup\.py|rollup\(|\"--auto\")")


def violations(message: str, files: list[str], diff: str) -> list[str]:
    if not any(PIPELINE.match(f) for f in files):
        return []
    out = []
    if not re.search(r"^Metrics:.*\bbefore=", message, re.M):
        out.append("touches the landing pipeline without a 'Metrics: before=...' line")
    if any(TRIGGER.match(line) for line in diff.splitlines()) and not re.search(r"^Removes:\s*\S", message, re.M):
        out.append("adds a timer or rollup trigger without a 'Removes: ...' line")
    return out
