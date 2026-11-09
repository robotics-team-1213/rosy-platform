"""D-1009 route drive: pass points are driven through, only stop points halt; one run, one admission."""

from __future__ import annotations

import math
import sys
import types
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import NavigationState
from core_features.navigation.manager import NavigationError, NavigationManager
from core_features.navigation.route import PASS, STOP, RoutePoint

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


class _State:
    map_id = "map"

    def set_navigation(self, state):
        self.navigation = state


class _Events:
    def __init__(self):
        self.names = []

    def publish(self, name, **kwargs):
        self.names.append(name)


class Nav2:
    """Records what the bridge would send; the test plays Nav2's answers."""

    def __init__(self):
        self.sent = []   # (spec, run_id, correlation_id)
        self.cancelled = 0

    def send_native_goal(self, spec, run_id, *, correlation_id=None):
        self.sent.append((spec, run_id, correlation_id))

    def cancel_goal(self):
        self.cancelled += 1


def make(**kwargs):
    nav = NavigationManager(_Events(), _State(), None, SimpleNamespace(estop=False), **kwargs)
    nav.executor = Nav2()
    return nav, nav.executor


def pts(spec):
    """'pPpS' style: x grows 0.2 per point, y = 0."""
    return [RoutePoint(0.2 * (i + 1), 0.0, PASS if c == "p" else STOP) for i, c in enumerate(spec)]


def finish(nav, ok=True, error=None):
    nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
    nav.on_result(ok, error, correlation_id=nav._active_correlation_id, native_run_id=nav.native.current.run_id)


def grid(blocked, size=50, res=0.1):
    """A 5 m x 5 m costmap at the origin with the given (x, y) cells lethal (254)."""
    data = [0] * (size * size)
    for x, y in blocked:
        data[int(y / res) * size + int(x / res)] = 254
    return {"width": size, "height": size, "resolution": res, "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": data}


def test_one_action_per_stop_and_one_run_for_the_whole_route():
    nav, nav2 = make()
    receipt = []
    nav.route(pts("ppSpS"), correlation_id="r1", receipt_sink=receipt.append)
    first, run_id, cid = nav2.sent[0]
    assert [v.x for v in first.via] == pytest.approx([0.2, 0.4]) and first.x == pytest.approx(0.6)
    assert cid == "r1" and run_id == receipt[0].run_id

    finish(nav)   # arrived at the first stop: the second action goes out by itself, same run
    assert len(nav2.sent) == 2
    second, run_id2, cid2 = nav2.sent[1]
    assert [v.x for v in second.via] == pytest.approx([0.8]) and second.x == pytest.approx(1.0)
    assert (run_id2, cid2) == (run_id, "r1")
    assert nav.nav_state is NavigationState.NAVIGATING and nav.native.current.phase == "RUNNING"
    assert nav.route_status()["stops_made"] == 1 and nav.route_status()["next_stop"]["index"] == 4

    finish(nav)
    assert nav.nav_state is NavigationState.ARRIVED and len(nav2.sent) == 2
    status = nav.route_status()
    assert status["result"] == "succeeded" and status["stops_made"] == 2 and status["actions"] == 2
    assert [p["state"] for p in status["points"]] == ["reached", "reached", "stopped", "reached", "stopped"]


def test_a_route_without_pass_points_is_navigate_to_pose_legs():
    nav, nav2 = make()
    nav.route(pts("SS"))
    assert nav2.sent[0][0].via == ()
    finish(nav)
    assert nav2.sent[1][0].via == () and len(nav2.sent) == 2


def test_second_route_or_goal_while_active_is_refused():
    nav, _ = make()
    nav.route(pts("pS"))
    with pytest.raises(NavigationError) as err:
        nav.route(pts("S"))
    assert err.value.code == "NAVIGATION_ACTIVE"


@pytest.mark.parametrize("points", [[], pts("pp"), [RoutePoint(1, 1, "go")], [RoutePoint(math.nan, 0, STOP)],
                                    [RoutePoint(0, 0, STOP, yaw=math.inf)], pts("p" * 64 + "S")])
def test_bad_routes_are_refused_before_admission(points):
    nav, nav2 = make()
    with pytest.raises(NavigationError) as err:
        nav.route(points)
    assert err.value.code == "VALIDATION_ERROR" and not nav2.sent and nav.native.current is None


