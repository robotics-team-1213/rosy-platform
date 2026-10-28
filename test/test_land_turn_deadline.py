"""A turn must release remote jobs even when no invocation has finished."""

import threading

import pytest

from test_land import cached, land, repos  # noqa: F401
from test_remote_pytest import _fake_hosts


REMOTE_RUN = land.remote_pytest.run


@pytest.mark.parametrize("hosts", [["a@1"], ["a@1", "b@2"]])
@pytest.mark.parametrize("failed_first", [False, True])
def test_elapsed_turn_cancels_unfinished_work_without_resetting_its_budget(
        cached, monkeypatch, hosts, failed_first):
    wt, run, _ = cached
    now, timers = [0], []

    class ClockTimer:
        def __init__(self, seconds, function):
            self.seconds, self.function, self.cancelled = seconds, function, False

        def start(self):
            self.due = now[0] + self.seconds
            timers.append(self)

        def cancel(self):
            self.cancelled = True

    def unfinished_job(host, path, stop):
        if failed_first and path == "pkg/test/test_a.py":
            now[0] = 540
            return 0
        # One job is still running at 601 s, including after a successful failed-first batch.
        now[0] = 601
        for timer in timers:
            if not timer.cancelled and timer.due <= now[0]:
                timer.function()
        assert stop.is_set(), "the 10-minute turn expired without interrupting the unfinished invocation"
        return land.remote_pytest.CANCELLED

    monkeypatch.setattr(threading, "Timer", ClockTimer)
    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(land.remote_pytest, "run", REMOTE_RUN)
    monkeypatch.setattr(land.remote_pytest, "HEADROOM", {})
    seen = _fake_hosts(monkeypatch, wt, hosts, unfinished_job)
    remote_job = land.remote_pytest.remote_job.run

    def run_job(host, name, number, log, *args, **kwargs):
        log.parent.mkdir(parents=True, exist_ok=True)
        code = remote_job(host, name, number, log, *args, **kwargs)
        if code == 0:
            log.write_text("1 passed\n", encoding="utf-8")
        return code

    monkeypatch.setattr(land.remote_pytest.remote_job, "run", run_job)
    if failed_first:
        land.land_cache.failed(wt, ["pkg/test/test_a.py"], True)

    with pytest.raises(land.Overtime):
        run([["pkg/test/test_a.py"], ["pkg/test"], ["pkg/test/test_a.py::test_a"], ["queued/test"]])

    assert seen, "the test must exercise an invocation already running at expiry"
    assert len(seen) < 4, "work still queued at expiry must not start"
    entries = land.land_cache.entries(wt)
    assert [entry["argv"] for entry in entries] == ([["pkg/test/test_a.py"]] if failed_first else []), (
        "only the invocation completed before expiry may become passing evidence")
