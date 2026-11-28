"""D-1080: a departed Nav2 road trip is slowed and given the recentring route; nothing here stops or holds it."""
import asyncio
import math
from types import SimpleNamespace as NS

import pytest

from fakes import FakeClock, run
from fleet.server import trip_lane_realign as realign
from fleet.server.nav2_route_sampling import sample_nav2_route
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_road_speed import RoadSpeed
from rosy.world.state.projections.map_pose import MapPose
from test_trip_nav2_route import RouteFakeRobot, _console_runner, _south_loop_map

LOCALIZED = {"localization": {"state": "LOCALIZED"}, "mode": "NAVIGATION"}


def _at(arc, s, left, yaw_off=0.0):
    """A point ``left`` m to the left of ``arc`` at ``s`` and the lane heading plus ``yaw_off``."""
    px, py, t = arc.point_at(s)
    return px - math.sin(t) * left, py + math.cos(t) * left, t + yaw_off


def _camera(xy, age=0.1, source="sighting"):
    # A moving robot's pose reads source "bridged": the anchor (what the camera set) carried on by odom.
    return MapPose(*xy, "LOCALIZED", "bridged", 0.02, 0.1, anchor_age_s=age, map_id="site-loop", anchor_source=source)


def _slam(xy):
    return MapPose(*xy, "LOCALIZED", "approved_slam", 0.0, 0.1, 0.1, "site-loop")


class Rig:
    def __init__(self, edge="upper_west:fwd", site=None):
        self.clock = FakeClock()
        self.store = SiteMapStore(clock=self.clock)
        self.store.import_if_empty(site or _south_loop_map(), source="test")
        graph = self.store.active()[2]
        self.arc = graph.arcs[edge]
        self.cam = None
        self.runner = NS(_clock=self.clock, _store=self.store, _poses=NS(arbitrated_pose=lambda _r: self.cam))
        self.live = NS(view={"robot_id": "r1", "detail": {}, "hold": None}, active_route={"end_index": 0},
                       graph=graph, arc=lambda _i: self.arc)

    def tick(self, cam_left, slam_left=None, *, state=LOCALIZED, nav="NAVIGATING", age=0.1, source="sighting",
             yaw_off=0.0):
        self.cam = _camera(_at(self.arc, 0.4, cam_left, yaw_off), age, source)
        slam = _slam(_at(self.arc, 0.4, cam_left if slam_left is None else slam_left, yaw_off))
        replace = run(realign.observe(self.runner, self.live, 0, slam, state, nav))
        self.clock.advance(0.5)
        return replace, self.live.view["detail"]["lane_departure"]


@pytest.mark.parametrize("cam, slam, state, kind, reason", [
    (0.06, 0.03, LOCALIZED, "departed", None),
    (0.06, 0.06, {"localization": {"state": "SUSPECT"}}, "location", "ROBOT_NOT_LOCALIZED"),
    (0.06, 0.06, None, "location", "STATE_UNREAD"),
    (0.06, 0.0, LOCALIZED, "location", "SLAM_CAMERA_GAP"),
    (0.0, 0.0, LOCALIZED, "on_lane", None),
    (0.03, 0.03, LOCALIZED, "near_edge", None),
])
def test_classification_and_only_a_trusted_departure_acts(cam, slam, state, kind, reason):
    rig = Rig()
    results = [rig.tick(cam, slam, state=state) for _ in range(realign.PERSIST_TICKS + 1)]
    record = results[-1][1]
    assert (record["kind"], record["reason"]) == (kind, reason)
    assert any(replace for replace, _ in results) == (kind == "departed")
    assert record["slow"] == (kind == "departed")
    if kind == "departed":   # the margin is judged from the camera pose, not the robot's own
        assert record["lat_m"] == pytest.approx(0.06) and record["margin_m"] < 0 and record["gap_m"] == pytest.approx(0.03)


@pytest.mark.parametrize("age, source, kind", [(1.1, "sighting", "camera_stale"), (None, "sighting", "camera_stale"),
                                                (0.1, "auto_locate", "camera_unavailable")])
