"""tools/land_tick.py: the unattended backlog pass (11-14: 160 main-red ids open, ~20 landings stopped for hours)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import pytest  # noqa: E402

import land_queue  # noqa: E402
import land_tick  # noqa: E402
import memory_history  # noqa: E402


def test_recheck_runs_once_per_main_and_only_with_open_ids(tmp_path, monkeypatch):
    runs = []
    main = ["a" * 40]
    opened = {"pkg/test/test_a.py::test_a": {}}
    monkeypatch.setattr(land_tick.land_async, "git", lambda repo, *a: main[0])
    monkeypatch.setattr(land_tick.land_mainred, "state", lambda repo: opened)
    monkeypatch.setattr(land_tick, "_run", lambda repo, *argv, timeout: runs.append(argv) or "closed 1")
    assert land_tick.recheck(tmp_path, tmp_path) == "closed 1"
    assert land_tick.recheck(tmp_path, tmp_path) == "nothing to recheck"  # same main: not again
    main[0] = "b" * 40
    assert land_tick.recheck(tmp_path, tmp_path) == "closed 1"  # main moved: the open ids run on it
    opened.clear()
    main[0] = "c" * 40
    assert land_tick.recheck(tmp_path, tmp_path) == "nothing to recheck"
    assert runs == [("tools/land_mainred.py", "recheck")] * 2


def test_report_counts_the_backlog_and_names_the_oldest_unowned_reds(tmp_path, monkeypatch):
    place = tmp_path / "rosy-land-wt"
    place.mkdir()
    (place / "land-a-1.stopped").write_text("x")
    (place / "land-b-1.stopped").write_text("x")
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: place)
    monkeypatch.setattr(land_tick.land_async, "main_red_stop", lambda place, name: "text" if name == "land-a-1" else None)
    monkeypatch.setattr(land_tick.land_async, "git", lambda repo, *a: "8b65ceaa0f")
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "ahead", lambda q, t: [{"status": "pending"}, {"status": "preparing"}])
    now = 10_000.0
    monkeypatch.setattr(land_tick.land_mainred, "state", lambda repo: {
        "old": {"since": now - 3600, "owner": None}, "owned": {"since": now - 3600, "owner": "robot-25"},
        "new": {"since": now - 60, "owner": None}})
    lines = land_tick.report(tmp_path, tmp_path, now=now)
    text = "\n".join(lines)
    assert "pending 1, preparing 1" in text
    assert "stopped: 2 (1 on MAIN-RED, wait for main; 1 for owners)" in text
    assert "auto-resumed 24h: queue full 0, watchdog 0, urgent 0" in text
    assert "main-red open: 3, 1 unowned over 30 min (ALERT)" in text
    assert (tmp_path / land_tick.REPORT).read_text(encoding="utf-8") == text + "\n"


def test_cleanup_prunes_lossless_worktrees_then_idle_ones_keeping_their_work(tmp_path, monkeypatch):
    """11-14: 41 worktrees against the 15 cap, 7 clean and idle 7-14 h, removed by hand."""
    calls = []
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "expired", lambda qdir: [])
    monkeypatch.setattr(land_tick.land_gc, "plan", lambda repo, now, days: [("remove", "x", None, [])])
    monkeypatch.setattr(land_tick.land_gc, "apply", lambda repo, rows: [])
    monkeypatch.setattr(land_tick.worktrees, "prune", lambda repo, **k: calls.append(k) or 2)
    assert land_tick.cleanup(tmp_path).endswith("worktrees removed 4")
    assert calls[0]["apply"] and not calls[0].get("snapshot")  # landed and orphan ones: nothing to keep
    assert calls[1]["snapshot"] and calls[1]["everyone"] and calls[1]["idle_hours"] == land_tick.WORKTREE_IDLE_H


def test_cleanup_reaps_expired_tickets_and_tightens_idle_hours_when_over_cap(tmp_path, monkeypatch):
    import json
    import land_rollup  # noqa: E402
    wt_root = tmp_path / ".worktrees"
    for i in range(land_tick.worktrees.CAP + 1):
        (wt_root / f"wt-{i}").mkdir(parents=True)
    holder = tmp_path / "holder"
    (holder / "land-fix-z").mkdir(parents=True)
    tpath = tmp_path / "01-99.json"
    tpath.write_text(json.dumps({"pid": 99}))
    stopped, remote = [], []
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: holder)
    monkeypatch.setattr(land_tick.land_queue, "expired", lambda qdir: [
        {"pid": 99, "age": 15000.0, "branch": "land/fix/z", "worktree": str(holder / "land-fix-z"), "path": tpath}])
    monkeypatch.setattr(land_rollup, "stop_remote", lambda h, rows: remote.append(len(rows)))
    monkeypatch.setattr(land_rollup, "stop", lambda pid: stopped.append(pid))
    monkeypatch.setattr(land_tick.land_gc, "plan", lambda repo, now, days: [])
    monkeypatch.setattr(land_tick.land_gc, "apply", lambda repo, rows: [])
    calls = []
    monkeypatch.setattr(land_tick.worktrees, "prune", lambda repo, **k: calls.append(k) or 0)
    out = land_tick.cleanup(tmp_path)
    assert "reaped 1 expired" in out and remote == [1] and stopped == [99] and not tpath.exists()
    assert (holder / "land-fix-z.stopped").read_text().startswith("STOP: EXPIRED")
    assert calls[1]["idle_hours"] == min(land_tick.WORKTREE_IDLE_H, 4)


def test_resume_counts_only_landings_it_relaunched(tmp_path, monkeypatch):
    def resume(repo, name, args, detach, wait):
        if name == "land-held-1":
            raise SystemExit("held by live ticket")

    monkeypatch.setattr(land_tick.land_async, "orphans", lambda repo: ["land-held-1", "land-ok-1"])
    monkeypatch.setattr(land_tick.land_async, "resume", resume)
    assert land_tick.resume(tmp_path) == "resumed 1 of 2: land-ok-1"


def test_requeue_relaunches_one_queue_full_stop_once(tmp_path, monkeypatch):
    """11-18: landings stopped on a full queue sat for days; an owner's own note or another STOP is left alone."""
    place, seen = tmp_path / "holder", []
    full, failed = "[land] STOP: landing queue full (12/12", "[land] STOP: NEW failure in test"
    for name, note, last in (("land-fix-a-20261114000000", "land.py exit 1; read", full),
                             ("land-fix-b-20261114000000", "stopped by owner: do not resume", full),
                             ("land-fix-c-20261114000000", "land.py exit 1; read", failed)):
        (place / name).mkdir(parents=True)
        (place / (name + ".stopped")).write_text(note, encoding="utf-8")
        (place / (name + ".log")).write_text(full + "\n" + last + "\n", encoding="utf-8")
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "full", lambda q: None)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: place)
    monkeypatch.setattr(land_tick.land_async, "git", lambda repo, *a: "abc")
    monkeypatch.setattr(land_tick.land_async, "resume", lambda repo, name, a, d, wait: seen.append(name))
    assert land_tick.requeue(tmp_path) == "requeued land-fix-a-20261114000000 (queue full)"
    assert land_tick.requeue(tmp_path) == "nothing to requeue" and seen == ["land-fix-a-20261114000000"]
    monkeypatch.setattr(land_tick.land_queue, "full", lambda q: "landing queue full (12/12 tickets)")
    assert land_tick.requeue(tmp_path) == "queue full"


