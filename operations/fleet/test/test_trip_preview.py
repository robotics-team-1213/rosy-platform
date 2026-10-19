"""D-767 P0: Fleet's route preview — built each trip period, shown on /traffic, never sent to a robot."""

from __future__ import annotations

import copy
import json
import logging

import pytest

from core_common.robot_body import PINKY_PRO
from fleet import site_map
from fleet.server import trip_preview
from fleet.server.trip_geometry import bend_geometry
from fleet.site_map import SiteMap
from fleet.server.trips.trip_crosswalks import crosswalk_spans, route_crosswalks
from test_trip_bend import SW_BEND, _bend_map, _trip
from test_trip_runner import _arc, _plan, _setup, _ticks, run

FRONT = PINKY_PRO.front_x_m


@pytest.fixture(autouse=True)
def _awake(monkeypatch):
    """Past the restart quiet (START_QUIET_S) unless a test says otherwise."""
    monkeypatch.setattr(trip_preview, "_STARTED", -1e9)


def _line(places, crosswalks=()):
    """Junction places ``(id, x, y)`` joined in order by one-way lanes of width 0.2."""
    return SiteMap.model_validate({
        "places": [{"id": p, "name": p, "x": x, "y": y, "kind": "junction"} for p, x, y in places],
        "edges": [{"id": f"{a[0]}{b[0]}".lower(), "from": a[0], "to": b[0], "polyline": [[a[1], a[2]], [b[1], b[2]]],
                   "width_m": 0.2, "speed_cap_mps": 0.2, "drive_mode": "lane"} for a, b in zip(places, places[1:])],
        "crosswalks": [{"id": c, "polygon": poly, "revision": "r1"} for c, poly in crosswalks]})


def _running(site_map, arc_id, s, to, ticks=1):
    runner, store, ports = _setup(site_map)
    _plan(store, ports, arc_id, s, to)
    run(runner.start("p1", "bob"))
    _ticks(runner, ports, ticks)
    return runner, store, ports, runner._live["rosy_60"]


def _row(runner):
    return next(row for row in runner.traffic.view()["robots"] if row["robot_id"] == "rosy_60")


TURN_MAP = _line([("A", 0, 0), ("B", 1, 0), ("C", 1, 1)])


def test_a_turn_and_the_trip_end_cap_the_horizon_and_reach_the_traffic_row():
    runner, _store, ports, live = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    preview = _row(runner)["preview"]
    front = 0.5 + FRONT
    assert preview["front_d_m"] == pytest.approx(front, abs=1e-3)
    assert preview["horizon_m"] == pytest.approx(2.0 - front, abs=1e-3)          # the trip ends 1.46 m ahead
    turn, stop = preview["events"]
    assert (turn["kind"], turn["place_id"], turn["s_m"]) == ("turn", "B", 1.0)
    assert turn["at_m"] == pytest.approx(1.0 - front, abs=1e-3)
    assert turn["params"]["action"] == "left" and turn["params"]["turn_deg"] == pytest.approx(90, abs=1)
    assert turn["params"]["line_before_m"] == pytest.approx(-0.1, abs=0.002)    # the painted line 0.1 m past B
    assert (stop["kind"], stop["place_id"], stop["s_m"], stop["params"]["reason"]) == ("stop", "C", 2.0, "trip_end")
    assert ports.sent[0][:2] == ("left", "B")                                    # sent this period, 0.5 m ahead
    assert preview["mismatch"] == {} and preview["seq"] == 0 and preview["age_s"] == 0.0


def test_the_preview_changes_only_with_its_events_not_as_the_robot_drives_on():
    runner, store, ports, live = _running(TURN_MAP, "ab:fwd", 0.2, "C")
    ports.at(_arc(store, "ab:fwd"), 0.205)
    _ticks(runner, ports)
    assert live.preview["seq"] == 0                                              # at_m shrank: not a change
    ports.at(_arc(store, "ab:fwd"), 0.6)                                         # C enters the horizon
    _ticks(runner, ports)
    assert live.preview["seq"] == 1                                              # seq counts the changes


def test_an_expired_or_quiet_preview_shows_as_nothing(monkeypatch):
    runner, _store, ports, live = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    runner.traffic.period(runner._live.values())
    trip_preview.observe(runner._live.values(), {"rosy_60"}, runner.traffic, runner._store, runner._routing,
                         runner.config, ports.now + trip_preview.TTL_S + 0.5)   # mid-step: not rebuilt
    assert "preview" not in _row(runner)
    monkeypatch.setattr(trip_preview, "_STARTED", trip_preview.time.monotonic())
    runner2, _store2, _ports2, live2 = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    assert "preview" not in _row(runner2) and getattr(live2, "preview", None) is None


