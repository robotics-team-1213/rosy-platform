"""land_watchdog: a landing with no progress stops itself, with stacks on file (2026-10-28, pid 100908 sat 76 min)."""

from __future__ import annotations

import json
import sys
import threading

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import land_events  # noqa: E402
import land_queue  # noqa: E402
import land_watchdog  # noqa: E402
import remote_job  # noqa: E402


def _run(tmp_path, monkeypatch, beats, limit=90 * 60, step=1800):
    """A fake clock: ``step`` s per check; ``beats`` says at which checks progress happens."""
    now, checks, exited = [0.0], [0], threading.Event()
    monkeypatch.setattr(land_events, "LAST", [0.0])
    monkeypatch.setattr(remote_job, "LAST_POLL", 0.0)
    monkeypatch.setitem(land_events._where, "path", tmp_path / land_events.EVENTS)
    monkeypatch.setitem(land_events._where, "branch", "feat/x")
    ticket = tmp_path / "q" / "1.json"
    ticket.parent.mkdir()
    ticket.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(land_queue, "_held", [ticket])

    def sleep(_):
        checks[0] += 1
        now[0] += step
        if checks[0] in beats:
            remote_job.LAST_POLL = now[0]  # a remote job still being polled
        if checks[0] > 12:
            exited.set()
            raise SystemExit  # ends the thread when the watchdog never fired

    code = []
    thread = land_watchdog.start(tmp_path / "logs", land_events, land_queue, remote_job, limit=limit,
                                 clock=lambda: now[0], sleep=sleep, exit_=lambda c: code.append(c) or exited.set())
    assert exited.wait(10)
    thread.join(10)
    return code, ticket, checks[0]


def test_no_progress_for_the_limit_dumps_stacks_records_a_stop_and_leaves_the_ticket(tmp_path, monkeypatch):
    code, ticket, checks = _run(tmp_path, monkeypatch, beats=())
    assert code == [3] and checks == 4, "past 90 min idle (4 x 30 min), not before"
    dump = next((tmp_path / "logs").glob("watchdog-*.txt")).read_text(encoding="utf-8")
    assert "land_watchdog" in dump and "Thread" in dump  # every thread's stack, so the next hang shows where
    (stop,) = [json.loads(line) for line in (tmp_path / land_events.EVENTS).read_text(encoding="utf-8").splitlines()]
    assert stop["event"] == "stop" and stop["reason"].startswith("watchdog: no progress for 120 min")
    assert not ticket.exists(), "the ticket goes with it, not after the 3 h stale timeout"


def test_a_polled_remote_job_or_an_event_is_progress(tmp_path, monkeypatch):
    code, ticket, _ = _run(tmp_path, monkeypatch, beats={2, 4, 6, 8, 10})  # a poll every hour: never 90 min idle
    assert code == [] and ticket.exists()


def test_the_watchdog_starts_only_from_the_command_line(monkeypatch):
    import land
    started = []
    monkeypatch.setattr(land.land_watchdog, "start", lambda *a, **k: started.append(a))
    monkeypatch.setattr(land, "land", lambda args: 0)
    monkeypatch.setattr(land.land_checks, "landed_copy", lambda *a: None)
    monkeypatch.setattr(land, "main_checkout", lambda wt: wt)
    monkeypatch.setattr(land.land_events, "bind", lambda *a: None)
    monkeypatch.setitem(land.land_events._where, "branch", "feat/x")
    monkeypatch.setattr(land, "out", lambda *a: "x")
    land.main(["--tests", "auto", "--dry-run"])
    assert not started, "a pytest process calling main() must never get a watchdog that can end it"
    monkeypatch.setattr(sys, "argv", ["land.py", "--tests", "auto", "--dry-run"])
    land.main()
    assert started


def test_a_sixty_minute_step_that_beats_does_not_fire_the_thirty_minute_limit(tmp_path, monkeypatch):
    """robot-45: lower the limit to 30 min only once long silent steps (venv setup up to 3,600 s) beat."""
    assert land_watchdog.LIMIT_S == 30 * 60
    code, _, checks = _run(tmp_path, monkeypatch, beats=set(range(1, 7)), limit=land_watchdog.LIMIT_S, step=600)
    assert code == [3] and checks == 10, "beats for 60 min keep it alive; 40 min of silence after them stops it"


def test_a_step_marks_progress_while_its_child_runs_and_keeps_run_semantics(monkeypatch):
    import subprocess
    monkeypatch.setattr(remote_job, "POLL_S", 0.05)
    monkeypatch.setattr(remote_job, "LAST_POLL", 0.0)
    seen, done = set(), threading.Event()

    def watch():
        while not done.is_set():
            seen.add(remote_job.LAST_POLL)
            done.wait(0.02)
    threading.Thread(target=watch, daemon=True).start()
    echo = [sys.executable, "-c", "import sys, time; time.sleep(0.6); sys.stdout.write(sys.stdin.read())"]
    result = remote_job.step(echo, timeout=30, input=b"venv", capture_output=True)
    done.set()
    assert (result.returncode, result.stdout) == (0, b"venv")
    assert len(seen - {0.0}) >= 3, "LAST_POLL advanced while the child ran"
    with pytest.raises(subprocess.TimeoutExpired):
        remote_job.step([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