def _stopped(place: Path, name: str, note: str, log: str) -> None:
    (place / name).mkdir(parents=True, exist_ok=True)
    (place / (name + ".stopped")).write_text(note, encoding="utf-8")
    (place / (name + ".log")).write_text(log + "\n", encoding="utf-8")


def _requeue_env(tmp_path, monkeypatch, place, seen, holder=None):
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "full", lambda q: None)
    monkeypatch.setattr(land_tick.land_queue, "urgent_holder", lambda q: holder)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: place)
    monkeypatch.setattr(land_tick.land_async, "git", lambda repo, *a: "abc")
    monkeypatch.setattr(land_tick.land_async, "resume", lambda repo, name, a, d, wait: seen.append(name))


def test_requeue_relaunches_a_watchdog_stop_once(tmp_path, monkeypatch):
    """11-20: watchdog stops (exit 3, reason only in the events) sat 9.5 h of 12 h; an owner's note is left alone."""
    place, seen = tmp_path / "rosy-land-wt", []
    dog, owned = "land-fix-dog-20261119000000", "land-fix-own-20261119000000"
    _stopped(place, dog, f"land.py exit 3; read {dog}.log", "[remote-pytest] pytest ...")
    _stopped(place, owned, "stopped by owner: hangs on purpose", "[remote-pytest] pytest ...")
    (tmp_path / land_tick.land_events.EVENTS).write_text("".join(json.dumps(
        {"t": 1.0, "event": "stop", "pid": 1, "branch": b, "reason": "watchdog: no progress for 31 min"}) + "\n"
        for b in ("land/fix/dog-20261119000000", "land/fix/own-20261119000000")), encoding="utf-8")
    _requeue_env(tmp_path, monkeypatch, place, seen)
    assert land_tick.requeue(tmp_path) == f"requeued {dog} (watchdog)"
    assert land_tick.requeue(tmp_path) == "nothing to requeue" and seen == [dog]  # once per stop
    later = time.time() + 60  # it hung again after that relaunch: its owner's to read, not a loop
    os.utime(place / (dog + ".stopped"), (later, later))
    assert land_tick.requeue(tmp_path) == "nothing to requeue" and seen == [dog]
    assert land_tick.resumed(place, time.time()) == ["watchdog"]