def test_headings_follow_the_route_and_a_stop_without_yaw_keeps_the_approach_heading():
    nav, nav2 = make()
    nav.route([RoutePoint(0, 0, PASS), RoutePoint(0, 1, PASS), RoutePoint(1, 1, STOP),
               RoutePoint(1, 2, STOP, yaw=0.5)])
    leg = nav2.sent[0][0]
    assert [v.yaw for v in leg.via] == pytest.approx([math.pi / 2, 0.0]) and leg.yaw == pytest.approx(0.0)
    finish(nav)
    assert nav2.sent[1][0].yaw == 0.5   # given yaw wins


def test_pass_point_inside_an_obstacle_is_skipped_but_a_stop_there_is_not():
    nav, nav2 = make()
    nav.costmap_provider = lambda: grid([(0.4, 0.0), (0.8, 0.0)])
    nav.route(pts("ppSpS"))   # x = 0.2 .. 1.0; 0.4 is a pass point, 0.8 a pass point
    leg = nav2.sent[0][0]
    assert [v.x for v in leg.via] == pytest.approx([0.2]) and leg.x == pytest.approx(0.6)
    finish(nav)
    assert [v.x for v in nav2.sent[1][0].via] == []   # 0.8 skipped too
    assert nav.route_status()["skipped"] == [1, 3]

    nav, nav2 = make()
    nav.costmap_provider = lambda: grid([(0.6, 0.0)])   # the stop itself is in the obstacle
    nav.route(pts("ppS"))
    assert nav2.sent[0][0].x == pytest.approx(0.6) and nav.route_status()["skipped"] == []


def test_pass_point_off_the_costmap_is_skipped():
    nav, nav2 = make()
    nav.costmap_provider = lambda: grid([])
    nav.route([RoutePoint(60.0, 0.0, PASS), RoutePoint(1.0, 1.0, STOP)])
    assert nav2.sent[0][0].via == ()


def test_failed_leg_is_resent_without_its_next_pass_point_until_none_is_left():
    nav, nav2 = make()
    nav.route(pts("pppS"))
    finish(nav, ok=False, error="ABORTED")
    assert len(nav2.sent) == 2 and [v.x for v in nav2.sent[1][0].via] == pytest.approx([0.4, 0.6])
    assert nav.nav_state is NavigationState.NAVIGATING
    finish(nav, ok=False, error="ABORTED")
    finish(nav, ok=False, error="ABORTED")
    assert len(nav2.sent) == 4 and nav2.sent[3][0].via == ()
    assert nav.nav_state is NavigationState.NAVIGATING and nav.route_status()["skipped"] == [0, 1, 2]
    finish(nav, ok=False, error="ABORTED")   # the stop leg itself fails: now the run fails
    assert nav.nav_state is NavigationState.FAILED and nav.route_status()["result"] == "failed"
    assert nav.native.lookup().result == "FAILED"


def test_a_stop_is_never_skipped_after_a_failure():
    nav, nav2 = make()
    nav.route(pts("SS"))
    finish(nav, ok=False, error="ABORTED")
    assert len(nav2.sent) == 1 and nav.nav_state is NavigationState.FAILED


def test_pass_points_the_robot_already_reached_are_not_dropped_or_resent():
    nav, nav2 = make()
    nav.route(pts("ppS"))
    nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
    nav.on_pose_progress(0.2, 0.05)   # at the first pass point
    finish(nav, ok=False, error="ABORTED")
    assert [v.x for v in nav2.sent[1][0].via] == pytest.approx([]) and nav.route_status()["skipped"] == [1]
    assert nav.route_status()["points"][0]["state"] == "reached"


def test_cancel_ends_the_route_and_sends_nothing_more():
    nav, nav2 = make()
    nav.route(pts("SS"), correlation_id="c")
    nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
    nav.cancel(source="api")
    assert nav2.cancelled == 1 and nav.route_status()["result"] == "canceled"
    nav.on_result(True, correlation_id="c", native_run_id=nav.native.current.run_id)   # a late Nav2 answer
    assert len(nav2.sent) == 1


def test_a_plain_goal_after_a_route_clears_the_route():
    nav, nav2 = make()
    nav.route(pts("S"))
    finish(nav)
    assert nav.route_status()["result"] == "succeeded"
    nav.goal(SimpleNamespace(x=1, y=1, yaw=0, frame="map", via=()))
    assert nav.route_status() is None


