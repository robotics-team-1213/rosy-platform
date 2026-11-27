"""A U-turn is a Nav2 stop/rotation followed by mandatory camera lanes."""
import math
from types import SimpleNamespace as NS

import pytest

from fleet.routing.cost import RoutingConfig
from fleet.routing.execute import unsupported, uturn_lane_index
from fleet.server.nav2_route_sampling import sample_nav2_route
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_progress import TripProgress
from fleet.server.trip_ports import TripError
from fleet.server import trip_nav2_route, trip_uturn_lane
from fakes import run


def route():
    incoming = NS(edge_id="out", drive_mode="lane", end_tangent=0., start_tangent=0., length_m=1.,
                  robot_kinds=None, end_place="turn", point_at=lambda s: (s, 0., 0.))
    outgoing = NS(edge_id="back", drive_mode="lane", end_tangent=math.pi, start_tangent=math.pi, length_m=1.,
                  robot_kinds=None, end_place="stop", point_at=lambda s: (1. - s, 0., math.pi))
    graph = NS(arcs={"out:fwd": incoming, "back:fwd": outgoing},
               places={"turn": NS(kind="turnaround"), "stop": NS(kind="stop")})
    segments = [{"edge_id": edge, "forward": True, "s_from": 0., "s_to": 1.}
                for edge in ("out", "back")]
    return graph, segments


def test_only_a_real_turn_with_a_painted_suffix_selects_the_handoff():
    graph, segments = route()
    assert uturn_lane_index(graph, segments, RoutingConfig()) == 0
    graph.arcs["back:fwd"].start_tangent = 0.
    assert uturn_lane_index(graph, segments, RoutingConfig()) is None
    graph.arcs["back:fwd"].start_tangent = math.pi
    graph.arcs["back:fwd"].drive_mode = "free"
    assert uturn_lane_index(graph, segments, RoutingConfig()) is None


def test_explicit_nav2_cannot_bypass_suffix_junction_capability():
    graph, segments = route()
    why = unsupported(graph, segments, kind="pinky_pro", modes={"lane", "free"},
                      junction_turn=False, config=RoutingConfig(), nav2=True)
    assert why == {"edge_id": "back", "reason": "JUNCTION_TURN_UNSUPPORTED"}
    assert unsupported(graph, segments, kind="pinky_pro", modes={"lane", "free"},
                       junction_turn=True, config=RoutingConfig(), nav2=True) is None
    assert unsupported(graph, segments, kind="pinky_pro", modes={"lane", "free"},
                       junction_turn=True, config=RoutingConfig(), nav2=False)["reason"] == "LANE_UTURN"


def test_sampler_keeps_one_terminal_stop_for_the_handoff_yaw():
    graph, segments = route()
    points = sample_nav2_route(graph, segments, 0, 0., 0)
    assert points[-1] == (1., 0., 0., "stop")
    assert sum(point[3] == "stop" for point in points) == 1
    assert len(points) <= 64
    assert all(point[0] >= 0. for point in points)


@pytest.mark.parametrize(("refusal", "problem", "code"), [
    (None, None, None), ("disabled", None, "TRIP_MODE_UNSUPPORTED"),
    ("pending", None, "pending"),
    ("unknown", None, "TRIP_MODE_UNSUPPORTED"),
    (None, "camera", "TRIP_LANE_CAMERA_UNAVAILABLE"),
    (None, "heading", "TRIP_CAMERA_FALLBACK_POSE_UNTRUSTED"),
    (None, "stop", "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED"),
    (None, "cue_pending", "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED"),
    (None, "lease", "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED")])
