"""tools/land_events.py and tools/land_stats.py: what each landing did, and the daily numbers from it."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_events  # noqa: E402


def test_events_append_one_line_each_and_a_torn_line_is_skipped(tmp_path, monkeypatch):
    path = tmp_path / land_events.EVENTS
    land_events.emit("queue", ticket="x")  # not bound yet: nothing written, nothing raised
    monkeypatch.setitem(land_events._where, "path", path)
    monkeypatch.setitem(land_events._where, "branch", "feat/x")
    land_events.emit("queue", ticket="x", position=3)
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"event": "tests", "t": 1\n')  # a foreign or corrupt line; one os.write per event never tears
    land_events.emit("turn", waited_s=120)
    rows = land_events.read(path)
    assert [r["event"] for r in rows] == ["queue", "turn"] and rows[0]["branch"] == "feat/x"
    assert rows[0]["position"] == 3 and rows[1]["waited_s"] == 120


def test_queue_and_landed_carry_the_branch_apps(tmp_path, monkeypatch):
    """2026-11-19: a week of ``apps`` on queue/landed lines decides per-app parallel turns."""
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    parts = tmp_path / "tools/harness/platform_parts.yaml"
    parts.parent.mkdir(parents=True)
    parts.write_text("app_neutral: ['**/logs.md']\nroots: [{path: ops/fleet, app: site-fleet}]\n", encoding="utf-8")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    git("checkout", "-qb", "feat/x")
    for name in ("ops/fleet/a.py", "ops/fleet/logs.md", "README.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("1", encoding="utf-8")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    monkeypatch.setattr(land_events, "_where", {})
    land_events.bind(tmp_path, "feat/x")
    land_events.emit("queue", ticket="x")
    land_events.emit("turn", waited_s=1)
    land_events.landed("abc")
    rows = land_events.read(tmp_path / ".git" / land_events.EVENTS)
    assert [r.get("apps") for r in rows] == [["core", "site-fleet"], None, ["core", "site-fleet"]]


def test_a_judged_failure_leaves_its_ids_and_host_user_never_the_address(tmp_path, monkeypatch):
    import land_checks
    sys.path.insert(0, str(ROOT / "tools" / "remote"))
    import memory_history

    history, inv, sha = tmp_path / memory_history.FILE, ["test/x.py"], "ab" * 20
    memory_history.record(history, inv, "ai@" + ".".join(["100", "1", "2", "3"]), 300, sha)
    monkeypatch.setattr(memory_history, "path", lambda repo: history)
    log = tmp_path / "run-1-1.txt"
    log.write_text("FAILED test/x.py::test_a - assert 0\nFAILED test/x.py::test_b\n1 failed\n", encoding="utf-8")
    emitted = []
    monkeypatch.setattr(land_checks.land_events, "emit", lambda event, **fields: emitted.append((event, fields)))
    land_checks.failure(tmp_path, inv, log, sha, [])
    land_checks.failure(tmp_path, inv, log, "cd" * 20, ["test/x.py::test_b"])
    assert emitted[0] == ("failure", {"argv": inv, "failed": ["test/x.py::test_a", "test/x.py::test_b"], "host": "ai",
                                      "flaky": [], "confirmed": True})
    assert emitted[1][1]["host"] is None and emitted[1][1]["confirmed"] is False