def test_requeue_relaunches_a_refused_urgent_once_no_urgent_ticket_is_live(tmp_path, monkeypatch):
    """11-20: --urgent refusals sat 9.7 h; the relaunch keeps the user's --urgent in args.json."""
    place, seen = tmp_path / "rosy-land-wt", []
    name = "land-fix-hot-20261119000000"
    _stopped(place, name, f"land.py exit 1; read {name}.log",
             "[land] STOP: --urgent refused: land/fix/x (preparing, pid 1) is already urgent (now); one at a time")
    args = place / (name + ".args.json")
    args.write_text(json.dumps(["--tests", "auto", "--urgent", "the user's words"]), encoding="utf-8")
    _requeue_env(tmp_path, monkeypatch, place, seen, holder={"ticket": "0001", "urgent": "now"})
    assert land_tick.requeue(tmp_path) == "nothing to requeue" and not seen  # the urgent lane is still taken
    monkeypatch.setattr(land_tick.land_queue, "urgent_holder", lambda q: None)
    assert land_tick.requeue(tmp_path) == f"requeued {name} (urgent)" and seen == [name]
    assert land_tick.requeue(tmp_path) == "nothing to requeue" and seen == [name]
    assert "--urgent" in json.loads(args.read_text(encoding="utf-8"))
    assert land_tick.no_verdict("NEW failure in test/test_a.py", tmp_path) is None


def test_warm_runs_only_when_queue_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "ahead", lambda q, t: [{"status": "pending"}])
    assert land_tick.warm(tmp_path) == "queue active; skipped"
    monkeypatch.setattr(land_tick.land_queue, "ahead", lambda q, t: [])
    monkeypatch.setattr(land_tick.land_cache, "warm_main", lambda repo, limit: (3, 4))
    assert land_tick.warm(tmp_path) == "warmed 3 of 4"


