"""Diagnostic reruns share the deadline of the turn that requested them."""

import threading

import pytest

from test_land import cached, land, repos  # noqa: F401
from test_remote_pytest import _fake_hosts


REMOTE_RUN = land.remote_pytest.run
FAILURE = "FAILED pkg/test/test_a.py::test_a - assert False\n1 failed in 0.01s\n"


@pytest.mark.parametrize("hosts", [["a@1"], ["a@1", "b@2"]])
@pytest.mark.parametrize("expires_in", ["alone", "main"])
def test_diagnostic_expiry_releases_the_turn_without_starting_another_check(
        cached, monkeypatch, capsys, hosts, expires_in):
    wt, run, _ = cached
    now, timers, diagnostics = [0], [], []

    class ClockTimer:
        def __init__(self, seconds, function):
            self.seconds, self.function, self.cancelled = seconds, function, False

        def start(self):
            self.due = now[0] + self.seconds
            timers.append(self)

        def cancel(self):
            self.cancelled = True

        def join(self):
            pass

    monkeypatch.setattr(threading, "Timer", ClockTimer)
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: True)  # a landing waits for the turn
    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(land.remote_pytest, "run", REMOTE_RUN)
    monkeypatch.setattr(land.remote_pytest, "HEADROOM", {})
    _fake_hosts(monkeypatch, wt, hosts, lambda *args: 0)

    def run_job(host, name, number, log, job_args, invocation, *args, **kwargs):
        log.parent.mkdir(parents=True, exist_ok=True)
        phase = "alone" if name.startswith("land-alone-") else "main" if name.startswith("land-main-") else "outer"
        if phase == "outer":
            if "pkg/test" not in invocation:
                log.write_text("1 passed in 0.01s\n", encoding="utf-8")
                return 0
            now[0] = land.TURN_CAP_S - 10
            log.write_text(FAILURE, encoding="utf-8")
            return 1
        diagnostics.append(phase)
        if phase == "alone" and expires_in == "main":
            now[0] = land.TURN_CAP_S - 5
            log.write_text(FAILURE, encoding="utf-8")
            return 1
        now[0] = land.TURN_CAP_S + 1
        for timer in timers:
            if not timer.cancelled and timer.due <= now[0]:
                timer.function()
        stop = kwargs.get("stop")
        assert stop is not None and stop.is_set(), "unfinished diagnostics escaped the turn's stop event"
        log.write_text("cancelled at the turn deadline\n", encoding="utf-8")
        return land.remote_pytest.CANCELLED

    monkeypatch.setattr(land.remote_pytest.remote_job, "run", run_job)
    with pytest.raises(land.Overtime):
        run([["pkg/test"], ["queued/test"]])

    assert diagnostics == (["alone"] if expires_in == "alone" else ["alone", "main"])
    assert land.land_cache.entries(wt) == [], "an incomplete diagnostic must not produce passing evidence"
    assert "on_done raised" not in capsys.readouterr().err, "deadline cancellation is not a broken callback"


def test_pass_after_a_verdictless_failure_survives_the_deadline_and_is_reused(cached, monkeypatch):
    wt, run, _ = cached
    now, timers = [0], []

    class ClockTimer:
        def __init__(self, seconds, function):
            self.function = function

        def start(self):
            timers.append(self)

        def cancel(self):
            pass

        def join(self):
            pass

    def remote(invocations, logs, *args, stop, **kwargs):
        now[0] = land.TURN_CAP_S + 1
        timers[0].function()
        assert stop.is_set()
        for log, text in zip(logs, [FAILURE, "1 passed in 0.01s\n", "cancelled\n"]):
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(text, encoding="utf-8")
        return [1, 0, land.remote_pytest.CANCELLED]

    def verdict(wt_, inv, *args):
        if inv == ["pkg/test"]:
            raise land.land_checks.CancelledError("turn deadline expired during diagnostic checks")
        return 0, [], ""

    monkeypatch.setattr(threading, "Timer", ClockTimer)
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: True)
    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(land.land_checks, "verdict", verdict)
    monkeypatch.setattr(land.remote_pytest, "run", remote)
    with pytest.raises(land.Overtime):
        run([["pkg/test"], ["queued/test"], ["late/test"]])

    assert [e["argv"] for e in land.land_cache.entries(wt)] == [["queued/test"]]
    head = land.out(wt, "rev-parse", "HEAD")
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    reused, todo, _ = land.land_cache.split(wt, args, [["pkg/test"], ["queued/test"], ["late/test"]],
                                            head, land.sys.executable, land.select)
    assert len(reused) == 1 and todo == [["pkg/test"], ["late/test"]]
