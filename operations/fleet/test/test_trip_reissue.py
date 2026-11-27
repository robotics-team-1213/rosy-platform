"""D-1086: a Nav2 road trip that ended for a non-hazard reason is planned and started again, never for a hazard."""
from uuid import uuid4

import pytest

from fakes import run
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server import trip_reissue as ri
from fleet.server.trip_ports import TripError
from test_nav2_trip_recovery import _trip


def _planner(store, graph, pose):
    calls = []

    async def plan(robot_id, body, principal_id):
        p = pose["v"]
        data = plan_body(plan_trip(graph, PlanRequest(map_version=store.active()[0], start_pose=(p.x, p.y, p.yaw),
                                                      goal=body.to, stop_offset=False), store.routing_config))
        plan_id = uuid4().hex
        store.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id=principal_id,
                          map_version=data["map_version"], request=body.model_dump(mode="json", exclude={"execute"}),
                          result={"plan": data})
        calls.append((robot_id, body.to, principal_id))
        return {"plan_id": plan_id}
    return plan, calls


def _rig():
    robot, clock, store, graph, pose, canceled, runner, live = _trip()
    plan, calls = _planner(store, graph, pose)
    reissue = ri.TripReissue(runner, plan)
    run(reissue.tick())                         # the first poll only marks the trips already closed
    return robot, clock, runner, live, reissue, calls


def _poll(reissue, clock, seconds, dt=1.0):
    for _ in range(int(seconds / dt)):
        run(reissue.tick())
        clock.advance(dt)


def _end_pose(runner, live):
    run(runner._stop(live, "stopped", "pose", {"pose_state": "DEGRADED"}))
    assert live.view["state"] == "stopped"


def test_a_pose_end_is_reissued_after_the_first_delay_with_both_trips_linked():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    record = live.view["detail"]["reissue"]
    assert record["state"] == "scheduled" and record["attempt"] == 1 and record["kind"] == "pose_wait_expired"
    _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] - 1)
    assert calls == []
    _poll(reissue, clock, 3)
    assert calls == [("rosy_42", "S4", "bob")]          # the original principal, the original request
    new = runner._live["rosy_42"]
    assert new.open and new.view["trip_id"] != live.view["trip_id"]
    assert live.view["detail"]["reissue"]["state"] == "reissued"
    assert live.view["detail"]["reissue"]["next_trip_id"] == new.view["trip_id"]
    link = new.view["detail"]["reissued_from"]
    assert link["trip_id"] == live.view["trip_id"] and link["attempt"] == 1 and link["by"] == "auto_reissue"
    assert runner.view(live.view["trip_id"])["detail"]["reissue"]["state"] == "reissued"   # stored, not only live


@pytest.mark.parametrize("change, why", [
    ("estop", "estop"), ("moving", "robot_stopped"), ("goal", "robot_idle"), ("lost", "localized"),
    ("unread", "state_unread"), ("map", "map_version")])
def test_an_unmet_condition_waits_one_more_interval(change, why):
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    saved = dict(robot._state)
    if change == "estop":
        robot._state["safety"] = {"estop": True}
    elif change == "moving":
        robot._state["velocity"] = {"linear": 0.05, "angular": 0.0}
    elif change == "goal":
        robot._state["goal"] = {"id": "g"}
    elif change == "lost":
        robot._state["localization"] = {"state": "SUSPECT"}
    elif change == "unread":
        robot.state_error = OSError("no answer")
    else:
        version = runner._store.active()
        runner._store.active = lambda: (version[0] + 1, *version[1:])
    _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] + 2)
    record = live.view["detail"]["reissue"]
    assert calls == [] and record["waiting_for"] == why and record["state"] == "scheduled"
    if change in ("estop", "moving", "goal", "lost", "unread"):
        robot._state.clear()
        robot._state.update(saved)
        robot.state_error = None
        _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] + 2)
        assert len(calls) == 1 and "waiting_for" not in live.view["detail"]["reissue"]


def test_one_good_read_is_not_enough():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    clock.advance(ri.REISSUE_DELAYS_S[0])
    run(reissue.tick())
    assert calls == [] and reissue.pending["rosy_42"]["reads"] == 1
    run(reissue.tick())
    assert len(calls) == 1