def test_a_crosswalk_is_its_lane_entry_on_the_route():
    slant = [[0.7, -0.2], [0.9, -0.2], [1.0, 0.2], [0.8, 0.2]]   # the lane y=0 crosses it from x 0.75 to 0.95
    runner, *_ = _running(_line([("A", 0, 0), ("B", 2, 0)], [("cw1", slant)]), "ab:fwd", 0.3, "B")
    walk = next(e for e in _row(runner)["preview"]["events"] if e["kind"] == "crosswalk")
    assert walk["s_m"] == pytest.approx(0.75, abs=0.002) and walk["params"]["zone_id"] == "cw1"
    assert walk["params"]["length_m"] == pytest.approx(0.20, abs=0.003)


def test_crosswalk_spans_from_inside_and_twice():
    class Line:
        def point_at(self, s):
            return s, 0.0, 0.0
    box = lambda a, b: [(a, -1), (b, -1), (b, 1), (a, 1)]  # noqa: E731
    route = [(0.0, Line(), 0.0)]
    near, far = crosswalk_spans(route, 0.0, 3.0, box(0.5, 1.0))[0]
    assert (near, far) == (pytest.approx(0.5, abs=1e-3), pytest.approx(1.0, abs=1e-3))
    assert crosswalk_spans(route, 0.6, 3.0, box(0.5, 1.0)) == []                 # already inside: no near edge ahead
    assert crosswalk_spans(route, 0.0, 0.8, box(0.5, 1.0))[0][1] is None         # its far edge beyond the scan


def test_every_signal_on_the_route_and_the_eight_event_cap():
    places = [(f"P{i}", 0.15 * i, 0) for i in range(14)]
    runner, store, _ports, live = _running(_line(places), "p0p1:fwd", 0.0, "P13")
    approaches = {"p1p2:fwd": "sig_a", "p3p4:fwd": "sig_b"}
    preview = trip_preview.build(live, store.active(), approaches, runner.traffic, runner._routing, runner.config)
    signals = [(e["place_id"], e["params"]["signal_id"]) for e in preview["events"] if e["kind"] == "signal"]
    assert signals == [("P2", "sig_a"), ("P4", "sig_b")]
    assert len(preview["events"]) == trip_preview.MAX_EVENTS
    assert [e["s_m"] for e in preview["events"]] == sorted(e["s_m"] for e in preview["events"])


def test_the_horizon_takes_the_authority_end_and_hold_back_none():
    runner, store, _ports, live = _running(_line([("A", 0, 0), ("B", 3, 0)]), "ab:fwd", 0.2, "B")
    live.view["traffic_authority"], live.traffic["authority_end_m"] = "core", 0.2 + FRONT + 1.95
    preview = trip_preview.build(live, store.active(), {}, runner.traffic, runner._routing, runner.config)
    assert preview["horizon_m"] == 2.0                                            # never past 2 m
    assert preview["events"][-1]["kind"] == "authority_end"
    live.view["traffic_authority"] = "hold_back"                                  # R = 0: speed x 8 s
    preview = trip_preview.build(live, store.active(), {}, runner.traffic, runner._routing, runner.config)
    assert preview["horizon_m"] == pytest.approx(0.2 * trip_preview.LEASE_S) and preview["events"] == []


def test_no_preview_in_link_wait_after_a_pose_jump_or_on_another_map():
    runner, store, _ports, live = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    args = (store.active(), {}, runner.traffic, runner._routing, runner.config)
    assert trip_preview.build(live, *args) is not None
    live.traffic["waiting_for"] = ["pose_jump"]
    assert trip_preview.build(live, *args) is None
    live.traffic["waiting_for"], live.view["state"] = [], "link_wait"
    assert trip_preview.build(live, *args) is None
    live.view["state"], live.view["map_version"] = "running", -1
    assert trip_preview.build(live, *args) is None


def test_a_bend_is_its_arc_start_and_matches_the_instruction():
    runner, store, ports, arc, s_start = _trip(_bend_map(SW_BEND))
    live = runner._live["rosy_60"]
    assert ports.sent == [("bend", "B_SW", None)]
    bend = next(e for e in live.preview["events"] if e["kind"] == "bend")
    assert bend["place_id"] == "B_SW" and bend["params"]["radius_m"] == 0.064
    assert bend["s_m"] == pytest.approx(live.segments[0]["s_from"] + live.progress(0, s_start), abs=1e-3)
    assert getattr(live, "preview_mismatch", {}) == {}


