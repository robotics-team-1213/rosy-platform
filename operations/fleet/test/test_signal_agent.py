"""D-525 rev 4: the AI PC signal controller decides only what to ask for, from fake Fleet reads."""

from __future__ import annotations

import urllib.error

from fleet.traffic.signal_agent import decide, run, waiting


def _traffic(mode="demand", robots=()):
    return {"signals": [{"signal_id": "sig", "mode": mode, "errors": [],
                         "approaches": [{"approach": "east:fwd"}, {"approach": "west:fwd"}]}],
            "robots": list(robots)}


def _ahead(robot_id, approach, d, lamp="red", may_enter=False):
    return {"robot_id": robot_id, "signal_ahead": {"signal_id": "sig", "approach": approach, "distance_m": d,
                                                   "lamp": lamp, "may_enter": may_enter}}


def _guide(*records):
    return {"robots": list(records)}


def _rec(robot_id, x, arc="east:fwd", to_place=0.4, lateral=0.01, state="LOCALIZED", online=True):
    return {"robot_id": robot_id, "online": online, "pose": {"x": x, "y": 0.0, "state": state},
            "lane": {"arc_id": arc, "lateral_m": lateral, "width_m": 0.2,
                     "next_place": {"place_id": "NE", "distance_m": to_place}}}


def test_rule_a_uses_signal_ahead_near_a_non_green_lamp():
    traffic = _traffic(robots=[_ahead("a", "east:fwd", 0.35), _ahead("b", "west:fwd", 0.9),
                               _ahead("c", "west:fwd", 0.2, lamp="green"), _ahead("d", "west:fwd", 0.1, may_enter=True)])
    assert waiting(traffic, _guide(), {}) == {"a": ("sig", "east:fwd", 0.35)}


def test_rule_b_needs_the_approach_lane_near_the_entry_inside_the_lane_localized_and_still():
    traffic = _traffic()
    last = {r: (1.0, 0.0) for r in "abcdef"}
    guide = _guide(_rec("a", 1.005),                       # waits
                   _rec("b", 1.10),                        # moving
                   _rec("c", 1.0, to_place=0.8),           # too far
                   _rec("d", 1.0, lateral=0.15),           # off the lane
                   _rec("e", 1.0, state="UNKNOWN"),
                   _rec("f", 1.0, arc="ring_n:fwd"))       # not an approach
    assert waiting(traffic, guide, last) == {"a": ("sig", "east:fwd", 0.4)}
    assert waiting(traffic, guide, {}) == {}               # no previous pose: stillness unknown


def test_decide_is_fifo_by_first_seen_and_keeps_alive_when_nobody_waits():
    sends, memory = decide(_traffic(), _guide(), {}, 0.0)
    assert sends == [{"signal_id": "sig", "approach": None, "reason": ""}]
    sends, memory = decide(_traffic(robots=[_ahead("b", "west:fwd", 0.3)]), _guide(), memory, 1.0)
    assert [s["approach"] for s in sends] == ["west:fwd"] and sends[0]["reason"] == "robot b waiting 0.30 m"
    both = _traffic(robots=[_ahead("a", "east:fwd", 0.3), _ahead("b", "west:fwd", 0.3)])
    sends, memory = decide(both, _guide(), memory, 2.0)
    assert [s["approach"] for s in sends] == ["west:fwd", "east:fwd"]     # b waited first
    sends, memory = decide(_traffic(robots=[_ahead("a", "east:fwd", 0.3)]), _guide(), memory, 3.0)
    sends, memory = decide(both, _guide(), memory, 4.0)
    assert [s["approach"] for s in sends] == ["east:fwd", "west:fwd"]     # b left and came back: now behind a


def test_signals_not_in_demand_mode_get_nothing():
    for mode in ("cycle", "occupancy", "all_red", "hold", "manual"):   # D-525 rev 5: occupancy is the default
        sends, _memory = decide(_traffic(mode=mode, robots=[_ahead("a", "east:fwd", 0.3)]),
                                _guide(_rec("b", 1.0, arc="west:fwd")), {"xy": {"b": (1.0, 0.0)}}, 0.0)
        assert sends == [], mode


class FakeFleet:
    def __init__(self, reads, refuse=False):
        self.reads, self.sent, self.refuse = list(reads), [], refuse

    def read(self):
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def demand(self, send):
        if self.refuse:
            raise urllib.error.HTTPError("u", 409, "SIGNAL_NOT_DEMAND", {}, None)
        self.sent.append(send)


def test_run_only_sends_demands_and_survives_fleet_errors():
    fleet = FakeFleet([(_traffic(robots=[_ahead("a", "east:fwd", 0.3)]), _guide()), OSError("down"),
                       (_traffic(), _guide())])
    t = iter(range(100))
    run(fleet, clock=lambda: next(t), sleep=lambda s: None, polls=3)
    assert [s["approach"] for s in fleet.sent] == ["east:fwd", None]
    refused = FakeFleet([(_traffic(robots=[_ahead("a", "east:fwd", 0.3)]), _guide())], refuse=True)
    run(refused, clock=lambda: 0.0, sleep=lambda s: None, polls=1)        # logged, not raised


def test_a_409_after_an_operator_leaves_demand_mode_is_dropped_quietly(caplog):
    """The operator switched the signal back to occupancy between the read and the send: no warning."""
    refused = FakeFleet([(_traffic(robots=[_ahead("a", "east:fwd", 0.3)]), _guide())], refuse=True)
    with caplog.at_level("INFO", logger="fleet.signal_agent"):
        run(refused, clock=lambda: 0.0, sleep=lambda s: None, polls=1)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
