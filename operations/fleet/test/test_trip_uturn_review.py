"""U-turn review regressions: capability, cue freshness and stopped ownership."""
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from fakes import run
from fleet.server.lane_compliance_service import LaneComplianceMonitor
from fleet.server.trip_ports import TripError
from fleet.server.trip_routes import TripRequest, install_trip_routes
from fleet.site_map import SiteMap
from fleet.swarm.transport import RobotApiError
from test_trip_runner import BOTH, LANE, _plan, _setup, _ticks


def uturn_site():
    return SiteMap.model_validate({
        "places": [{"id": p, "name": p, "kind": kind, "x": x, "y": 0.}
                   for p, kind, x in (("start", "junction", 0.), ("turn", "turnaround", 1.),
                                      ("finish", "junction", .1))],
        "edges": [{"id": edge, "from": a, "to": b, "direction": "one_way", "drive_mode": "lane",
                   "polyline": [[x, 0.], [y, 0.]], "width_m": .4, "speed_cap_mps": .2}
                  for edge, a, b, x, y in (("out", "start", "turn", 0., 1.),
                                          ("back", "turn", "finish", 1., .1))]})


def planner(runner, store, ports):
    app = FastAPI()

    async def caps_for(rid):
        return ports.caps_for(rid)

    install_trip_routes(app, console=NS(robot_ids=["rosy_60"]), site_maps=store,
                        routing_config=store.routing_config, require_operator=lambda: None,
                        require_named_operator=lambda: None, caps_for=caps_for,
                        runner=runner, read_guard=[])
    return app.state.trip_plan


@pytest.mark.parametrize("drive_mode", [None, "nav2"])
def test_uturn_preview_and_start_refuse_robot_without_free(drive_mode):
    runner, store, ports = _setup(uturn_site(), caps=LANE, map_binding_required=False)
    _plan(store, ports, "out:fwd", .2, "finish")
    plan = planner(runner, store, ports)
    with pytest.raises(HTTPException) as refused:
        run(plan("rosy_60", TripRequest(to="finish", drive_mode=drive_mode), "bob"))
    assert refused.value.detail == {"code": "TRIP_MODE_UNSUPPORTED", "detail": {"drive_mode": "free"}}
    with pytest.raises(TripError) as refused:
        run(runner.start("p1", "bob"))
    assert refused.value.code == "TRIP_MODE_UNSUPPORTED"
    assert refused.value.detail["drive_mode"] == "free"
    assert not ports.goals and not ports.line_starts


def test_forced_nav2_replans_with_nav2_bounds(monkeypatch):
    from fleet.server import trip_routes

    runner, store, ports = _setup(uturn_site(), caps=BOTH, map_binding_required=False)
    ports.at(store.active()[2].arcs["out:fwd"], .2)
    requests, original = [], trip_routes.plan_trip

    def capture(graph, request, config):
        requests.append(request)
        return original(graph, request, config)

    monkeypatch.setattr(trip_routes, "plan_trip", capture)
    result = run(planner(runner, store, ports)("rosy_60", TripRequest(to="finish"), "bob"))
    assert len(requests) == 2
    assert requests[-1].ignore_start_heading and requests[-1].ignore_arrive_heading
    assert requests[-1].nav2_off_lane_margin_m == runner.config.nav2_off_lane_margin_m
    assert store.plan(result["plan_id"])["request"]["drive_mode"] == "nav2"


def test_forced_nav2_replan_without_cusp_restores_original_lane_plan(monkeypatch):
    from fleet.server import trip_routes

    runner, store, ports = _setup(uturn_site(), caps=BOTH, map_binding_required=False)
    ports.at(store.active()[2].arcs["out:fwd"], .2)
    calls = []

    def fake_uturn(_graph, _segments, _config):
        calls.append(len(calls))
        return 0 if len(calls) == 1 else None

    monkeypatch.setattr(trip_routes, "uturn_lane_index", fake_uturn)
    result = run(planner(runner, store, ports)("rosy_60", TripRequest(to="finish"), "bob"))
    assert len(calls) == 2
    assert store.plan(result["plan_id"])["request"]["drive_mode"] is None
    assert "nav2_preflight" not in result


def cue_monitor(outcomes):
    now = [100.]
    outcomes = iter(outcomes)

    async def send(_):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=None, site_maps=None, wall=lambda: now[0],
                                    clients=lambda: {"r1": NS(line_follow_lane_cue=send)})
    back = {"state": "ON_LANE", "raw": "ON_LANE", "moving": True, "pose_stamp": 100.,
            "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": 180.,
            "offset_m": 0., "edge_id": "back", "guide": None, "turn_spot": False, "context": None}
    monitor._latest["r1"] = {"at": now[0], "return": back}
    return monitor, now, back