def test_lane_handoff_never_replaces_a_refused_camera_with_nav2(monkeypatch, refusal, problem, code):
    graph, segments = route()
    graph.arcs["back:fwd"].project = lambda x, y: (0., 1. - x, math.pi)  # (distance, s, tangent) like Arc.project
    graph.arcs["back:fwd"].width_m = .4
    view = {"robot_id": "r1", "trip_id": "trip", "state": "running", "map_version": 1,
            "plan": {"segments": segments, "actions": [{"place_id": "stop"}]},
            "segment_index": 0, "caps": {"kind": "pinky_pro"},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}, "hold": None}
    live = NS(view=view, graph=graph, segments=segments, open=True, repeat=False, request={"drive_mode": "nav2"},
              arc=lambda i: graph.arcs[("out:fwd", "back:fwd")[i]], active_route={"end_index": 0})
    events = []
    clock = [100.]

    async def stationary(*_):
        events.append("stationary")
        return None if problem == "stop" else (99. if problem == "lease" else 110.)

    async def caps(*_, **__):
        return NS(line_follow_authority_required=True)

    async def front(_):
        return {"available": problem != "camera", "stale": False, "age_ms": 0}

    pose = NS(x=1., y=0., yaw=0. if problem == "heading" else math.pi,
              odom_stamp=100., age_s=0., state="LOCALIZED")

    async def read_pose(_):
        return pose

    async def start(_):
        events.append("camera")

    async def call(value):
        return await value

    async def probe(_):
        return refusal

    runner = NS(
        _caps_checks=caps, _call=call, _clock=lambda: clock[0], map_pose=read_pose,
        _junction=NS(front_camera=front),
        lane_cue_refusal=lambda _: "pending" if problem == "cue_pending" else refusal, lane_cue_check=probe,
        named_stop_state=front,
        _check_human_hold=lambda: None, _start_line=start, _save=lambda _: None, _describe=lambda _: None,
        _store=NS(active=lambda: (1, NS()), map_bindings=NS(active=lambda _: {})),
        authority=NS(mode=lambda _: "core"), traffic=NS(holds=lambda *_: False),
        lease=NS(required=True), config=NS(start_heading_tol_deg=15.),
    )
    monkeypatch.setattr(trip_uturn_lane, "_camera_stationary", stationary)
    if code == "pending":
        run(trip_uturn_lane.start_uturn_lane(runner, live, 1))
        assert events == ["stationary"]
        assert view["hold"] is None and view["segment_index"] == 0
        assert view["detail"]["uturn_handoff"]["phase"] == "approaching"
    elif code:
        with pytest.raises(TripError) as error:
            run(trip_uturn_lane.start_uturn_lane(runner, live, 1))
        assert error.value.code == code
        assert "camera" not in events
    else:
        run(trip_uturn_lane.start_uturn_lane(runner, live, 1))
        assert events == ["stationary", "camera"]
        assert live.request.get("drive_mode") is None
        assert view["segment_index"] == 1


def test_projection_cannot_consume_cusp_before_native_heading_stop():
    graph, segments = route()
    graph.arcs["out:fwd"].project = lambda *_: (0., 1., 0.)
    graph.arcs["back:fwd"].project = lambda *_: (0., .01, 0.)
    for arc in graph.arcs.values():
        arc.width_m = .4
    live = NS(view={"segment_index": 0, "hold": None, "detail": {
        "uturn_handoff": {"index": 0, "phase": "approaching"}}},
        segments=segments, nav2=True, arc=lambda i: graph.arcs[("out:fwd", "back:fwd")[i]])
    runner = NS(_named_stop_handoff=lambda *_: False, config=NS(nav2_off_lane_margin_m=.06))
    assert TripProgress._locate(runner, live, NS(x=1., y=0.))[0] == 0


def test_free_to_lane_projection_waits_for_camera_admission():
    graph, segments = route()
    graph.arcs["out:fwd"].drive_mode = "free"
    graph.arcs["out:fwd"].project = lambda *_: (.01, 1., 0.)
    graph.arcs["back:fwd"].project = lambda *_: (0., .1, 0.)
    for arc in graph.arcs.values():
        arc.width_m = .4
    view = {"segment_index": 0, "hold": None, "plan": {"segments": segments},
            "detail": {"uturn_handoff": {"phase": "running"}}}
    live = LiveTrip(view, graph, {})
    assert TripProgress._locate(NS(), live, NS(x=1., y=0.))[0] == 0


