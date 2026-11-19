"""Members of a rollup that stopped on a NEW failure are not rolled up again (bn-L-2, 2026-11-20).

On 11-19 16:07~19:42 the same four members rode about ten rollups, each stopping on test_learning_boundary: split's
halves and its members resumed alone went 'pending', and ``apply --auto`` (D-889 34) rolled them up again. In 24 hours
42 rollups were built, 3 landed and 19 stopped. ``split ... bisect`` now records each member's candidate in
``<git-common-dir>/rosy-rollup-failed.jsonl``; ``plan`` and ``apply --auto`` leave out, for KEEP, a row with such a
candidate and every row of a rollup that holds one, so those land alone. split's own halves are built directly and
still bisect. A new commit on a member makes a new candidate, which may roll up again. A missing or broken record
leaves nothing out.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

NAME = "rosy-rollup-failed.jsonl"
KEEP = timedelta(hours=24)


def record(place: Path, rollup: str, members: list[dict], now: datetime) -> None:
    """Append each member's candidate as failed in ``rollup`` to ``place`` (the git common dir); best effort."""
    lines = "".join(json.dumps({"t": now.isoformat(), "rollup": rollup, "candidate": m["candidate"],
                                "branch": m.get("branch")}) + "\n"
                    for m in members if isinstance(m, dict) and m.get("candidate"))
    try:
        with (place / NAME).open("a", encoding="utf-8", newline="\n") as f:
            f.write(lines)
    except OSError:
        pass


def failed(place: Path, now: datetime) -> dict[str, str]:
    """Candidate -> the rollup it failed in, recorded within KEEP; unreadable lines are skipped."""
    try:
        text = (place / NAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        try:
            e = json.loads(line)
            if now - datetime.fromisoformat(e["t"]) <= KEEP:
                found[str(e["candidate"])] = str(e["rollup"])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def drop(repo: Path, place: Path, rows: list[dict], now: datetime) -> list[dict]:
    """``rows`` without failed candidates and without every row of a rollup that holds one (it keeps its ticket)."""
    bad = failed(place, now)
    if not bad:
        return rows
    hit: dict[str, str] = {}
    for r in rows:
        tip = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/heads/{r['branch']}"],
                             capture_output=True, text=True).stdout.strip() or r.get("candidate")
        if tip in bad:
            hit[r.get("rollup") or r["branch"]] = bad[tip]
    for r in rows:
        if (r.get("rollup") or r["branch"]) in hit:
            print(f"[rollup] {r['branch']} left out: failed in {hit[r.get('rollup') or r['branch']]}", flush=True)
    return [r for r in rows if (r.get("rollup") or r["branch"]) not in hit]