@pytest.mark.parametrize("failure", [TimeoutError(), httpx.ConnectError("offline"),
                                      RobotApiError("r1", 429, "RATE_LIMIT", "busy"),
                                      RobotApiError("r1", 500, "INTERNAL", "server"),
                                      RobotApiError("r1", 501, "NOT_IMPLEMENTED", "server"),
                                      RobotApiError("r1", 503, "UNAVAILABLE", "server")])
def test_cue_transient_failure_holds_only_after_three_and_recovers(failure):
    monitor, now, back = cue_monitor([{"accepted": True}, failure, failure, failure, {"accepted": True}])
    run(monitor._send_cue("r1", back, now[0]))
    for attempt in range(1, 4):
        now[0] += .5
        run(monitor._send_cue("r1", back, now[0]))
        assert monitor.cue_refusal("r1") == (None if attempt < 3 else "unknown")
    now[0] += 5.0 if getattr(failure, "status", None) in (500, 501) else .5
    run(monitor._send_cue("r1", back, now[0]))
    assert monitor.cue_refusal("r1") is None


@pytest.mark.parametrize("status", [500, 501])
def test_unsupported_server_mutes_for_five_seconds_when_never_accepted(status):
    sent = []

    async def send(body):
        sent.append(body)
        raise RobotApiError("r1", status, "NO_WIRING", "server")

    now = [100.]
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=None, site_maps=None, wall=lambda: now[0],
                                    clients=lambda: {"r1": NS(line_follow_lane_cue=send)})
    back = {"state": "OFF_LANE", "raw": "OFF_LANE", "moving": True, "pose_stamp": 100.,
            "side": "left", "bearing_deg": 10., "turn_deg": 5., "lane_heading_deg": 180.,
            "offset_m": .1, "edge_id": "back", "guide": None, "turn_spot": False, "context": None}
    monitor._latest["r1"] = {"at": now[0], "return": back}
    run(monitor._send_cue("r1", back, now[0]))
    assert len(sent) == 1 and monitor.cue_refusal("r1") == "unknown"
    for _ in range(9):
        now[0] += .5
        run(monitor._send_cue("r1", back, now[0]))
        assert len(sent) == 1 and monitor.cue_refusal("r1") == "unknown"
    now[0] += .5
    run(monitor._send_cue("r1", back, now[0]))
    assert len(sent) == 2


def test_check_cue_returns_unknown_when_view_is_stale_or_unseen():
    sent = []

    async def send(body):
        sent.append(body)
        return {"accepted": True}

    now = [100.]
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=None, site_maps=None, wall=lambda: now[0],
                                    clients=lambda: {"r1": NS(line_follow_lane_cue=send)})
    assert run(monitor.check_cue("r1")) == "unknown"
    monitor._latest["r1"] = {"at": now[0], "return": None}
    assert run(monitor.check_cue("r1")) == "unknown"
    back = {"state": "ON_LANE", "raw": "ON_LANE", "moving": False, "pose_stamp": 100.,
            "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": 180.,
            "offset_m": 0., "edge_id": "back", "guide": None, "turn_spot": False, "context": None}
    monitor._latest["r1"] = {"at": now[0] - 1.0, "return": back}
    assert run(monitor.check_cue("r1")) == "unknown"
    monitor._latest["r1"] = {"at": now[0], "return": {**back, "raw": "UNSEEN"}}
    assert run(monitor.check_cue("r1")) == "unknown"
    assert not sent


def test_uturn_to_named_stop_with_map_binding_required_tracks_strict_stop():
    from fleet.server.trip_live import LiveTrip
    from fleet.server.trip_progress import TripProgress

    site = SiteMap.model_validate({
        "places": [{"id": p, "name": p, "kind": kind, "x": x, "y": 0.}
                   for p, kind, x in (("start", "junction", 0.), ("turn", "turnaround", 1.),
                                      ("finish", "stop", .1))],
        "edges": [{"id": edge, "from": a, "to": b, "direction": "one_way", "drive_mode": "lane",
                   "polyline": [[x, 0.], [y, 0.]], "width_m": .4, "speed_cap_mps": .2}
                  for edge, a, b, x, y in (("out", "start", "turn", 0., 1.),
                                          ("back", "turn", "finish", 1., .1))]})
    runner, store, _ = _setup(site, caps=BOTH, map_binding_required=True)
    graph = store.active()[2]
    segments = [{"edge_id": "out", "forward": True, "s_from": 0., "s_to": 1.},
                {"edge_id": "back", "forward": True, "s_from": 0., "s_to": .9}]
    view = {"state": "running", "map_version": 1, "segment_index": 0, "repeat": False,
            "plan": {"segments": segments},
            "detail": {"nav2_binding_id": "bind-1", "uturn_handoff": {"index": 0, "phase": "approaching"}}}
    live = LiveTrip(view, graph, {"to": "finish", "drive_mode": "nav2"})
    assert TripProgress._strict_named_stop(runner, live, 0) is None
    assert TripProgress._strict_named_stop(runner, live, 1).id == "finish"
    live.request.pop("drive_mode")
    view["detail"]["uturn_handoff"]["phase"] = "running"
    assert TripProgress._strict_named_stop(runner, live, 1).id == "finish"


