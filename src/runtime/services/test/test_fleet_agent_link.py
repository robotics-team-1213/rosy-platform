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


# ---- review fixes (2026-10-02) -------------------------------------------------------
class ScriptedHub(FakeHubSocket):
    """Replies to events from a script: code per (seq, attempt); default accepted."""

    def __init__(self, script=None, hello=None):
        super().__init__(reject_events=False)
        self.script = script or {}
        self.hello = hello
        self.attempts = {}

    async def send(self, text):
        env = json.loads(text)
        self.sent.append((env["type"], env["payload"].get("seq")))
        if env["type"] == "hello":
            if self.hello == "refuse":
                await self.inbox.put(_reply(EnvelopeType.ERROR, code="PAIRING_INVALID"))
            elif self.hello != "silent":
                await self.inbox.put(_reply(EnvelopeType.WELCOME, last_event_seq=0))
        elif env["type"] == "heartbeat":
            await self.inbox.put(_reply(EnvelopeType.HEARTBEAT))
        else:
            seq = env["payload"]["seq"]
            n = self.attempts[seq] = self.attempts.get(seq, 0) + 1
            code = self.script.get((seq, n))
            await self.inbox.put(_reply(EnvelopeType.ERROR, code=code) if code
                                 else _reply(EnvelopeType.EVENT, accepted=True))


def _session_for(agent, ws, seconds=1.0):
    async def run():
        session = asyncio.create_task(agent._session(ws, "pair-token"))
        await asyncio.sleep(seconds)
        agent.enabled = False
        ws.closed = True
        return await asyncio.wait_for(session, 3.0)
    return asyncio.run(run())


def _agent_with(events):
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    agent._event_buffer = list(events)
    return agent


def test_a_transient_hub_error_re_sends_the_event(caplog):
    """M3: EVENT_STORAGE_UNAVAILABLE / TASK_PROJECTION_UNAVAILABLE are not a loss."""
    agent = _agent_with([_event(1), _event(2)])
    ws = ScriptedHub({(1, 1): "EVENT_STORAGE_UNAVAILABLE", (2, 1): "TASK_PROJECTION_UNAVAILABLE"})
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        _session_for(agent, ws)
    assert ws.attempts == {1: 2, 2: 2}                          # each re-sent once, then taken
    assert agent._event_buffer == [] and agent._tries == {}
    assert "will re-send" in caplog.text


def test_a_permanent_refusal_drops_the_event_with_its_seq_and_type(caplog):
    agent = _agent_with([_event(7)])
    ws = ScriptedHub({(7, 1): "EVENT_NOT_AUDITABLE"})
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        _session_for(agent, ws)
    assert ws.attempts == {7: 1} and agent._event_buffer == []
    assert "seq 7 (nav.line_stuck_answered)" in caplog.text and "dropped" in caplog.text


def test_transient_retries_are_bounded():
    agent = _agent_with([_event(3)])
    ws = ScriptedHub({(3, n): "EVENT_STORAGE_UNAVAILABLE" for n in range(1, 10)})
    _session_for(agent, ws)
    assert ws.attempts == {3: 3} and agent._event_buffer == []


def test_an_event_cancelled_mid_send_is_kept():
    """M2: cancelling the event loop while ws.send is awaited must not lose the event."""
    agent = _agent_with([_event(5)])
    agent._send_lock = None

    class Stuck(FakeHubSocket):
        async def send(self, text):
            await asyncio.sleep(10)

    async def run():
        agent._send_lock = asyncio.Lock()
        task = asyncio.create_task(agent._event_loop(Stuck(reject_events=False)))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    assert [e.seq for e in agent._event_buffer] == [5]


def test_unanswered_events_go_back_when_the_session_ends():
    agent = _agent_with([_event(1), _event(2)])

    class Mute(ScriptedHub):
        async def send(self, text):
            env = json.loads(text)
            if env["type"] == "hello":
                await self.inbox.put(_reply(EnvelopeType.WELCOME, last_event_seq=0))
            # events and heartbeats get no reply

    _session_for(agent, Mute(), seconds=0.5)
    assert [e.seq for e in agent._event_buffer] == [1, 2]


def test_a_refused_hello_never_reads_as_linked():
    """M1: connected only after WELCOME; a refused HELLO leaves linked_within false."""
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    ws = ScriptedHub(hello="refuse")
    assert asyncio.run(agent._session(ws, "pair-token")) is None
    assert agent.connected is False and agent.linked_within(3.0) is False


def test_a_silent_hello_times_out(monkeypatch):
    """L2: no HELLO reply within HELLO_TIMEOUT_S ends the session (it is retried)."""
    import core_features.fleet_agent.agent as module
    monkeypatch.setattr(module, "HELLO_TIMEOUT_S", 0.2)
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    why = asyncio.run(agent._session(ScriptedHub(hello="silent"), "pair-token"))
    assert why.startswith("no hello reply") and agent.connected is False


def test_backoff_resets_only_after_a_welcome(monkeypatch):
    """L1: a socket that connects but never gets WELCOME keeps backing off."""
    import websockets
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            agent.enabled = False

    class Connect:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return ScriptedHub(hello="silent")

        async def __aexit__(self, *exc):
            return False

    import core_features.fleet_agent.agent as module
    monkeypatch.setattr(module, "HELLO_TIMEOUT_S", 0.01)
    monkeypatch.setattr(websockets, "connect", Connect)
    real_sleep = asyncio.sleep

    async def run():
        monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
        try:
            await agent._run("ws://hub", "pair-token")
        finally:
            monkeypatch.setattr(module.asyncio, "sleep", real_sleep)
    asyncio.run(run())
    assert sleeps == [1.0, 2.0, 4.0]
