"""The Fleet road loop keeps one source warm and releases it on idle."""
import asyncio
from types import SimpleNamespace as NS
import pytest

from fleet.server.road_vision_demand import RoadVisionDemand, RENEW_S


def peer_wait():
    return {"stage":"pre_dispatch_peer_check", "dispatch_attempted":False, "site_route_map":"site",
            "reason":"LOCALIZATION_UNTRUSTED", "command_robot_id":"42", "blocked_by":"45", "waiting_on":["45","46"],
            "peer_evidence":{r:{"reason":"keep_out_intersection"} for r in ("45","46")}, "checked_at":99.}


@pytest.mark.parametrize("problem", ["none", "stale", "missing", "replay", "wrong_site", "calibration",
                                     "future", "manual_hold", "post_dispatch", "claimed", "repeat"])
def test_only_a_new_complete_scoped_peer_observation_can_request_an_early_recheck(problem):
    ids = ["45","46"]
    wait = peer_wait()
    live = NS(open=True, view={"robot_id":"42", "detail":{"peer_wait":wait}})
    rows = [{"robot_id":rid, "source_id":"cam", "map_id":"site", "seq":n, "captured_at":99.9,
             "calibration_source":"approved_record", "calibration_revision":"rev"} for n,rid in enumerate(ids)]
    if problem == "missing": rows.pop()
    if problem == "stale": rows[0]["captured_at"] = 99.5
    if problem == "replay": wait["checked_at"] = 99.91
    if problem == "wrong_site": rows[0]["map_id"] = "neighbor"
    if problem == "calibration": rows[0]["calibration_revision"] = "old"
    if problem == "future": rows[0]["captured_at"] = 100.1
    if problem == "manual_hold": live.view["hold"] = {"reason":"fleet_hold"}
    if problem == "post_dispatch": wait["dispatch_attempted"] = True
    if problem == "claimed": wait["peer_evidence"]["45"]["reason"] = "peer_has_motion_owner"
    if problem == "repeat": wait["observation_retry"] = {"checked_at":99.8}
    service = RoadVisionDemand(None, NS(sources=[NS(source_id="cam", map_id="site", robot_markers=[("45",45),("46",46)])],
        approved_sighting_revision=lambda *_:"rev", snapshot=lambda:{"sightings":rows}))
    observed = service.new_peer_observations(live, "site", 100.)
    assert (observed is not None) == (problem == "none")
    if observed:
        assert set(observed["peers"]) == set(ids)


def test_a_held_trip_requests_the_enrolled_peer_camera_once_for_both_blockers():
    async def scenario():
        sources = [NS(source_id=src, robot_ids=ids, robot_markers=[(r,int(r)) for r in ids], map_id="site")
                   for src, ids in [("mover", ["42"]), ("peers", ["45","46"]), ("other", ["47"])]]
        live = NS(open=True, nav2=True, view={"robot_id":"42", "map_version":5, "detail":{"peer_wait":peer_wait()}})
        runner = NS(_live={"42":live}, _store=NS(active=lambda:(5, NS(map_id="site"))))
        sent = []
        async def hold(src): sent.append(src)
        demand = RoadVisionDemand(NS(hold_stream=hold), NS(sources=sources), clock=lambda:10.)
        demand.period(runner)
        await asyncio.sleep(0)
        demand.period(runner)
        assert sorted(sent) == ["mover","peers"]
    asyncio.run(scenario())


def test_two_active_trips_share_the_source_and_peer_wait_keeps_it_warm():
    async def scenario():
        now = [10.]
        sent = []
        async def hold(source):
            sent.append(source)
        async def close():
            pass
        trips = {rid: NS(open=False, nav2=True, view={"map_version":7}) for rid in ("42","46")}
        runner = NS(_live=trips, _store=NS(active=lambda:(7, NS(map_id="road"))))
        def source(name, robots, map_id="road"):
            return NS(source_id=name, map_id=map_id, robot_ids=robots)
        sources = NS(sources=[source("overhead", trips), source("other_site",trips,"other"),
                              source("workcell", ["arm"])])
        demand = RoadVisionDemand(NS(hold_stream=hold, aclose=close), sources, clock=lambda:now[0])
        async def tick():
            demand.period(runner)
            await asyncio.sleep(0)
        await tick()
        assert not sent
        trips["42"].open = trips["46"].open = True
        await tick()
        await tick()
        assert sent == ["overhead"]
        trips["42"].open = False
        trips["46"].view["hold"] = {"reason":"waiting_for_peer"}
        now[0] += RENEW_S
        await tick()
        assert sent == ["overhead", "overhead"]
        trips["46"].open = False
        now[0] += 100
        await tick()
        assert len(sent) == 2
        await demand.aclose()
    asyncio.run(scenario())

def test_ambiguous_sources_wait_for_scoped_evidence_and_network_errors_back_off():
    async def scenario():
        now = [0.]
        attempts = []
        async def hold(source):
            attempts.append(source)
            if len(attempts) == 1:
                raise TimeoutError()
        async def close():
            pass
        live = NS(open=True, nav2=True, view={"map_version":4})
        runner = NS(_live={"42":live}, _store=NS(active=lambda:(4,NS(map_id="road"))))
        rows = []
        sources = NS(sources=[NS(source_id=name, robot_ids=("42",), map_id="road") for name in ("A","B")],
                     snapshot=lambda:{"sightings":rows})
        service = RoadVisionDemand(NS(hold_stream=hold,aclose=close), sources, clock=lambda:now[0])
        async def tick():
            service.period(runner)
            await asyncio.sleep(0)
        await tick()
        assert not attempts
        rows.append({"robot_id":"42", "map_id":"road", "source_id":"B"})
        await tick()
        for _ in range(3):
            await tick()
        assert attempts == ["B"]
        now[0] += RENEW_S
        await tick()
        assert attempts == ["B","B"]
        live.view["map_version"] = 5
        now[0] += RENEW_S
        await tick()
        assert attempts == ["B","B"]
        await service.aclose()
    asyncio.run(scenario())
