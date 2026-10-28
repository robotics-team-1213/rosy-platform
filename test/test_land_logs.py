"""tools/land_logs.py append_blocks when both sides inserted logs.md entries mid-file (test_land.py holds the rest)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/harness"))

from land_logs import append_blocks  # noqa: E402
import rosy_harness  # noqa: E402

ENTRY = "\n## 2026-10-07 · uncommitted · {who}\n- 변경: {who}\n- 증거: 없음\n- gate 변화: 없음\n- 결정: 없음\n- 교훈: 없음\n"


def dated(day: str, who: str) -> str:
    return ENTRY.replace("2026-10-07", day).format(who=who)


def test_both_sides_inserting_mid_file_keep_their_spots():
    """2026-10-28: feat/fleet-arm-observation stopped on deploy/logs.md, both sides only inserting whole entries."""
    a, b, c = dated("2026-10-13", "a"), dated("2026-10-15", "b"), dated("2026-10-17", "c")
    base = "# docs logs\n" + a + b + c
    same_spot = ("# docs logs\n" + a + dated("2026-10-14", "x") + b + c,
                 "# docs logs\n" + a + dated("2026-10-14", "y") + b + c,
                 "# docs logs\n" + a + dated("2026-10-14", "y") + dated("2026-10-14", "x") + b + c)
    other_spots = ("# docs logs\n" + a + b + dated("2026-10-16", "x") + c,
                   "# docs logs\n" + a + dated("2026-10-14", "y") + b + c,
                   "# docs logs\n" + a + dated("2026-10-14", "y") + b + dated("2026-10-16", "x") + c)
    for ours, theirs, merged in (same_spot, other_spots):
        got = append_blocks(base.encode(), ours.encode(), theirs.encode()).decode()
        assert got == merged
        assert rosy_harness.validate_log(got) == []


def test_both_sides_inserting_mid_file_out_of_date_order_refuses():
    a, b = dated("2026-10-13", "a"), dated("2026-10-15", "b")
    base = "# docs logs\n" + a + b
    ours = "# docs logs\n" + a + dated("2026-10-16", "x") + b  # already out of order on the branch
    theirs = "# docs logs\n" + a + dated("2026-10-14", "y") + b
    assert append_blocks(base.encode(), ours.encode(), theirs.encode()) is None
