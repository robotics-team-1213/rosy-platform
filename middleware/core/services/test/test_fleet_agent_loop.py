"""FleetAgent starts on the loop that runs, not inside CoreServices.build (D-407 sim 2026-10-02).

With fleet.hub_url + pairing_token set, build() ran start() before uvicorn's loop existed and
asyncio.create_task raised "no running event loop", killing CORE.
"""
import asyncio
from types import SimpleNamespace

from core_features.fleet_agent.agent import FleetAgent

CONFIG = {"fleet": {"hub_url": "ws://127.0.0.1:1/ws", "pairing_token": "pair-token"}}


def _agent(config=CONFIG):
    agent = FleetAgent(state_manager=None, event_bus=None, config=config,
                       identity=SimpleNamespace(robot_id="rosy_01"))
    runs = []

    async def fake_run(hub_url, pairing_token):
        runs.append((hub_url, pairing_token))

    agent._run = fake_run
    return agent, runs


def test_start_without_a_running_loop_defers_instead_of_crashing():
    agent, runs = _agent()
    agent.start()                                    # no loop here, like CoreServices.build
    assert agent.enabled and agent._task is None and runs == []

    async def api_startup():
        agent.start_on_loop()
        agent.start_on_loop()                        # idempotent
        await agent._task
    asyncio.run(api_startup())
    assert runs == [("ws://127.0.0.1:1/ws", "pair-token")]


def test_start_inside_a_running_loop_starts_at_once():
    agent, runs = _agent()

    async def inside():
        agent.start()
        await agent._task
    asyncio.run(inside())
    assert len(runs) == 1


def test_disabled_agent_never_creates_a_task():
    agent, runs = _agent({"fleet": {}})
    agent.start()

    async def api_startup():
        agent.start_on_loop()
    asyncio.run(api_startup())
    assert agent._task is None and not agent.enabled