def test_cleanup_trims_the_pytest_memory_history_past_its_cap(tmp_path, monkeypatch):
    """2026-11-17: rosy-pytest-memory.jsonl only grew; every tick keeps it under memory_history.MAX_ROWS."""
    small = tmp_path / "small.jsonl"
    small.write_text("".join(f'{{"key": "{i}"}}\n' for i in range(21)), encoding="utf-8")
    assert memory_history.trim(small, max_rows=20, keep_rows=15) == 6  # past max_rows: the last keep_rows stay
    assert memory_history.trim(small, max_rows=20, keep_rows=15) == 0  # at the cap: untouched
    assert small.read_text(encoding="utf-8").splitlines()[-1] == '{"key": "20"}'
    assert not small.with_suffix(".jsonl.tmp").exists()  # the rewrite was atomic
    history = tmp_path / memory_history.FILE
    history.write_text("".join(f'{{"key": "{i}"}}\n' for i in range(memory_history.MAX_ROWS + 1)),
                       encoding="utf-8")
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_queue, "expired", lambda qdir: [])
    monkeypatch.setattr(land_tick.land_gc, "plan", lambda repo, now, days: [])
    monkeypatch.setattr(land_tick.land_gc, "apply", lambda repo, rows: [])
    monkeypatch.setattr(land_tick.worktrees, "prune", lambda repo, **k: 0)
    monkeypatch.setattr(memory_history, "path", lambda repo: history)
    land_tick.cleanup(tmp_path)
    rows = history.read_text(encoding="utf-8").splitlines()
    assert len(rows) == memory_history.KEEP_ROWS and rows[-1] == f'{{"key": "{memory_history.MAX_ROWS}"}}'


def test_cleanup_keeps_an_old_ticket_whose_landing_is_still_logging(tmp_path, monkeypatch):
    """11-17: land_queue.expired counts age from queueing; the tick killed a rollup and a landing mid-test at 4 h."""
    import json
    import land_rollup  # noqa: E402
    holder = tmp_path / "holder"
    (holder / "land-fix-z").mkdir(parents=True)
    (holder / "land-fix-z.log").write_text("[remote-pytest] pytest ..." + chr(10))
    tpath = tmp_path / "01-99.json"
    tpath.write_text(json.dumps({"pid": 99}))
    stopped = []
    monkeypatch.setattr(land_tick.land_queue, "queue_dir", lambda repo: tmp_path)
    monkeypatch.setattr(land_tick.land_async, "holder", lambda repo: holder)
    monkeypatch.setattr(land_tick.land_queue, "expired", lambda qdir: [
        {"pid": 99, "age": 15000.0, "branch": "land/fix/z", "worktree": str(holder / "land-fix-z"), "path": tpath}])
    monkeypatch.setattr(land_rollup, "stop_remote", lambda h, rows: None)
    monkeypatch.setattr(land_rollup, "stop", lambda pid: stopped.append(pid))
    monkeypatch.setattr(land_tick.land_gc, "plan", lambda repo, now, days: [])
    monkeypatch.setattr(land_tick.land_gc, "apply", lambda repo, rows: [])
    monkeypatch.setattr(land_tick.worktrees, "prune", lambda repo, **k: 0)
    assert "reaped 0 expired" in land_tick.cleanup(tmp_path) and stopped == [] and tpath.exists()
    old = time.time() - land_tick.ACTIVE_LOG_S - 60
    os.utime(holder / "land-fix-z.log", (old, old))  # silent for 30 min: stuck, reaped as before
    assert "reaped 1 expired" in land_tick.cleanup(tmp_path) and stopped == [99]


