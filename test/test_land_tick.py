"""tools/land_tick.py: the unattended backlog pass (11-14: 160 main-red ids open, ~20 landings stopped for hours)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

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
