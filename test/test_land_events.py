"""tools/land_events.py and tools/land_stats.py: what each landing did, and the daily numbers from it."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_events  # noqa: E402
import land_stats  # noqa: E402


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


def test_daily_numbers_from_waits_turns_and_verdicts():
    t = 1_792_900_000.0
    rows = [{"t": t, "event": "turn", "pid": 1, "waited_s": 600},
            {"t": t + 300, "event": "tests", "pid": 1, "verdict": "pass"},
            {"t": t + 300, "event": "tests", "pid": 1, "verdict": "new"},
            {"t": t + 360, "event": "stop", "pid": 1},
            {"t": t + 400, "event": "turn", "pid": 2, "waited_s": 1800},
            {"t": t + 700, "event": "tests", "pid": 2, "verdict": "flaky"},
            {"t": t + 760, "event": "landed", "pid": 2},
            {"t": t + 800, "event": "prepared", "pid": 3, "seconds": 1500}]
    (day,) = land_stats.daily(rows).values()
    assert (day["landed"], day["stopped"], day["invocations"]) == (1, 1, 3)
    assert day["wait_p90_min"] == 30 and day["turn_p50_min"] in (6, 6.0)
    assert day["new_share"] == round(1 / 3, 3) and day["flaky_share"] == round(1 / 3, 3)
    assert day["prepare_p50_min"] == 25, "prepare time is apart from the queue wait"
    assert json.dumps(land_stats.daily(rows))  # --json prints it


def test_confirmed_failures_split_into_shared_host_and_branch_causes():
    """D-889 addendum 3: the new-failure share (p) caps batching; shared and host causes are tooling's to fix."""
    t = 1_792_900_000.0
    fail = lambda dt, branch, host, *ids, confirmed=True: {  # noqa: E731
        "t": t + dt, "event": "failure", "branch": branch, "host": host, "failed": list(ids), "confirmed": confirmed}
    rows = [fail(0, "a", "ai", "test/x.py::t"), fail(600, "b", "rosy", "test/x.py::t"),  # two branches: shared
            fail(0, "c", "robttt", "test/y.py::t"), fail(900, "c", "robttt", "test/y.py::t"),  # one host: host
            fail(0, "d", "ai", "test/z.py::t"),  # one branch once: branch
            fail(0, "e", "ai", "test/w.py::t", confirmed=False),  # load-flaky: not counted
            fail(land_stats.WINDOW + 1, "f", "ai", "test/z.py::t")]  # same id, far apart, other host: branch
    (day,) = land_stats.daily(rows).values()
    assert (day["failed_shared"], day["failed_host"], day["failed_branch"]) == (2, 2, 2)


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
