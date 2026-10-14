"""D-763 8: a CORE regulation wait (``line_follow.regulation_wait``, API v1.227) is no stall within its bound."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fleet.server.trip_progress import CROSSWALK_WAIT_S, TripProgress
from fleet.server.trip_ports import HttpLaneJunction, TripConfig

STALL_S = TripConfig().stall_s


class _Progress(TripProgress):
    def __init__(self):
        self.lease, self.config, self.t = SimpleNamespace(ttl_s=8.0), TripConfig(), 0.0
        self._clock = lambda: self.t


class _Live(SimpleNamespace):
    def progress(self, index, s):
        return s


def _live(regulation=None, wait=None):
    return _Live(view={"hold": None, **({"wait": wait} if wait else {})}, junction={"regulation_wait": regulation},
                 progress_at=0.0, best_progress=0.0, traffic=None, authority=None)


def _stalled_at(p, live, t, s=0.0):
    p.t = t
    return p._stalled(live, 0, s)


def test_a_crosswalk_episode_is_no_stall_for_its_bound_then_the_stall_rule_runs():
    p, live = _Progress(), _live("crosswalk_look")
    assert not _stalled_at(p, live, 0.0)
    assert not _stalled_at(p, live, CROSSWALK_WAIT_S - 0.1)
    assert not _stalled_at(p, live, CROSSWALK_WAIT_S)                        # the stall clock starts now
    assert _stalled_at(p, live, CROSSWALK_WAIT_S + STALL_S)                  # then stall (D-622 next)


def test_a_reason_flapping_or_a_null_poll_does_not_restart_the_episode():
    p, live = _Progress(), _live("crosswalk_look")
    _stalled_at(p, live, 0.0)
    for t, reason in ((4.0, "crosswalk_wait"), (8.0, None), (9.0, "authority"), (10.0, "crosswalk_look")):
        live.junction["regulation_wait"] = reason
        _stalled_at(p, live, t)
    assert live.view["wait"]["since"] == 0.0                                 # one episode from its first reason
    assert _stalled_at(p, live, CROSSWALK_WAIT_S + STALL_S)                  # bounded from 0, not from 10


def test_progress_ends_the_episode_and_a_later_wait_gets_a_fresh_bound():
    p, live = _Progress(), _live("crosswalk_look")
    _stalled_at(p, live, 0.0)
    live.junction["regulation_wait"] = None
    assert not _stalled_at(p, live, 5.0, s=1.0) and "wait" not in live.view  # it crossed
    live.junction["regulation_wait"] = "signal"
    _stalled_at(p, live, 30.0, s=1.0)
    assert live.view["wait"] == {"since": 30.0, "reason": "signal", "bound_s": STALL_S, "over_bound": False,
                                 "waiting": True}


def test_a_link_wait_is_not_replaced_and_old_core_without_the_field_is_unchanged():
    p, live = _Progress(), _live("crosswalk_look", wait={"reason": "link_wait", "since": 5.0})
    assert p._waiting(live, 6.0) and live.view["wait"]["reason"] == "link_wait"
    p, live = _Progress(), _live(None)
    _stalled_at(p, live, 0.0)
    assert _stalled_at(p, live, STALL_S) and "wait" not in live.view
    assert p._wait_bound("person_present") is None and p._wait_bound("authority") == 8.0


def test_junction_state_carries_the_regulation_wait():
    state = {"line_follow": {"junction": {"state": "idle"}, "regulation_wait": "crosswalk_look"}}
    client = SimpleNamespace(state=lambda: asyncio.sleep(0, result=state))
    port = HttpLaneJunction(lambda: {"rosy_01": client})
    assert asyncio.run(port.junction_state("rosy_01"))["regulation_wait"] == "crosswalk_look"


def test_the_trip_read_carries_each_reason_and_its_bound_then_over_bound_past_it():
    """D-763 2 (API v1.231): ``view.wait`` keeps the one predicate's answer the stall clock uses."""
    for reason in ("crosswalk_look", "crosswalk_wait", "crosswalk_held", "signal", "authority"):
        p, live = _Progress(), _live(reason)
        bound = p._wait_bound(reason)
        assert not _stalled_at(p, live, 0.0) and not _stalled_at(p, live, bound - 0.1)
        assert live.view["wait"] == {"since": 0.0, "reason": reason, "bound_s": bound, "over_bound": False,
                                     "waiting": True}
        _stalled_at(p, live, bound)
        assert live.view["wait"]["over_bound"] and not live.view["wait"]["waiting"]


def test_the_read_keeps_one_episode_across_reasons_and_progress_clears_it():
    p, live = _Progress(), _live("crosswalk_look")
    _stalled_at(p, live, 0.0)
    live.junction["regulation_wait"] = "signal"
    _stalled_at(p, live, 10.0)
    assert live.view["wait"] == {"since": 0.0, "reason": "signal", "bound_s": STALL_S, "over_bound": False,
                                 "waiting": True}
    live.junction["regulation_wait"] = None
    _stalled_at(p, live, 12.0)                                               # a null poll: no wait now, episode kept
    assert live.view["wait"]["since"] == 0.0 and not live.view["wait"]["waiting"]
    _stalled_at(p, live, STALL_S + 1.0)
    assert live.view["wait"]["over_bound"]
    assert not _stalled_at(p, live, STALL_S + 2.0, s=1.0) and "wait" not in live.view


def test_a_link_wait_reads_its_lease_bound():
    p, live = _Progress(), _live(None, wait={"reason": "link_wait", "since": 0.0})
    assert p._waiting(live, 1.0) and live.view["wait"]["bound_s"] == 8.0
    assert not p._waiting(live, 8.0) and live.view["wait"]["over_bound"]


def test_a_tick_that_returns_before_the_wait_check_shows_no_stale_answer():
    """D-763 8: ``waiting``/``bound_s``/``over_bound`` are unknown (None) on a tick that never reaches ``_waiting``."""
    from test_trip_runner import _plan, _setup, _ticks, run
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    runner._live["rosy_60"].view["wait"] = {"reason": "signal", "since": 0.0, "bound_s": STALL_S,
                                            "over_bound": False, "waiting": True}
    ports.pose = None                                                         # the step stops on the pose first
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["reason"] == "pose" and view["wait"]["reason"] == "signal"
    assert (view["wait"]["waiting"], view["wait"]["bound_s"], view["wait"]["over_bound"]) == (None, None, None)
