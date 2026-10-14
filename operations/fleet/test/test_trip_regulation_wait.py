"""D-763 8: a CORE regulation wait (``line_follow.regulation_wait``, API v1.227) is no stall within its bound."""
from __future__ import annotations

from types import SimpleNamespace

from fleet.server.trip_progress import CROSSWALK_WAIT_S, TripProgress
from fleet.server.trip_ports import TripConfig


class _Progress(TripProgress):
    def __init__(self):
        self.lease, self.config = SimpleNamespace(ttl_s=8.0), TripConfig()


def _live(regulation=None, wait=None):
    return SimpleNamespace(view={"wait": wait} if wait else {}, junction={"regulation_wait": regulation})


def test_a_crosswalk_look_is_no_stall_within_its_bound_and_is_one_again_after():
    p, live = _Progress(), _live("crosswalk_look")
    assert p._waiting(live, 100.0) and live.view["wait"] == {"reason": "crosswalk_look", "since": 100.0}
    live.junction["regulation_wait"] = "crosswalk_wait"        # a new reason starts its own bound
    assert p._waiting(live, 110.0) and live.view["wait"]["since"] == 110.0
    assert p._waiting(live, 110.0 + CROSSWALK_WAIT_S - 0.1)
    assert not p._waiting(live, 110.0 + CROSSWALK_WAIT_S)     # past the bound: the stall rule again (D-622 next)


def test_signal_and_authority_bounds_and_a_cleared_wait():
    p = _Progress()
    assert p._wait_bound("signal") == TripConfig().stall_s and p._wait_bound("authority") == 8.0
    live = _live("signal")
    assert p._waiting(live, 0.0)
    live.junction["regulation_wait"] = None                  # CORE drove on: the wait is gone at once
    assert not p._waiting(live, 1.0) and live.view["wait"] == {}
    assert p._wait_bound("person_present") is None           # only CORE's listed reasons


def test_a_link_wait_is_not_replaced_by_a_regulation_reason():
    p, live = _Progress(), _live("crosswalk_look", wait={"reason": "link_wait", "since": 5.0})
    assert p._waiting(live, 6.0) and live.view["wait"]["reason"] == "link_wait"