def test_a_skewed_preview_counts_a_mismatch(monkeypatch):
    def skewed(place, arc):
        found = bend_geometry(place, arc)
        return found and (found[0] + 0.01, *found[1:])
    monkeypatch.setattr(trip_preview, "bend_geometry", skewed)
    runner, *_ = _trip(_bend_map(SW_BEND))
    assert runner._live["rosy_60"].preview_mismatch == {"bend": 1}
    assert _row(runner)["preview"]["mismatch"] == {"bend": 1}


def test_the_preview_sends_nothing_to_the_robot(monkeypatch, tmp_path):
    def drive():
        runner, store, ports, _live = _running(TURN_MAP, "ab:fwd", 0.2, "C")
        for s in (0.3, 0.45, 0.6, 0.8):
            ports.at(_arc(store, "ab:fwd"), s)
            _ticks(runner, ports)
        return ports.sent, ports.expects, ports.refreshes, ports.goals, ports.held, ports.core.mode
    log = tmp_path / "preview.jsonl"
    monkeypatch.setenv(trip_preview.LOG_ENV, str(log))
    with_preview = drive()
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) >= 1 and {"robot_id", "t", "pose_stamp", "front_d_m", "events"} <= set(lines[0])
    monkeypatch.setattr("fleet.server.trip_runner.observe", lambda *a, **k: None)
    assert drive() == with_preview


def test_crosswalks_are_sampled_once_per_route_and_far_ones_never(monkeypatch):
    calls, real = [], site_map._inside
    monkeypatch.setattr(site_map, "_inside", lambda point, poly: calls.append(tuple(poly)) or real(point, poly))
    route_crosswalks.cache_clear()
    slant = [[0.7, -0.2], [0.9, -0.2], [1.0, 0.2], [0.8, 0.2]]
    far = [[5.9, 4.8], [6.1, 4.8], [6.1, 5.2], [5.9, 5.2]]   # on the lane C -> D, which this trip never drives
    places = [("A", 0, 0), ("B", 2, 0), ("C", 5, 5), ("D", 7, 5)]
    runner, store, ports = _setup(_line(places, [("cw1", slant), ("cw2", far)]))
    _plan(store, ports, "ab:fwd", 0.3, "B")
    run(runner.start("p1", "bob"))
    calls.clear()                                                                 # the map's own validation
    _ticks(runner, ports)
    near_calls = [c for c in calls if c == tuple(map(tuple, slant))]
    assert [c for c in calls if c == tuple(map(tuple, far))] == []              # its box misses the route's
    assert 0 < len(near_calls) <= 2.0 / 0.02 + 30                                 # 2 cm steps, bisection at 2 edges
    calls.clear()
    ports.at(_arc(store, "ab:fwd"), 0.35)
    _ticks(runner, ports, 3)
    assert calls == [] and _row(runner)["preview"]["events"][0]["kind"] == "crosswalk"   # cached per route


def test_one_robots_bad_build_is_logged_once_and_blanks_only_its_own_preview(monkeypatch, caplog):
    runner, store, ports, live = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    other = copy.copy(live)
    other.view, other.preview = {**live.view, "robot_id": "rosy_61"}, None
    real = trip_preview.build
    monkeypatch.setattr(trip_preview, "build", lambda one, *a: (_ for _ in ()).throw(ValueError("bad"))
                        if one is live else real(one, *a))
    runner.traffic.period([live])
    runner.traffic.view()["robots"].append({"robot_id": "rosy_61"})
    with caplog.at_level(logging.ERROR, logger=trip_preview.__name__):
        for _ in range(2):
            trip_preview.observe([live, other], set(), runner.traffic, store, runner._routing, runner.config, ports.now)
    rows = {row["robot_id"]: row for row in runner.traffic.view()["robots"]}
    assert "preview" not in rows["rosy_60"] and live.preview is None
    assert rows["rosy_61"]["preview"]["events"][0]["place_id"] == "B"
    assert len([r for r in caplog.records if "rosy_60" in r.getMessage()]) == 1     # repeats muted


def test_an_event_between_the_pose_and_the_front_is_not_listed():
    runner, *_rest, live = _running(TURN_MAP, "ab:fwd", 0.98, "C")             # B is 2 cm ahead, the front 4 cm
    events = _row(runner)["preview"]["events"]
    assert all(e["at_m"] >= 0 for e in events) and "B" not in [e["place_id"] for e in events]
    assert getattr(live, "preview_mismatch", {}) == {}                            # the turn sent there is not a miss


def test_the_rollback_switch_turns_the_preview_off(monkeypatch):
    monkeypatch.setenv("ROSY_ROUTE_PREVIEW", "off")
    runner, *_rest, live = _running(TURN_MAP, "ab:fwd", 0.5, "C")
    assert "preview" not in _row(runner) and getattr(live, "preview", None) is None