def test_cue_single_failure_expires_at_two_seconds_and_success_resets_streak():
    monitor, now, back = cue_monitor([{"accepted": True}, TimeoutError(), {"accepted": True}, TimeoutError()])
    run(monitor._send_cue("r1", back, now[0]))
    now[0] += .5
    run(monitor._send_cue("r1", back, now[0]))
    now[0] += 1.9
    assert monitor.cue_refusal("r1") == "pending"  # acceptance expired; no new lane owner
    now[0] += .1
    assert monitor.cue_refusal("r1") == "unknown"
    run(monitor._send_cue("r1", back, now[0]))
    run(monitor._send_cue("r1", back, now[0]))
    assert monitor.cue_refusal("r1") is None


@pytest.mark.parametrize("reason", ["disabled", "pose_stale", "epoch_busy"])
def test_explicit_cue_refusal_is_immediate(reason):
    monitor, now, back = cue_monitor([{"accepted": True}, {"accepted": False, "reason": reason}])
    run(monitor._send_cue("r1", back, now[0]))
    run(monitor._send_cue("r1", back, now[0]))
    assert monitor.cue_refusal("r1") == reason


def test_cue_support_requires_recent_acceptance_and_probe_waits_on_first_timeout():
    monitor, now, back = cue_monitor([{"accepted": True}, TimeoutError()])
    assert monitor.cue_refusal("r1") == "unknown"
    run(monitor._send_cue("r1", back, now[0]))
    now[0] += 1.99
    assert monitor.cue_refusal("r1") is None
    now[0] += .02
    assert monitor.cue_refusal("r1") == "unknown"
    monitor._latest["r1"]["at"] = now[0]
    assert run(monitor.check_cue("r1")) == "pending"


def test_stopped_supported_robot_keeps_cue_support_without_repeating_clear():
    sent = []

    async def send(body):
        sent.append(body)
        return {"accepted": True}

    now = [100.]
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=None, site_maps=None, wall=lambda: now[0],
                                    clients=lambda: {"r1": NS(line_follow_lane_cue=send)})
    back = {"state": "ON_LANE", "raw": "ON_LANE", "moving": True, "pose_stamp": 100.,
            "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": 180.,
            "offset_m": 0., "edge_id": "back", "guide": None, "turn_spot": False, "context": None}
    monitor._latest["r1"] = {"at": now[0], "return": back}
    run(monitor._send_cue("r1", back, now[0]))
    back["moving"] = False
    for _ in range(12):
        now[0] += .5
        run(monitor._send_cue("r1", back, now[0]))
        assert monitor.cue_refusal("r1") is None
    assert len(sent) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_explicit_cue_http_contract_refusal_holds_immediately(status):
    monitor, now, back = cue_monitor([{"accepted": True}, RobotApiError("r1", status, "REFUSED", "no cue")])
    run(monitor._send_cue("r1", back, now[0]))
    run(monitor._send_cue("r1", back, now[0]))
    assert monitor.cue_refusal("r1") == "REFUSED"


def test_explicit_nav2_precision_stop_refuses_before_pose_or_planning(monkeypatch):
    from fleet.server import trip_routes

    runner, store, ports = _setup(uturn_site(), caps=BOTH, map_binding_required=False)
    monkeypatch.setattr(trip_routes, "commissioned_stop", lambda *_: NS())

    def forbidden(*_):
        pytest.fail("the commissioned-stop refusal must precede pose reads and planning")

    monkeypatch.setattr(trip_routes, "plan_trip", forbidden)
    monkeypatch.setattr(trip_routes, "read_precision_pose", forbidden)
    with pytest.raises(HTTPException) as refused:
        run(planner(runner, store, ports)("rosy_60", TripRequest(to="finish", drive_mode="nav2"), "bob"))
    assert refused.value.detail["code"] == "PRECISION_STOP_REQUIRES_NAV2_TERMINAL"


@pytest.mark.parametrize("failure", ["FAILED", "CANCELED", "prefix_failed", "prefix_canceled",
                                      "stall", "refused", "api_refused", "timeout"])
