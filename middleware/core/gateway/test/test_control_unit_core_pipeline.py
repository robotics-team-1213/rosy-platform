"""Real Fleet dispatch/CORE receipt chain; sensors, readiness and actuator are synthetic."""

import asyncio
from pathlib import Path
from uuid import UUID

import pytest


@pytest.mark.parametrize("outcome", ["completed", "canceled"])
def test_delegated_task_dispatches_through_core_and_projects_exact_terminal_result(
        core_client, monkeypatch, tmp_path, outcome):
    repo = Path(__file__).resolve().parents[4]
    for path in ["operations/fleet", "operations/fleet/test", "operations/decision/src", "operations/world/src",
                 "operations/site_execution/src", "operations/processes/palletizing/src"]:
        monkeypatch.syspath_prepend(str(repo / path))
    import httpx
    from fakes import FakeRobot
    from core_common.protocol.control_units import ControlWorkRequest
    from fleet.server.app import create_app
    from fleet.server.cancel_all import DriveCancelFence
    from fleet.server.console import FleetConsole
    from fleet.server.channel.execution.outcomes.reconcile import reconcile_tasks
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient
    from test_control_unit_service import cluster, WORK

    core, services = core_client()
    # As in scoped-cancel API tests, the fake backend supplies no live Nav2 readiness.
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)

    class Executor:
        def __init__(self):
            self.goals, self.cancels = [], 0

        def send_goal(self, spec, *, correlation_id=None):
            self.goals.append((spec, correlation_id))

        def cancel_goal(self):
            self.cancels += 1

        def native_transport_snapshot(self):
            return (1, False, False)

    executor = Executor()
    services.nav.executor = executor

    async def exercise():
        nodes, _ = cluster(tmp_path / "units")
        leaf = nodes["A1"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=core.app), base_url="http://core.invalid") as http:
            class SensorFixtureClient(HttpRobotClient):
                async def state(self):
                    return await FakeRobot("a1").state()
            endpoint = RobotEndpoint("a1", "http://core.invalid", "rosy-dev-operator")
            client = SensorFixtureClient(endpoint, http=http)
            console = FleetConsole([endpoint], [client])
            leaf.console = console
            create_app(console, task_service=leaf.tasks, start_task_dispatcher=False)
            await nodes["R"].submit(ControlWorkRequest.model_validate(WORK))
            assert not executor.goals
            await leaf.approve("R", "job-1", actor_id="operator-a1", expected_revision=1)
            task_id = leaf.store.get("R", "job-1")["local_task_id"]
            assert not executor.goals
            control = leaf.tasks.store.dispatch_control()
            leaf.tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator-a1")
            fence = DriveCancelFence()
            task = await leaf.tasks.dispatch_next({"a1"}, dispatch=lambda task: fence.fenced_goal(console, task))
            assert task["status"] == "ACCEPTED", task
            assert len(executor.goals) == 1
            operation = task["receipt"]["operation"]
            assert executor.goals[0][1] == task["attempt_id"] == operation["correlation_id"]
            services.nav.on_goal_accepted(native_run_id=UUID(operation["run_id"]))
            if outcome == "completed":
                services.nav.on_result(True, correlation_id=task["attempt_id"], native_run_id=UUID(operation["run_id"]))
            else:
                await nodes["R"].cancel("R", "job-1")
                assert executor.cancels == 1
                assert leaf.store.get("R", "job-1")["status"] not in {"COMPLETED", "CANCELED"}
            await reconcile_tasks(leaf.tasks, console)
            await nodes["R"].refresh()
            result = nodes["R"].store.get("R", "job-1")["result"]
            assert result["task_id"] == task_id
            assert result["receipt"]["outcome"]["run_id"] == operation["run_id"]
            assert result["receipt"]["outcome"]["result"] == ("SUCCEEDED" if outcome == "completed" else "CANCELED")
            assert result["receipt"]["safe_released"] is True
            assert not leaf.tasks.store.resource_claims(resource_kind="robot", resource_id="a1")
            assert nodes["B"].store.list() == []
    asyncio.run(exercise())
