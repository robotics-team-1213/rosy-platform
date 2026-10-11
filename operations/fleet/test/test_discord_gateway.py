"""Gateway sequencing must not turn a Discord message into device authority."""
import asyncio
import json

import pytest

import fleet  # noqa: F401 - Load the same source holders as the installed Fleet caller.
from rosy_discord.gateway import DiscordGateway, GatewayStop

GUILD, CHANNEL, BOT, USER = [str(100000000000000000 + i) for i in range(4)]


class Socket:
    def __init__(self, events):
        self.events = list(events)
        self.sent = []
        self.closed = False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        return json.dumps(self.events.pop(0))

    async def close(self):
        self.closed = True


def packet(event, data, seq):
    return {"op": 0, "t": event, "d": data, "s": seq}


def message(**updates):
    return {"guild_id": GUILD, "channel_id": CHANNEL, "id": USER,
            "author": {"id": USER}, "content": f"<@{BOT}> inspect", "mentions": [{"id": BOT}], **updates}


def gateway(consume):
    return DiscordGateway(token="private-test-bot-token-" * 3,
                          guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, consume=consume)


def test_ready_identity_and_message_scope_are_checked():
    async def scenario():
        received = []
        async def consume(envelope):
            received.append(envelope)
        worker = gateway(consume)
        await worker.dispatch(packet("READY", {"user": {"id": BOT, "bot": True}, "session_id": "s"}, 1))
        for body in (message(guild_id=None), message(author={"id": USER, "bot": True}), message(mentions=[])):
            await worker.dispatch(packet("MESSAGE_CREATE", body, 2))
        await worker.dispatch(packet("MESSAGE_CREATE", message(), 3))
        assert len(received) == 1 and worker.sequence == 3
        with pytest.raises(GatewayStop):
            await gateway(consume).dispatch(packet("READY", {"user": {"id": USER}, "session_id": "s"}, 1))
    asyncio.run(scenario())


def test_failed_receipt_preserves_resume_sequence():
    async def scenario():
        async def consume(envelope):
            raise OSError("journal temporarily unavailable")
        worker = gateway(consume)
        await worker.dispatch(packet("READY", {"user": {"id": BOT, "bot": True}, "session_id": "s"}, 4))
        with pytest.raises(OSError):
            await worker.dispatch(packet("MESSAGE_CREATE", message(), 5))
        assert worker.sequence == 4 and worker.session_id == "s"
    asyncio.run(scenario())


def test_identify_and_resume_and_missing_heartbeat_ack():
    async def scenario():
        async def consume(envelope):
            pass
        worker = gateway(consume)
        socket = Socket([])
        await worker.authenticate(socket)
        assert socket.sent[0]["op"] == 2 and socket.sent[0]["d"]["intents"] == 513
        worker.session_id, worker.sequence = "session", 7
        await worker.authenticate(socket)
        assert socket.sent[1]["op"] == 6 and socket.sent[1]["d"]["seq"] == 7
        worker.awaiting_ack = True
        assert await worker.heartbeat(socket) is False and socket.closed
        assert "private-test-bot-token" not in repr(worker)
    asyncio.run(scenario())


def test_session_loss_stops_when_receipt_is_unresolved():
    worker = gateway(None)
    worker.pending = True
    with pytest.raises(GatewayStop):
        worker.forget_session()


def test_fleet_lifespan_starts_and_cancels_worker(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fleet.server.channel_gateway import install_gateway
    from fleet.server.channel_requests import ChannelConfig, ChannelRequests
    states = []
    async def run(self):
        states.append("start")
        try:
            await asyncio.Event().wait()
        finally:
            states.append("stop")
    monkeypatch.setattr(DiscordGateway, "run", run)
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key="transport-key-" * 3, users={USER: "operator"})
    journal = ChannelRequests(tmp_path / "tasks.db", config, {"operator": "operator"})
    app = FastAPI()
    install_gateway(app, journal, "private-bot-token-" * 4)
    with TestClient(app):
        assert states == ["start"]
    assert states == ["start", "stop"]