def test_stale_or_untrusted_camera_is_recorded_never_acted_on(age, source, kind):
    rig = Rig()
    for _ in range(4):
        replace, record = rig.tick(0.08, 0.06, age=age, source=source)
        assert not replace and record["kind"] == kind and not record["slow"] and record["ticks"] == 0


def test_persistent_fresh_ticks_then_one_resend_per_cooldown_then_release():
    rig = Rig()
    for _ in range(realign.PERSIST_TICKS - 1):
        assert rig.tick(0.06, 0.04)[0] is False and not rig.live.view["detail"]["lane_departure"]["slow"]
    replace, record = rig.tick(0.06, 0.04)
    assert replace and record["slow"] and record["replaced"] == 1
    assert rig.tick(0.07, 0.05)[0] is False                      # same departure, inside COOLDOWN_S
    rig.clock.advance(realign.COOLDOWN_S)
    replace, record = rig.tick(0.07, 0.05)
    assert replace and record["replaced"] == 2
    _, record = rig.tick(0.01, 0.01, yaw_off=math.radians(20))   # centred but still crooked: stays slow
    assert record["kind"] == "on_lane" and record["slow"]
    _, record = rig.tick(0.01, 0.01, yaw_off=math.radians(5))
    assert not record["slow"] and record["realigned_at"] is not None


def test_a_stale_tick_breaks_the_tick_count():
    rig = Rig()
    rig.tick(0.06, 0.04)
    rig.tick(0.06, 0.04, age=1.2)
    assert rig.tick(0.06, 0.04)[0] is False and rig.live.view["detail"]["lane_departure"]["ticks"] == 1


def test_not_navigating_hold_or_wait_prefix_slow_but_never_resend():
    rig = Rig()
    assert not any(rig.tick(0.06, 0.04, nav="IDLE")[0] for _ in range(3))
    rig = Rig()
    rig.live.view["hold"] = {"reason": "replan"}
    results = [rig.tick(0.06, 0.04) for _ in range(realign.PERSIST_TICKS + 1)]
    assert not any(r for r, _ in results) and results[-1][1]["slow"]
    rig = Rig()
    rig.live.active_route["wait_prefix"] = True
    assert not any(rig.tick(0.06, 0.04)[0] for _ in range(realign.PERSIST_TICKS + 1))


def test_charge_bay_leg_and_parking_handoff_are_out_of_scope():
    import json
    from fleet.site_map import SiteMap
    layout = json.loads(_south_loop_map().model_dump_json(by_alias=True))
    layout["places"].append({"id": "C2", "name": "C2", "x": .91, "y": -.68, "kind": "charge", "yaw": math.pi / 2})
    layout["edges"].append({"id": "bay2", "from": "S5", "to": "C2", "direction": "two_way", "drive_mode": "lane",
                            "width_m": .2, "speed_cap_mps": .1, "polyline": [[.91, -.48], [.91, -.68]]})
    rig = Rig("bay2:fwd", SiteMap.model_validate(layout))
    for _ in range(3):
        replace, record = rig.tick(0.08, 0.06)
        assert not replace and record["kind"] == "excluded" and not record["slow"]
    rig = Rig()
    for _ in range(realign.PERSIST_TICKS - 1):
        rig.tick(0.06, 0.04)
    assert rig.tick(0.06, 0.04)[1]["slow"]
    rig.live.view["detail"]["parking_handoff"] = {"phase": "approaching"}
    replace, record = rig.tick(0.06, 0.04)
    assert not replace and record["kind"] == "excluded" and not record["slow"]


