"""Run the Fleet speed-grant calculation with an actual ring and route profile."""
import asyncio
from types import SimpleNamespace as NS

from fleet.server.trip_road_speed import RoadSpeed
from fleet.site_map import SiteMap


def test_lease_409_after_core_arrived_is_arrival_not_failure():
    from fleet.swarm.api.ports import RobotApiError
    site = SiteMap.model_validate({"schema": "rosy.site_map/1", "map_id": "road",
        "places": [dict(id=n, name=n, x=x, y=y) for n, x, y in [("A", 0, 0), ("B", 1, 0)]],
        "edges": [{"id": "AB", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "direction": "one_way",
                   "width_m": .1, "speed_cap_mps": .15}]})
    pose = NS(x=.1, y=0., map_id="road", state="LOCALIZED", odom_stamp=9.8)
    live = NS(open=True, active_route={"road_speed_owner": "run"}, view={"robot_id": "first", "detail": {}},
              route_rev=0, trim_m=0., segments=[dict(edge_id="AB", forward=True, s_from=0., s_to=1.)],
              progress=lambda idx, s: s)
    state = {"navigation": "ARRIVED", "goal": None, "velocity": {"linear": 0.0, "angular": 0.0},
             "safety": {"estop": False}, "evidence": {"velocity": {"evidence": "fresh", "sampled_at": "1970-01-01T00:00:09.9Z"}}}
    async def update(rid, cid, grant):
        raise RobotApiError(rid, 409, "GOAL_LEASE_NOT_ACTIVE", "not active")
    rules = NS(formation=NS(min_gap_m=.4, max_speed_mps=.15))
    runner = NS(_clock=lambda: 10., _roster=lambda: ["first"], _live={}, _call=lambda coro: coro,
                _robot_state=lambda rid: asyncio.sleep(0, state),
                _store=NS(active=lambda: (1, site), rules=NS(active_rules=lambda: rules)))
    async def check():
        road = RoadSpeed(NS(arbitrated_pose=lambda rid: None), update)
        await road.renew(runner, live, (1, site), 0, .1, pose)
        assert live.view["detail"]["road_speed"]["state"] == "arrived"
        for bad in ({"navigation": "FAILED"}, {"goal": {"x": 1}}, {"safety": {"estop": True}},
                    {"velocity": {"linear": .1, "angular": 0.0}}):
            state.update(bad)
            try:
                await road.renew(runner, live, (1, site), 0, .1, pose)
            except RobotApiError as exc:
                assert exc.code == "GOAL_LEASE_NOT_ACTIVE"
            else:
                raise AssertionError(bad)
            state.update(navigation="ARRIVED", goal=None, safety={"estop": False}, velocity={"linear": 0.0, "angular": 0.0})
    asyncio.run(check())


def test_ring_leader_gap_common_frame_and_expiry_bound_the_grant():
    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "road",
        "places": [dict(id=n, name=n, x=x, y=y) for n,x,y in [
            ("A",0,0),("B",1,0),("C",1,1),("D",0,1)]],
        "edges": [{"id": a+b, "from": a, "to": b, "polyline": [p,q], "direction": "one_way",
                   "width_m": .1, "speed_cap_mps": .15}
                  for a,b,p,q in [("A","B",[0,0],[1,0]), ("B","C",[1,0],[1,1]),
                                  ("C","D",[1,1],[0,1]), ("D","A",[0,1],[0,0])]]})
    pose = NS(x=.1,y=0.,map_id="road",state="LOCALIZED",odom_stamp=9.8)
    peer = NS(x=.35,y=0.,map_id="road",state="LOCALIZED",odom_stamp=9.9)
    live = NS(open=True, active_route={"road_speed_owner":"run"}, view={"robot_id":"first","detail":{}},
              route_rev=0, trim_m=0., segments=[dict(edge_id="AB",forward=True,s_from=0.,s_to=1.)],
              progress=lambda idx,s:s)
    calls = []
    async def update(rid, cid, grant):
        calls.append((rid,cid,grant))
        return {"renewed": True, "correlation_id": cid}
    rules = NS(formation=NS(min_gap_m=.4,max_speed_mps=.15))
    runner = NS(_clock=lambda:10., _roster=lambda:["first","second"], _live={"second":NS(open=True)},
                _call=lambda coro:coro, _store=NS(active=lambda:(1,site),rules=NS(active_rules=lambda:rules)))
    async def check():
        road = RoadSpeed(NS(arbitrated_pose=lambda rid:peer),update)
        async def tick():
            await road.renew(runner,live,(1,site),0,.1,pose)
            assert calls[-1][:2] == ("first","run")
            return calls[-1][2]
        assert (await tick())["limit_mps"] == 0.
        peer.x=.9
        grant=await tick()
        assert grant["limit_mps"] == .15 and grant["expires_at"] == 11.3
        peer.map_id="another"
        assert (await tick())["limit_mps"] == 0.
        assert live.view["detail"]["road_speed"]["reason"] == "peer_pose_stale"
        runner._live["second"].road_pose = NS(x=.95, y=0., source="approved_slam", state="LOCALIZED",
                                                map_id="road", odom_stamp=9.9)
        assert (await tick())["limit_mps"] == .15
        pose.odom_stamp = None
        assert (await tick())["limit_mps"] == 0.
        assert live.view["detail"]["road_speed"]["reason"] == "pose_stale"
    asyncio.run(check())
