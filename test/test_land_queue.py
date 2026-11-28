"""tools/land_queue.py: arrival order, stale-ticket reclaim and the wait timeout."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import types
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


def test_turn_clock_resets_on_actual_reacquisition_and_old_release_cannot_touch_it(tmp_path, monkeypatch):
    ticket = queue.take(tmp_path, "feat/clock")
    now = [100.0]
    monkeypatch.setattr(queue.time, "monotonic", lambda: now[0])
    events = []
    monkeypatch.setattr(queue.land_events, "emit", lambda event, **kw: events.append(event))
    queue.wait(tmp_path, ticket, 0)
    assert json.loads(ticket.read_text())["turn_started"] == 100
    assert queue.release(ticket, "deadline", started=100)
    assert not queue.release(ticket, "again", started=100)
    now[0] = 900
    queue.wait(tmp_path, ticket, 0)
    assert json.loads(ticket.read_text())["turn_started"] == 900
    assert not queue.release(ticket, "old timer", started=100)
    queue.set_status(ticket, "turn", pid=os.getpid() + 1)
    assert not queue.release(ticket, "old owner", started=900)
    assert json.loads(ticket.read_text())["status"] == "turn"
    assert events.count("released") == 1


@pytest.mark.parametrize("fields", [{"pid": 0}, {"pid": None}, {"turn_started": None}])
def test_unknown_pid_or_epoch_never_counts_as_turn_ownership(tmp_path, fields):
    ticket = queue.take(tmp_path, "feat/clock")
    queue.set_status(ticket, "turn", turn_started=100)
    queue.set_status(ticket, "turn", **fields)
    assert not queue.owns_turn(ticket)
    assert not queue.release(ticket, "unknown owner")


def test_completed_batch_member_finishes_before_rule_refresh(tmp_path):
    mine = queue.take(tmp_path, "feat/member")
    assert queue.wait(tmp_path, mine, 0, done=lambda: True,
                      changed=lambda: pytest.fail("an already landed member restarted")) == "landed"


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


def test_who_is_ahead_shows_each_tickets_status(tmp_path):
    queue.take(tmp_path, "feat/full", status="preparing")
    mine = queue.take(tmp_path, "feat/mine")
    assert "feat/full (preparing," in queue.describe(queue.ahead(tmp_path, mine))


def test_a_check_that_names_a_reason_stops_the_wait_at_once_and_zero_means_no_limit(tmp_path):
    """Rule 9 (2026-10-26): a conflict main made during the wait stopped the landing only at its turn."""
    ticket(tmp_path, "feat/peer", os.getpid())
    mine = queue.take(tmp_path, "feat/mine")
    calls = []
    with pytest.raises(queue.QueueError, match="conflicts with this branch"):
        queue.wait(tmp_path, mine, timeout=0, sleep=lambda s: None,
                   check=lambda: calls.append(1) or ("main abc conflicts with this branch" if len(calls) > 2 else None))
    assert len(calls) == 3, "no time limit: it waited until the check spoke"


def test_a_ticket_tested_on_the_current_main_passes_an_earlier_stale_waiting_one(tmp_path, monkeypatch):
    """2026-10-30..31: turning a stale ticket first made the fresh one behind it re-run FULL (~984 min/day)."""
    monkeypatch.setattr(queue, "current_main", lambda qdir: "m")
    older = queue.take(tmp_path, "feat/older")
    mine = queue.take(tmp_path, "feat/mine")
    queue.set_status(mine, "waiting", tested="m", waiting_since=time.time())

    def blocked_by(status="waiting", tested="old", since=0.0, **extra) -> bool:
        queue.set_status(older, status, tested=tested, waiting_since=time.time() - since, **extra)
        return [r["branch"] for r in queue.blockers(tmp_path, mine)] == ["feat/older"]

    assert not blocked_by(), "stale and young: passed"
    assert blocked_by(tested="m"), "both fresh: order holds"
    assert blocked_by(since=queue.PASS_CAP_S + 1), "waited past the cap: order holds"
    assert blocked_by(status="turn"), "a turn is never cut short"
    queue.set_status(mine, "waiting", tested="x", waiting_since=time.time())
    assert blocked_by(), "only a ticket tested on the current main passes"
    queue.set_status(mine, "waiting", tested="m", waiting_since=time.time())
    assert blocked_by(urgent="the user's words"), "urgent is never passed (last: the field stays)"


def test_a_waiting_member_never_blocks_the_leader_that_carries_it(tmp_path):
    """2026-10-31: a member that had prepared on its own waited for its leader, and the leader for it (earlier and
    waiting); three such pairs stopped main for 2 h 15 min."""
    member = queue.take(tmp_path, "land/docs/member", status="waiting")
    leader = queue.take(tmp_path, "land/feat/leader", status="waiting")
    queue.set_status(leader, "waiting", batch=["land/docs/member"])
    assert queue.blockers(tmp_path, leader) == [], "the leader turns and lands its member"
    assert [r["branch"] for r in queue.blockers(tmp_path, member)] == ["land/feat/leader"]
    other = queue.take(tmp_path, "land/fix/other", status="waiting")
    assert [r["branch"] for r in queue.blockers(tmp_path, other)] == ["land/feat/leader"], "a carried member: no one"
    queue.set_status(leader, "preparing", batch=["land/docs/member"])
    assert queue.blockers(tmp_path, other) == [], "behind a leader still preparing, its waiting member holds no one"


def test_a_full_queue_refuses_an_ordinary_ticket_but_not_an_urgent_or_adopted_one(tmp_path, monkeypatch):
    """2026-10-31: 34 tickets at ~2 landings/h meant ~15 h of waiting; past CAP a landing is refused at once."""
    monkeypatch.setattr(queue, "CAP", 2)
    monkeypatch.setattr(queue, "queue_dir", lambda wt: tmp_path)
    monkeypatch.setattr(queue, "_held", [])
    first = queue.take(tmp_path, "feat/a")
    assert queue.full(tmp_path) is None
    queue.take(tmp_path, "feat/b")
    assert "landing queue full (2/2" in queue.full(tmp_path)
    with pytest.raises(queue.QueueError, match="queue full"):
        queue.enter(tmp_path, "feat/c")
    _, urgent = queue.enter(tmp_path, "feat/u", urgent="the user's words")
    assert urgent.exists()
    monkeypatch.setenv(queue.TICKET_ENV, str(first))
    _, adopted = queue.enter(tmp_path, "feat/a")
    assert adopted == first, "a relaunched lander keeps its own ticket even when the queue is full"


def test_a_held_ticket_stays_fresh_while_its_process_lives(tmp_path, monkeypatch):
    """2026-11-01: a pretest past STALE_AFTER let others reclaim a live landing's ticket."""
    import time as _t
    monkeypatch.setattr(queue, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(queue, "_alive", [])
    ticket = queue.take(tmp_path, "feat/long")
    old = _t.time() - 4 * 3600
    import os as _os
    _os.utime(ticket, (old, old))
    monkeypatch.setattr(queue, "_held", [ticket])
    queue._keepalive()
    _t.sleep(0.3)
    assert _t.time() - ticket.stat().st_mtime < 60


def test_expired_flags_tickets_past_age_limits_and_skips_self(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "pid_alive", lambda pid: True)
    now = 100_000.0
    other = queue.take(tmp_path, "feat/old")
    info = json.loads(other.read_text())
    info["pid"] = 424242
    info["start"] = now - (queue.MAX_AGE_S + 10)
    other.write_text(json.dumps(info))
    full_wait = queue.take(tmp_path, "feat/full")
    finfo = json.loads(full_wait.read_text())
    finfo.update(pid=424243, tier="full", start=now - (queue.MAX_AGE_S + 10))
    full_wait.write_text(json.dumps(finfo))
    mine = queue.take(tmp_path, "feat/self")
    minfo = json.loads(mine.read_text())
    minfo["start"] = now - (queue.FULL_MAX_AGE_S + 10)
    mine.write_text(json.dumps(minfo))
    assert [r["branch"] for r in queue.expired(tmp_path, now)] == ["feat/old"]
    finfo["start"] = now - (queue.FULL_MAX_AGE_S + 10)
    full_wait.write_text(json.dumps(finfo))
    assert [r["branch"] for r in queue.expired(tmp_path, now)] == ["feat/old", "feat/full"]


def test_a_rollup_with_a_test_record_gets_the_six_hour_window(tmp_path, monkeypatch):
    """D-889 35: 224327 was killed 4 h in, after its FULL passed."""
    monkeypatch.setattr(queue, "pid_alive", lambda pid: True)
    now = 100_000.0
    rollup = "land/fix/land-rollup-20261117000000-20261117000000"
    for n, extra in enumerate(({}, {"tested": "abc"}, {"tier": "full_done"})):
        ticket = queue.take(tmp_path, f"{rollup}-{n}")
        info = json.loads(ticket.read_text())
        info.update(pid=424250 + n, start=now - (queue.MAX_AGE_S + 10), **extra)
        ticket.write_text(json.dumps(info))
    assert [r.get("tested") or r.get("tier") for r in queue.expired(tmp_path, now)] == [None]


def test_lane_has_its_own_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "CAP", 2)
    monkeypatch.setattr(queue, "LANE_CAP", 1)
    queue.take(tmp_path, "feat/a"), queue.take(tmp_path, "feat/b")
    assert "landing queue full (2/2" in queue.full(tmp_path)
    assert queue.full(tmp_path, queue.LANE) is None  # ordinary tickets do not fill the lane
    queue.take(tmp_path, "feat/learn", lane=queue.LANE)
    assert "learning lane full (1/1" in queue.full(tmp_path, queue.LANE)


