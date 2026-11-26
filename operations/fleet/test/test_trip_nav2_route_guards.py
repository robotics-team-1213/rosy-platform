"""D-430 safety guard regression tests for Nav2 repeat routes (zone holds and NAVIGATION_ACTIVE)."""

from __future__ import annotations

import math

import pytest

from fakes import run
from fleet.routing.execute import plan_body
from fleet.routing.graph import build_graph
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.trip_laps import next_lap, stop_points
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_nav2_route import NAV2_SPLIT_WALL_CLEAR_M, _wall_clearance, sample_nav2_route
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripError
from fleet.site_map import SiteMap
from fleet.swarm.transport import RobotApiError
from fleet.traffic.zone_hold import hold_back_m
from test_trip_nav2_route import RouteFakeRobot, _console_runner, _south_loop_map


def _zone_loop_map() -> SiteMap:
    """1 m square lane loop where ``ab`` approaches zone ``bc`` (``0 < hold_back_m < 1``) while ``D`` clears it."""
    pts = {"A": (0.0, 0.0, -math.pi / 2), "B": (1.0, 0.0, 0.0), "C": (1.0, 1.0, math.pi / 2), "D": (0.0, 1.0, math.pi)}
    edges = [("ab", "A", "B"), ("bc", "B", "C"), ("cd", "C", "D"), ("da", "D", "A")]
    return SiteMap.model_validate({
        "map_id": "site-loop",
        "places": [{"id": pid, "name": pid, "x": x, "y": y, "kind": "stop", "yaw": yaw}
                   for pid, (x, y, yaw) in pts.items()],
        "edges": [{"id": eid, "from": u, "to": v, "direction": "one_way", "drive_mode": "lane",
                   "width_m": 0.2, "speed_cap_mps": 0.15, "polyline": [list(pts[u][:2]), list(pts[v][:2])]}
                  for eid, u, v in edges],
    })


def test_nav2_repeat_and_replan_defer_holds_with_nonzero_hold_back_m():
    robot = RouteFakeRobot("rosy_42")
    _clock, _console, store, graph, pose, _canceled, runner = _console_runner(
        robot, _zone_loop_map(), traffic_zones={"z_bc": (["bc"], 1)}
    )
    pose["v"] = type(pose["v"])(0.2, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    active = store.active()
    ver = active[0]
    ab_seg = {"edge_id": "ab", "forward": True, "s_from": 0.0, "s_to": graph.arcs["ab:fwd"].length_m}
    assert 0.0 < hold_back_m(runner.traffic, ab_seg) < ab_seg["s_to"]

    req = {"to": "B", "via": ["D"], "repeat": True, "drive_mode": "nav2"}
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="B", via=("D",), stop_offset=False,
    ), store.routing_config))
    caps = {"kind": "pinky_pro", "modes": ["lane", "free"], "max_speed": 0.12, "junction_turn": True, "junction_pivot": True}
    moved_plan, _moved_req, _lap_route, _arcs, stop_moved = stop_points(
        active, plan, req, caps, frozenset(), store.routing_config, runner.config.max_turn_deg, runner.traffic
    )
    assert stop_moved == {"from": "B", "to": "D"}
    assert hold_back_m(runner.traffic, moved_plan["segments"][-1]) == 0.0

    # next_lap ending at B (0 < hold_back_m) is rejected with TRIP_STOP_IN_ZONE when drive_mode=='nav2'.
    end_a = graph.arcs["da:fwd"].point_at(graph.arcs["da:fwd"].length_m)
    body, hold = next_lap(
        active, end_a, {"to": "B", "via": [], "repeat": True, "drive_mode": "nav2"},
        caps, frozenset(), store.routing_config, runner.config.max_turn_deg, runner.traffic
    )
    assert body is None and hold["code"] == "TRIP_STOP_IN_ZONE"

    # During an active nav2 trip currently on ab (0 < hold_back_m), _replan defers via replan_pending=True.
    store.record_plan(plan_id="p-z", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "B", "via": ["D"], "repeat": True, "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-z", "bob"))
    live = runner._live["rosy_42"]
    runner._replan(live, 0)
    assert live.replan_pending is True and live.view["hold"] is None


