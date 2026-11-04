"""A run placed on small hosts only moves to a lab PC once one has room (2026-11-04: 253 of 256 pretest jobs ran
serially on the site PC for 131 min while the AI PC sat idle)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import work_queue as wq  # noqa: E402

ROOM = {"site": {"site": True}, "light": {"light": True}, "ai": {"cores": 20, "mem": 20}}


def test_small_hosts_retire_once_a_lab_pc_is_placed():
    work, deferred, placements = wq.Work([0, 1, 2]), set(), [["site"], ["site", "ai"]]
    done = wq.upgrade_watch(work, [("site", "any")], ROOM, lambda: placements.pop(0) if placements else ["ai"],
                            deferred, every=0.01)
    deadline = time.monotonic() + 5
    while not deferred and time.monotonic() < deadline:
        time.sleep(0.01)
    done.set()
    assert deferred == {"site"}
    assert work.take(None, "site") is None and work.take_small(None, "site") is None
    assert work.take(None, "ai") == 0, "the rest stays queued for the lab PC"


def test_only_runs_on_small_hosts_watch():
    assert wq.small_only([("site", "any"), ("light", "any")], ROOM)
    assert not wq.small_only([("site", "any"), ("ai", "main")], ROOM)
    assert not wq.small_only([("unmeasured", "any")], ROOM), "no headroom entry: keep the one-host fast path"
    work = wq.Work([0])
    wq.upgrade_watch(work, [("ai", "main")], ROOM, lambda: pytest.fail("placed again"), set(), every=0.01)
    time.sleep(0.05)
    work.retired.add("old")
    wq.upgrade_watch(work, [("light", "any")], ROOM, lambda: ["light"], set(), every=0.01).set()
    assert work.retired == set(), "a new placement round starts with no retired host"