def test_lane_ticket_passes_waiting_tickets_but_never_a_turn_or_urgent(tmp_path):
    turn = queue.take(tmp_path, "feat/turn", status="turn")
    waiting = queue.take(tmp_path, "feat/wait", status="waiting")
    urgent = queue.take(tmp_path, "feat/urgent", status="waiting", urgent="user: now")
    lane = queue.take(tmp_path, "feat/learn", status="waiting", lane=queue.LANE)
    assert [r["branch"] for r in queue.blockers(tmp_path, lane)] == ["feat/turn", "feat/urgent"]
    urgent.unlink(), turn.unlink()
    assert queue.blockers(tmp_path, lane) == []
    assert queue.blockers(tmp_path, waiting) == []  # a later lane ticket never holds an earlier ordinary one
    plain = queue.take(tmp_path, "feat/plain", status="waiting")
    assert [r["branch"] for r in queue.blockers(tmp_path, plain)] == ["feat/wait", "feat/learn"]


def test_lane_of_reads_the_changed_paths(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("switch", "-q", "-c", "feat/x")
    (tmp_path / "learning").mkdir()
    (tmp_path / "learning" / "a.py").write_text("x = 1\n")
    git("add", "learning/a.py")
    git("commit", "-q", "-m", "learning only")
    assert queue.lane_of(tmp_path) == queue.LANE
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "b.py").write_text("y = 2\n")
    git("add", "tools/b.py")
    git("commit", "-q", "-m", "mixed")
    assert queue.lane_of(tmp_path) == ""
    assert queue.lane_of(tmp_path, "main") == ""  # nothing changed: not a lane landing