@pytest.mark.parametrize("code", ["TRIP_MODE_UNSUPPORTED", "TRIP_LANE_CAMERA_UNAVAILABLE",
                                  "TRIP_CAMERA_FALLBACK_STOP_UNCONFIRMED", "TRIP_LINE_FOLLOW_START_FAILED"])
def test_refused_handoff_holds_with_reason_and_confirms_stop(monkeypatch, code):
    graph, segments = route()
    view = {"state": "running", "detail": {"uturn_handoff": {"phase": "approaching"}}, "hold": None}
    live = NS(view=view, open=True, arc=lambda i: graph.arcs["back:fwd"])
    events = []

    async def refused(*_):
        raise TripError(409, code, {"reason": "disabled"})

    async def pause(live):
        events.append("stop")
        live.view["hold"]["stop"]["confirmed"] = True

    runner = NS(traffic=NS(holds=lambda *_: False), _clock=lambda: 100.,
                _check_pause=pause, _describe=lambda _: None, _save=lambda _: None)
    monkeypatch.setattr(trip_uturn_lane, "start_uturn_lane", refused)
    run(trip_uturn_lane.uturn_handoff_or_hold(runner, live, 1))
    assert live.open and view["state"] == "running"
    assert view["hold"]["reason"] == "fleet_hold"
    assert view["hold"]["code"] == code
    assert view["hold"]["stop"]["confirmed"] is True
    assert events == ["stop"]


def test_resume_after_camera_off_reenters_lane_admission():
    import asyncio
    from fleet.server.trip_replan import TripReplan

    graph, segments = route()
    view = {"robot_id": "r1", "trip_id": "trip", "state": "running", "map_version": 1,
            "plan": {"segments": segments}, "segment_index": 1,
            "detail": {"uturn_handoff": {"index": 0, "phase": "running"}, "line_follow_started": True},
            "hold": {"reason": "fleet_hold", "plan": None, "stop": {"confirmed": True}}}
    live = LiveTrip(view, graph, {"to": "stop"})

    async def caps(*_, **__):
        return None

    runner = NS(_open=lambda _: live, _lock_for=lambda _: asyncio.Lock(),
                _store=NS(active=lambda: (1, NS(), graph)), _caps_checks=caps,
                _clock=lambda: 100., _describe=lambda _: None, _save=lambda _: None)
    run(TripReplan.resume(runner, "trip", "operator"))
    assert live.nav2 is False
    assert view["hold"] is None
    assert view["detail"]["uturn_handoff"]["phase"] == "starting"
    assert view["detail"]["line_follow_started"] is False


def test_free_prefix_dispatch_ends_at_cusp_with_one_outgoing_heading_stop(monkeypatch):
    graph, segments = route()
    view = {"robot_id": "r1", "state": "running", "map_version": 1, "hold": None,
            "segment_index": 0, "plan": {"segments": segments},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}}
    live = LiveTrip(view, graph, {"drive_mode": "nav2"})
    payloads = []

    class Captured(Exception):
        pass

    async def call(value):
        return await value

    async def state(_):
        return {"navigation": "IDLE"}

    async def ready(*_):
        return True

    async def send(_, points, **__):
        payloads.append(points)
        raise Captured

    runner = NS(_store=NS(active=lambda: (1, NS(walls=()), graph), rules=NS(active_rules=lambda: None)),
                _call=call, _robot_state=state, traffic=NS(holds=lambda *_: False),
                _clock=lambda: 100., config=NS(map_binding_required=False, arrive_free_m=.15),
                _route=send)
    monkeypatch.setattr(trip_nav2_route, "ready_free_goal", ready)
    monkeypatch.setattr(trip_nav2_route, "_convert_points", lambda *args: (args[3], None))
    with pytest.raises(Captured):
        run(trip_nav2_route.step_nav2_route(runner, live, 0, 0., NS()))
    points = payloads[0]
    assert points[-1] == {"x": 1., "y": 0., "yaw": round(math.pi, 4), "kind": "stop"}
    assert sum(point["kind"] == "stop" for point in points) == 1
    assert all(point["x"] > 0 for point in points)