def test_nav2_navigation_active_preserves_goal_lease_and_active_route_supervision():
    robot = RouteFakeRobot("rosy_42")
    _clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="S3",
        via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-na", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-na", "bob"))
    run(runner.tick())
    lease_before = dict(console.goal_leases["rosy_42"])
    live = runner._live["rosy_42"]
    assert live.active_route is not None

    # Simulate partial telemetry (navigation omitted) near lap rollover while CORE still runs and refuses 409 NAVIGATION_ACTIVE.
    robot._state.pop("navigation", None)
    end_idx = live.active_route["end_index"]
    s_end = live.segments[end_idx]["s_to"] - 0.05
    ex, ey, eyaw = graph.arcs[f"{live.segments[end_idx]['edge_id']}:fwd"].point_at(s_end)
    pose["v"] = type(pose["v"])(ex, ey, eyaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    live.view["segment_index"] = end_idx

    async def busy_route(*_a, **_kw):
        raise RobotApiError("rosy_42", 409, "NAVIGATION_ACTIVE", "still running")

    orig_route = robot.navigation_route
    robot.navigation_route = busy_route
    run(runner.tick())
    assert console.goal_leases["rosy_42"] == lease_before
    assert live.active_route is not None
    assert runner.view("p-na")["detail"]["goal_wait"] == "still running"

    # When CORE aborts afterwards, active_route supervision still stops the trip cleanly.
    robot._state["navigation"] = "FAILED"
    run(runner.tick())
    assert runner.view("p-na")["state"] == "stopped" and runner.view("p-na")["reason"] == "navigation"

    # Cancellation during an in-flight dispatch must never restore a superseded lease on NAVIGATION_ACTIVE.
    async def busy_after_cancel(*_a, **_kw):
        console.goal_leases._stop_generation["rosy_42"] = console.goal_leases._stop_generation.get("rosy_42", 0) + 1
        raise RobotApiError("rosy_42", 409, "NAVIGATION_ACTIVE", "busy")

    robot.navigation_route = busy_after_cancel
    console.goal_leases["rosy_42"] = lease_before
    with pytest.raises(RobotApiError):
        run(console.goal_leases.send_route("rosy_42", robot, run(robot.capabilities()), [{"x": 0.5, "y": -0.23, "kind": "stop", "yaw": 0.0}], source="trip"))
    assert "rosy_42" not in console.goal_leases
    robot.navigation_route = orig_route


def test_sample_nav2_route_split_avoids_tight_wall_when_walls_present():
    smap = _zone_loop_map()
    graph = build_graph(smap)
    segs = [{"edge_id": eid, "forward": True, "s_from": 0.0, "s_to": graph.arcs[f"{eid}:fwd"].length_m}
            for eid in ("ab", "bc", "cd", "da")]
    walls = [{"id": "tight_north", "face": [[-0.2, 1.12], [1.2, 1.12]]}]
    without_walls = sample_nav2_route(graph, segs, 0, 0.0, len(segs) - 1)
    mid_plain = next(p for p in without_walls[:-1] if p[3] == "stop")
    assert _wall_clearance(mid_plain[0], mid_plain[1], walls) < NAV2_SPLIT_WALL_CLEAR_M

    with_walls = sample_nav2_route(graph, segs, 0, 0.0, len(segs) - 1, walls=walls)
    mid_clear = next(p for p in with_walls[:-1] if p[3] == "stop")
    assert _wall_clearance(mid_clear[0], mid_clear[1], walls) >= NAV2_SPLIT_WALL_CLEAR_M


def test_nav2_goal_refused_stops_as_goal_refused_not_unreachable():
    robot = RouteFakeRobot("rosy_42")
    _clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="S3",
        via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-ref", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "S3", "via": ["S4", "S5"], "repeat": False, "drive_mode": "nav2"}, result={"plan": plan})

    async def refused(*_a, **_kw):
        return {"accepted": False, "reason": "LOCALIZATION_UNTRUSTED"}

    robot.navigation_route = refused
    run(runner.start("p-ref", "bob"))
    run(runner.tick())
    view = runner.view("p-ref")
    assert view["state"] == "failed" and view["reason"] == "TRIP_GOAL_REFUSED"
    assert view["detail"]["goal_reason"] == "LOCALIZATION_UNTRUSTED"

@pytest.mark.parametrize("blocker, dispatched", [("rosy_42", False), ("rosy_45", True)])
def test_nav2_localization_refusal_records_blocker_and_dispatch_stage(blocker, dispatched):
    robot = RouteFakeRobot("rosy_42")
    peer = RouteFakeRobot("rosy_45")
    _clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map(), peers=[peer])
    peer._state["pose"] = dict(robot._state["pose"])
    run(console.snapshot())
    # Localization can change between the trip preflight and console admission.
    route = runner._route

    async def route_after_localization_change(*args):
        (peer if dispatched else robot)._state["localization"] = {"state": "CANDIDATES", "pose_frame": "odom"}
        return await route(*args)

    runner._route = route_after_localization_change
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="S3",
        via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-ref", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "S3", "via": ["S4", "S5"], "repeat": False, "drive_mode": "nav2"}, result={"plan": plan})

    run(runner.start("p-ref", "bob"))
    run(runner.tick())
    view = runner.view("p-ref")
    stored = store.trip("p-ref")
    if blocker == "rosy_45":
        assert view["state"] == "running"
        wait = stored["detail"]["peer_wait"]
        assert wait["command_robot_id"] == "rosy_42" and wait["waiting_on"] == [blocker]
        assert wait["stage"] == "pre_dispatch_peer_check" and not wait["dispatch_attempted"]
    else:
        assert view["state"] == "failed" and view["reason"] == "TRIP_GOAL_REFUSED"
        assert view["detail"]["goal_reason"] == "LOCALIZATION_UNTRUSTED"
        assert stored["detail"]["goal_admission"] == {
            "blocked_by": blocker, "waiting_on": [blocker],
            "dispatch_attempted": False, "cancel_confirmed": False,
        }
    assert stored["detail"] == view["detail"]
    assert not robot.routes