def test_three_reissues_then_the_original_reason_stands():
    robot, clock, runner, live, reissue, calls = _rig()
    for attempt in range(1, ri.MAX_REISSUES + 2):
        _end_pose(runner, live)
        run(reissue.tick())
        if attempt > ri.MAX_REISSUES:
            break
        _poll(reissue, clock, ri.REISSUE_DELAYS_S[attempt - 1] + 2)
        assert len(calls) == attempt
        live = runner._live["rosy_42"]
        assert live.view["detail"]["reissued_from"]["attempt"] == attempt
    record = live.view["detail"]["reissue"]
    assert record["state"] == "limit" and (live.view["state"], live.view["reason"]) == ("stopped", "pose")
    _poll(reissue, clock, 60)
    assert len(calls) == ri.MAX_REISSUES


def test_the_chain_ends_ten_minutes_after_its_first_end():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    robot._state["safety"] = {"estop": True}
    _poll(reissue, clock, ri.TOTAL_S + 5, dt=5.0)
    assert calls == [] and live.view["detail"]["reissue"]["dropped"] == "total_limit"
    assert "rosy_42" not in reissue.pending


def test_a_new_trip_from_anyone_drops_the_pending_reissue():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    planned = run(reissue.plan("rosy_42", __import__("fleet.server.trip_routes", fromlist=["TripRequest"]).TripRequest(
        to="S4", drive_mode="nav2"), "carol"))
    run(runner.start(planned["plan_id"], "carol"))       # an operator's own trip
    calls.clear()
    _poll(reissue, clock, 30)
    assert calls == [] and live.view["detail"]["reissue"]["dropped"] == "new_trip"


def test_a_refused_start_is_recorded_and_spends_the_attempt(monkeypatch):
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())

    async def refuse(*_a, **_k):
        raise TripError(409, "TRIP_BATTERY_LOW")
    monkeypatch.setattr(runner, "start", refuse)
    _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] + 2)
    record = live.view["detail"]["reissue"]
    assert (record["state"], record["error"]) == ("start_refused", "TRIP_BATTERY_LOW") and "rosy_42" not in reissue.pending


def _view(state="stopped", reason="pose", detail=None, **extra):
    return {"state": state, "reason": reason, "detail": detail or {}, "hold": None, **extra}


NAV2 = {"to": "S4", "drive_mode": "nav2"}
EXHAUSTED = {"recovery": {"state": "exhausted", "waiting_for": None, "attempts": [{}, {}, {}]}}


@pytest.mark.parametrize("view, kind", [
    (_view(), "pose_wait_expired"),
    (_view(reason="map_frame", detail={"binding": "ROBOT_NOT_LOCALIZED"}), "relocalization_wait_expired"),
    (_view("failed", "TRIP_ROBOT_UNREACHABLE"), "robot_unreachable"),
    (_view("failed", "GOAL_LEASE_NOT_ACTIVE"), "goal_lease_ended"),
    (_view(reason="stall", detail=EXHAUSTED), "recovery_exhausted"),
    (_view(reason="navigation", detail={**EXHAUSTED, "recovery_end": "window"}), "recovery_exhausted"),
])
def test_eligible_ends(view, kind):
    assert ri.eligible(view, NAV2) == kind


