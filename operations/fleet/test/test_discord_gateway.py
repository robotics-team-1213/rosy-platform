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

    async def close(self, **options):
        self.closed = True
        self.close_code = options.get("code")

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return await self.recv()


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
        assert socket.close_code == 4000
        assert "private-test-bot-token" not in repr(worker)
    asyncio.run(scenario())


def test_session_loss_stops_when_receipt_is_unresolved():
    worker = gateway(None)
    worker.pending = True
    with pytest.raises(GatewayStop):
        worker.forget_session()


@pytest.mark.parametrize("failure", ["journal", "reconnect", "invalid-resumable", "before-hello"])
def test_session_retries_keep_resume_valid(monkeypatch, failure):
    import rosy_discord.gateway as module

    async def scenario():

        async def consume(envelope):
            raise OSError("journal unavailable")
        worker = gateway(consume)
        await worker.dispatch(packet("READY", {"user": {"id": BOT, "bot": True}, "session_id": "s"}, 4))
        event = {"journal": packet("MESSAGE_CREATE", message(), 5),
                 "reconnect": {"op": 7}, "invalid-resumable": {"op": 9, "d": True},
                 "before-hello": {"op": 7, "d": None}}[failure]
        socket = Socket([event] if failure == "before-hello" else
                        [{"op": 10, "d": {"heartbeat_interval": 45000}}, event])

        class Connection:

            async def __aenter__(self):
                return socket

            async def __aexit__(self, *args):
                if not socket.closed:
                    await socket.close(code=1000)
        monkeypatch.setattr(module, "connect", lambda *a, **kw: Connection())
        if failure == "journal":
            with pytest.raises(OSError):
                await worker.session()
        else:
            await worker.session()
        assert socket.close_code == 4000 and worker.sequence == 4
        next_socket = Socket([])
        await worker.authenticate(next_socket)
        assert next_socket.sent[0]["op"] == 6 and next_socket.sent[0]["d"]["seq"] == 4
    asyncio.run(scenario())


@pytest.mark.parametrize("url,allowed", [
    ("wss://gateway-us-east1-b.discord.gg", True),
    ("wss://gateway.discord.gg/", True),
    ("wss://gateway.discord.gg.evil.example", False),
    ("ws://gateway.discord.gg", False), ("wss://user@gateway.discord.gg", False),
    ("wss://gateway.discord.gg:443", False), ("wss://gateway.discord.gg/other", False),
    ("wss://gateway.discord.gg/?token=value", False),
])
def test_ready_resume_endpoint_is_discord_only(url, allowed):

    async def scenario():
        worker = gateway(None)
        event = packet("READY", {"user": {"id": BOT, "bot": True}, "session_id": "s",
                                 "resume_gateway_url": url}, 1)
        if allowed:
            await worker.dispatch(event)
            assert worker.url == url.rstrip("/")
        else:
            with pytest.raises(GatewayStop):
                await worker.dispatch(event)
    asyncio.run(scenario())


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


def test_opt_in_lifespan_receives_and_persists_verified_reply(monkeypatch, tmp_path):
    import ssl
    import certifi
    import httpx
    from fastapi import FastAPI
    from fleet.server import channel_gateway
    from fleet.server.channel_requests import ChannelConfig, ChannelRequests

    sent, stopped = [], []
    client = httpx.AsyncClient
    public_roots = ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True)
    site_ca = tmp_path / "site-ca.pem"
    site_ca.write_text(ssl.DER_cert_to_PEM_cert(public_roots[0]))
    monkeypatch.setenv("SSL_CERT_FILE", str(site_ca))

    def public_client(**options):
        context = options.get("verify")
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert set(context.get_ca_certs(binary_form=True)) == set(public_roots)
        return client(transport=httpx.MockTransport(handle), **options)

    async def handle(request):
        assert request.method == "POST"
        assert str(request.url) == f"https://discord.com/api/v10/channels/{CHANNEL}/messages"
        payload = json.loads(request.content)
        assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
        assert payload["message_reference"]["message_id"] == USER
        assert "inspect" not in payload["content"]
        sent.append(payload)
        return httpx.Response(200, json={
            "id": BOT, "channel_id": CHANNEL, "author": {"id": BOT, "bot": True},
            "message_reference": payload["message_reference"],
        })

    async def run(self):
        try:
            await self.dispatch(packet("READY", {"user": {"id": BOT, "bot": True}, "session_id": "s"}, 1))
            await self.dispatch(packet("MESSAGE_CREATE", message(), 2))
            await self.dispatch(packet("MESSAGE_CREATE", message(), 3))
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    monkeypatch.setattr(DiscordGateway, "run", run)
    monkeypatch.setattr(channel_gateway.httpx, "AsyncClient", public_client)
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, replies_enabled=True,
                           transport_key="transport-key-" * 3, users={USER: "operator"})
    journal = ChannelRequests(tmp_path / "tasks.db", config, {"operator": "operator"})
    app = FastAPI()
    channel_gateway.install_gateway(app, journal, "private-bot-token-" * 4)

    async def scenario():
        before = asyncio.all_tasks()
        async with app.router.lifespan_context(app):
            async def delivered():
                while True:
                    rows = await asyncio.to_thread(journal.reply_outbox.rows, "operator")
                    if rows and rows[0]["state"] == "SENT":
                        assert len(rows) == 1 and rows[0]["provider_id"] == BOT
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(delivered(), timeout=5)
        assert len(sent) == 1 and stopped == [True]
        assert asyncio.all_tasks() == before
        assert journal.reply_outbox.rows("operator")[0]["state"] == "SENT"
    asyncio.run(scenario())


