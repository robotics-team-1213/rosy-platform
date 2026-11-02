"""A turn must release remote jobs even when no invocation has finished."""

import threading
import json

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

        def join(self):
            pass

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
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: True)  # a landing waits for the turn
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


def test_with_no_landing_waiting_the_turn_cap_does_not_cut_the_turn(cached, monkeypatch):
    """2026-10-31: an urgent landing's turn hit the cap at 584 s with no one waiting and redid its pretest outside."""
    from test_land import GREEN, _runner
    wt, run, _ = cached
    asked = []
    monkeypatch.setattr(land, "TURN_CAP_S", -1)
    monkeypatch.setattr(land.land_checks, "CAP_POLL_S", 0.05)
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: asked.append(1) or False)
    monkeypatch.setattr(land.remote_pytest, "run", _runner({"pkg/test": GREEN, "pkg/test/test_a.py": GREEN}))
    assert land.run_tests(wt, land.argparse.Namespace(tests="auto", node=False, no_cache=False),
                          [["pkg/test"], ["pkg/test/test_a.py"]], wt.parent / "logs", 1)


@pytest.mark.parametrize("sent_back", [1, 2])
def test_the_turn_cap_grows_each_time_it_sent_the_landing_back(cached, monkeypatch, sent_back):
    """D-889 15/19, 11-01: FULL landings went back 3-6 times; then one uncapped turn held main for over 90 min.
    Once sent back the cap is 3x (still cut when a landing waits), twice it is gone."""
    from test_land import GREEN, _runner
    wt, run, _ = cached
    monkeypatch.setattr(land, "TURN_CAP_S", -1)
    asked = []
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: asked.append(1) or True)
    monkeypatch.setattr(land.remote_pytest, "run", _runner({"pkg/test": GREEN, "pkg/test/test_a.py": GREEN}))
    args = land.argparse.Namespace(tests="auto", node=False, no_cache=False, _overtime=sent_back)
    if sent_back == 1:
        with pytest.raises(land.Overtime):
            land.run_tests(wt, args, [["pkg/test"], ["pkg/test/test_a.py"]], wt.parent / "logs", 1)
    else:
        assert land.run_tests(wt, args, [["pkg/test"], ["pkg/test/test_a.py"]], wt.parent / "logs", 1)
        assert not asked, "no cap: nobody is asked whether they wait"


def test_the_ticket_keeps_the_sent_back_count_across_a_relaunch(tmp_path, monkeypatch):
    """11-01 13:26: the rest bundle relaunched on main's new landing code, lost the mark and went back again."""
    ticket = tmp_path / "1.json"
    ticket.write_text('{"status": "preparing", "branch": "b"}', encoding="utf-8")
    monkeypatch.setattr(land.land_queue, "_held", [ticket])
    fresh = land.argparse.Namespace()  # a relaunched process: nothing in memory
    assert land.land_checks.overtimes(land, fresh) == 0
    land.land_queue.set_status(ticket, "preparing", overtime=True)  # a ticket written by D-889 16 code
    land.land_queue.set_status(ticket, "waiting")  # later status changes keep the field
    assert land.land_checks.overtimes(land, fresh) == 1
    land.land_queue.set_status(ticket, "preparing", overtime=2)
    assert land.land_checks.overtimes(land, fresh) == 2


def test_guard_and_body_share_the_budget_from_turn_acquisition(cached, monkeypatch):
    from test_land import GREEN, _runner
    wt, _, _ = cached
    now, armed = [1000.0], []

    class Timer:
        def __init__(self, seconds, function):
            armed.append(seconds)

        def start(self): pass
        def cancel(self): pass
        def join(self): pass

    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(threading, "Timer", Timer)
    queue = land.land_queue
    qdir = queue.queue_dir(wt)
    ticket = queue.take(qdir, "feat/x")
    monkeypatch.setattr(queue, "_held", [ticket])
    queue.wait(qdir, ticket, 0)
    now[0] = 1180  # mandatory merge/selection/lint work already used three minutes
    run = _runner({"pkg/test": GREEN})

    def remote(*a, **kw):
        result = run(*a, **kw)
        now[0] += 120
        return result

    monkeypatch.setattr(land.remote_pytest, "run", remote)
    args = land.argparse.Namespace(tests="auto", node=False, no_cache=True)
    for phase in ("g1", 1):
        land.run_tests(wt, args, [["pkg/test"]], wt.parent / "logs", phase)
    assert armed == [land.TURN_CAP_S - 180, land.TURN_CAP_S - 300], "guard and body must share the acquired budget"


def test_expiry_marks_preparing_while_remote_cancellation_is_still_draining(cached, monkeypatch):
    wt, _, _ = cached
    now, timers, events = [0.0], [], []

    class Timer:
        def __init__(self, seconds, function): self.function = function
        def start(self): timers.append(self)
        def cancel(self): pass
        def join(self): pass

    monkeypatch.setattr(threading, "Timer", Timer)
    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(land.land_checks, "turn_wanted", lambda *a: True)
    monkeypatch.setattr(land.land_events, "emit", lambda event, **kw: events.append(event))
    queue = land.land_queue
    qdir = queue.queue_dir(wt)
    ticket = queue.take(qdir, "feat/x")
    monkeypatch.setattr(queue, "_held", [ticket])
    queue.wait(qdir, ticket, 0)

    def draining(invocations, logs, *a, stop, **kw):
        now[0] = 601
        timers[0].function()
        assert stop.is_set()
        assert json.loads(ticket.read_text())["status"] == "preparing", "drain still held the turn"
        return [land.remote_pytest.CANCELLED] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, "run", draining)
    args = land.argparse.Namespace(tests="auto", node=False, no_cache=True)
    with pytest.raises(land.Overtime):
        land.run_tests(wt, args, [["pkg/test"]], wt.parent / "logs", 1)
    assert not queue.release(ticket, "outside prepare", started=0)
    assert events.count("released") == 1


@pytest.mark.parametrize("at_join", [False, True])
def test_expired_turn_yields_even_when_every_check_passed_and_peer_already_owns_turn(cached, monkeypatch, at_join):
    wt, _, _ = cached
    now, timers = [0.0], []
    queue = land.land_queue
    qdir = queue.queue_dir(wt)
    ticket = queue.take(qdir, "feat/x")
    monkeypatch.setattr(queue, "_held", [ticket])
    monkeypatch.setattr(land.time, "monotonic", lambda: now[0])
    queue.wait(qdir, ticket, 0)
    peer = queue.take(qdir, "feat/peer", status="waiting")

    def handoff():
        now[0] = 601
        timers[0].function()
        queue.wait(qdir, peer, 0)
        assert not land.land_checks.turn_wanted(land, wt), "the waiter already acquired its turn"

    class Timer:
        def __init__(self, seconds, function): self.function = function
        def start(self): timers.append(self)
        def cancel(self): pass  # callback already entered; cancellation cannot undo it
        def join(self):
            if at_join:
                handoff()

    monkeypatch.setattr(threading, "Timer", Timer)

    def passed(invocations, logs, *a, **kw):
        for log in logs:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("1 passed\n", encoding="utf-8")
        if not at_join:
            handoff()
        return [0] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, "run", passed)
    invocations = [["pkg/test"], ["queued/test"]]
    args = land.argparse.Namespace(tests="auto", node=False, no_cache=False)
    with pytest.raises(land.Overtime):
        land.run_tests(wt, args, invocations, wt.parent / "logs", 1)
    assert [entry["argv"] for entry in land.land_cache.entries(wt)] == invocations, "all completed passes remain reusable"
    assert json.loads(peer.read_text())["status"] == "turn"
