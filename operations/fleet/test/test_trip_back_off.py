"""D-1087: a same-spot failure backs off once (CORE's nudge_backward), looks again, then is reissued slow and recentred."""
import pytest
from fastapi import HTTPException

from fakes import run
from fleet.server import named_stop_map_pose
from fleet.server import nav2_recovery_ladder as ladder
from fleet.server import trip_back_off as back
from fleet.server import trip_reissue as ri
from rosy.world.state.projections.map_pose import MapPose
from test_trip_reissue import _planner, _poll
from test_nav2_trip_recovery import _trip


def _cam(x, y, yaw, odom_stamp=0.0):
    return MapPose(x, y, yaw, "LOCALIZED", "bridged", 0.02, 0.1, anchor_age_s=0.1, map_id="site-loop",
                   odom_stamp=odom_stamp, anchor_source="sighting")


SAME_SPOT = {"state": "exhausted", "waiting_for": None, "same_spot": {"count": 4, "lat_m": -0.03, "wall_clear_m": 0.10},
             "attempts": [{"attempt": k, "speed_cap_mps": None if k == 1 else 0.05, "recentre": "forced"}
                          for k in (1, 2, 3)]}


class Rig:
    def __init__(self, monkeypatch, chain=None):
        robot, clock, store, graph, pose, _c, runner, live = _trip()
        self.robot, self.clock, self.runner, self.live, self.pose = robot, clock, runner, live, pose
        x, y, t = graph.arcs["upper_east:fwd"].point_at(0.3)
        pose["v"] = _cam(x, y, t, odom_stamp=clock())
        run(runner.tick())
        robot._state["mode"] = "IDLE"
        self.steps, self.status = [], {"kind": "nudge_backward", "state": "running"}

        async def step(robot_id, direction, distance):
            self.steps.append((robot_id, direction, distance))
            return {"state": "running", "traffic_held": []}

        async def status(_robot_id):
            if isinstance(self.status, Exception):
                raise self.status
            return self.status

        async def slam(_runner, _robot_id, _version, binding_id=None):
            return (self.pose["v"], "b1")
        runner.robot_step, runner.robot_step_status = step, status
        runner.bay_cable_inhibited = lambda _r: False
        runner._roster = lambda: ["rosy_42"]
        monkeypatch.setattr(named_stop_map_pose, "read_precision_pose", slam)
        plan, self.calls = _planner(store, graph, pose)
        self.reissue = ri.TripReissue(runner, plan)
        run(self.reissue.tick())
        live.view["detail"]["recovery"] = dict(SAME_SPOT)
        if chain is not None:
            live.view["detail"]["reissued_from"] = {**chain, "first_end_at": clock()}
        run(runner._stop(live, "stopped", "stall", {}))
        assert live.view["state"] == "stopped"
        run(self.reissue.tick())

    @property
    def record(self):
        return self.live.view["detail"]["reissue"]

    def poll(self, seconds):
        for _ in range(int(seconds)):   # poses stay fresh as a live robot's do
            self.pose["v"] = _cam(self.pose["v"].x, self.pose["v"].y, self.pose["v"].yaw, odom_stamp=self.clock())
            _poll(self.reissue, self.clock, 1)


def test_backs_off_once_looks_again_then_reissues_slow_and_recentred(monkeypatch):
    rig = Rig(monkeypatch)
    assert rig.record["kind"] == "same_spot" and rig.record["back_off"]["phase"] == "pending"
    rig.poll(ri.REISSUE_DELAYS_S[0] + 2)
    assert rig.steps == [("rosy_42", "backward", back.BACK_OFF_M)] and rig.calls == [], rig.record.get("waiting_for")
    assert rig.record["back_off"]["phase"] == "backing" and rig.record["back_off"]["before"] is not None
    rig.status = {"kind": "nudge_backward", "state": "done", "reason": "done"}
    rig.poll(3)
    assert rig.record["back_off"]["result"] == "done" and rig.record["back_off"]["phase"] == "looking"
    rig.poll(ri.REISSUE_DELAYS_S[0] + 2)
    assert len(rig.calls) == 1 and rig.record["state"] == "reissued"
    new = rig.runner._live["rosy_42"]
    assert new.view["detail"]["first_leg"] == {"until_m": back.FIRST_LEG_M, "why": "back_off"}
    assert new.view["detail"]["reissued_from"]["back_offs"] == 1
    assert new.view["detail"]["reissued_from"]["back_off_m"] == pytest.approx(back.BACK_OFF_M)


@pytest.mark.parametrize("setup, why", [
    ("peer_unknown", "peer_unknown"), ("peer_near", "peer_near"), ("excluded", "excluded_zone"),
    ("crosswalk", "crosswalk"), ("navigation_mode", "mode_not_idle"), ("cable", "cable"),
    ("no_room", "no_room"), ("estop", "estop")])
