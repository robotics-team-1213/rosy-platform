"""D-525 S1: virtual signals inside the Fleet trip loop — config, view, verbs, E-stop, start checks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fleet.cli import _traffic_signals
from fleet.traffic import blocks
from fleet.traffic.lane_traffic import TrafficService
from fleet.traffic.signal_phase import SignalPlan, entering_arcs
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripError, TripRunner
from test_lane_traffic import START_N, Fleet, _s_of, _trip
from test_routing import demo_site

RING = ("ring_n", "ring_s", "ring_e", "ring_w")


def _setup(capacity=1, plans=None):
    fleet = Fleet(("a", "b"))
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    zones = {"roundabout": (RING, capacity)}
    probe = TrafficService(store, TripConfig(), zones=zones)
    layout = probe._layout_for(store.active())
    entries = sorted(entering_arcs(store.active()[2], layout, "roundabout"))
    plans = plans if plans is not None else [SignalPlan("sig", "roundabout", tuple((a, 8.0) for a in entries))]
    traffic = TrafficService(store, TripConfig(), zones=zones, signals=plans, clock=lambda: fleet.now,
                             signal_clock=lambda: fleet.now)
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal, clock=lambda: fleet.now,
                        traffic=traffic)
    return runner, store, fleet, entries


def _signals(runner):
    runner.traffic.step([])
    return {row["signal_id"]: row for row in runner.traffic.view()["signals"]}


def test_a_fresh_signal_is_all_red_with_a_stop_line_per_approach():
    runner, store, _fleet, entries = _setup()
    row = _signals(runner)["sig"]
    assert row["virtual"] and row["mode"] == "all_red" and row["aspect"] == "all_red" and row["errors"] == []
    assert [a["approach"] for a in row["approaches"]] == entries and {a["lamp"] for a in row["approaches"]} == {"red"}
    graph = store.active()[2]
    for approach in row["approaches"]:
        x, y, _yaw = graph.arcs[approach["approach"]].point_at(graph.arcs[approach["approach"]].length_m)
        assert approach["stop_line"]["x"] == pytest.approx(x, abs=1e-3)
        assert approach["stop_line"]["y"] == pytest.approx(y, abs=1e-3)


def test_cycle_lights_one_approach_and_estop_turns_it_all_red():
    runner, _store, fleet, entries = _setup()
    runner.traffic.signal_command("sig", "cycle")
    fleet.advance(0.5)
    assert _signals(runner)["sig"]["aspect"] == "all_red"  # the first period learns whether the zone is busy
    fleet.advance(0.5)
    row = _signals(runner)["sig"]
    assert row["aspect"] == "green" and [a["lamp"] for a in row["approaches"]].count("green") == 1
    runner.traffic.signals_all_red()
    row = _signals(runner)["sig"]
    assert row["aspect"] == "all_red" and row["mode"] == "all_red"
    with pytest.raises(ValueError):
        runner.traffic.signal_command("sig", "set_aspect")
    with pytest.raises(KeyError):
        runner.traffic.signal_command("nope", "cycle")


def test_a_plan_that_fails_the_map_check_keeps_its_zone_red(monkeypatch):
    runner, _store, fleet, _entries = _setup(capacity=2)
    runner.traffic.signal_command("sig", "cycle")
    seen = []
    real = blocks.step
    monkeypatch.setattr(blocks, "step", lambda *a, **k: seen.append(k["green"]) or real(*a, **k))
    for _ in range(4):
        fleet.advance(0.5)
        row = _signals(runner)["sig"]
    assert any("capacity 2" in e for e in row["errors"]) and row["aspect"] == "all_red"
    assert seen and all(green == {"roundabout": frozenset()} for green in seen)


def test_the_block_table_gets_the_green_approach(monkeypatch):
    runner, _store, fleet, entries = _setup()
    runner.traffic.signal_command("sig", "cycle")
    seen = []
    real = blocks.step
    monkeypatch.setattr(blocks, "step", lambda *a, **k: seen.append(k["green"]) or real(*a, **k))
    for _ in range(2):  # the first period learns whether the zone is busy
        fleet.advance(0.5)
        _signals(runner)
    assert seen == [{"roundabout": frozenset()}, {"roundabout": frozenset({entries[0]})}]


def test_a_trip_across_a_signal_needs_core_authority():
    runner, store, fleet, _entries = _setup()
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    assert err.value.code == "TRIP_SIGNAL_NEEDS_AUTHORITY" and err.value.detail == {"signals": ["sig"]}


def test_signal_refusal_for_a_route_that_starts_inside_the_zone():
    runner, _store, _fleet, _entries = _setup()
    refused = runner.traffic.signal_refusal([{"edge_id": "ring_n", "forward": True}], "core")
    assert refused == ("TRIP_SIGNAL_START_IN_ZONE", {"signal_id": "sig"})
    assert runner.traffic.signal_refusal([{"edge_id": "east", "forward": True}], "core") is None


def test_no_signals_means_no_refusal_and_no_rows():
    runner, _store, _fleet, _entries = _setup(plans=[])
    assert runner.traffic.signal_refusal([{"edge_id": "ring_n", "forward": True}], "hold_back") is None
    assert _signals(runner) == {}


def test_site_config_signals_parse(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("fleet:\n  traffic:\n    signals:\n      sig:\n        zone: roundabout\n"
                    "        phases: [{approach: 'east:fwd', green_s: 8}, {approach: 'west:fwd', green_s: 6}]\n"
                    "        yellow_s: 2\n", encoding="utf-8")
    plans = _traffic_signals(SimpleNamespace(site_config=path))
    assert plans == [SignalPlan("sig", "roundabout", (("east:fwd", 8.0), ("west:fwd", 6.0)), 2.0, 1.0)]
    path.write_text("fleet:\n  traffic:\n    signals:\n      sig: {zone: roundabout}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        _traffic_signals(SimpleNamespace(site_config=path))


def test_signal_route_needs_a_named_operator_and_a_known_signal(tmp_path):
    from test_trip_runner import OPERATOR, VIEWER, Ports, _app

    client, *_rest = _app(tmp_path, Ports())
    url = "/api/fleet/traffic/signals/sig"
    assert client.post(url, json={"verb": "cycle"}).status_code in (401, 403)
    assert client.post(url, json={"verb": "cycle"}, headers=VIEWER).status_code in (401, 403)
    assert client.post("/api/fleet/traffic/signals/presence", headers=OPERATOR).json()["present"] is True
    response = client.post(url, json={"verb": "cycle"}, headers=OPERATOR)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "SIGNAL_UNKNOWN"
    assert client.post(url, json={"verb": ""}, headers=OPERATOR).status_code == 422


def test_a_pose_jump_beyond_travel_and_two_u_gives_no_authority_that_period():
    """D-525 real-map finding (D-517 premise): |Δfront| > max speed × dt + 2u + margin is a jump."""
    now = [100.0]
    service = TrafficService(None, TripConfig(), clock=lambda: now[0])
    guard = lambda d, trim=0.0, route="t:1": service._jump_guard("a", route, d, trim, 0.2, 0.195)  # noqa: E731
    assert guard(1.00) == 1.00
    now[0] += 0.5                      # allowed 0.1 + 0.39 + 0.05 = 0.54 m
    assert guard(1.50) == 1.50
    now[0] += 0.5
    assert guard(2.10) is None         # +0.60: a jump forward, refused
    now[0] += 0.5
    assert guard(1.55) == 1.55         # agrees with the last accepted front again
    now[0] += 0.5
    assert guard(0.95) is None         # −0.60: a jump back would let CORE overrun its authority
    assert guard(0.20, trim=1.40) == 0.20  # a repeat trip dropped 1.4 m of laps: same place, no jump
    assert guard(5.0, route="t:2") == 5.0  # a new route starts fresh
    assert guard(None) is None


def test_manual_green_needs_presence_and_falls_to_all_red_when_the_console_leaves():
    runner, _store, fleet, entries = _setup()
    with pytest.raises(PermissionError):
        runner.traffic.signal_command("sig", "set_aspect", entries[1])
    runner.traffic.signal_presence()
    with pytest.raises(ValueError):
        runner.traffic.signal_command("sig", "set_aspect", "nope:fwd")
    row = runner.traffic.signal_command("sig", "set_aspect", entries[1])
    assert row["mode"] == "manual" and row["manual"] == entries[1]
    for _ in range(4):                      # learn the zone, then the manual approach goes green
        fleet.advance(0.5)
        runner.traffic.signal_presence()
        row = _signals(runner)["sig"]
    assert row["aspect"] == "green" and [a["approach"] for a in row["approaches"] if a["lamp"] == "green"] == [entries[1]]
    fleet.advance(10.5)                     # no presence for longer than PRESENCE_S
    row = _signals(runner)["sig"]
    assert row["mode"] == "all_red" and row["aspect"] == "all_red", "never back to cycle on its own"
