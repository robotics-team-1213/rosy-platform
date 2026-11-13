"""tools/land_tick.py: the unattended backlog pass (11-14: 160 main-red ids open, ~20 landings stopped for hours)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_tick  # noqa: E402


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
    monkeypatch.setattr(land_tick.land_gc, "plan", lambda repo, now, days: [("remove", "x", None, [])])
    monkeypatch.setattr(land_tick.land_gc, "apply", lambda repo, rows: [])
    monkeypatch.setattr(land_tick.worktrees, "prune", lambda repo, **k: calls.append(k) or 2)
    assert land_tick.cleanup(tmp_path).endswith("worktrees removed 4")
    assert calls[0]["apply"] and not calls[0].get("snapshot")  # landed and orphan ones: nothing to keep
    assert calls[1]["snapshot"] and calls[1]["everyone"] and calls[1]["idle_hours"] == land_tick.WORKTREE_IDLE_H
