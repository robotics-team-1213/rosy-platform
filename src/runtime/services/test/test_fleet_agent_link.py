"""FleetAgent keeps one reader for every hub reply (D-407 Gazebo re-run 2026-10-02).

The hub answers each heartbeat AND each event (accepted or ERROR). The agent used to read
one reply per heartbeat, so event replies piled up; the websocket client stopped reading,
keepalive pongs went unread and the link dropped mid-stuck (`no_console` after ~10 s).
"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import Envelope, EnvelopeType, EventMessage
from core_features.fleet_agent.agent import FleetAgent

CONFIG = {"fleet": {"hub_url": "ws://127.0.0.1:1/ws", "pairing_token": "pair-token"}}


class State:
    def snapshot(self):
        from core_common.protocol.schemas import StateSnapshot
        return StateSnapshot(robot_id="rosy_01")


class Bus:
    def subscribe(self, cb):
        return lambda: None


IDENTITY = SimpleNamespace(robot_id="rosy_01", device_uid="u", device_name="n", model="m",
                           hardware_serial="s")


def _reply(kind, **payload):
    return Envelope(type=kind, payload=payload).model_dump_json()


class FakeHubSocket:
    """Answers every envelope like hub.handle: WELCOME, HEARTBEAT {}, EVENT accepted or ERROR."""

    def __init__(self, reject_events: bool):
        self.reject_events = reject_events
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent = []
        self.read = 0
        self.closed = False

    async def send(self, text):
        env = json.loads(text)
        self.sent.append(env["type"])
        if env["type"] == "hello":
            await self.inbox.put(_reply(EnvelopeType.WELCOME, last_event_seq=0))
        elif env["type"] == "heartbeat":
            await self.inbox.put(_reply(EnvelopeType.HEARTBEAT))
        elif self.reject_events:
            await self.inbox.put(_reply(EnvelopeType.ERROR, code="EVENT_NOT_AUDITABLE",
                                        message="event is outside the safe audit contract"))
        else:
            await self.inbox.put(_reply(EnvelopeType.EVENT, accepted=True))

    async def recv(self):
        self.read += 1
        return await self.inbox.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed and self.inbox.empty():
            raise StopAsyncIteration
        return await self.recv()


def _event(seq):
    return EventMessage(seq=seq, robot_id="rosy_01", type="nav.line_stuck_answered",
                        source="line_follow_manager", data={"stuck_id": "stuck-1"})


@pytest.mark.parametrize("reject", [False, True])
def test_every_reply_is_drained_and_a_refused_event_keeps_the_link(reject, caplog):
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    agent._event_buffer = [_event(i) for i in range(1, 41)]   # a burst, faster than heartbeats
    ws = FakeHubSocket(reject_events=reject)

    async def run():
        session = asyncio.create_task(agent._session(ws, "pair-token"))
        await asyncio.sleep(1.5)
        assert not session.done(), "an event reply (or ERROR) must not end the session"
        assert ws.inbox.empty(), "every hub reply must be read, or the client stalls"
        agent.enabled = False
        ws.closed = True
        return await asyncio.wait_for(session, 3.0)

    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        why = asyncio.run(run())
    assert ws.sent.count("event") == 40
    assert why is not None
    if reject:
        assert "EVENT_NOT_AUDITABLE" in caplog.text


def test_a_lost_link_is_logged_with_its_reason(monkeypatch, caplog):
    """A reconnect is no longer silent."""
    import websockets

    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True

    class Closing(FakeHubSocket):
        async def __anext__(self):
            raise websockets.exceptions.ConnectionClosedError(None, None)

    calls = []

    class Connect:
        def __init__(self, *a, **k):
            calls.append(1)

        async def __aenter__(self):
            if len(calls) > 1:
                agent.enabled = False                         # stop on the reconnect
                raise OSError("stop")
            return Closing(reject_events=False)

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets, "connect", Connect)
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        asyncio.run(asyncio.wait_for(agent._run("ws://hub", "pair-token"), 5.0))
    assert "Fleet agent link lost (receive loop ended: connection closed" in caplog.text
    assert len(calls) == 2                                     # it did reconnect


def test_linked_within_bridges_a_brief_reconnect():
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    clock = {"t": 100.0}
    agent._clock = lambda: clock["t"]
    assert agent.linked_within(3.0) is False                   # never linked
    agent.connected = True
    assert agent.linked_within(3.0) is True
    agent.connected = False                                    # link dropped at t=100
    clock["t"] = 102.5
    assert agent.linked_within(3.0) is True                    # inside the grace
    clock["t"] = 103.5
    assert agent.linked_within(3.0) is False
    assert agent.linked_within(0.0) is False
