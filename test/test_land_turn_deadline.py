"""A turn must release remote jobs even when no invocation has finished."""

import threading

import pytest

from test_land import cached, land, repos  # noqa: F401
from test_remote_pytest import _fake_hosts


REMOTE_RUN = land.remote_pytest.run


@pytest.mark.parametrize("hosts", [["a@1"], ["a@1", "b@2"]])
def test_elapsed_turn_cancels_running_and_queued_work_before_any_result(cached, monkeypatch, hosts):
    wt, run, _ = cached
    timers = []

    class ClockTimer:
        def __init__(self, seconds, function):
            self.seconds, self.function, self.cancelled = seconds, function, False

        def start(self):
            timers.append(self)

        def cancel(self):
            self.cancelled = True

    def unfinished_job(host, path, stop):
        # Advance the clock only after a real worker has started its first invocation.
        for timer in timers:
            if not timer.cancelled and timer.seconds <= 601:
                timer.function()
        assert stop.is_set(), "the 10-minute turn expired without interrupting the unfinished invocation"
        return land.remote_pytest.CANCELLED

    monkeypatch.setattr(threading, "Timer", ClockTimer)
    monkeypatch.setattr(land.remote_pytest, "run", REMOTE_RUN)
    monkeypatch.setattr(land.remote_pytest, "HEADROOM", {})
    seen = _fake_hosts(monkeypatch, wt, hosts, unfinished_job)

    with pytest.raises(land.Overtime):
        run([["pkg/test"], ["pkg/test/test_a.py"], ["pkg/test/test_a.py::test_a"]])

    assert seen, "the test must exercise an invocation already running at expiry"
    assert len(seen) < 3, "work still queued at expiry must not start"
    assert land.land_cache.entries(wt) == [], "cancelled work must never become passing evidence"