def test_superseded_arrival_cannot_start_a_new_lane_owner(monkeypatch):
    graph, segments = route()
    view = {"robot_id": "r1", "state": "running", "map_version": 1, "hold": None,
            "segment_index": 0, "plan": {"segments": segments},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}}
    live = LiveTrip(view, graph, {"drive_mode": "nav2"})
    live.active_route = {"end_index": 0, "superseded": True}

    class CancelOld(Exception):
        pass

    async def state(_):
        return {"navigation": "ARRIVED"}

    async def call(value):
        return await value

    async def cancel(*_):
        raise CancelOld

    async def forbidden(*_):
        pytest.fail("an old route cannot admit CAMERA_LINE")

    runner = NS(_store=NS(active=lambda: (1, NS(), graph)), _call=call, _robot_state=state,
                traffic=NS(holds=lambda *_: False), config=NS(map_binding_required=False))
    monkeypatch.setattr(trip_nav2_route, "_cancel_active_route", cancel)
    monkeypatch.setattr(trip_nav2_route, "uturn_handoff_or_hold", forbidden)
    with pytest.raises(CancelOld):
        run(trip_nav2_route.step_nav2_route(runner, live, 0, 1., NS()))


def test_cue_probe_does_not_trust_past_acceptance_when_core_is_disabled():
    from fleet.server.lane_compliance_service import LaneComplianceMonitor

    calls = []

    async def cue(body):
        calls.append(body)
        return {"accepted": False, "reason": "disabled"}

    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=None, site_maps=None,
                                    clients=lambda: {"r1": NS(line_follow_lane_cue=cue)}, wall=lambda: 100.)
    monitor._cue_sent["r1"] = "ON_LANE"
    back = {"state": "ON_LANE", "raw": "ON_LANE", "moving": False, "pose_stamp": 100.,
            "side": None, "bearing_deg": None, "turn_deg": None, "lane_heading_deg": 180.,
            "offset_m": 0., "edge_id": "back", "guide": None, "turn_spot": False, "context": None}
    monitor._latest["r1"] = {"at": 100., "return": back}
    assert run(monitor.check_cue("r1")) == "disabled"
    assert len(calls) == 1  # a stationary ON_LANE robot is probed too
    assert monitor.cue_refusal("r1") == "disabled"


@pytest.mark.parametrize(("phase", "superseded", "confirmed"), [
    ("approaching", False, True), ("approaching", True, False), ("starting", False, False)])
def test_arrived_prefix_hold_uses_same_wire_measured_stop_without_cancel_ack(phase, superseded, confirmed):
    from fleet.server.trip_replan import TripReplan

    events = []
    view = {"robot_id": "r1", "segment_index": 0, "hold": {"reason": "fleet_hold"},
            "detail": {"uturn_handoff": {"index": 0, "phase": phase}}}
    live = NS(view=view, active_route={"end_index": 0, "nav_state": "ARRIVED", "superseded": superseded},
              last_goal=None)

    async def cancel(_):
        return {"navigation": "ARRIVED", "operation": None}

    async def off(_):
        events.append("off")
        return {"mode": "OFF"}

    async def measured(rid, after, nav, wire):
        assert (rid, after, nav, wire) == ("r1", 100., "ARRIVED", "wire")
        events.append("measured")
        return {"navigation": "ARRIVED", "sampled_at": "fresh-after-cancel"}

    async def call(value):
        return await value

    runner = NS(config=NS(restart_retry_s=2.), _clock=lambda: 100., _call=call,
                _cancel_goal=cancel, _junction=NS(hold=off), _fence=lambda _: None,
                halts=NS(idle_wire=lambda _: "wire", measured_ended_stop=measured))
    assert run(TripReplan._check_pause(runner, live)) is confirmed
    assert events == (["off", "measured"] if confirmed else ["off"])
    assert view["hold"]["stop"]["confirmed"] is confirmed