@pytest.mark.parametrize("view, request_", [
    (_view("canceled", None), NAV2),                                                   # operator cancel, E-stop close
    (_view(reason="lease_lost"), NAV2),
    (_view(reason="ROAD_SPEED_OWNER_MISSING"), NAV2), (_view("failed", "ROAD_SPEED_OWNER_CHANGED"), NAV2),
    (_view(reason="map_version"), NAV2),
    *[(_view(reason="map_frame", detail={"binding": b}), NAV2)
      for b in ("MAP_FRAME_MISMATCH", "MAP_BINDING_REQUIRED", "MAP_BINDING_CHANGED", "GRID_CHANGED",
                "MAP_BINDING_SITE_CHANGED")],
    (_view(detail={"off_lane_m": 0.2}), NAV2),                                         # off-lane backstop
    *[(_view("failed", code), NAV2) for code in (
        "TRIP_BATTERY_LOW", "TRIP_BATTERY_UNKNOWN", "CHARGE_BAY_DOCK_FAILED", "DOCK_TIMEOUT",
        "TRIP_LEASE_UNSUPPORTED", "TRIP_PAUSE_STOP_UNCONFIRMED", "TRIP_GOAL_REFUSED", "TRIP_POSE_UNTRUSTED",
        "MAP_FRAME_MISMATCH", "TRIP_LOOP_ERROR")],
    (_view(reason="stall"), NAV2),                                                     # no recovery: link loss etc.
    (_view(reason="stall", detail={"recovery": {"state": "exhausted", "waiting_for": None}}), NAV2),   # no ladder
    (_view(reason="stall", detail={"recovery": {**EXHAUSTED["recovery"], "waiting_for": "robot_stopped"}}), NAV2),
    (_view("failed", "TRIP_ROBOT_UNREACHABLE", {"kind": "RuntimeError"}), NAV2),     # a Fleet fault, not the link
    (_view(reason="stall", detail={"recovery": {**EXHAUSTED["recovery"], "same_spot": {"count": 4}}}), NAV2),
    (_view(reason="stall", detail={**EXHAUSTED, "recovery_end": "estop"}), NAV2),
    (_view(reason="stall", detail={**EXHAUSTED, "recovery_end": "out_of_scope"}), NAV2),
    (_view(reason="stall", detail={**EXHAUSTED, "recovery_end": "wait_s"}), NAV2),    # never proven stopped
    (_view(reason="junction_no_window"), NAV2), (_view(reason="WAIT_PREFIX_RESERVATION_LOST"), NAV2),
    (_view(detail={"stop_sent": False}), NAV2),                                        # halt unconfirmed
    (_view(detail={"error": "STOP_FAILED"}), NAV2),
    (_view(hold={"reason": "fleet_hold"}), NAV2),                                      # pause / hold
    (_view(detail={"canceled_by": "bob"}), NAV2),
    (_view(detail={"traffic_hold": {"names": ["x"]}}), NAV2), (_view(detail={"peer_wait": {"waiting_on": ["y"]}}), NAV2),
    (_view(detail={"parking_handoff": {"phase": "docking"}}), NAV2),                   # dock custody
    (_view(lease={"job_id": "job-1"}), NAV2),                                          # a job owns it
    (_view(purpose="charge_return"), NAV2),                                            # a charge session owns it
    (_view(repeat=True), NAV2), (_view(convoy={"leader": "r9"}), NAV2),
    (_view(), {"to": "S4", "drive_mode": "lane"}), (_view(), {"to": {"x": 0, "y": 0}, "drive_mode": "nav2"}),
    (_view(), {**NAV2, "repeat": True}), (_view(), {**NAV2, "convoy": {"leader": "r9"}}),
])
def test_never_reissued(view, request_):
    assert ri.eligible(view, request_) is None


def test_forbidden_end_schedules_nothing():
    robot, clock, runner, live, reissue, calls = _rig()
    run(runner._stop(live, "stopped", "map_frame", {"binding": "MAP_FRAME_MISMATCH"}))
    _poll(reissue, clock, 60)
    assert calls == [] and "reissue" not in live.view["detail"] and reissue.pending == {}


def test_an_estop_since_the_end_drops_the_reissue_even_when_released():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    runner.close_all("estop")                    # pressed and released while the reissue waited
    _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] + 5)
    assert calls == [] and live.view["detail"]["reissue"]["dropped"] == "stopped_since"


def test_a_line_follow_off_for_this_robot_drops_the_reissue():
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    run(reissue.tick())
    runner._start_cancels["rosy_42"] = runner._start_cancels.get("rosy_42", 0) + 1
    _poll(reissue, clock, ri.REISSUE_DELAYS_S[0] + 5)
    assert calls == [] and live.view["detail"]["reissue"]["dropped"] == "stopped_since"


def test_a_fault_on_one_robot_does_not_end_the_poll(monkeypatch):
    robot, clock, runner, live, reissue, calls = _rig()
    _end_pose(runner, live)
    monkeypatch.setattr(reissue, "_judge", lambda _live: 1 / 0)
    run(reissue.tick())                          # logged, not raised
    assert reissue.pending == {}
