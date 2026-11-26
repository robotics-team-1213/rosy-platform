"""A downstream refusal may dispatch only a positively checked intermediate waiting place."""
import asyncio
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
            "command_robot_id": "m", "dispatch_attempted": False, "waiting_on": ["p"], "stage": "pre_dispatch_peer_check",
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
    monkeypatch.setattr(nav2, "sample_nav2_route", lambda graph, segs, index, s, end, **kw:
                        [(live.progress(end, segs[end]["s_to"]), 0., 0., "stop")])
    if not ordinary:
        monkeypatch.setattr(nav2, "_convert_points", lambda runner, live, active, pts, pose, state: (pts, None))
    run(nav2.step_nav2_route(runner, live, 0, 0., pose))
    assert live.view["detail"]["peer_wait"]["waiting_on"] == ["p"] and actual == []
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
    monkeypatch.setattr(nav2, "reservation_covers", lambda *_: loss != "reservation")
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