def test_nav2_drive_mode_refuses_precision_stop_and_skips_non_precision_binding_checks():
    body = _south_loop_map().body()
    s3 = next(p for p in body["places"] if p["id"] == "S3")
    s3["precision_stop"] = {
        "evidence_ref": "synthetic", "reference_pose": [0.75, -0.21, math.pi],
        "longitudinal_m": 0.02, "lateral_m": 0.02, "heading_rad": 0.05,
        "position_uncertainty_m": 0.002, "heading_uncertainty_rad": 0.01, "max_correction_m": 0.08,
    }
    robot = RouteFakeRobot("rosy_42")
    _clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, SiteMap.model_validate(body))
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="S3",
        via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-prec", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2"},
                      result={"plan": plan})
    with pytest.raises(TripError) as err:
        run(runner.start("p-prec", "bob"))
    assert err.value.code == "PRECISION_STOP_REQUIRES_NAV2_TERMINAL"
    live_prec = LiveTrip(
        {"robot_id": "rosy_42", "detail": {"drive_mode": "nav2"}, "segment_index": 0, "plan": {"segments": plan["segments"]}},
        graph, {"to": "S3", "drive_mode": "nav2"},
    )
    assert runner._precision_terminal_mismatch(live_prec) is True

    plain_robot = RouteFakeRobot("rosy_42")
    _c, _co, _st, plain_graph, _p, _ca, plain_runner = _console_runner(plain_robot, _south_loop_map())
    plain_runner.config = TripConfig(map_binding_required=True)
    live_plain = LiveTrip(
        {"robot_id": "rosy_42", "detail": {"drive_mode": "nav2"}, "segment_index": 0, "plan": {"segments": plan["segments"]}},
        plain_graph, {"to": "S3", "drive_mode": "nav2"},
    )
    assert plain_runner._strict_named_stop(live_plain, len(live_plain.segments) - 1) is None
    assert plain_runner._named_stop_handoff(live_plain, 1) is False
