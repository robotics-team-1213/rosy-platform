"""D-1082: a Nav2 road trip stopped for pose, stall or navigation recovers and resends; hazards still end it."""
import math

import pytest

from fakes import run
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server import nav2_trip_recovery as rec
from fleet.server.nav2_route_sampling import sample_nav2_route
from rosy.world.state.projections.map_pose import MapPose
from test_trip_nav2_route import RouteFakeRobot, _console_runner, _south_loop_map


def _pose(x, y, yaw, state="LOCALIZED"):
    return MapPose(x, y, yaw, state, "sighting", 0.0, 0.1, 0.1, "site-loop")


def _trip(autonomous=False):
    robot = RouteFakeRobot("rosy_42")
    clock, _console, store, graph, pose, canceled, runner = _console_runner(robot, _south_loop_map())
    robot._state.update(map_id="site-loop", mode="NAVIGATION", safety={"estop": False},
                        localization={"state": "LOCALIZED", "pose_frame": "map"},
                        velocity={"linear": 0.0, "angular": 0.0},
                        evidence={"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}})
    arc = graph.arcs["upper_east:fwd"]
    x, y, t = arc.point_at(0.05)
    pose["v"] = _pose(x, y, t)
    if autonomous:
        runner.autonomous_robots = frozenset({"rosy_42"})
    plan = plan_body(plan_trip(graph, PlanRequest(map_version=store.active()[0], start_pose=(x, y, t),
                                                  goal="S4", stop_offset=False), store.routing_config))
    store.record_plan(plan_id="p-rc", robot_id="rosy_42", principal_id="bob", map_version=plan["map_version"],
                      request={"to": "S4", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-rc", "bob"))
    run(runner.tick())
    assert len(robot.routes) == 1 and robot._state["navigation"] == "NAVIGATING"
    return robot, clock, store, graph, pose, canceled, runner, runner._live["rosy_42"]


def _tick(runner, clock, n=1, dt=0.5):
    for _ in range(n):
        run(runner.tick())
        clock.advance(dt)


def test_nav2_failed_recovers_then_resends_the_lane_return_route_from_here():
    robot, clock, store, graph, pose, canceled, runner, live = _trip()
    robot._state["navigation"] = "FAILED"
    _tick(runner, clock)
    view = runner.view("p-rc")
    assert view["state"] == "running" and view["detail"]["recovery"]["state"] == "waiting"
    assert view["detail"]["recovery"]["reason"] == "navigation" and view["detail"]["recovery"]["attempt"] == 1
    assert canceled == ["rosy_42"] and live.active_route is None and len(robot.routes) == 1
    _tick(runner, clock, 2)                                     # inside SETTLE_S: nothing goes out
    assert len(robot.routes) == 1
    x, y, t = graph.arcs["upper_east:fwd"].point_at(0.12)
    pose["v"] = _pose(x - math.sin(t) * 0.04, y + math.cos(t) * 0.04, t)   # 4 cm off the centre line
    _tick(runner, clock, 3)
    assert len(robot.routes) == 2 and runner.view("p-rc")["state"] == "running"
    assert live.view["detail"]["recovery"]["state"] == "resumed"
    index, s = live.at
    expected = sample_nav2_route(graph, live.segments, index, s, live.active_route["end_index"],
                                 walls=getattr(store.active()[1], "walls", ()), here=(pose["v"].x, pose["v"].y))
    first = robot.routes[1][0][0]
    assert (first["x"], first["y"]) == pytest.approx(expected[0][:2], abs=1e-3)


def test_a_degraded_pose_waits_for_localization_then_resends():
    robot, clock, _store, graph, pose, canceled, runner, live = _trip()
    good = pose["v"]
    pose["v"] = _pose(good.x, good.y, good.yaw, "DEGRADED")
    _tick(runner, clock, 6)
    view = runner.view("p-rc")
    assert view["state"] == "running" and view["detail"]["recovery"]["reason"] == "pose"
    assert view["detail"]["recovery"]["attempt"] == 1 and canceled == ["rosy_42"] and len(robot.routes) == 1
    pose["v"] = good
    _tick(runner, clock, 2)
    assert len(robot.routes) == 2 and runner.view("p-rc")["state"] == "running"


@pytest.mark.parametrize("reason", rec.RECOVERABLE)
def test_each_recoverable_reason_keeps_the_trip(reason):
    robot, clock, *_rest, canceled, runner, live = _trip()
    run(runner._stop(live, "stopped", reason, {"stall_s": 20.0} if reason == "stall" else {}))
    assert live.view["state"] == "running" and live.view["detail"]["recovery"]["reason"] == reason
    assert canceled == ["rosy_42"] and live.active_route is None


def test_a_robot_still_moving_is_not_resent_and_the_wait_ends_with_the_old_reason():
    robot, clock, *_rest, runner, live = _trip()
    run(runner._stop(live, "stopped", "stall", {"stall_s": 20.0, "progress_m": 0.1}))
    robot._state["velocity"] = {"linear": 0.05, "angular": 0.0}
    _tick(runner, clock, int(rec.WAIT_S / 0.5) - 1)
    assert live.view["state"] == "running" and len(robot.routes) == 1
    assert live.view["detail"]["recovery"]["waiting_for"] == "robot_stopped"
    _tick(runner, clock, 3)
    view = runner.view("p-rc")
    assert (view["state"], view["reason"]) == ("stopped", "stall") and view["detail"]["progress_m"] == 0.1
    assert view["detail"]["recovery"]["state"] == "exhausted"


def _recover_once(runner, clock, live, reason="navigation"):
    run(runner._stop(live, "stopped", reason, {}))
    _tick(runner, clock, 6)


def test_three_recoveries_then_the_fourth_stop_ends_the_trip():
    robot, clock, *_rest, runner, live = _trip()
    for attempt in range(1, rec.MAX_ATTEMPTS + 1):
        _recover_once(runner, clock, live)
        assert live.view["state"] == "running" and live.view["detail"]["recovery"]["attempt"] == attempt
        assert live.view["detail"]["recovery"]["state"] == "resumed"
    run(runner._stop(live, "stopped", "navigation", {"navigation": "FAILED"}))
    view = runner.view("p-rc")
    assert (view["state"], view["reason"]) == ("stopped", "navigation") and view["detail"]["recovery"]["state"] == "exhausted"


def test_the_window_closes_five_minutes_after_the_first_recovery():
    robot, clock, *_rest, runner, live = _trip()
    _recover_once(runner, clock, live)
    clock.advance(rec.WINDOW_S)
    run(runner._stop(live, "stopped", "stall", {}))
    assert (live.view["state"], live.view["reason"]) == ("stopped", "stall")


def test_progress_after_a_resume_closes_the_episode():
    robot, clock, _store, graph, pose, _c, runner, live = _trip()
    _recover_once(runner, clock, live)
    arc = graph.arcs["upper_east:fwd"]
    x, y, t = arc.point_at(arc.length_m - 0.01)
    pose["v"] = _pose(x, y, t)
    s0 = live.view["detail"]["recovery"]["resumed_progress"]
    live.view["detail"]["recovery"]["resumed_progress"] = s0 - rec.RESET_M   # as if 1 m had passed since
    _tick(runner, clock)
    assert "recovery" not in live.view["detail"] and live.view["detail"]["last_recovery"]["state"] == "recovered"
    _recover_once(runner, clock, live)
    assert live.view["detail"]["recovery"]["attempt"] == 1


@pytest.mark.parametrize("reason, detail", [
    ("map_frame", {"binding": "MAP_FRAME_MISMATCH"}), ("map_frame", {"binding": "MAP_BINDING_REQUIRED"}),
    ("map_version", {}), ("ROAD_SPEED_OWNER_CHANGED", {}), ("ROAD_SPEED_OWNER_MISSING", {}), ("lane_arc", {}),
    ("WAIT_PREFIX_RESERVATION_LOST", {}), ("lease_lost", {}), ("junction", {}),
    ("pose", {"off_lane_m": 0.2}), ("stall", {"link_wait": "timeout"}),
])
def test_hazard_and_authority_stops_end_at_once(reason, detail):
    robot, clock, *_rest, runner, live = _trip()
    run(runner._stop(live, "stopped", reason, detail))
    assert (live.view["state"], live.view["reason"]) == ("stopped", reason) and "recovery" not in live.view["detail"]


@pytest.mark.parametrize("setup", ["estop", "estop_unknown", "pause", "parking", "camera", "lane_trip", "cancel_unacked",
                                   "map_changed"])
def test_out_of_scope_or_unproven_stops_end_as_before(setup):
    robot, clock, store, *_rest, runner, live = _trip()
    if setup == "estop":
        robot._state["safety"] = {"estop": True}
    elif setup == "estop_unknown":
        robot._state.pop("safety")
    elif setup == "pause":
        live.view["hold"] = {"reason": "fleet_hold", "stop": {"confirmed": True}}
    elif setup == "parking":
        live.view["detail"]["parking_handoff"] = {"phase": "approaching"}
    elif setup == "camera":
        live.view["detail"]["camera_lane_fallback"] = {"phase": "running", "index": 0}
    elif setup == "lane_trip":
        live.request["drive_mode"] = "lane"
    elif setup == "cancel_unacked":
        async def no_ack(_rid):
            return {"ok": False}
        runner._cancel_goal = no_ack
    elif setup == "map_changed":
        store.active = lambda: None
    run(runner._stop(live, "stopped", "navigation", {"navigation": "FAILED"}))
    assert (live.view["state"], live.view["reason"]) == ("stopped", "navigation") and "recovery" not in live.view["detail"]


def test_a_charge_bay_leg_and_a_strict_named_stop_are_out_of_scope(monkeypatch):
    robot, clock, *_rest, runner, live = _trip()
    monkeypatch.setattr(runner, "_strict_named_stop", lambda _live, _i: object())
    run(runner._stop(live, "stopped", "stall", {}))
    assert live.view["state"] == "stopped"
    robot, clock, *_rest, runner, live = _trip()
    monkeypatch.setattr(rec, "_excluded", lambda *_a: True)
    run(runner._stop(live, "stopped", "stall", {}))
    assert live.view["state"] == "stopped"


def test_an_estop_while_waiting_ends_the_trip_with_the_old_reason():
    robot, clock, *_rest, runner, live = _trip()
    run(runner._stop(live, "stopped", "stall", {"stall_s": 20.0}))
    robot._state["safety"] = {"estop": True}
    _tick(runner, clock)
    assert (live.view["state"], live.view["reason"]) == ("stopped", "stall")


def test_an_operator_cancel_while_recovering_is_final():
    robot, clock, *_rest, runner, live = _trip()
    run(runner._stop(live, "stopped", "navigation", {}))
    run(runner.cancel("p-rc", "bob"))
    _tick(runner, clock, 6)
    assert runner.view("p-rc")["state"] == "canceled" and len(robot.routes) == 1


def test_an_autonomous_robots_nav2_failure_stays_with_its_own_retry():
    robot, clock, *_rest, canceled, runner, live = _trip(autonomous=True)
    robot._state["navigation"] = "FAILED"
    _tick(runner, clock)
    assert live.view["detail"]["nav2_problem"]["state"] in ("retry_wait", "rerouted", "held")
    assert "recovery" not in live.view["detail"] and canceled == []