def test_arrived_prefix_keeps_idle_owner_until_a_fresh_stop_sample_arrives():
    from datetime import datetime, timezone
    from fleet.server.trip_replan import TripReplan

    owner = {"boot_id": "boot", "owner_run_id": None, "owner_generation": 0,
             "transport_generation": 0, "mode_epoch": 0, "dock_owner_generation": 0}
    clock, calls = [100.], []
    view = {"robot_id": "r1", "segment_index": 0, "hold": {"reason": "fleet_hold"},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}}
    live = NS(view=view, active_route={"end_index": 0, "nav_state": "ARRIVED"}, last_goal=None)

    async def cancel(_):
        calls.append("cancel")
        return {"navigation": "IDLE", "operation": None, "idle_owner": owner,
                "idle_observed_at": datetime.fromtimestamp(100., timezone.utc).isoformat()}

    async def off(_):
        return {"mode": "OFF"}

    async def measured(*_):
        return None if clock[0] == 100. else {"basis": "pre_dispatch_idle"}

    async def call(value):
        return await value

    runner = NS(config=NS(restart_retry_s=2.), _clock=lambda: clock[0], _call=call,
                _cancel_goal=cancel, _junction=NS(hold=off), _fence=lambda _: None,
                halts=NS(idle_wire=lambda _: "wire", measured_idle_stop=measured))
    assert run(TripReplan._check_pause(runner, live)) is False
    clock[0] = 100.5
    assert run(TripReplan._check_pause(runner, live)) is True
    assert calls == ["cancel"]


@pytest.mark.parametrize(("phase", "lane", "dual"), [
    ("approaching", False, False), ("starting", False, True), ("running", True, False)])
def test_restart_keeps_terminal_proof_for_known_owner_and_stops_both_only_during_put(phase, lane, dual):
    from fleet.server.trip_halts import TripHalts

    calls = []

    async def halt(rid, is_lane, place, *, handoff_pending, terminal, **kwargs):
        calls.append((is_lane, handoff_pending, terminal))
        return {"stop_sent": True}

    runner = NS(dock_owned=lambda _: False, halt_robot=halt,
                _store=NS(put_trip=lambda _: None), _clock=lambda: 100.)
    trip = {"robot_id": "r1", "trip_id": "trip", "drive_mode": "lane" if lane else "free",
            "next_place": "stop", "detail": {"uturn_handoff": {"phase": phase}}}
    assert run(TripHalts._retry_trip_entry(runner, trip)) is True
    assert calls == [(lane, dual, True)]


def test_lane_suffix_keeps_existing_precision_terminal_handoff():
    from fleet.routing.execute import lane_action

    graph, segments = route()
    graph.arcs["back:fwd"].end_place = "stage"
    graph.arcs["terminal:fwd"] = NS(drive_mode="free", length_m=.2, end_place="stop",
                                      point_at=lambda s: (-s, 0., math.pi))
    segments.append({"edge_id": "terminal", "forward": True, "s_from": 0., "s_to": .2})
    graph.places["stop"] = NS(id="stop", kind="stop", x=-.2, y=0., precision_stop=NS())
    view = {"state": "running", "segment_index": 0, "repeat": False, "plan": {"segments": segments},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}}
    live = LiveTrip(view, graph, {"to": "stop", "drive_mode": "nav2"})
    runner = TripProgress()
    assert runner._precision_terminal_mismatch(live) is False
    live.request.pop("drive_mode")
    view["detail"]["uturn_handoff"]["phase"] = "running"
    assert lane_action(graph, segments, 1, RoutingConfig()) == "stop"
    assert runner._named_stop_handoff(live, 2) is True
    assert runner._precision_terminal_matches(graph, segments, graph.places["stop"]) is True


