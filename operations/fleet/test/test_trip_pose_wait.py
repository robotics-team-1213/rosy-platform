"""2026-11-27 rosy_46: a robot standing in a traffic hold lost a Nav2 trip only because its camera sighting went stale."""
import dataclasses

from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.trips.transient_loc_hold import POSE_WAIT_S
from test_site_map_frame_safety import _in_robot_map, _state
from test_trip_runner import BOTH, _free_map, _setup, _ticks, run


def _running(nav="IDLE", linear=0.0):
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"
    body = {"nav": nav, "linear": linear}

    async def robot_state(_rid):
        return {**_state(_in_robot_map(ports.pose.x, ports.pose.y, ports.pose.yaw)), "navigation": body["nav"],
                "mode": "NAVIGATION", "safety": {"estop": False}, "velocity": {"linear": body["linear"], "angular": 0.0},
                "evidence": {"velocity": {"evidence": "fresh"}}}

    runner._robot_state = robot_state
    graph = store.active()[2]
    ports.at(graph.arcs["ab:fwd"], 0.1)
    x, y, yaw = graph.arcs["ab:fwd"].point_at(0.1)
    plan = plan_trip(graph, PlanRequest(map_version=store.active()[0], start_pose=(x, y, yaw), goal="C",
                                        drive_modes=frozenset({"free"}), ignore_start_heading=True,
                                        ignore_arrive_heading=True, stop_offset=False), store.routing_config)
    store.record_plan(plan_id="p1", robot_id="rosy_60", principal_id="bob", map_version=plan.map_version,
                      request={"to": "C", "via": [], "drive_mode": "nav2"}, result={"plan": plan_body(plan)})
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"
    good = ports.pose
    ports.pose = dataclasses.replace(good, state="DEGRADED")
    return runner, ports, body, good


def test_a_standing_robot_waits_for_the_camera_and_resumes():
    runner, ports, _body, good = _running()
    sent = len(ports.goals)
    _ticks(runner, ports, 4)
    view = runner.view("p1")
    assert view["state"] == "running" and view["detail"]["pose_wait"]["pose_state"] == "DEGRADED"
    assert len(ports.goals) == sent  # nothing new goes out while the pose is unusable
    ports.pose = good
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"


def test_a_moving_robot_with_an_unusable_pose_still_stops():
    for nav, linear in (("NAVIGATING", 0.0), ("IDLE", 0.2)):
        runner, ports, _body, _good = _running(nav, linear)
        _ticks(runner, ports, 2)
        assert (runner.view("p1")["state"], runner.view("p1")["reason"]) == ("stopped", "pose"), (nav, linear)


def test_the_pose_wait_ends_with_the_old_stop_reason_at_its_bound():
    runner, ports, _body, _good = _running()
    _ticks(runner, ports, 2)
    assert runner.view("p1")["state"] == "running"
    _ticks(runner, ports, int(POSE_WAIT_S / 0.5) + 2)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "pose") and "pose_wait" not in view["detail"]


def test_a_flapping_pose_does_not_restart_the_wait():
    runner, ports, _body, good = _running()
    bad = ports.pose
    for _ in range(int(POSE_WAIT_S / 0.5) + 2):  # usable for one tick in every four: still one 120 s budget
        ports.pose = good if _ % 4 == 3 else bad
        _ticks(runner, ports)
        if runner.view("p1")["state"] != "running":
            break
    assert (runner.view("p1")["state"], runner.view("p1")["reason"]) == ("stopped", "pose")