def test_tooling_lane_covers_only_land_tool_paths_and_has_its_own_cap(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       check=True, capture_output=True)

    def add(*rels):
        for rel in rels:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x = 1\n")
        git("add", *rels)
        git("commit", "-q", "-m", "c")
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("switch", "-q", "-c", "feat/x")
    add("tools/land_queue.py", "test/test_land_queue.py")
    assert queue.lane_of(tmp_path) == "tooling"
    add("tools/remote/x.py")
    assert queue.lane_of(tmp_path) == ""
    monkeypatch.setattr(queue, "TOOLING_CAP", 2)
    queue.take(tmp_path / "q", "feat/a", lane="tooling")
    assert queue.full(tmp_path / "q", "tooling") is None
    queue.take(tmp_path / "q", "feat/b", lane="tooling")
    assert "tooling lane full (2/2" in queue.full(tmp_path / "q", "tooling")
    assert queue.full(tmp_path / "q", queue.LANE) is None  # lanes count apart


def _reserver(qdir: Path, cap: int = 12) -> subprocess.Popen:
    """A live process that reserves once, prints ok/full and then stays alive (its marker only counts while it lives)."""
    code = ("import sys\nsys.path.insert(0, sys.argv[2])\nimport land_queue as q\nfrom pathlib import Path\n"
            "try:\n    q.reserve(Path(sys.argv[1]), 'feat/x')\n    print('ok', flush=True)\n"
            "except q.QueueError:\n    print('full', flush=True)\nsys.stdin.read()\n")
    return subprocess.Popen([sys.executable, "-c", code, str(qdir), str(ROOT / "tools")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env={**os.environ, "ROSY_LAND_QUEUE_CAP": str(cap)})


def test_twenty_processes_reserving_at_cap_twelve_get_exactly_twelve_markers(tmp_path):
    """11-17/18: 13/12 in 37 stop events: every supervisor passed full(), then each entered."""
    procs = [_reserver(tmp_path) for _ in range(20)]
    try:
        answers = [p.stdout.readline().strip() for p in procs]
    finally:
        for p in procs:
            p.stdin.close()
            p.wait(timeout=30)
    assert answers.count("ok") == 12 and answers.count("full") == 8
    assert len(list(tmp_path.glob("*.reserve"))) == 12


def test_a_dead_reservation_is_reclaimed_and_the_own_one_never_blocks_enter(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "CAP", 1)
    monkeypatch.setattr(queue, "queue_dir", lambda wt: tmp_path)
    monkeypatch.setattr(queue, "_held", [])
    dead = tmp_path / "00000000000000000001-1.reserve"
    dead.write_text(json.dumps({"pid": gone_pid(), "host": socket.gethostname(), "start": time.time(), "branch": "x"}))
    old = tmp_path / "00000000000000000002-1.reserve"
    old.write_text(json.dumps({"pid": os.getpid(), "host": "elsewhere", "start": time.time() - queue.RESERVE_TTL - 1}))
    os.utime(old, (time.time() - queue.RESERVE_TTL - 1,) * 2)  # expiry follows the mtime (_keepalive refreshes it)
    marker = queue.reserve(tmp_path, "feat/a")
    assert not dead.exists() and not old.exists() and marker.exists()
    other = tmp_path / f"{time.time_ns():020d}-{os.getpid()}.reserve"
    marker.rename(other)  # keep it as another process's marker: same pid is excluded, so fake a foreign pid
    other.write_text(json.dumps({"pid": os.getppid(), "host": socket.gethostname(), "start": time.time(), "branch": "x"}))
    with pytest.raises(queue.QueueError, match="landing queue full"):
        queue.reserve(tmp_path, "feat/b")
    other.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "start": time.time(), "branch": "x"}))
    _, mine = queue.enter(tmp_path, "feat/a")  # its own marker never blocks its enter
    assert mine.exists()
    queue.unreserve(other)
    queue.unreserve(None)