def test_executor_that_cannot_send_the_next_leg_fails_the_run_not_arrives():
    nav, nav2 = make()
    nav.route(pts("SS"), correlation_id="c")
    nav2.send_native_goal = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    finish(nav)   # the first stop was reached, but the second leg cannot go out
    assert nav.nav_state is NavigationState.FAILED and nav.route_status()["result"] == "failed"
    assert nav.native.lookup().result == "FAILED"
    names = nav._events.names
    assert "nav.failed" in names and "nav.completed" not in names


def test_nav_006_clock_runs_across_leg_resends():
    now = [0.0]
    nav, nav2 = make(clock=lambda: now[0])
    nav.route(pts("pppS"))
    nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
    nav.on_pose_progress(0.0, 0.0)          # baseline at t=0
    for _ in range(2):                      # Nav2 aborts and CORE resends; the robot never moves
        now[0] += 12.0
        nav.on_result(False, "ABORTED", native_run_id=nav.native.current.run_id)
        nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
        nav.on_pose_progress(0.0, 0.0)
    now[0] += 12.0
    nav.on_pose_progress(0.0, 0.0)          # 36 s without 5 cm of progress
    assert nav.nav_state is NavigationState.CANCELED and nav.route_status()["result"] == "failed"
    assert "nav.stuck" in nav._events.names


def test_first_acceptance_of_a_route_restarts_the_progress_clock():
    now = [0.0]
    nav, nav2 = make(clock=lambda: now[0])
    nav._last_progress_pos, nav._last_progress_ts = (9.0, 9.0), -100.0   # an earlier goal left a stale baseline
    nav.route(pts("S"))
    nav.on_goal_accepted(native_run_id=nav.native.current.run_id)
    assert nav._last_progress_pos is None and nav._last_progress_ts == 0.0


def test_lease_expiring_between_legs_cancels_the_whole_route():
    lease = [0.0]
    nav, nav2 = make(lease_clock=lambda: lease[0])
    nav.route(pts("SS"), correlation_id="L", lease_ttl_s=2.0, lease_owner="tok")
    finish(nav)
    assert len(nav2.sent) == 2
    lease[0] = 3.0
    assert nav.expire_goal_lease() is True
    assert nav2.cancelled == 1 and nav.route_status()["result"] == "canceled"
    nav.on_result(True, correlation_id="L", native_run_id=nav.native.current.run_id)
    assert len(nav2.sent) == 2 and nav.nav_state is NavigationState.CANCELED


def test_with_the_real_goal_tracker_a_late_result_of_the_first_leg_is_not_the_second_legs():
    from core.bridge import goal_tracker
    goals = goal_tracker.GoalTracker()
    nav, _ = make()
    gens = []

    class BridgeLike(Nav2):
        def send_native_goal(self, spec, run_id, *, correlation_id=None):
            super().send_native_goal(spec, run_id, correlation_id=correlation_id)
            gens.append(goals.opening(correlation_id, run_id))

    nav.executor = BridgeLike()
    handle = SimpleNamespace(accepted=True, get_result_async=lambda: None)
    done = lambda status: SimpleNamespace(result=lambda: SimpleNamespace(status=status))  # noqa: E731
    nav.route(pts("SS"), correlation_id="c")
    goal_tracker.on_response(goals, nav, SimpleNamespace(result=lambda: handle), gens[0], attach_result=lambda *a: None)
    goal_tracker.on_result(goals, nav, done(4), gens[0])            # leg 1 succeeded: leg 2 goes out, same run
    assert len(gens) == 2 and gens[1] != gens[0] and nav.nav_state is NavigationState.NAVIGATING
    goal_tracker.on_result(goals, nav, done(4), gens[0])            # the same result delivered again: stale
    assert nav.nav_state is NavigationState.NAVIGATING and nav.route_status()["stops_made"] == 1
    goal_tracker.on_response(goals, nav, SimpleNamespace(result=lambda: handle), gens[1], attach_result=lambda *a: None)
    goal_tracker.on_result(goals, nav, done(4), gens[1])
    assert nav.nav_state is NavigationState.ARRIVED and nav.route_status()["result"] == "succeeded"


# --- REST ---------------------------------------------------------------------------------------------------

@pytest.fixture
def robot(core_client, monkeypatch):
    tc, svc = core_client()
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    svc.nav.executor = Nav2()
    return tc, svc


def _route(tc, points, **extra):
    return tc.post("/api/v1/navigation/route", json={"points": points, **extra}, headers=OPERATOR)