def test_departure_resends_the_recentring_route_and_the_trip_keeps_running():
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip

    robot = RouteFakeRobot("rosy_42")
    clock, _console, store, graph, pose, canceled, runner = _console_runner(robot, _south_loop_map())
    robot._state["localization"] = {"state": "LOCALIZED", "pose_frame": "map"}
    robot._state["map_id"] = "site-loop"   # one frame: the sent points are the site points
    arc = graph.arcs["upper_east:fwd"]
    slam = {"v": _slam(_at(arc, 0.05, 0.0))}
    pose["v"] = _camera(_at(arc, 0.05, 0.0))
    runner._poses.driving_pose = lambda _id: slam["v"]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(slam["v"].x, slam["v"].y, slam["v"].yaw),
        goal="S4", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-re", robot_id="rosy_42", principal_id="bob", map_version=plan["map_version"],
                      request={"to": "S4", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-re", "bob"))
    run(runner.tick())
    live = runner._live["rosy_42"]
    assert len(robot.routes) == 1 and robot._state["navigation"] == "NAVIGATING"

    def drift(cam_left, slam_left):
        pose["v"] = _camera(_at(arc, 0.12, cam_left))
        slam["v"] = _slam(_at(arc, 0.12, slam_left))
        run(runner.tick())
        clock.advance(0.5)

    for _ in range(realign.PERSIST_TICKS - 1):
        drift(0.06, 0.04)
    assert len(robot.routes) == 1 and not canceled
    drift(0.06, 0.04)
    view = runner.view("p-re")
    assert view["state"] == "running" and view["hold"] is None and canceled == ["rosy_42"]
    assert len(robot.routes) == 2 and view["detail"]["lane_departure"]["slow"]
    index, s = live.at
    expected = sample_nav2_route(graph, live.segments, index, s, live.active_route["end_index"],
                                 walls=getattr(store.active()[1], "walls", ()), here=(slam["v"].x, slam["v"].y))
    first = robot.routes[1][0][0]
    assert (first["x"], first["y"]) == pytest.approx(expected[0][:2], abs=1e-3)
    _, _, t = arc.point_at(0.12)   # the recentring point lies ahead of the robot, not at its own projection
    assert (first["x"] - slam["v"].x) * math.cos(t) + (first["y"] - slam["v"].y) * math.sin(t) >= 0.10 - 1e-3

    drift(0.06, 0.04)                                       # inside COOLDOWN_S: no second resend
    assert len(robot.routes) == 2 and canceled == ["rosy_42"]
    drift(0.0, 0.0)
    view = runner.view("p-re")
    assert view["state"] == "running" and not view["detail"]["lane_departure"]["slow"]


def test_a_fault_in_the_watch_is_recorded_and_never_fails_the_trip():
    rig = Rig()
    rig.live.arc = lambda _i: 1 / 0
    rig.cam = _camera((0.0, -0.3, math.pi))
    assert run(realign.observe(rig.runner, rig.live, 0, _slam((0.0, -0.3, math.pi)), LOCALIZED, "NAVIGATING")) is False
    assert rig.live.view["detail"]["lane_departure"]["kind"] == "error"


def test_a_replaced_route_reported_canceled_is_resent_not_aborted():
    from fleet.server.trip_nav2_route import _route_finished
    live = NS(active_route={"end_index": 1, "superseded": True}, segments=[{}, {}], view={"hold": None})
    assert _route_finished(NS(config=NS()), live, 0, 0.0, "CANCELED") == "ready"
    live.active_route.pop("superseded")
    assert _route_finished(NS(config=NS()), live, 0, 0.0, "CANCELED") == "aborted"
    assert _route_finished(NS(config=NS()), live, 0, 0.0, "FAILED") == "aborted"


def _grant(site, segments, detail=None):
    grants = []

    async def update(rid, cid, grant):
        grants.append(grant)
        return {"renewed": True, "correlation_id": cid}
    rules = NS(formation=NS(min_gap_m=.4, max_speed_mps=.15))
    runner = NS(_clock=lambda: 10., _roster=lambda: ["first"], _live={}, _call=lambda coro: coro,
                _store=NS(active=lambda: (1, site), rules=NS(active_rules=lambda: rules)))
    live = NS(request={}, repeat=False, open=True, active_route={"road_speed_owner": "run"}, view={"robot_id": "first", "detail": detail or {}},
              route_rev=0, trim_m=0., segments=segments, progress=lambda idx, s: s)
    pose = NS(x=.5, y=-.25, map_id="site-loop", state="LOCALIZED", odom_stamp=9.8)
    asyncio.run(RoadSpeed(NS(arbitrated_pose=lambda rid: None), update).renew(runner, live, (1, site), 0, .1, pose))
    return grants[-1]["limit_mps"], live.view["detail"]["road_speed"]["reason"]


def test_road_speed_slows_a_departed_robot_and_caps_tight_curves():
    site = _south_loop_map()
    straight = [dict(edge_id="upper_west", forward=True, s_from=0., s_to=1.)]
    assert _grant(site, straight) == (.15, "route_profile")
    assert _grant(site, straight, {"lane_departure": {"slow": True}}) == (realign.REALIGN_SLOW_MPS, "lane_realign")
    limit, _ = _grant(site, [dict(edge_id="loop_right", forward=True, s_from=0., s_to=.4)])
    assert limit == pytest.approx(.08)


@pytest.mark.parametrize("after", ["camera_stale", "location", "near_edge"])
def test_the_slow_cap_is_lifted_when_no_fresh_departure_has_been_seen_for_a_while(after):
    rig = Rig()
    assert [rig.tick(0.06)[1]["slow"] for _ in range(realign.PERSIST_TICKS)][-1] is True

    def tick():   # no fresh evidence of a departure any more
        if after == "camera_stale":
            return rig.tick(0.06, age=2.0)
        if after == "location":
            return rig.tick(0.06, state={"localization": {"state": "SUSPECT"}})
        return rig.tick(0.03, yaw_off=math.radians(20))   # inside the lane, not aligned yet

    slow = [tick()[1]["slow"] for _ in range(int(realign.SLOW_EVIDENCE_S / 0.5) + 1)]
    assert all(slow[:int(realign.SLOW_EVIDENCE_S / 0.5) - 1]) and slow[-1] is False   # kept until 9.5 s, lifted at 10 s
    assert [rig.tick(0.06)[1]["slow"] for _ in range(realign.PERSIST_TICKS)] == [False] * (realign.PERSIST_TICKS - 1) + [True]   # a new departure slows again


def test_a_departure_that_lasts_keeps_the_slow_cap():
    rig = Rig()
    slow = [rig.tick(0.06)[1]["slow"] for _ in range(int(realign.SLOW_EVIDENCE_S / 0.5) + 6)]
    assert not any(slow[:realign.PERSIST_TICKS - 1]) and all(slow[realign.PERSIST_TICKS - 1:])


def test_a_record_from_before_the_expiry_field_does_not_keep_the_cap():
    rig = Rig()
    rig.live.view["detail"]["lane_departure"] = {"kind": "departed", "slow": True, "ticks": 2}   # no departed_at
    assert rig.tick(0.06, age=2.0)[1]["slow"] is False


def test_a_camera_anchor_counts_whether_or_not_odom_carried_it_on():
    """2026-11-27 live run on R: the moving robot's pose source is "bridged", and every tick read camera_unavailable."""
    rig = Rig()
    for source, anchor, kind in (("bridged", "sighting", "departed"), ("sighting", "sighting", "departed"),
                                 ("bridged", "track", "departed"), ("bridged", "operator_pin", "camera_unavailable"),
                                 ("bridged", None, "camera_unavailable")):
        rig.cam = MapPose(*_at(rig.arc, 0.4, 0.06), "LOCALIZED", source, 0.02, 0.1, anchor_age_s=0.1,
                          map_id="site-loop", anchor_source=anchor)
        run(realign.observe(rig.runner, rig.live, 0, _slam(_at(rig.arc, 0.4, 0.06)), LOCALIZED, "NAVIGATING"))
        assert rig.live.view["detail"]["lane_departure"]["kind"] == kind, (source, anchor)


def test_the_site_camera_age_acts_and_a_long_odom_bridge_does_not():
    rig = Rig()
    assert {rig.tick(0.06, age=0.6)[1]["kind"] for _ in range(realign.PERSIST_TICKS)} == {"departed"}   # 0.4-0.6 s on site
    assert rig.live.view["detail"]["lane_departure"]["slow"] is True
    rig.cam = MapPose(*_at(rig.arc, 0.4, 0.06), "LOCALIZED", "bridged", 0.2, 0.1, anchor_age_s=0.6,
                      map_id="site-loop", anchor_source="sighting")   # 0.2 m carried by odom since the camera saw it
    run(realign.observe(rig.runner, rig.live, 0, _slam(_at(rig.arc, 0.4, 0.06)), LOCALIZED, "NAVIGATING"))
    record = rig.live.view["detail"]["lane_departure"]
    assert record["kind"] == "camera_stale" and record["bridged_m"] == 0.2


def test_a_trip_on_the_camera_pose_reads_the_robots_bound_slam_instead(monkeypatch):
    """2026-11-27 live run on R: a console trip drives on the camera pose, and every tick read SLAM_POSE_UNBOUND."""
    rig = Rig()
    native = {"v": _at(rig.arc, 0.4, 0.06)}
    asked = []
    rig.runner._store = NS(active=rig.store.active, map_bindings=NS(
        matching_fit=lambda rid, state, site: asked.append((rid, state, site)) or ("fit", None)))
    monkeypatch.setattr(realign, "fresh_native_slam", lambda state, now: (native["v"], 0.1, now))
    monkeypatch.setattr(realign, "bound_pose", lambda fit, pose: pose)

    def tick(cam_left):
        rig.cam = _camera(_at(rig.arc, 0.4, cam_left))
        trip_pose = MapPose(*_at(rig.arc, 0.4, cam_left), "LOCALIZED", "bridged", 0.02, 0.1, anchor_age_s=0.1,
                            map_id="site-loop", anchor_source="sighting")   # the trip's pose is the camera's
        replace = run(realign.observe(rig.runner, rig.live, 0, trip_pose, LOCALIZED, "NAVIGATING"))
        rig.clock.advance(0.5)
        return replace, rig.live.view["detail"]["lane_departure"]

    assert [tick(0.06)[1]["kind"] for _ in range(2)] == ["departed", "departed"]   # both poses past the line
    version, site = rig.store.active()[:2]
    assert asked[-1] == ("r1", LOCALIZED, (site.map_id, version))                   # this robot, its state, this map
    native["v"] = _at(rig.arc, 0.4, 0.0)                                             # the robot's own pose is on the lane
    record = tick(0.06)[1]
    assert (record["kind"], record["reason"]) == ("location", "SLAM_CAMERA_GAP")


@pytest.mark.parametrize("fit, sample, why", [((None, "GRID_MISMATCH"), "ok", "GRID_MISMATCH"),
                                              ((None, None), "ok", "MAP_BINDING_REQUIRED"),
                                              (("fit", None), None, "SLAM_POSE_STALE")])
def test_without_a_bound_slam_pose_it_stays_a_location_record(monkeypatch, fit, sample, why):
    rig = Rig()
    rig.runner._store = NS(active=rig.store.active, map_bindings=NS(matching_fit=lambda *a: fit))
    monkeypatch.setattr(realign, "fresh_native_slam",
                        lambda state, now: None if sample is None else (_at(rig.arc, 0.4, 0.06), 0.1, now))
    monkeypatch.setattr(realign, "bound_pose", lambda f, pose: pose)
    rig.cam = _camera(_at(rig.arc, 0.4, 0.06))
    camera_trip_pose = MapPose(*_at(rig.arc, 0.4, 0.06), "LOCALIZED", "bridged", 0.02, 0.1, anchor_age_s=0.1,
                               map_id="site-loop", anchor_source="sighting")
    assert run(realign.observe(rig.runner, rig.live, 0, camera_trip_pose, LOCALIZED, "NAVIGATING")) is False
    record = rig.live.view["detail"]["lane_departure"]
    assert (record["kind"], record["reason"], record["slam_reason"]) == ("location", "SLAM_POSE_UNBOUND", why)


def test_guide_bar_junction_exits_are_excluded_from_lane_realign():
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    _, world_graph, _ = build_world_261026_site_map()
    clock = FakeClock()
    arc = world_graph.arcs["park_out:fwd"]
    cam = _camera(_at(arc, 0.1, 0.06))
    runner = NS(_clock=clock, _store=NS(active=lambda: (1, NS(map_id="world_261026", walls=()))),
                _poses=NS(arbitrated_pose=lambda _r: cam))
    live = NS(view={"robot_id": "rosy_46", "detail": {}, "hold": None},
              active_route={"end_index": 0}, graph=world_graph, arc=lambda _i: arc)
    assert run(realign.observe(runner, live, 0, _slam(_at(arc, 0.1, 0.06)), LOCALIZED, "NAVIGATING")) is False
    assert live.view["detail"]["lane_departure"]["kind"] == "excluded"
