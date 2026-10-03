"""CORE with a paired Fleet hub configured builds without a loop and starts the agent on the
API loop at startup (D-407 sim 2026-10-02 crash regression)."""


def test_core_with_hub_url_builds_and_starts_the_agent_on_api_startup(core_client):
    fleet = {"hub_url": "ws://127.0.0.1:1/ws", "pairing_token": "pair-token"}
    client, services = core_client(config_overrides={"fleet": fleet})   # build: no loop
    agent = services.fleet_agent
    assert agent.enabled and agent._task is None
    started = []

    async def fake_run(hub_url, pairing_token):
        started.append(hub_url)

    agent._run = fake_run
    with client:                                     # uvicorn-style startup on the app loop
        assert agent._task is not None
    assert started == ["ws://127.0.0.1:1/ws"]