def test_metrics_line_is_written_once_per_day(tmp_path):
    """D-889 36: arrivals, landed, lead p50/p90, turn-deadline releases and rollups, once per 24 h."""
    import json
    now, rollup = 1_000_000.0, "land/fix/land-rollup-20261117000000-20261117000001"
    row = lambda t, event, pid, **kw: json.dumps({"t": t, "event": event, "pid": pid, **kw})  # noqa: E731
    (tmp_path / land_tick.land_events.EVENTS).write_text("\n".join([
        row(now - 7200, "queue", 1, branch="a"), row(now - 3600, "landed", 1, branch="a"),
        row(now - 5400, "queue", 2, branch=rollup), row(now - 1800, "landed", 2, branch=rollup),
        row(now - 100, "released", 3, branch="b", note="turn deadline"),
        row(now - 90000, "queue", 9, branch="old")]) + "\n", encoding="utf-8")
    line = land_tick.metrics(tmp_path, now)
    assert line == ("[metrics] arrivals 0.08/h, landed 0.08/h, lead p50/p90 60/60 min, turn-deadline releases 1/24h,"
                    " rollups built 1 landed 1")
    assert land_tick.metrics(tmp_path, now + 3600) is None  # already written today
    assert json.loads((tmp_path / land_tick.METRICS_LOG).read_text().splitlines()[-1])["deadline_releases"] == 1
    assert land_tick.metrics(tmp_path, now + 25 * 3600)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def pending_repo(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    _git(work, "checkout", "-q", "-b", "feat/x")
    return work


def _tick(monkeypatch, launched, full=None, holders=()):
    monkeypatch.setattr(land_tick.land_queue, "full", lambda qdir, lane="": full)
    monkeypatch.setattr(land_tick.land_async, "holders", lambda pending_repo, branch: list(holders))
    monkeypatch.setattr(land_tick.land_async, "detach", lambda argv, log, cwd=None: launched.append(argv))


def _kept(pending_repo):
    return sorted(land_queue.queue_dir(pending_repo).glob("pending-*.json"))


def test_not_queued_request_leaves_one_pending_request(pending_repo):
    said = land_queue.keep_pending(pending_repo, ["--tests", "auto"])
    land_queue.keep_pending(pending_repo, ["--tests", "auto"])  # the same branch again supersedes, not duplicates
    (path,) = _kept(pending_repo)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert str(path) in said
    assert (row["branch"], row["args"], row["cwd"]) == ("feat/x", ["--tests", "auto"], str(pending_repo))
    assert row["ref"] == _git(pending_repo, "rev-parse", "feat/x")


def test_pending_request_is_launched_once_when_the_queue_has_room(pending_repo, monkeypatch):
    land_queue.keep_pending(pending_repo, ["--tests", "auto"])
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(pending_repo) == "relaunched pending feat/x"
    assert len(launched) == 1 and launched[0][-4:] == ["--branch", "feat/x", "--tests", "auto"][-4:]
    assert not _kept(pending_repo)


def test_pending_request_is_kept_while_the_queue_is_full(pending_repo, monkeypatch):
    land_queue.keep_pending(pending_repo, [])
    launched = []
    _tick(monkeypatch, launched, full="landing queue full (12/12 tickets)")
    assert land_tick.requeue(pending_repo) == "queue full"
    assert not launched and len(_kept(pending_repo)) == 1


def test_pending_request_is_dropped_when_the_branch_already_lands(pending_repo, monkeypatch):
    land_queue.keep_pending(pending_repo, [])
    launched = []
    _tick(monkeypatch, launched, holders=[{"ticket": "0001"}])
    land_tick.requeue(pending_repo)
    assert not launched and not _kept(pending_repo)


def test_pending_request_is_dropped_when_the_branch_moved_past_it(pending_repo, monkeypatch):
    land_queue.keep_pending(pending_repo, [])
    _git(pending_repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "newer")
    launched = []
    _tick(monkeypatch, launched)
    land_tick.requeue(pending_repo)
    assert not launched and not _kept(pending_repo)


def test_pending_requests_are_requeued_oldest_first_one_per_tick(pending_repo, monkeypatch):
    _git(pending_repo, "checkout", "-q", "-b", "feat/y")
    land_queue.keep_pending(pending_repo, [])
    time.sleep(0.01)  # Windows time.time() resolution: keep the start stamps apart (else names order feat/x first)
    _git(pending_repo, "checkout", "-q", "feat/x")
    land_queue.keep_pending(pending_repo, [])
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(pending_repo) == "relaunched pending feat/y"  # kept earlier, though y sorts after x
    assert len(launched) == 1 and launched[0][-2:] == ["--branch", "feat/y"]
    assert land_tick.requeue(pending_repo) == "relaunched pending feat/x"  # at most one launch per tick
    assert not _kept(pending_repo)


def test_pending_request_file_that_is_unreadable_is_cleaned(pending_repo, monkeypatch):
    land_queue.keep_pending(pending_repo, [])
    path = _kept(pending_repo)[0]
    path.write_text("{oops", encoding="utf-8")
    launched = []
    _tick(monkeypatch, launched)
    assert land_tick.requeue(pending_repo) == "nothing to requeue" and not path.exists() and not launched