def test_a_head_tested_over_an_older_main_is_refreshed_outside_the_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "current_main", lambda qdir: "m2")
    mine = queue.take(tmp_path, "feat/mine")
    nxt = queue.take(tmp_path, "feat/next")
    queue.set_status(nxt, "waiting", tested="m2", waiting_since=time.time())
    seen = []

    def refresh(tested_after):
        def run():
            seen.append((json.loads(mine.read_text())["status"], queue.blockers(tmp_path, nxt)))
            return tested_after
        return run

    monkeypatch.setattr(queue, "REFRESH", refresh("m2"))
    assert queue.wait(tmp_path, mine, 0, tested="m1", sleep=lambda s: None) is None
    assert seen == [("preparing", [])], "preparing while it refreshes: it holds no one, and the next fresh ticket may pass"
    assert json.loads(mine.read_text())["status"] == "turn" and json.loads(mine.read_text())["tested"] == "m2"
    seen.clear()
    queue.set_status(mine, "waiting", tested="m2")
    assert queue.wait(tmp_path, mine, 0, tested="m2", sleep=lambda s: None) is None and seen == [], "fresh: turn at once"
    monkeypatch.setattr(queue, "REFRESH", refresh(None))  # a refresh that cannot catch up: two tries, then the turn
    assert queue.wait(tmp_path, mine, 0, tested="m1", sleep=lambda s: None) is None and len(seen) == queue.REFRESHES == 2


def test_nt_lock_waits_past_the_msvcrt_ten_second_give_up(monkeypatch):
    import errno
    calls = []

    def locking(fd, mode, n):
        calls.append(mode)
        if len(calls) < 3:
            raise OSError(errno.EDEADLK, "Resource deadlock avoided")

    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(LK_NBLCK=2, locking=locking))
    monkeypatch.setattr(queue.time, "sleep", lambda s: None)
    queue.nt_lock(5, True)
    assert calls == [2, 2, 2]


def test_nt_lock_without_wait_fails_at_once(monkeypatch):
    import errno

    def locking(fd, mode, n):
        raise OSError(errno.EACCES, "locked")

    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(LK_NBLCK=2, locking=locking))
    with pytest.raises(OSError):
        queue.nt_lock(5, False)


def test_keepalive_refreshes_the_reservation_marker_so_a_long_admit_is_not_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "_marked", [])
    marker = queue.reserve(tmp_path, "feat/a")
    os.utime(marker, (time.time() - queue.RESERVE_TTL - 5,) * 2)  # admit work ran past the TTL
    queue._beat()  # what the keepalive thread does every KEEPALIVE_S
    assert time.time() - marker.stat().st_mtime < 60
    assert queue._markers(tmp_path) and marker.exists()
    queue.unreserve(marker)


def test_a_child_adopts_the_reservation_its_supervisor_made_and_enter_is_not_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "CAP", 1)
    monkeypatch.setattr(queue, "queue_dir", lambda wt: tmp_path)
    monkeypatch.setattr(queue, "_held", [])
    monkeypatch.setattr(queue, "_marked", [])
    marker = tmp_path / f"{time.time_ns():020d}-1.reserve"  # the supervisor's: another pid, same host
    marker.write_text(json.dumps({"pid": os.getppid(), "host": socket.gethostname(), "start": time.time(), "branch": "x"}))
    assert queue.full(tmp_path) is not None  # without the hand-over the child finds the queue full
    assert queue.adopt_reserved(str(marker)) == marker
    _, ticket = queue.enter(tmp_path, "feat/a")
    assert ticket.exists()
    queue.unreserve(marker)
    assert queue.adopt_reserved(str(marker)) is None and queue.adopt_reserved("") is None  # consumed: reserve() as usual
