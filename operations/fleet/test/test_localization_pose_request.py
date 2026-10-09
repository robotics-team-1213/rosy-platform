"""D-546 6: Fleet answers a robot's pose request - overhead first, arbiter, model hook, then a human.

Fake robots, a fake clock and a fake overhead pose; every tick is one 0.5 s poll."""

from __future__ import annotations

from core_common.protocol.localization import DecisionSource
from fakes import FakeClock, FakeRobot, run
from fleet.localization import pose_request
from fleet.localization.map_pose import MapPose
from fleet.server.localization_service import LocalizationService


def trusted(x=1.0, y=2.0, yaw=0.5, anchor_age_s=0.2):
    return MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, anchor_age_s=anchor_age_s)


UNKNOWN = MapPose(None, None, None, "UNKNOWN", None, 0.0, None)
DEGRADED = MapPose(1.0, 2.0, 0.5, "DEGRADED", "bridged", 1.5, 0.1, anchor_age_s=9.0)


def request(request_id="pose-1", age_s=0.5, ttl_s=30.0, reason="pose_stale"):
    return {"request_id": request_id, "robot_id": "r1", "reason": reason, "created_at": 1.0,
            "age_s": age_s, "ttl_s": ttl_s, "evidence": {"odom_pose": {"x": 9.0, "y": 9.0, "yaw": 0.0}}}


def robot(loc="LOCALIZED", frame="map", lf_reason="lane_return_pose_stale"):
    state = {"robot_id": "r1", "pose": {"x": 9.0, "y": 9.0, "yaw": 0.0},        # the robot's own (odom) pose
             "localization": {"state": loc, "pose_frame": frame},
             "line_follow": {"mode": "CAMERA_LINE", "state": "HOLD", "reason": lf_reason}}
    r = FakeRobot("r1", state=state)
    r.pose_request = request()
    return r


def rig(r, pose, *, overhead=True):
    clock = FakeClock()
    svc = LocalizationService(lambda: {"r1": r}, clock=clock, wall=clock, overhead_cue=overhead)
    svc.set_overhead_pose(lambda rid: pose)
    return svc, clock


def ticks(svc, clock, seconds):
    for _ in range(int(round(seconds / 0.5))):
        run(svc.tick())
        clock.advance(0.5)


def test_a_trusted_fresh_overhead_pose_answers_with_the_request_id_and_a_ttl():
    r = robot()
    svc, clock = rig(r, trusted())
    ticks(svc, clock, 2.0)
    assert len(r.decisions) == 1
    d = r.decisions[0]
    assert d.request_id == "pose-1" and d.source is DecisionSource.OVERHEAD
    assert (d.pose.x, d.pose.y, d.pose.yaw) == (1.0, 2.0, 0.5)       # not the robot's own 9, 9
    assert d.ttl_s == pose_request.DECISION_TTL_S
    view = svc.view("r1")
    assert view["pose_request"]["by"] == "overhead" and not view["needs_human"]


def test_the_decision_is_not_repeated_inside_its_ttl_but_asked_again_after_it():
    r = robot()
    svc, clock = rig(r, trusted())
    ticks(svc, clock, pose_request.RETRY_S - 1.0)
    assert len(r.decisions) == 1
    ticks(svc, clock, 3.0)                       # the robot's check failed or the answer was lost
    assert len(r.decisions) == 2


def test_untrusted_overhead_or_none_is_never_used_and_the_operator_is_told():
    for pose in (DEGRADED, UNKNOWN, None, trusted(anchor_age_s=pose_request.OVERHEAD_ANCHOR_FRESH_S + 1)):
        r = robot()
        svc, clock = rig(r, pose)
        ticks(svc, clock, 2.0)
        assert r.decisions == [], pose
        view = svc.view("r1")
        assert view["needs_human"] and view["pose_request"]["state"] == "needs_human"