def test_reply_client_startup_failure_leaves_no_gateway_task(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fleet.server import channel_gateway
    from fleet.server.channel_requests import ChannelConfig, ChannelRequests

    class Unavailable:
        def __init__(self, **options):
            pass

        async def __aenter__(self):
            await asyncio.sleep(0)
            raise OSError("HTTP client unavailable")

        async def __aexit__(self, *args):
            pass

    async def wait(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(channel_gateway.httpx, "AsyncClient", Unavailable)
    monkeypatch.setattr(DiscordGateway, "run", wait)
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, replies_enabled=True,
                           transport_key="transport-key-" * 3, users={USER: "operator"})
    journal = ChannelRequests(tmp_path / "tasks.db", config, {"operator": "operator"})
    app = FastAPI()
    channel_gateway.install_gateway(app, journal, "private-bot-token-" * 4)

    async def scenario():
        before = asyncio.all_tasks()
        with pytest.raises(OSError):
            async with app.router.lifespan_context(app):
                raise AssertionError("startup failure admitted lifespan")
        await asyncio.sleep(0)
        leaked = asyncio.all_tasks() - before
        try:
            assert not leaked
        finally:
            for pending in leaked:
                pending.cancel()
            await asyncio.gather(*leaked, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("status,retries", [(503, 2), (401, 1), (403, 1)])
def test_handshake_retry_is_bounded_to_transient_status(monkeypatch, status, retries):
    from websockets.datastructures import Headers
    from websockets.http11 import Response
    from websockets.exceptions import InvalidStatus
    import rosy_discord.gateway as module

    async def scenario():
        attempts = []

        async def session(self):
            attempts.append(True)
            if len(attempts) > 1:
                raise GatewayStop("finished test")
            raise InvalidStatus(Response(status, "private server body", Headers()))

        async def pause(seconds):
            assert 2.5 <= seconds <= 5            # D-432 equal jitter on the 5 s base
        monkeypatch.setattr(DiscordGateway, "session", session)
        monkeypatch.setattr(module.asyncio, "sleep", pause)
        await gateway(None).run()
        assert len(attempts) == retries
    asyncio.run(scenario())


def test_reconnect_backs_off_with_jitter_after_repeated_transport_failures(monkeypatch):
    """Network load: repeated drops back off 5 -> 10 -> 20 s (equal jitter) instead of a fixed 5 s."""
    import rosy_discord.gateway as module

    async def scenario():
        attempts, pauses = [], []

        async def session(self):
            attempts.append(True)
            if len(attempts) > 3:
                raise GatewayStop("finished test")
            raise OSError("connection reset")

        async def pause(seconds):
            pauses.append(seconds)
        monkeypatch.setattr(DiscordGateway, "session", session)
        monkeypatch.setattr(module.asyncio, "sleep", pause)
        await gateway(None).run()
        assert len(pauses) == 3
        for seconds, base in zip(pauses, (5, 10, 20)):
            assert base / 2 <= seconds <= base
    asyncio.run(scenario())
