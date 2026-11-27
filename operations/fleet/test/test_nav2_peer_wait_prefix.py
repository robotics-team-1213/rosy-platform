"""A downstream refusal may dispatch only a positively checked intermediate waiting place."""
import asyncio
import math
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from fleet.server import trip_nav2_route as nav2
from fleet.server.peer_wait_prefix import check_wait_prefix, downstream_refusal, prefix_guard, reserved_wait
from fleet.server.traffic_arbitration_helpers import guarded_road_send
from fleet.swarm.dispatch_guard import check_dispatch
from fleet.traffic.lane_traffic import TrafficService
from fakes import FakeClock, run


def snapshot():
    clock = FakeClock()
    lengths = [0., 0.6, 1.0]
    segs = [{"s_from": 0., "s_to": length} for length in lengths]
    places = {pid: NS(id=pid, kind="stop", precision_stop=None, stop_zone=None, x=x, y=0.)
              for pid, x in zip(("bay", "W", "D"), (0., .6, 1.6))}
    graph = NS(places=places)
    active = (3, NS(map_id="site", crosswalks=[]), graph)
    rules = NS(stops=[NS(place=pid, role="wait") for pid in places])
    store = NS(active=lambda: active, rules=NS(active_rules=lambda: rules))
    table = NS(_zones={}, _store=store, holds=lambda live, i: False)
    table._seen = {"m": ("t:1", 0., [NS(unit="a", forward=True, d0=0., d1=.4),
                                      NS(unit="b", forward=True, d0=.4, d1=1.1)])}
    table._state = NS(route={"m": "t:1"}, held={"m": {0: ("a", True), 1: ("b", True)}})
    table.owns_span = lambda *args: TrafficService.owns_span(table, *args)
    runner = NS(_clock=clock, config=NS(arrive_free_m=.05, map_binding_required=True),
                road_speed=NS(renew=lambda *args: asyncio.sleep(0)), _store=store, traffic=table)
    live = NS(open=True, nav2_binding_scope=(3, "binding"), graph=graph, segments=segs,
              view={"robot_id": "m", "trip_id": "t", "map_version": 3, "caps": {"kind": "pinky_pro"}, "hold": None,
                    "pose": {"state": "LOCALIZED", "x": 0., "y": 0.}, "detail": {
                        "goal_frame": {"map_id": "site", "map_version": 3, "map_grid_id": "g", "binding_id": "b"}}},
              place=lambda i: tuple(places)[i], progress=lambda i, s: sum(lengths[:i]) + s,
              request={"to": "D"}, arc=lambda i: NS(point_at=lambda s: (sum(lengths[:i]) + s, 0., 0.),
                                                    knots=(), polyline=()),
              repeat=False, convoy=None, at=(0, 0.), traffic={"authority_end_m": 1.1, "front_d_m": .08,
              "pose_stamp": clock()}, route_rev=1, trim_m=0., active_route=None, nav2_retry_at=0.)
    return runner, live, active


def refusal():
    return {"reason": "LOCALIZATION_UNTRUSTED", "accepted": False, "queued": False, "blocked_by": "p",
            "command_robot_id": "m", "site_route_map": "site", "dispatch_attempted": False, "waiting_on": ["p"], "stage": "pre_dispatch_peer_check",
            "peer_evidence": {"p": {"reason": "keep_out_intersection"}}}


def test_wait_place_requires_a_real_intermediate_stop_and_current_reservation():
    runner, live, active = snapshot()
    choose = lambda: reserved_wait(runner, live, active, *live.at, 2)[0]
    assert choose() == 1  # the starting bay is zero-length
    live.at = 1, .58
    assert choose() is None
    live.at = 0, 0.
    live.traffic["authority_end_m"] = .62
    assert choose() is None  # front footprint extends beyond authority
    live.traffic["authority_end_m"] = 1.1
    del runner.traffic._state.held["m"][0]
    assert choose() is None
    runner.traffic._state.held["m"][0] = ("a", True)
    live.route_rev += 1
    assert choose() is None
    live.route_rev -= 1
    runner._store.rules.active_rules().stops[1].role = "unload"
    assert choose() is None
    runner._store.rules.active_rules().stops[1].role = "wait"
    live.view["detail"]["parking_handoff"] = {"phase": "staging_confirmed"}
    assert choose() is None
    del live.view["detail"]["parking_handoff"]
    runner._clock.advance(3.)
    assert choose() is None


