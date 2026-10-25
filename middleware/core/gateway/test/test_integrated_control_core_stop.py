"""Typed Fleet stop reaches actual CORE HTTP with a synthetic motion fixture only."""

import asyncio
from pathlib import Path

import pytest


@pytest.mark.parametrize("lose_reply", [False, True])
def test_typed_stop_reaches_core_without_claiming_physical_stop(core_client, monkeypatch, tmp_path, lose_reply):
    repo = Path(__file__).resolve().parents[4]
    for path in ["operations/fleet", "operations/fleet/test", "operations/decision/src", "operations/world/src",
                 "operations/site_execution/src", "operations/processes/palletizing/src"]:
        monkeypatch.syspath_prepend(str(repo / path))
    import httpx
    from core_common.protocol.integrated_control import ControlStopRequest
    from core_features.command.arbitration import Mode
    from fleet.server.console import FleetConsole
    from fleet.server.control_stop_store import ControlStopStore
    from fleet.server.control_unit_config import ControlUnitTopology
    from fleet.server.control_unit_runtime import ControlUnitConfig
    from fleet.server.control_unit_stops import ControlUnitStops
    from fleet.server.task_dispatch_routes import execute_local_fleet_stop
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient

    core, services = core_client(config_overrides={"robot": {"id": "a1", "model": "pinky_pro"}})
    services.modes.transition(Mode.MANUAL)
    assert services.command.teleop(0.1, 0)[0]
    requests = []

    class Network(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            response = await httpx.ASGITransport(app=core.app).handle_async_request(request)
            if request.url.path == "/api/v1/safety/stop":
                requests.append(request.method)
                if lose_reply:
                    await response.aclose()
                    raise httpx.ReadError("synthetic reply loss after CORE latched")
            return response

    async def exercise():
        async with httpx.AsyncClient(transport=Network(), base_url="http://core.invalid") as http:
            endpoint = RobotEndpoint("a1", "http://core.invalid", "rosy-dev-operator")
            console = FleetConsole([endpoint], [HttpRobotClient(endpoint, http=http)])
            tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"a1"})
            topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [
                {"id": "R", "resources": ["robot:a1"]}]})
            config = ControlUnitConfig("R", topology, {})
            journal = ControlStopStore(tasks.store, unit_id="R", config_revision="v1")
            journal.recover()

            async def stop(control, actor):
                return await execute_local_fleet_stop(
                    console=console, task_service=tasks, configured_omx={}, stop_transport=None,
                    stop_control=control, actor_id=actor)

            service = ControlUnitStops(config, journal, None, stop)
            before = tasks.store.dispatch_control()
            body = ControlStopRequest(stop_id="typed-stop", target_unit="R", config_revision="v1",
                expected_controls={"R": {key: before[key] for key in ["authority_epoch", "generation"]}})
            result = await service.submit(body, actor_id="named-human")
            assert requests == ["POST"]
            assert services.safety.estop and services.modes.mode is Mode.EMERGENCY
            row = result.results[0]
            assert row.physical_stop == "UNVERIFIED"
            assert row.state == ("UNKNOWN" if lose_reply else "ACKNOWLEDGED")
            control = tasks.store.dispatch_control()
            assert not control["dispatch_enabled"] and control["generation"] == before["generation"] + 1
            if lose_reply:
                assert control["rearm_available"] is False
                with pytest.raises(InvalidTaskTransition):
                    tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="named-human")
            else:
                tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="named-human")
                assert services.safety.estop  # Fleet rearm never releases CORE's own safety latch.
            replay = await service.submit(body, actor_id="named-human")
            assert replay.revision == result.revision and requests == ["POST"]
            await service.aclose()

    asyncio.run(exercise())