def test_stop_zone_extension_cannot_add_an_untracked_nav2_uturn(monkeypatch):
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    from fleet.server import trip_runner
    from fleet.site_map import SiteMap
    from test_trip_runner import BOTH, _setup

    site = SiteMap.model_validate({
        "places": [{"id": p, "name": p, "kind": kind, "x": x, "y": 0.}
                   for p, kind, x in (("start", "junction", 0.), ("turn", "turnaround", 1.),
                                      ("finish", "stop", .1))],
        "edges": [{"id": edge, "from": a, "to": b, "direction": "one_way", "drive_mode": "lane",
                   "polyline": [[x, 0.], [y, 0.]], "width_m": .4, "speed_cap_mps": .2}
                  for edge, a, b, x, y in (("out", "start", "turn", 0., 1.),
                                          ("back", "turn", "finish", 1., .1))]})
    runner, store, ports = _setup(site_map=site, caps=BOTH, map_binding_required=False)
    version, _, graph, *_ = store.active()
    ports.at(graph.arcs["out:fwd"], .1)
    original = plan_body(plan_trip(graph, PlanRequest(map_version=version, start_pose=(.1, 0., 0.), goal="turn"),
                                   store.routing_config))
    request = {"to": "turn", "drive_mode": "nav2"}
    store.record_plan(plan_id="extended", robot_id="rosy_60", principal_id="operator", map_version=version,
                      request=request, result={"plan": original})
    extended = {**original, "segments": [*original["segments"],
                 {"edge_id": "back", "forward": True, "s_from": 0., "s_to": .9}],
                "actions": [{"place_id": "finish", "action": "stop", "theta_deg": 0.}]}
    monkeypatch.setattr(trip_runner, "stop_points", lambda *_: (
        extended, {**request, "to": "finish"}, [], (), None))
    view = run(runner.start("extended", "operator"))
    assert view["detail"]["uturn_handoff"] == {"index": 0, "phase": "approaching"}
    assert runner._live["rosy_60"].nav2 is True


def test_check_time_cue_pending_holds_instead_of_stranding_starting_phase(monkeypatch):
    graph, segments = route()
    graph.arcs["back:fwd"].project = lambda x, y: (0., 1. - x, math.pi)
    graph.arcs["back:fwd"].width_m = .4
    view = {"robot_id": "r1", "trip_id": "trip", "state": "running", "map_version": 1,
            "plan": {"segments": segments, "actions": [{"place_id": "stop"}]},
            "segment_index": 0, "caps": {"kind": "pinky_pro"},
            "detail": {"uturn_handoff": {"index": 0, "phase": "approaching"}}, "hold": None}
    live = NS(view=view, graph=graph, segments=segments, open=True, repeat=False, request={"drive_mode": "nav2"},
              arc=lambda i: graph.arcs[("out:fwd", "back:fwd")[i]], active_route={"end_index": 0})
    events = []

    async def stationary(*_):
        return 110.

    async def caps(*_, **__):
        return NS(line_follow_authority_required=True)

    async def front(_):
        return {"available": True, "stale": False, "age_ms": 0}

    async def read_pose(_):
        return NS(x=1., y=0., yaw=math.pi, odom_stamp=100., age_s=0., state="LOCALIZED")

    async def start(_):
        events.append("camera")

    async def call(value):
        return await value

    async def probe(_):
        return None

    async def pause(live):
        events.append("stop")
        live.view["hold"]["stop"]["confirmed"] = True

    runner = NS(
        _caps_checks=caps, _call=call, _clock=lambda: 100., map_pose=read_pose,
        _junction=NS(front_camera=front),
        lane_cue_refusal=lambda _: "pending", lane_cue_check=probe,
        named_stop_state=front, _check_pause=pause,
        _check_human_hold=lambda: None, _start_line=start, _save=lambda _: None, _describe=lambda _: None,
        _store=NS(active=lambda: (1, NS()), map_bindings=NS(active=lambda _: {})),
        authority=NS(mode=lambda _: "core"), traffic=NS(holds=lambda *_: False),
        lease=NS(required=True), config=NS(start_heading_tol_deg=15.),
    )
    monkeypatch.setattr(trip_uturn_lane, "_camera_stationary", stationary)
    run(trip_uturn_lane.uturn_handoff_or_hold(runner, live, 1))
    assert events == ["stop"]
    assert view["hold"]["reason"] == "fleet_hold"
    assert view["hold"]["code"] == "TRIP_CAMERA_FALLBACK_ADMISSION_CHANGED"
    assert view["hold"]["stop"]["confirmed"] is True
    assert view["detail"]["uturn_handoff"]["phase"] != "starting"

