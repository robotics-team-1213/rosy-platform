"""D-763 10 (c): a lane route over a site-map crosswalk (D-573 1) or a signalled zone (D-525) is refused
for a robot whose CORE announces that rule off (``lane_crosswalk_gate`` / ``lane_junction_signal`` false),
starts with a ``regulation_caps_unknown`` warning for an older CORE without the field, and starts plainly
with it on. A route over neither starts regardless."""

from __future__ import annotations

import dataclasses
import sys

import pytest

from fleet.server.console_view import trip_caps
from fleet.server.trip_admission import crosswalks_on, signals_on
from fleet.server.trip_runner import TripError
from fleet.site_map import SiteMap, from_lane_graph
from test_lane_traffic import START_N, _s_of, _trip
from test_trip_caps import _caps
from test_trip_runner import LANE, LANE_GRAPH, _plan, _setup, run
import test_traffic_signals

ABSENT = dataclasses.replace(LANE, lane_crosswalk_gate=None, lane_junction_signal=None)  # older CORE
OFF = dataclasses.replace(LANE, lane_crosswalk_gate=False, lane_junction_signal=False)
ON = dataclasses.replace(LANE, lane_crosswalk_gate=True, lane_junction_signal=True)


def test_caps_read_both_rules_and_keep_absent_apart_from_false():
    assert trip_caps(_caps()).lane_crosswalk_gate is None and trip_caps(_caps()).lane_junction_signal is None
    both = trip_caps(_caps(lane_crosswalk_gate=False, lane_junction_signal=True))
    assert both.lane_crosswalk_gate is False and both.lane_junction_signal is True
    assert trip_caps(_caps(lane_crosswalk_gate="true")).lane_crosswalk_gate is False  # malformed: refused like false
    assert trip_caps(_caps(lane_junction_signal=None)).lane_junction_signal is False


def _east(caps, site_map=None):
    runner, store, ports = _setup(site_map=site_map, caps=caps)
    _plan(store, ports, "east:fwd", 0.5, "SE")
    segments = store.plan("p1")["result"]["plan"]["segments"]
    return runner, crosswalks_on(store.active()[2], segments, store.active()[1].crosswalks)


def test_a_route_over_a_crosswalk_by_announced_gate():
    runner, crossed = _east(OFF)
    assert crossed  # the map_v2_fleet east lane carries a crosswalk
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_REGULATION_CAPS_MISSING"
    assert err.value.detail == {"missing": {"lane_crosswalk_gate": crossed}}
    runner, _ = _east(ON)
    view = run(runner.start("p1", "bob"))
    assert view["state"] == "started" and "regulation_caps_unknown" not in view["detail"]
    runner, _ = _east(ABSENT)  # ponytail: allowed with a warning until every robot announces the field
    view = run(runner.start("p1", "bob"))
    assert view["state"] == "started" and view["detail"]["regulation_caps_unknown"] == {"lane_crosswalk_gate": crossed}


def test_a_route_over_neither_starts_without_either_rule():
    body = from_lane_graph(LANE_GRAPH).body()
    body.pop("crosswalks", None)
    for caps in (OFF, ABSENT):
        runner, crossed = _east(caps, SiteMap.model_validate(body))
        assert crossed == []
        view = run(runner.start("p1", "bob"))
        assert view["state"] == "started" and view["detail"] == {}


def _signal_trip(caps):
    runner, store, fleet, _entries = test_traffic_signals._setup()
    runner._caps = lambda _robot_id: caps
    try:
        return _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    except TripError as exc:
        return exc


def test_a_route_through_a_signalled_zone_by_announced_signal():
    missing = _signal_trip(dataclasses.replace(ON, lane_junction_signal=False))
    assert missing.code == "TRIP_REGULATION_CAPS_MISSING"
    assert missing.detail == {"missing": {"lane_junction_signal": ["sig"]}}
    # passes this rule either way; D-525 6 (CORE authority) is the next refusal
    assert _signal_trip(ON).code == "TRIP_SIGNAL_NEEDS_AUTHORITY"
    assert _signal_trip(dataclasses.replace(ON, lane_junction_signal=None)).code == "TRIP_SIGNAL_NEEDS_AUTHORITY"


def _replan_hold(runner):
    """The running trip's own plan held as an operator replan (the crosswalk route again)."""
    live = runner._live["rosy_60"]
    live.view["hold"] = {"reason": "replan", "map_version": live.view["map_version"], "plan": dict(live.view["plan"])}
    return live


def test_an_operator_replan_is_checked_like_a_start_and_a_clean_check_clears_the_warning():
    runner, crossed = _east(ABSENT)
    assert run(runner.start("p1", "bob"))["detail"]["regulation_caps_unknown"] == {"lane_crosswalk_gate": crossed}
    live = _replan_hold(runner)
    runner._caps = lambda _robot_id: OFF
    with pytest.raises(TripError) as err:
        run(runner.confirm_replan("p1", "bob"))
    assert err.value.code == "TRIP_REGULATION_CAPS_MISSING" and live.view["hold"] is not None
    runner._caps = lambda _robot_id: ON
    view = run(runner.confirm_replan("p1", "bob"))
    assert view["hold"] is None and "regulation_caps_unknown" not in view["detail"]


def test_the_next_lap_is_checked_on_its_own_segments(monkeypatch):
    runner, _ = _east(ON)
    run(runner.start("p1", "bob"))
    live = runner._live["rosy_60"]
    body = {"segments": live.view["plan"]["segments"][:1]}
    module = sys.modules[type(runner)._next_lap.__module__]  # trip_replan since the D-798 split
    checked = []

    async def caps_checks(_robot_id, _graph, segments, *_args, **_kwargs):
        checked.append(segments)

    async def pose_checks(*_args, **_kwargs):
        return None, False

    monkeypatch.setattr(runner, "_caps_checks", caps_checks)
    monkeypatch.setattr(runner, "_pose_checks", pose_checks)
    monkeypatch.setattr(module, "next_lap", lambda *_args: (body, None))
    monkeypatch.setattr(module, "carry_on", lambda *_args: None)
    run(runner._next_lap(live, 0))
    assert checked == [body["segments"]]

def test_signals_on_walks_the_same_spans_as_signal_refusal():
    """``signals_on`` copies ``TrafficService.signal_refusal``'s span walk (and reads its private table);
    on the same route both name the same crossed signals, and neither names one without signals."""
    route = [{"edge_id": "east", "forward": True}, {"edge_id": "ring_n", "forward": True}]
    runner, _store, _fleet, _entries = test_traffic_signals._setup()
    assert signals_on(runner.traffic, route) == ["sig"]
    assert runner.traffic.signal_refusal(route, "hold_back") == (
        "TRIP_SIGNAL_NEEDS_AUTHORITY", {"signals": signals_on(runner.traffic, route)})
    runner, _store, _fleet, _entries = test_traffic_signals._setup(plans=[])
    assert signals_on(runner.traffic, route) == [] and runner.traffic.signal_refusal(route, "hold_back") is None
