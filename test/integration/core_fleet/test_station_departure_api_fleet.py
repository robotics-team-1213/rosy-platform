"""Fleet's HTTP transport drives CORE's station departure routes (CORE + Fleet integration)."""
from test_station_docking_api import station_api  # noqa: F401
from test_station_camera_pipeline import pipeline_sources  # noqa: F401


def test_fleet_http_transport_renews_same_reverse_and_reads_lost_finish_receipt(station_api, pipeline_sources):
    import asyncio
    import httpx
    from fleet.swarm.transport import HttpRobotClient
    from fleet.swarm.robots import RobotEndpoint
    from core_common.protocol.station_charging import StationMotionCommand
    from test_station_departure_owner import departure

    async def run():
        core, svc, _, auth, _, _ = station_api
        owner, manager, now, sample, permission = departure()
        owner.principal_id = 'fleet-a'
        svc.station_docking, svc.docking = owner, manager
        token = auth['fleet-a']['Authorization'].split(' ', 1)[1]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url='http://core') as http:
            client = HttpRobotClient(RobotEndpoint(permission.robot_id, 'http://core', token), http=http)
            permission = permission.model_copy(update={'valid_until': now[0]+.8})
            operation = await client.station_undock(permission)
            initial_deadline = permission.valid_until
            assert operation.kind == 'undock'
            for _ in range(100):
                now[0] += .05
                manager.executor.step(.05)
                sample(load_present=False, measured_linear_m_s=-.08)
                permission = permission.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+.8,
                    'expected_owner_generation': manager.native_owner()['owner_generation']})
                assert (await client.station_departure(permission))['accepted'] is True
                owner.tick()
                if owner.state == 'DEPARTURE_CHECK':
                    break
            assert now[0] > initial_deadline and owner.state == 'DEPARTURE_CHECK'
            assert manager.native.current.run_id == operation.run_id
            command = StationMotionCommand(session_id=permission.session_id,
                correlation_id=permission.correlation_id, expected_boot_id=permission.boot_id,
                expected_owner_generation=manager.native_owner()['owner_generation'])
            for _ in range(6):
                now[0] += .1
                sample(load_present=False)
                permission = permission.model_copy(update={'captured_at': now[0], 'valid_until': now[0]+.8,
                    'expected_owner_generation': manager.native_owner()['owner_generation']})
                await client.station_departure(permission)
                owner.tick()
            proof = await client.station_departure_finish(command)
            # Treat the POST response as lost: GET must expose the same fixed receipt.
            assert (await client.station_target()).departure_receipt == proof
            assert proof.operation_id == str(operation.run_id)
            assert manager.native.current.run_id == operation.run_id
    asyncio.run(run())
