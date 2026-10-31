"""tools/land_queue.py: arrival order, stale-ticket reclaim and the wait timeout."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_queue as queue  # noqa: E402


def gone_pid() -> int:
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    return int(done.stdout)


def ticket(qdir: Path, branch: str, pid: int, host: str | None = None, age: float = 0.0) -> Path:
    path = queue.take(qdir, branch)
    path.write_text(json.dumps({"pid": pid, "host": host or socket.gethostname(), "start": time.time() - age,
                                "branch": branch}), encoding="utf-8")
    os.utime(path, (time.time() - age,) * 2)
    return path


def test_tickets_go_in_arrival_order(tmp_path):
    first, second, third = (queue.take(tmp_path, b) for b in ("feat/a", "feat/b", "feat/c"))
    assert queue.ahead(tmp_path, first) == []
    assert [r["branch"] for r in queue.ahead(tmp_path, third)] == ["feat/a", "feat/b"]
    first.unlink()
    assert [r["branch"] for r in queue.ahead(tmp_path, third)] == ["feat/b"]
    assert [r["branch"] for r in queue.ahead(tmp_path, second)] == []
    assert not list(tmp_path.glob(".*")), "no half-written ticket is left behind"


def test_stale_tickets_are_reclaimed_and_live_ones_kept(tmp_path, capsys):
    dead = ticket(tmp_path, "feat/dead", gone_pid())
    old = ticket(tmp_path, "feat/old", os.getpid(), age=queue.STALE_AFTER + 60)
    elsewhere = ticket(tmp_path, "feat/elsewhere", gone_pid(), host="another-host")  # PID says nothing there
    live = ticket(tmp_path, "feat/live", os.getpid())
    mine = queue.take(tmp_path, "feat/mine")
    assert [r["branch"] for r in queue.ahead(tmp_path, mine)] == ["feat/elsewhere", "feat/live"]
    assert not dead.exists() and not old.exists() and elsewhere.exists() and live.exists()
    out = capsys.readouterr().out
    assert "feat/dead" in out and "is gone" in out and "feat/old" in out and "not refreshed" in out


def test_wait_returns_when_the_one_ahead_leaves(tmp_path):
    peer = ticket(tmp_path, "feat/peer", os.getpid())
    mine = queue.take(tmp_path, "feat/mine")
    naps = []
    queue.wait(tmp_path, mine, timeout=600, sleep=lambda s: naps.append(s) or peer.unlink())
    assert len(naps) == 1


def test_wait_times_out_with_who_is_ahead(tmp_path):
    ticket(tmp_path, "feat/peer", os.getpid())
    mine = queue.take(tmp_path, "feat/mine")
    now = [1000.0]
    with pytest.raises(queue.QueueError, match=r"feat/peer.*--no-queue"):
        queue.wait(tmp_path, mine, timeout=60, clock=lambda: now[0],
                   sleep=lambda s: now.__setitem__(0, now[0] + 30))
    assert mine.exists(), "the caller's leave() removes it, not wait()"


def test_leave_removes_held_tickets(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "_held", [queue.take(tmp_path, "feat/a")])
    queue.leave()
    queue.leave()
    assert not list(tmp_path.iterdir())


def test_a_preparing_ticket_keeps_its_place_without_blocking_and_a_turn_blocks_everyone(tmp_path):
    """2026-10-26: a FULL tier at the front of the queue held every lander behind it 40+ min."""
    full = queue.take(tmp_path, "feat/full", status="preparing")
    small = queue.take(tmp_path, "feat/small")
    assert queue.blockers(tmp_path, small) == [], "the preparing FULL lander ahead does not block"
    queue.wait(tmp_path, small, timeout=0)
    assert json.loads(small.read_text())["status"] == "turn"
    later = queue.take(tmp_path, "feat/later")
    assert [r["branch"] for r in queue.blockers(tmp_path, full)] == ["feat/small"], "in its turn: blocks all"
    small.unlink()
    queue.set_status(full, "waiting")
    assert queue.blockers(tmp_path, full) == [] and [r["branch"] for r in queue.blockers(tmp_path, later)] == [
        "feat/full"], "done preparing, the FULL lander is first again"


def test_at_most_max_preparing_landings_prepare_at_once_and_a_pending_one_blocks_no_one(tmp_path):
    import land_prepare
    busy = [queue.take(tmp_path, f"feat/p{n}", status="preparing") for n in range(land_prepare.MAX_PREPARING)]
    mine = queue.take(tmp_path, "feat/mine")
    later = queue.take(tmp_path, "feat/later")
    naps = []

    def nap(s):
        naps.append(s)
        assert json.loads(mine.read_text())["status"] == "pending"
        assert [r["branch"] for r in queue.blockers(tmp_path, later)] == [], "pending blocks no one"
        busy.pop().unlink()  # one preparing lander finishes

    land_prepare.slot(tmp_path, mine, sleep=nap)
    assert len(naps) == 1 and json.loads(mine.read_text())["status"] == "preparing"


def test_an_urgent_ticket_prepares_without_waiting_behind_older_pending_ones(tmp_path):
    import land_prepare
    for n in range(land_prepare.MAX_PREPARING + 2):
        queue.take(tmp_path, f"feat/older{n}", status="pending")
    mine = queue.take(tmp_path, "feat/urgent", status="pending", urgent="the user's words")
    land_prepare.slot(tmp_path, mine, sleep=lambda s: pytest.fail("urgent waited behind pending reservations"))
    assert json.loads(mine.read_text())["status"] == "preparing"


def test_who_is_ahead_shows_each_tickets_status(tmp_path):
    queue.take(tmp_path, "feat/full", status="preparing")
    mine = queue.take(tmp_path, "feat/mine")
    assert "feat/full (preparing," in queue.describe(queue.ahead(tmp_path, mine))


def test_preparation_slot_reserves_capacity_for_older_pending_ticket(tmp_path):
    import land_prepare
    busy = [queue.take(tmp_path, f"feat/p{n}", status="preparing") for n in range(land_prepare.MAX_PREPARING - 1)]
    older = queue.take(tmp_path, "feat/older", status="pending")
    mine = queue.take(tmp_path, "feat/mine", status="pending")
    naps = []

    def nap(seconds):
        naps.append(seconds)
        assert json.loads(mine.read_text())["status"] == "pending"
        if len(naps) == 1:
            queue.set_status(older, "preparing")
        else:
            busy.pop().unlink()

    land_prepare.slot(tmp_path, mine, sleep=nap)
    assert len(naps) == 2
    assert json.loads(mine.read_text())["status"] == "preparing"


@pytest.mark.parametrize("status,later", [("pending", True), ("waiting", False), ("turn", False)])
def test_preparation_slot_ignores_non_preparing_tickets_without_prior_claim(tmp_path, status, later):
    import land_prepare
    for n in range(2):
        queue.take(tmp_path, f"feat/p{n}", status="preparing")
    if not later:
        queue.take(tmp_path, "feat/peer", status=status)
    mine = queue.take(tmp_path, "feat/mine", status="pending")
    if later:
        queue.take(tmp_path, "feat/peer", status=status)
    land_prepare.slot(tmp_path, mine, sleep=lambda _: pytest.fail("a preparation slot is available"))
    assert json.loads(mine.read_text())["status"] == "preparing"


def test_a_check_that_names_a_reason_stops_the_wait_at_once_and_zero_means_no_limit(tmp_path):
    """Rule 9 (2026-10-26): a conflict main made during the wait stopped the landing only at its turn."""
    ticket(tmp_path, "feat/peer", os.getpid())
    mine = queue.take(tmp_path, "feat/mine")
    calls = []
    with pytest.raises(queue.QueueError, match="conflicts with this branch"):
        queue.wait(tmp_path, mine, timeout=0, sleep=lambda s: None,
                   check=lambda: calls.append(1) or ("main abc conflicts with this branch" if len(calls) > 2 else None))
    assert len(calls) == 3, "no time limit: it waited until the check spoke"


def test_an_older_pending_ticket_a_batch_carries_reserves_no_preparation_slot(tmp_path):
    """A carried member never prepares on its own (land_batch), so it must not hold back younger tickets."""
    import land_prepare
    for n in range(2):
        queue.take(tmp_path, f"feat/p{n}", status="preparing")
    queue.take(tmp_path, "feat/carried", status="pending")
    leader = queue.take(tmp_path, "feat/leader", status="waiting")
    queue.set_status(leader, "waiting", batch=["feat/carried"])
    mine = queue.take(tmp_path, "feat/mine", status="pending")
    land_prepare.slot(tmp_path, mine, sleep=lambda _: pytest.fail("a carried ticket kept the slot"))
    assert json.loads(mine.read_text())["status"] == "preparing"
