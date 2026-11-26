"""The Fleet road loop keeps one source warm and releases it on idle."""
import asyncio
from types import SimpleNamespace as NS

from fleet.server.road_vision_demand import RoadVisionDemand, RENEW_S


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