def test_the_overhead_answer_needs_the_overhead_flag():
    r = robot()
    svc, clock = rig(r, trusted(), overhead=False)       # D-257 amendment not accepted
    ticks(svc, clock, 2.0)
    assert r.decisions == [] and svc.view("r1")["needs_human"]


def test_the_robots_own_odom_pose_is_never_an_answer():
    r = robot(frame="odom")
    svc, clock = rig(r, None)
    ticks(svc, clock, 2.0)
    assert r.decisions == [] and svc.view("r1")["needs_human"]


def test_the_arbiter_owns_it_when_the_robot_has_candidates():
    r = robot(loc="CANDIDATES")
    svc, clock = rig(r, None)
    svc._arbiter.pending = lambda rid, request_id: True
    ticks(svc, clock, 2.0)
    assert svc.view("r1")["pose_request"]["by"] == "arbiter" and not svc.view("r1")["needs_human"]


def test_a_request_past_its_ttl_is_ignored():
    r = robot()
    r.pose_request = request(age_s=31.0, ttl_s=30.0)
    svc, clock = rig(r, trusted())
    ticks(svc, clock, 2.0)
    assert r.decisions == [] and svc.view("r1")["pose_request"] is None and not svc.view("r1")["needs_human"]


def test_no_request_is_read_unless_lane_return_holds():
    r = robot(lf_reason="following")
    svc, clock = rig(r, trusted())
    ticks(svc, clock, 2.0)
    assert not any(c[0] == "localization_request" for c in r.calls) and r.decisions == []


def test_a_closed_request_clears_the_human_flag():
    r = robot()
    svc, clock = rig(r, UNKNOWN)
    ticks(svc, clock, 1.0)
    assert svc.view("r1")["needs_human"]
    r.pose_request = None                                 # lane_return resumed, CORE closed it
    ticks(svc, clock, 1.0)
    assert not svc.view("r1")["needs_human"] and svc.view("r1")["pose_request"] is None


def test_the_model_hook_is_a_named_stub_that_answers_nothing():
    assert pose_request.resolve_pose_with_model(request(), {}) is None


def test_a_request_that_keeps_failing_goes_to_a_human_after_three_answers():
    r = robot()
    svc, clock = rig(r, trusted())
    ticks(svc, clock, 40.0)                      # the request stays open: every answer was refused
    assert len(r.decisions) == pose_request.MAX_ANSWERS
    view = svc.view("r1")
    assert view["needs_human"] and view["pose_request"]["failed"]
    r.pose_request = request(request_id="pose-2")        # CORE reopened it after its ttl
    ticks(svc, clock, 20.0)
    assert len(r.decisions) == pose_request.MAX_ANSWERS and svc.view("r1")["needs_human"]
    r._state["line_follow"]["reason"] = "following"      # lane_return let go: a new episode
    ticks(svc, clock, 1.0)
    assert not svc.view("r1")["needs_human"]


def test_a_request_closed_after_the_answer_is_not_a_failure():
    r = robot()
    svc, clock = rig(r, trusted())
    ticks(svc, clock, 1.0)
    r.pose_request = None                                # accepted: CORE closed it
    ticks(svc, clock, 1.0)
    r.pose_request = request(request_id="pose-2")
    ticks(svc, clock, 1.0)
    assert len(r.decisions) == 2 and not svc.view("r1")["needs_human"]


def test_the_overhead_cue_is_on_by_default_and_can_be_turned_off(tmp_path):
    from fleet import cli
    from fleet.server.localization_service import build_localization_service
    robots = tmp_path / "robots.yaml"
    robots.write_text("robots: []" + chr(10), encoding="utf-8")
    assert cli.parse_args(["console", "--robots", str(robots)]).localization_overhead_cue is True
    assert cli.parse_args(["console", "--robots", str(robots),
                           "--no-localization-overhead-cue"]).localization_overhead_cue is False
    console = type("C", (), {"clients": staticmethod(lambda: {})})()
    assert build_localization_service(console, None).overhead_cue is True
    assert build_localization_service(console, None, overhead_cue=False).overhead_cue is False