def test_no_back_off_when_a_condition_fails(monkeypatch, setup, why):
    rig = Rig(monkeypatch)
    me = rig.pose["v"]
    if setup in ("peer_unknown", "peer_near"):
        rig.runner._roster = lambda: ["rosy_42", "rosy_43"]
        own = rig.runner._poses.arbitrated_pose

        def poses(r):
            if r != "rosy_43":
                return own(r)
            return None if setup == "peer_unknown" else _cam(me.x - 0.2, me.y, me.yaw, odom_stamp=rig.clock())
        rig.runner._poses.arbitrated_pose = poses
    elif setup == "excluded":
        monkeypatch.setattr(back, "_excluded", lambda *_a: True)
    elif setup == "crosswalk":
        monkeypatch.setattr(back, "crosswalks_on", lambda *_a: ["cw1"])
    elif setup == "navigation_mode":
        rig.robot._state["mode"] = "NAVIGATION"
    elif setup == "cable":
        rig.runner.bay_cable_inhibited = lambda _r: True
    elif setup == "no_room":
        monkeypatch.setattr(back, "_room", lambda *_a: False)
    else:
        rig.robot._state["safety"] = {"estop": True}
    rig.poll(ri.REISSUE_DELAYS_S[0] + 3)
    assert rig.steps == [] and rig.calls == []
    assert rig.record["waiting_for"] == why


def test_a_core_refusal_ends_the_chain_without_a_reissue(monkeypatch):
    rig = Rig(monkeypatch)

    async def refuse(*_a):
        raise HTTPException(status_code=409, detail={"code": "LOCALIZATION_MISSION_REFUSED"})
    rig.runner.robot_step = refuse
    rig.poll(ri.REISSUE_DELAYS_S[0] + 2)
    rig.poll(60)
    assert rig.calls == [] and rig.record["dropped"] == "back_off_refused"
    assert rig.record["back_off"]["result"] == "LOCALIZATION_MISSION_REFUSED"


@pytest.mark.parametrize("end, dropped", [("aborted", "back_off_aborted"), ("unread", "back_off_unconfirmed"),
                                          ("running", "back_off_unconfirmed")])
def test_a_step_that_did_not_finish_or_could_not_be_read_is_no_reissue(monkeypatch, end, dropped):
    rig = Rig(monkeypatch)
    rig.poll(ri.REISSUE_DELAYS_S[0] + 2)
    assert rig.steps
    rig.status = ({"kind": "nudge_backward", "state": "aborted", "reason": "obstacle"} if end == "aborted"
                  else OSError("link lost") if end == "unread" else rig.status)
    rig.poll(back.BACK_OFF_M / back.STEP_SPEED_MPS + back.STEP_SPARE_S + 2)
    assert rig.calls == [] and rig.record["dropped"] == dropped and rig.record["state"] == "dropped"


def test_a_second_same_spot_failure_backs_off_again_then_gives_up(monkeypatch):
    rig = Rig(monkeypatch, chain={"trip_id": "t0", "root": "t0", "attempt": 1,
                                  "back_offs": 1, "back_off_m": back.BACK_OFF_M})
    assert rig.record["back_off"]["attempt"] == 2
    rig2 = Rig(monkeypatch, chain={"trip_id": "t0", "root": "t0", "attempt": 2,
                                   "back_offs": back.MAX_BACK_OFFS, "back_off_m": back.MAX_TOTAL_M})
    assert rig2.record["state"] == "gave_up" and rig2.record["gave_up"].startswith("한쪽 치우침 복구 실패")
    assert "lat -0.03" in rig2.record["gave_up"] and "벽 여유 0.1" in rig2.record["gave_up"]
    rig2.poll(60)
    assert rig2.steps == [] and rig2.calls == []


def test_an_operator_trip_or_an_estop_while_backing_ends_it(monkeypatch):
    rig = Rig(monkeypatch)
    rig.poll(ri.REISSUE_DELAYS_S[0] + 2)
    rig.runner.close_all("estop")
    rig.poll(3)
    assert rig.record["dropped"] == "stopped_since" and rig.calls == []


def test_the_first_leg_is_slow_until_its_distance():
    detail = {"first_leg": {"until_m": back.FIRST_LEG_M}}
    assert ladder.recovery_slow(detail, 0.4) and not ladder.recovery_slow(detail, back.FIRST_LEG_M + 0.01)
    assert not ladder.recovery_slow(detail)            # no progress known: only the D-1082 rule


def test_room_behind_needs_the_same_edge_or_a_straight_predecessor():
    from fleet.routing.graph import build_graph
    from test_trip_nav2_route import _south_loop_map
    graph = build_graph(_south_loop_map())
    upper_east, upper_west, loop_left = (graph.arcs[a] for a in ("upper_east:fwd", "upper_west:fwd", "loop_left:fwd"))

    class Live:
        def __init__(self, arcs):
            self.arcs = arcs

        def arc(self, i):
            return self.arcs[i]
    x, y, t = upper_west.point_at(0.3)
    assert back._room(Live([upper_west]), 0, x, y, t)
    x, y, t = upper_west.point_at(0.03)
    assert not back._room(Live([upper_west]), 0, x, y, t)                  # no predecessor
    assert back._room(Live([upper_east, upper_west]), 1, x, y, t)             # J_in joins within 10 degrees
    x, y, t = loop_left.point_at(0.03)
    assert not back._room(Live([upper_west, loop_left]), 1, x, y, t)          # the bend into the U-turn