@pytest.mark.parametrize("change", [
    {"dispatch_attempted": True}, {"queued": True}, {"waiting_on": ["m"]}, {"peer_evidence": {}},
    {"stage": "post_dispatch"}, {"peer_evidence": {"p": {"reason": "peer_pose_conflict"}}},
])
def test_ambiguous_or_post_dispatch_refusal_never_starts_a_prefix(change):
    assert not downstream_refusal({**refusal(), **change}, "m")


def test_first_wait_past_an_observed_peer_cannot_be_used_even_with_full_reservation():
    runner, live, active = snapshot()
    live.view["detail"]["peer_wait"] = {"peer_evidence": {"p": {
        "reason": "keep_out_intersection", "observations": [{"x": .3, "y": .1, "keep_out_m": .4}]}}}
    assert reserved_wait(runner, live, active, *live.at, 2) == (None, "no_wait_before_peer_clearance")


@pytest.mark.parametrize("change", ["none", "ordinary_c2", "projection_changed", "already_blocked", "peer_disappears",
                                    "reservation_lost", "stale_mover", "offline_pin_only"])
def test_full_refusal_then_prefix_uses_both_normal_wire_gates(monkeypatch, change):
    runner, live, active = snapshot()
    ordinary = change in ("ordinary_c2", "projection_changed")
    if ordinary:
        live.nav2_binding_scope = None
        runner.config.map_binding_required = False
        live.request["to"] = "P2"
        live.view["detail"]["parking_handoff"] = {"bay_id": "C2", "dock_id": "bay_c2", "owner": "core_docking",
                                                  "phase": "approaching", "staging_place_id": "P2", "terminal_motion": "rear_dock"}
    from fleet.localization import trust
    native_x = 3.0 if ordinary else 0.
    native = {"pose": {"x": native_x, "y": 0., "yaw": 0.}, "navigation": "IDLE", "map_id": "native-map",
              "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    now = datetime.now(timezone.utc)
    native.update(pose_frame="map", odom_pose={"x": 0., "y": 0., "yaw": 0., "stamp": now.timestamp()},
                  evidence={"pose": {"evidence": "fresh", "received_at": now.isoformat()}})
    projected = {"x": 0.}
    pose = NS(x=0., y=0., yaw=0., state="LOCALIZED", map_id="site")
    peer = {"point": ("site", .6 if change == "already_blocked" else 1.5, 0.)}
    actual, attempts = [], []
    console = NS(_observe=lambda: asyncio.sleep(0), map=lambda: asyncio.sleep(0),
                 _order=["m", "p"], goal_leases=NS(check_stop=lambda rid, tok: None),
                 _pose_of=lambda rid: (native_x, 0.), _site_obstacle_pose=lambda rid: peer["point"], _site_keep_out_m=.32,
                 _seen={"m": native, "p": native}, _verdict=lambda _: trust.TRUSTED,
                 _site_mover_pose=lambda rid: ("site", projected["x"], 0., 0.) if rid == "m" else peer["point"])
    from fleet.server import traffic_arbitration_helpers as helpers
    monkeypatch.setattr(helpers, "road_peer_wait",
                        lambda *args: None if abs(args[2][-1]["x"] - native_x - .6) < .0001 else refusal())
    async def route(rid, points, **options):
        attempts.append(round(points[-1]["x"] - native_x, 4))
        async def send():
            if change == "peer_disappears":
                peer["point"] = None
            if change == "reservation_lost":
                live.traffic["authority_end_m"] = .1
            if change == "projection_changed":
                projected["x"] = .08
            if change == "stale_mover":
                native["odom_pose"]["stamp"] -= 5.
            if change == "offline_pin_only":
                console._site_marker_clearance = NS(offline={"p": 1}, clear=lambda *args: None)
            check_dispatch(path="/api/v1/navigation/bound-route" if "route_binding" in options else "/api/v1/navigation/route")
            actual.append((rid, points, options))
            return {"accepted": True, "road_speed_owner": "lease"}
        def project(pts):
            return helpers.site_route_for(console, rid, pts, trust_mod=trust)
        return await guarded_road_send(console, rid, points, (points[-1]["x"], 0.), "token", project, send,
                                       grid_from=lambda _: None, check_wait_prefix=check_wait_prefix)

    runner._route = route
    runner._robot_state = lambda _: asyncio.sleep(0, result=native)
    runner._call = lambda awaitable: awaitable
    runner._after_send = lambda _: asyncio.sleep(0)
    runner._fence = lambda _: None
    runner._strict_named_stop = lambda *_: None
    runner.autonomous_robots = set()
    monkeypatch.setattr(nav2, "ready_free_goal", lambda *_: asyncio.sleep(0, result=True))
    sampled_from = []  # the sampler gets the robot's site position (off-lane resend, 2026-11-27)
    monkeypatch.setattr(nav2, "sample_nav2_route", lambda graph, segs, index, s, end, **kw:
                        sampled_from.append(kw["here"]) or [(live.progress(end, segs[end]["s_to"]), 0., 0., "stop")])
    if not ordinary:
        monkeypatch.setattr(nav2, "_convert_points", lambda runner, live, active, pts, pose, state: (pts, None))
    run(nav2.step_nav2_route(runner, live, 0, 0., pose))
    assert live.view["detail"]["peer_wait"]["waiting_on"] == ["p"] and actual == []
    assert sampled_from and sampled_from[-1] == (pose.x, pose.y)
    if change in ("none", "peer_disappears"):
        from fleet.server.road_vision_demand import RoadVisionDemand
        rows = []
        cam = NS(source_id="cam", map_id="site", robot_markers=[("p",45)])
        runner.road_vision_demand = RoadVisionDemand(None, NS(sources=[cam], snapshot=lambda:{"sightings":rows},
                                                               approved_sighting_revision=lambda *_:"rev"))
        runner._clock.advance(.5)
        run(nav2.step_nav2_route(runner, live, 0, 0., pose))
        assert attempts == [1.6] and not actual
        rows.append({"robot_id":"p", "source_id":"cam", "seq":12, "captured_at":runner._clock()-.05,
                     "map_id":"site", "calibration_revision":"rev", "calibration_source":"approved_record"})
    else:
        runner._clock.advance(nav2.NAV2_TRANSIENT_RETRY_S)
    live.traffic["pose_stamp"] = runner._clock()
    run(nav2.step_nav2_route(runner, live, 0, 0., pose))
    assert attempts == [1.6, .6] and prefix_guard.get() is None
    if change in ("none", "ordinary_c2"):
        assert actual[0][0] == "m" and actual[0][1][-1]["kind"] == "stop"
        assert actual[0][2]["road_speed_controlled"] and "attempt_id" not in actual[0][2]
        assert live.active_route["end_index"] == 1 and live.active_route["wait_prefix"]
        assert live.view["detail"]["wait_prefix"]["place"] == "W"
        if change == "ordinary_c2":
            assert "route_binding" not in actual[0][2]
            assert actual[0][1][-1]["x"] == 3.6
            assert live.view["detail"]["parking_handoff"]["phase"] == "approaching" and live.request["to"] == "P2"
    else:
        assert not actual and live.active_route is None and live.view["detail"]["wait_prefix"]["state"] == "held"


@pytest.mark.parametrize("loss", ["stalled", "reservation", "owner", "trip_lease", "binding"])
def test_active_prefix_obeys_progress_watchdog_and_goal_ownership(monkeypatch, loss):
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    from fleet.server.trip_ports import TripError
    from test_trip_nav2_route import RouteFakeRobot, _console_runner, _south_loop_map

    bot = RouteFakeRobot("rosy_42")
    clock, console, store, graph, poses, canceled, runner = _console_runner(bot, _south_loop_map())
    pose = poses["v"]
    version = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(map_version=version, start_pose=(pose.x, pose.y, pose.yaw),
                         goal="S3", via=("S4", "S5"), stop_offset=False), store.routing_config))
    store.record_plan(plan_id="wait", robot_id=bot.robot_id, principal_id="bob", map_version=version,
                      request={"to": "S3", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("wait", "bob"))
    run(runner.tick())
    live = runner._live[bot.robot_id]
    assert live.active_route and len(bot.routes) == 1
    live.active_route.update(wait_prefix=True, end_index=2, road_speed_owner="prefix-owner")
    live.view["detail"]["wait_prefix"] = {"state": "dispatched", "place": live.place(2)}
    bot._state["navigation"] = "NAVIGATING"
    from fleet.server import peer_wait_prefix
    monkeypatch.setattr(peer_wait_prefix, "reservation_covers", lambda *_: loss != "reservation")  # supervised there
    renewals = []
    async def renew(_, trip, *args):
        renewals.append(trip.active_route["road_speed_owner"])
        if loss == "owner":
            raise TripError(409, "ROAD_SPEED_OWNER_CHANGED")
    runner.road_speed = NS(renew=renew)
    if loss == "binding":
        from dataclasses import replace
        runner.config = replace(runner.config, map_binding_required=True)
    # A peer can block the rest of the plan, while the prefix itself has authority.
    live.traffic["waiting_for"] = ["peer"]
    if loss == "trip_lease":
        run(runner._lease_lost(live, {"lease_error": "revoked"}))
    else:
        run(runner.tick())
        if loss == "stalled":
            assert live.open and renewals == ["prefix-owner"]
            clock.advance(runner.config.stall_s + .1)
            live.traffic["waiting_for"] = ["peer"]
            run(runner.tick())
    assert not live.open and canceled and bot.robot_id not in console.goal_leases
    assert live.view["reason"] == {"stalled": "stall", "reservation": "WAIT_PREFIX_RESERVATION_LOST",
                                   "owner": "ROAD_SPEED_OWNER_CHANGED", "trip_lease": "lease_lost", "binding": "map_frame"}[loss]
    assert len(bot.routes) == 1



# ---- table-cut hold point: depart, stop short of the peer, wait, continue (2026-11-27 rosy_45 live run) ----------

from core_common.robot_body import PINKY_PRO  # noqa: E402
from fleet.server.peer_wait_prefix import hold_point  # noqa: E402
from fleet.server.trip_live import trip_execution  # noqa: E402
from fleet.traffic.blocks import ZONE_STOP_CLEARANCE_M  # noqa: E402

CLEAR = PINKY_PRO.rotation_clear_m()
S_FROM, S_TO = 0.0228, 0.9867  # upper_west in the live capture: the trip starts mid-edge
CUT = S_TO  # route metres where rosy_46's pinned loop_left#0 begins (occupied_ahead_m 0.964 plan metres)


def hold_snapshot(lengths=((S_FROM, S_TO), (0., .5)), authority=.867):
    clock = FakeClock()
    segs = [{"s_from": a, "s_to": b, "edge_id": f"e{i}", "forward": True} for i, (a, b) in enumerate(lengths)]
    spans = [b - a for a, b in lengths]

    def progress(i, s):
        return sum(spans[:i]) + s - segs[i]["s_from"]

    curve = {}  # arc metre -> yaw after it (a corner), per test
    def point_at(i, s):
        x = S_FROM + progress(i, s)  # a straight lane in route metres along x
        return x, 0., next((yaw for at, yaw in curve.items() if i == 0 and s >= at), 0.)

    places = {"J_out": NS(id="J_out", kind="junction", x=S_TO, y=0.), "P3": NS(id="P3", kind="stop", x=S_TO + .5, y=0.)}
    graph = NS(places=places)
    active = (3, NS(map_id="site", crosswalks=[]), graph)
    store = NS(active=lambda: active, rules=NS(active_rules=lambda: None))
    owned = {"end": authority}
    table = NS(_store=store, _layout_for=lambda _active: None,
               holds=lambda lv, k: (lv.traffic or {}).get("refused_at_m") is not None
               and lv.traffic["refused_at_m"] < lv.progress(k, lv.segments[k]["s_to"]) + .05,
               owns_span=lambda lv, a, b: a <= b <= owned["end"] + 1e-9)
    sent, stops, cancels, renewals, guards = [], [], [], [], []
    state = {"navigation": "IDLE"}

    async def route(rid, payload, **options):
        guard = prefix_guard.get()
        guards.append(guard is not None and guard[3]())  # the console asks the closure at the wire
        sent.append((payload, options))
        return {"accepted": True, "road_speed_owner": "lease"}

    async def stop(live, status, reason, detail=None):
        stops.append(reason)
        live.view["state"] = status

    async def cancel(rid):
        cancels.append(rid)
        return {"ok": True, "cancel_confirmed": True}

    async def renew(*_args):
        renewals.append(1)

    runner = NS(_clock=clock, config=NS(arrive_free_m=.15, advance_free_m=.15, map_binding_required=False,
                                        stall_m=.05, stall_s=20.), _store=store, traffic=table,
                road_speed=NS(renew=renew), _route=route, _stop=stop, _cancel_goal=cancel,
                _robot_state=lambda _rid: asyncio.sleep(0, result=state), _call=lambda awaitable: awaitable,
                _after_send=lambda _live: asyncio.sleep(0), _fence=lambda _rid: None, autonomous_robots=set(),
                _strict_named_stop=lambda *_: None)
    live = NS(open=True, nav2_binding_scope=None, graph=graph, segments=segs, progress=progress,
              view={"robot_id": "rosy_45", "trip_id": "t", "map_version": 3, "caps": {"kind": "pinky_pro"},
                    "hold": None, "state": "running", "pose": {"state": "LOCALIZED", "x": S_FROM, "y": 0.},
                    "detail": {}},
              place=lambda i: ("J_out", "P3")[i], request={"to": "P3"}, repeat=False, convoy=None,
              arc=lambda i: NS(point_at=lambda s: point_at(i, s), knots=(), polyline=()),
              at=(0, S_FROM), route_rev=1, trim_m=0., active_route=None, nav2_retry_at=-math.inf,
              best_progress=-math.inf, progress_at=None, junction={}, authority=None, command_ack_mono=None,
              last_goal=None, sent=None)
    live.traffic = None

    def table_row(**change):
        live.traffic = {"waiting_for": [], "authority_end_m": owned["end"], "refused_at_m": None, "front_d_m": .065,
                        "pose_stamp": clock(), "route_rev": 1, "peers": {"rosy_46": ["site", -.83, -.36]},
                        "occupied_ahead_m": CUT - S_FROM, "occupied_ahead_by": ["rosy_46"], **change}
    table_row()
    return NS(runner=runner, live=live, active=active, state=state, sent=sent, stops=stops, cancels=cancels,
              renewals=renewals, guards=guards, owned=owned, table_row=table_row, curve=curve, clock=clock)


def _drive(monkeypatch, h, s, nav="IDLE", stopped=False):
    """One trip period at arc metre ``s`` of segment 0 (the robot projected on the lane centre)."""
    monkeypatch.setattr(nav2, "ready_free_goal", lambda *_: asyncio.sleep(0, result=True))
    monkeypatch.setattr(nav2, "observe_lane_departure", lambda *_: asyncio.sleep(0, result=False))
    monkeypatch.setattr(nav2, "_convert_points", lambda runner, live, active, pts, pose, state: (pts, None))
    monkeypatch.setattr(nav2, "sample_nav2_route", lambda graph, segs, index, s0, end, **kw: [(
        S_FROM + h.live.progress(end, segs[end]["s_to"] if kw.get("end_s") is None else kw["end_s"]), 0., 0., "stop")])
    h.state.clear()
    h.state["navigation"] = nav
    if stopped:
        h.state.update(velocity={"linear": 0., "angular": 0.},
                       evidence={"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}})
    x = S_FROM + h.live.progress(0, s)
    h.live.at = (0, s)
    h.live.view["pose"] = {"state": "LOCALIZED", "x": x, "y": 0.}
    run(nav2.step_nav2_route(h.runner, h.live, 0, s, NS(x=x, y=0., yaw=0., odom_stamp=h.clock())))


def _stalled(h, s):
    from fleet.server.trip_progress import TripProgress
    return TripProgress._stalled(h.runner, h.live, 0, s)


def test_first_span_pin_dispatches_hold_point_and_resumes(monkeypatch):
    h = hold_snapshot()
    assert nav2._traffic_end_index(h.runner, h.live, 0) is None  # the live cause: the pin cuts segment 0
    _drive(monkeypatch, h, S_FROM)
    assert len(h.sent) == 1 and h.guards == [True] and h.stops == []
    end = h.sent[0][0][-1]
    hold = h.live.view["detail"]["wait_prefix"]
    assert end["kind"] == "stop" and end["x"] + CLEAR <= .867 + 1e-6 and end["x"] + CLEAR <= CUT
    assert end["x"] > S_FROM + .5  # it departs: most of the granted lane is used
    assert hold["kind"] == "hold_point" and hold["segment"] == 0 and hold["waiting_on"] == ["rosy_46"]
    assert hold["target_xy"] == [end["x"], 0.] and h.live.active_route["hold_point"]["segment"] == 0
    assert "attempt_id" not in h.sent[0][1] and h.sent[0][1]["road_speed_controlled"]
    for s in (.2, .4, .6):  # driving under the cut: never cancelled, the watchdog stays on
        h.clock.advance(1.)
        h.table_row()
        _drive(monkeypatch, h, s, nav="NAVIGATING")
        assert h.live.active_route and h.cancels == [] and not _stalled(h, s)
    hold_s = h.live.active_route["hold_point"]["end_s"]
    _drive(monkeypatch, h, hold_s, stopped=True)
    assert h.live.active_route is None and hold["state"] == "at_hold_point" and len(h.sent) == 1
    for _ in range(60):  # 30 s standing, past stall_s: no resend, no stall, the blocker named
        h.clock.advance(.5)
        h.table_row()
        _drive(monkeypatch, h, hold_s, stopped=True)
        assert not _stalled(h, hold_s)
    assert len(h.sent) == 1 and h.stops == [] and h.live.view["detail"]["traffic_hold"]["waiting_for"] == ["rosy_46"]
    execution = trip_execution(h.live.view, h.live)
    assert (execution["phase"], execution["reason"], execution["waiting_on"]) == ("goal_wait", "traffic_hold", ["rosy_46"])
    h.owned["end"] = 2.
    h.table_row(occupied_ahead_m=None, occupied_ahead_by=[])  # rosy_46 left
    _drive(monkeypatch, h, hold_s, stopped=True)
    assert len(h.sent) == 2 and h.sent[1][0][-1]["x"] == pytest.approx(S_FROM + h.live.progress(1, .5))
    assert "traffic_hold" not in h.live.view["detail"] and not h.live.active_route.get("hold_point")


def test_hold_point_route_survives_refusal_beyond_it(monkeypatch):
    h = hold_snapshot()
    _drive(monkeypatch, h, S_FROM)
    h.clock.advance(1.)
    h.table_row(refused_at_m=CUT - S_FROM, waiting_for=["rosy_46"])  # loop_left#0 asked for and refused mid-drive
    _drive(monkeypatch, h, .3, nav="NAVIGATING")
    assert h.stops == [] and h.cancels == [] and h.live.active_route["hold_point"] and h.renewals
    assert h.live.view["detail"]["wait_prefix"]["state"] == "dispatched"


@pytest.mark.parametrize("acked", [True, False])
def test_hold_point_coverage_lost_cancels_and_waits(monkeypatch, acked):
    h = hold_snapshot()
    _drive(monkeypatch, h, S_FROM)
    if not acked:
        h.runner._cancel_goal = lambda _rid: asyncio.sleep(0, result={"ok": False})
    h.clock.advance(1.)
    h.owned["end"] = .45
    h.table_row()  # the authority shrank below the stop's turn footprint
    _drive(monkeypatch, h, .3, nav="NAVIGATING")
    if not acked:  # an unconfirmed cancel keeps the existing safety stop
        assert h.stops == ["WAIT_PREFIX_RESERVATION_LOST"]
        return
    assert h.stops == [] and h.live.active_route is None and h.cancels == ["rosy_45"]
    assert h.live.view["detail"]["wait_prefix"]["state"] == "reservation_lost" and len(h.sent) == 1
    h.owned["end"] = .867
    h.table_row()
    _drive(monkeypatch, h, .32, nav="CANCELED")  # not yet shown stopped: no replacement
    assert len(h.sent) == 1
    _drive(monkeypatch, h, .32, nav="CANCELED", stopped=True)
    assert len(h.sent) == 2 and h.live.view["detail"]["wait_prefix"]["state"] == "dispatched"


@pytest.mark.parametrize("feature", ["two_way_zone", "crosswalk", "tight_curve"])
def test_hold_point_backs_off_two_way_zone_crosswalk_and_tight_curve(feature):
    h = hold_snapshot()
    free, _ = hold_point(h.runner, h.live, h.active, 0, S_FROM)
    # a corner under the free stop's turn footprint, a crosswalk just ahead of it, a two-way lane farther back
    edge = {"tight_curve": .75, "crosswalk": .8}.get(feature, .5)
    if feature == "two_way_zone":  # an auto two-way lane unit (zone=True) the configured zones do not list
        layout = NS(units={"lane:bay": NS(zone=True), "upper_west#0": NS(zone=False)})
        h.runner.traffic._layout_for = lambda _active: layout
        h.runner.traffic._under = lambda _layout, _graph, pose: {"lane:bay" if pose[0] > edge else "upper_west#0": True}
    elif feature == "crosswalk":
        h.active[1].crosswalks.append(NS(polygon=[(edge, -.1), (edge + .1, -.1), (edge + .1, .1), (edge, .1)], approach=()))
    else:
        h.curve[edge] = 1.5
    stop, why = hold_point(h.runner, h.live, h.active, 0, S_FROM)
    x = stop  # the fake lane: x equals arc metres on segment 0
    assert why == "hold_point" and stop < free
    if feature == "two_way_zone":
        assert edge - ZONE_STOP_CLEARANCE_M - .02 - 1e-9 <= x <= edge - ZONE_STOP_CLEARANCE_M + 1e-9
    else:
        assert edge - CLEAR - .02 - 1e-9 <= x < edge - CLEAR + 1e-9 if feature == "crosswalk" else x + CLEAR < edge


def test_final_segment_hold_point_is_not_arrival(monkeypatch):
    h = hold_snapshot(lengths=((S_FROM, S_TO),))
    h.live.place = lambda i: "P3"
    named = []
    h.runner._strict_named_stop = lambda *_: named.append(1) or NS(id="P3")
    h.live.nav2_binding_scope = (3, "binding")
    monkeypatch.setattr(nav2, "recheck_binding", lambda *_: asyncio.sleep(0))
    h.live.view["detail"]["goal_frame"] = {"map_id": "site", "map_version": 3, "map_grid_id": "g", "binding_id": "b"}
    recorded = []
    monkeypatch.setattr(nav2, "record_stop_dispatch", lambda *args: recorded.append(args))
    h.table_row(occupied_ahead_m=S_TO - S_FROM - .01)  # the peer stands on the destination bay's approach
    _drive(monkeypatch, h, S_FROM)
    assert len(h.sent) == 1 and "attempt_id" not in h.sent[0][1] and not named and not recorded
    hold_s = h.live.active_route["hold_point"]["end_s"]
    _drive(monkeypatch, h, hold_s, stopped=True)
    # trip_steps never reports arrival while this cut stands (``traffic_hold`` is its guard)
    assert h.live.view["detail"]["traffic_hold"] and h.live.view["detail"]["wait_prefix"]["state"] == "at_hold_point"


def test_short_advance_sends_nothing_and_names_blocker(monkeypatch):
    h = hold_snapshot()
    free, _ = hold_point(h.runner, h.live, h.active, 0, S_FROM)
    _drive(monkeypatch, h, free - .1)
    assert h.sent == [] and h.stops == []
    hold = h.live.view["detail"]["wait_prefix"]
    assert (hold["state"], hold["reason"], hold["waiting_on"]) == ("held", "no_room_to_advance", ["rosy_46"])
    assert h.live.view["detail"]["traffic_hold"]["waiting_for"] == ["rosy_46"]
    h.live.progress_at = h.clock()
    h.clock.advance(25.)
    assert not _stalled(h, free - .1)


@pytest.mark.parametrize("refusal", ["LOCALIZATION_UNTRUSTED", "MAP_FRAME_MISMATCH", "convoy"])
def test_hold_point_keeps_hard_refusals(monkeypatch, refusal):
    h = hold_snapshot()
    if refusal == "convoy":
        h.live.convoy = "lead"
        h.table_row(refused_at_m=CUT - S_FROM, waiting_for=["rosy_46"])  # no table answer for a convoy member
    else:
        async def refuse(rid, payload, **options):
            h.sent.append((payload, options))
            return {"accepted": False, "queued": False, "reason": refusal, "blocked_by": "rosy_46",
                    "dispatch_attempted": False, "waiting_on": ["rosy_46"], "command_robot_id": rid}
        h.runner._route = refuse
        monkeypatch.setattr(nav2, "inspect_held_route", lambda *_: asyncio.sleep(0))
    _drive(monkeypatch, h, S_FROM)
    assert h.live.active_route is None and h.stops == []
    if refusal == "convoy":
        assert h.sent == [] and h.live.view["detail"]["wait_prefix"]["reason"] == "no_table_answer"
    else:
        assert len(h.sent) == 1 and h.live.view["detail"]["peer_wait"]["reason"] == refusal
        assert h.live.view["detail"]["wait_prefix"]["state"] == "held"


@pytest.mark.parametrize("waiting, asked", [({"signal:roundabout", "pose_jump"}, True), ({"gone"}, False)])
def test_check_wait_prefix_ignores_pseudo_waiting_ids(waiting, asked):
    console = NS(_pose_of=lambda rid: None, _order=["m"])
    calls = []
    token = prefix_guard.set(("m", "site", waiting, lambda: calls.append(1) or False, [], []))
    try:  # a pseudo id never fails the roster check; a robot that left the roster still does
        assert check_wait_prefix(console, "m", [], lambda pts: None) is False
        assert bool(calls) is asked
    finally:
        prefix_guard.reset(token)