def test_uturn_without_arrival_enters_operator_hold(failure):
    runner, store, ports = _setup(uturn_site(), caps=BOTH, map_binding_required=False)
    _plan(store, ports, "out:fwd", .2, "finish")

    async def state(_):
        nav = {"prefix_failed": "FAILED", "prefix_canceled": "CANCELED"}.get(failure, failure)
        return {"navigation": nav if nav in ("FAILED", "CANCELED") else "NAVIGATING",
                "map_id": store.active()[1].map_id}

    async def route(*_, **__):
        if failure == "refused":
            return {"accepted": False, "reason": "blocked"}
        if failure == "timeout":
            raise TimeoutError()
        if failure == "api_refused":
            raise RobotApiError("rosy_60", 409, "NAVIGATION_REFUSED", "refused")
        return {"accepted": True}

    runner._robot_state, runner._route = state, route
    run(runner.start("p1", "bob"))
    live = runner._live["rosy_60"]
    if failure in ("FAILED", "CANCELED", "stall", "prefix_failed", "prefix_canceled"):
        live.active_route = {"end_index": 0}
    if failure.startswith("prefix_"):
        live.active_route["wait_prefix"] = True
        live.view["detail"]["wait_prefix"] = {"place": "turn"}
    _ticks(runner, ports)
    if failure == "stall":
        _ticks(runner, ports, dt=runner.config.stall_s + .1)
    assert live.open and live.view["hold"]["reason"] == "fleet_hold"
    assert live.view["hold"]["code"] in ("TRIP_NAVIGATION_ABORTED", "TRIP_STALL", "TRIP_GOAL_REFUSED",
                                         "TRIP_ROBOT_UNREACHABLE", "NAVIGATION_REFUSED")
    assert ports.canceled and ports.held and not ports.line_starts


@pytest.mark.parametrize("stop", ["cancel", "estop"])
def test_uturn_lane_stop_turns_line_follow_off(stop):
    runner, store, ports = _setup(uturn_site(), caps=BOTH, map_binding_required=False)
    _plan(store, ports, "out:fwd", .2, "finish")
    run(runner.start("p1", "bob"))
    live = runner._live["rosy_60"]
    live.request.pop("drive_mode")
    live.view["detail"]["uturn_handoff"]["phase"] = "running"
    live.view["segment_index"] = 1
    run(ports.start_camera_line("rosy_60"))
    if stop == "cancel":
        run(runner.cancel("p1", "bob"))
    else:
        run(runner.halt_closed(runner.close_all("operator_estop")))
    assert not live.open and live.view["detail"]["stop_sent"]
    assert ports.core.mode == "OFF" and ports.held == ["rosy_60"]


@pytest.mark.parametrize("nav2", [False, True])
def test_no_uturn_keeps_requested_lane_or_nav2_owner(nav2):
    runner, store, ports = _setup(caps=BOTH, map_binding_required=False)
    plan = _plan(store, ports, "ring_s:fwd", .1, "SE")
    if nav2:
        row = store.plan("p1")
        store.record_plan(plan_id="p2", robot_id="rosy_60", principal_id="bob", map_version=plan.map_version,
                          request={**row["request"], "drive_mode": "nav2"}, result=row["result"])
    view = run(runner.start("p2" if nav2 else "p1", "bob"))
    live = runner._live["rosy_60"]
    assert "uturn_handoff" not in view["detail"]
    assert live.nav2 is nav2 and live.segment_is_lane(0) is not nav2


def test_running_lane_keeps_two_cue_transport_misses_then_holds():
    runner, store, ports = _setup(caps=BOTH, map_binding_required=False)
    _plan(store, ports, "ring_s:fwd", .1, "NW")
    run(runner.start("p1", "bob"))
    live = runner._live["rosy_60"]
    live.view["detail"]["uturn_handoff"] = {"index": 0, "phase": "running"}
    monitor, now, back = cue_monitor([{"accepted": True}, TimeoutError(), TimeoutError(), TimeoutError()])
    run(monitor._send_cue("r1", back, now[0]))
    runner.lane_cue_refusal = lambda _: monitor.cue_refusal("r1")
    for attempt in range(1, 4):
        now[0] += .5
        run(monitor._send_cue("r1", back, now[0]))
        _ticks(runner, ports)
        if attempt < 3:
            assert live.open and live.view["hold"] is None
    assert live.open and live.view["hold"]["reason"] == "fleet_hold"
    assert live.view["hold"]["detail"]["reason"] == "unknown"
    assert ports.core.mode == "OFF"


def test_cue_expiring_during_admission_retries_without_operator_hold(monkeypatch):
    from fleet.server import trip_uturn_lane

    async def pending(*_):
        raise TripError(409, "TRIP_LANE_CUE_PENDING")

    monkeypatch.setattr(trip_uturn_lane, "start_uturn_lane", pending)
    live = NS(view={"hold": None}, open=True, arc=lambda _: NS(drive_mode="lane"))
    runner = NS(traffic=NS(holds=lambda *_: False))
    run(trip_uturn_lane.uturn_handoff_or_hold(runner, live, 1))
    assert live.view["hold"] is None