def test_route_endpoint_runs_the_whole_route_from_one_request(robot):
    tc, svc = robot
    body = [{"x": 0.2, "y": 0, "kind": "pass"}, {"x": 0.4, "y": 0, "kind": "pass"},
            {"x": 0.6, "y": 0}, {"x": 0.8, "y": 0, "kind": "stop", "yaw": 0.0}]
    reply = _route(tc, body, correlation_id="trip-1")
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["accepted"] and data["operation"]["kind"] == "navigate" and data["route"]["legs"] == 2
    assert data["route"]["active"] and data["route"]["next_stop"]["index"] == 2

    assert _route(tc, body).json()["error"]["code"] == "NAVIGATION_ACTIVE"   # only while this route is active
    state = tc.get("/api/v1/navigation/state", headers=OPERATOR).json()
    assert state["route"]["remaining"] == 4 and [p["kind"] for p in state["route"]["points"]] == \
        ["pass", "pass", "stop", "stop"]

    run_id = svc.nav.native.current.run_id
    finish(svc.nav)
    assert len(svc.nav.executor.sent) == 2 and svc.nav.native.current.run_id == run_id
    finish(svc.nav)
    state = tc.get("/api/v1/navigation/state", headers=OPERATOR).json()
    assert state["navigation"] == "ARRIVED" and state["route"]["stops_made"] == 2


@pytest.mark.parametrize("body", [{"points": []}, {"points": [{"x": 0, "y": 0, "kind": "go"}]},
                                  {"points": [{"x": 0, "y": 0, "kind": "pass"}]},
                                  {"points": [{"x": 0, "y": 0}], "lease_ttl_s": 2.0}])
def test_route_endpoint_rejects_bad_requests_before_moving(robot, body):
    tc, svc = robot
    reply = tc.post("/api/v1/navigation/route", json=body, headers=OPERATOR)
    assert reply.status_code in (400, 422) and not svc.nav.executor.sent
    assert svc.nav.nav_state is NavigationState.IDLE


def test_route_lease_is_one_lease_for_the_route(robot):
    tc, svc = robot
    assert _route(tc, [{"x": 0.2, "y": 0}, {"x": 0.4, "y": 0}], correlation_id="L", lease_ttl_s=2.0).status_code == 200
    svc.nav.on_goal_accepted(native_run_id=svc.nav.native.current.run_id)
    assert tc.post("/api/v1/navigation/goal/lease", json={"correlation_id": "L", "ttl_s": 2.0},
                   headers=OPERATOR).status_code == 200
    finish(svc.nav)   # first stop reached; the lease still belongs to the same route
    assert tc.post("/api/v1/navigation/goal/lease", json={"correlation_id": "L", "ttl_s": 2.0},
                   headers=OPERATOR).status_code == 200


# --- bridge goal builder (ROS messages stubbed) -------------------------------------------------------------

def test_bridge_builds_through_poses_only_for_a_leg_with_pass_points(monkeypatch):
    class Msg(SimpleNamespace):
        pass

    class Pose:
        def __init__(self):
            self.header = SimpleNamespace(frame_id=None, stamp=None)
            self.pose = SimpleNamespace(position=SimpleNamespace(x=0, y=0),
                                        orientation=SimpleNamespace(z=0, w=1))

    class Through:
        class Goal(Msg):
            pass

    class ToPose:
        class Goal(Msg):
            pass

    monkeypatch.setitem(sys.modules, "geometry_msgs", types.ModuleType("geometry_msgs"))
    monkeypatch.setitem(sys.modules, "geometry_msgs.msg", types.SimpleNamespace(PoseStamped=Pose))
    monkeypatch.setitem(sys.modules, "nav2_msgs", types.ModuleType("nav2_msgs"))
    monkeypatch.setitem(sys.modules, "nav2_msgs.action",
                        types.SimpleNamespace(NavigateThroughPoses=Through, NavigateToPose=ToPose))
    sys.modules.pop("core.bridge.nav_goal", None)
    from core.bridge import nav_goal
    from core_features.navigation.manager import NavGoalSpec

    goal, through = nav_goal.build(NavGoalSpec(1, 2, 0.0), "t")
    assert not through and isinstance(goal, ToPose.Goal) and goal.pose.pose.position.x == 1
    goal, through = nav_goal.build(NavGoalSpec(3, 0, 0.0, via=(NavGoalSpec(1, 0, 0.0), NavGoalSpec(2, 0, 0.0))), "t")
    assert through and isinstance(goal, Through.Goal)
    assert [p.pose.position.x for p in goal.poses] == [1, 2, 3] and goal.poses[0].header.frame_id == "map"
    sys.modules.pop("core.bridge.nav_goal", None)
