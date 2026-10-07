"""ADR gap lines and local reservations for the harness lint (D-510).

Split out of ``rosy_harness.py`` (size verdict) like ``sim2real.py``; the harness
re-exports these names. ``adr_reserve.py`` is the CLI that creates the refs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ADR_GAPS = Path("tools") / "harness" / "adr_gaps.txt"  # D-510, merge=union
ADR_ID = re.compile(r"^D-(\d+)$")


def _number(adr_id: str) -> int:
    return int(adr_id.split("-")[1])


def parse_adr_gaps(text: str) -> tuple[dict[str, str], list[str]]:
    """``D-nnn reason`` per line; union merges may repeat or reorder lines (D-510)."""
    gaps: dict[str, str] = {}
    errors: list[str] = []
    for number, line in enumerate(text.removeprefix("﻿").replace("\r\n", "\n").split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        adr_id, reason = (line.split(None, 1) + [""])[:2]
        if not ADR_ID.match(adr_id) or not reason:
            errors.append(f"line {number}: expected 'D-nnn reason', got {line!r}")
            continue
        gaps.setdefault(adr_id, reason)
    return gaps, errors


def reserved_adrs(repo: Path) -> set[str]:
    """Numbers claimed with tools/harness/adr_reserve.py (refs/adr/D-nnn, D-510). Local only."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:lstrip=2)", "refs/adr"],
            capture_output=True, text=True, encoding="utf-8", check=False)
    except OSError:
        return set()
    out = result.stdout if result.returncode == 0 else ""
    return {name for name in out.split() if ADR_ID.match(name)}


def load_adr_gaps(repo: Path, config: dict) -> tuple[dict[str, str], list[str]]:
    # ponytail: harness.yaml adr_gaps still read for in-flight branches; drop once none add there.
    gaps = dict(config.get("adr_gaps") or {})
    errors: list[str] = []
    path = repo / ADR_GAPS
    if path.is_file():
        parsed, errors = parse_adr_gaps(path.read_text(encoding="utf-8"))
        for adr_id, reason in parsed.items():
            gaps.setdefault(adr_id, reason)
    return gaps, errors


def reservation_warnings(adr, gaps: dict[str, str], reserved: set[str]) -> list[str]:
    """refs/adr are local: CI and other clones lack them, so they never excuse a gap (D-510).

    Only a number below the branch's highest ADR would fail CI as a missing gap.
    """
    present = set(adr.index) | set(adr.bodies)
    highest = max((_number(i) for i in present), default=0)
    return [f"{adr_id} reserved locally (refs/adr) but not on this branch"
            " — land its ADR or add a gap line to tools/harness/adr_gaps.txt before push"
            for adr_id in sorted(reserved - present - set(gaps), key=_number)
            if _number(adr_id) < highest]


def validate_adr_log(adr, gaps: dict[str, str]) -> list[str]:
    errors = [f"{adr_id}: duplicate body section" for adr_id in adr.duplicates]
    errors += [f"{adr_id}: duplicate index row" for adr_id in adr.index_duplicates]
    for adr_id in sorted(set(adr.bodies) - set(adr.index), key=_number):
        errors.append(f"{adr_id}: body section missing from index")
    for adr_id in sorted(set(adr.index) - set(adr.bodies), key=_number):
        errors.append(f"{adr_id}: index row has no body section")

    present = set(adr.index) | set(adr.bodies)
    highest = max((_number(i) for i in present), default=0)
    for number in range(1, highest + 1):
        adr_id = f"D-{number}"
        if adr_id not in present and adr_id not in gaps:
            errors.append(f"{adr_id}: missing and not declared in adr_gaps")
    for adr_id in sorted(gaps, key=_number):
        if adr_id in present:
            errors.append(f"{adr_id}: declared gap now exists; remove it from adr_gaps")
    return errors
