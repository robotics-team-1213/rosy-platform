"""FleetAgent link truth for SAF-003 (D-419 reviews, rounds 1-4), and one reader for
every hub reply with bounded event re-sends (D-407 Gazebo re-run 2026-10-02, below).

`connected` is True only after the hub's WELCOME; one reader task receives every hub
message and refreshes `last_rx`; the reply that answers a heartbeat (HEARTBEAT, or a
non-fatal ERROR from a degraded but alive hub) satisfies its deadline; a pairing ERROR
ends the session; a missed deadline aborts the socket; the reconnect backoff resets only
after a session survives STABLE_HEARTBEATS answered heartbeats. Fake websockets only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from types import SimpleNamespace

import pytest

import core_features.fleet_agent.agent as agent_mod
from core_common.protocol.schemas import Envelope, EnvelopeType, EventMessage
from core_features.fleet_agent.agent import FleetAgent, heartbeat_reply_timeout_s
from core_features.state.manager import StateManager
from fleet_hub_fake import FakeHub, envelope

CONFIG = {"fleet": {"hub_url": "ws://hub.invalid/", "pairing_token": "pair-token"}}


class Bus:
    def subscribe(self, _cb):
        return lambda: None


def _agent(**fleet) -> FleetAgent:
    config = {"fleet": {**CONFIG["fleet"], **fleet}}
    agent = FleetAgent(StateManager(robot_id="rosy_01"), Bus(), config,
                       SimpleNamespace(robot_id="rosy_01"))
    agent.enabled = True
    return agent


def _event(i: int):
    return SimpleNamespace(model_dump=lambda mode="json", i=i: {"type": "x.y", "seq": i}, seq=i)


@pytest.fixture
def fast(monkeypatch):
    """Heartbeat period 50 ms so a test covers many heartbeats in well under a second."""
    monkeypatch.setattr(agent_mod, "HEARTBEAT_PERIOD_S", 0.05)


def _record_backoff(monkeypatch, agent, sleeps, stop_after=4):
    real_sleep = asyncio.sleep

    async def record_sleep(seconds):
        if seconds >= 1.0:                   # the reconnect backoff, not the heartbeat
            sleeps.append(seconds)
            if len(sleeps) >= stop_after:
                agent.enabled = False
            return
        await real_sleep(seconds)
    monkeypatch.setattr(agent_mod.asyncio, "sleep", record_sleep)


def test_reply_timeout_config_is_validated():
    assert heartbeat_reply_timeout_s({}) == 2.0
    assert heartbeat_reply_timeout_s({"heartbeat_reply_timeout_s": 3}) == 3.0
    for bad in (0, 0.4, 11, math.nan, "2", True):
        with pytest.raises(ValueError):
            heartbeat_reply_timeout_s({"heartbeat_reply_timeout_s": bad})
    agent = _agent(heartbeat_reply_timeout_s=3.0)
    assert agent.reply_timeout_s == 3.0
    assert agent.link_fresh_s == pytest.approx(1.0 + 3.0 + 0.5)


def test_bad_reply_timeout_fails_only_with_a_fleet_link(caplog):
    """Round 3 MEDIUM 1: a robot without Fleet boots on a bad Fleet setting (one warning)."""
    with pytest.raises(ValueError):
        _agent(heartbeat_reply_timeout_s=0.1)
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        agent = FleetAgent(StateManager(robot_id="rosy_01"), Bus(),
                           {"fleet": {"heartbeat_reply_timeout_s": 0.1}},
                           SimpleNamespace(robot_id="rosy_01"))
    assert agent.reply_timeout_s == 2.0
    assert any("heartbeat_reply_timeout_s" in r.getMessage() for r in caplog.records)


def test_connected_only_after_welcome_and_every_message_moves_last_rx(fast):
    agent = _agent()
    agent.reply_timeout_s = 0.5
    hub = FakeHub()

    async def run():
        task = asyncio.create_task(agent._serve(hub))
        await asyncio.sleep(0.3)
        seen = (agent.connected, agent.last_rx, hub.answered)
        agent.enabled = False
        hub._abort()
        await task
        return seen
    connected, last_rx, answered = asyncio.run(run())
    assert connected is True and last_rx is not None and answered >= 3
    assert agent.connected is False


def test_open_socket_that_never_gets_welcome_stays_disconnected(monkeypatch):
    """Sockets open, the hub answers something other than WELCOME: never connected, and
    `last_rx` is not stamped by a reply that failed the WELCOME check."""
    import websockets
    agent = _agent()
    observed = []
    sockets = [FakeHub(welcome=False) for _ in range(3)]
    monkeypatch.setattr(websockets, "connect", lambda _url, **_o: sockets.pop(0))

    async def fake_sleep(_s):
        observed.append(agent.connected)
        if len(observed) >= 3:
            agent.enabled = False
    monkeypatch.setattr(agent_mod.asyncio, "sleep", fake_sleep)
    asyncio.run(agent._run("ws://hub.invalid/", "pair-token"))
    assert observed and not any(observed)
    assert agent.last_rx is None


def test_half_open_link_is_aborted_at_the_reply_deadline_despite_event_acks(fast):
    """The hub keeps acking EVENTs but stopped answering heartbeats. Acks must not satisfy
    the heartbeat deadline; the socket is aborted."""
    agent = _agent()
    agent.reply_timeout_s = 0.2
    hub = FakeHub(answered_limit=2)

    async def run():
        task = asyncio.create_task(agent._serve(hub))
        for i in range(20):                  # interleaved EVENT traffic all along
            agent._event_buffer.append(_event(i))
            await asyncio.sleep(0.03)
            if task.done():
                break
        return await asyncio.wait_for(task, timeout=2.0)
    stable = asyncio.run(run())
    events_sent = sum(1 for m in hub.sent
                      if Envelope.model_validate_json(m).type is EnvelopeType.EVENT)
    assert events_sent > 0                   # each one drew an ACK the reader drained
    assert hub.aborted is True
    assert agent.connected is False
    assert stable is False                   # only 2 answered heartbeats


def test_degraded_hub_error_keeps_the_link(fast, caplog):
    """Round 3 HIGH: a live hub with one poisoned event row answers every heartbeat with
    ERROR TASK_PROJECTION_UNAVAILABLE. That is an answer: no abort, still connected, the
    session counts as stable, and the warning is rate-limited."""
    agent = _agent()
    agent.reply_timeout_s = 0.4              # generous: Windows timer granularity ~16 ms
    hub = FakeHub(heartbeat_error="TASK_PROJECTION_UNAVAILABLE", delay=0.02)

    async def run():
        task = asyncio.create_task(agent._serve(hub))
        await asyncio.sleep(0.8)
        seen = agent.connected
        agent.enabled = False
        hub._abort()
        stable = await task
        return seen, stable
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        connected, stable = asyncio.run(run())
    assert connected is True and hub.answered >= 5
    assert stable is True                    # >= STABLE_HEARTBEATS answers
    degraded = [r for r in caplog.records if "TASK_PROJECTION_UNAVAILABLE" in r.getMessage()]
    assert len(degraded) == 1


def test_degraded_hub_resets_the_backoff(monkeypatch):
    import websockets
    monkeypatch.setattr(agent_mod, "HEARTBEAT_PERIOD_S", 0.01)
    agent = _agent()
    agent.reply_timeout_s = 0.2
    hubs = [FakeHub(delay=1.0), FakeHub(delay=1.0),
            FakeHub(heartbeat_error="TASK_PROJECTION_UNAVAILABLE", answered_limit=3),
            FakeHub(delay=1.0)]
    monkeypatch.setattr(websockets, "connect", lambda _url, **_o: hubs.pop(0))
    sleeps = []
    _record_backoff(monkeypatch, agent, sleeps)
    asyncio.run(asyncio.wait_for(agent._run("ws://hub.invalid/", "pair-token"), timeout=5.0))
    assert sleeps == [1.0, 2.0, 1.0, 2.0]


@pytest.mark.parametrize("code", ["SESSION_NOT_PAIRED", "PAIRING_INVALID"])
def test_pairing_error_ends_the_session_at_once(fast, code):
    agent = _agent()
    agent.reply_timeout_s = 5.0              # the deadline is not what ends it
    hub = FakeHub(heartbeat_error=code)

    async def run():
        start = asyncio.get_running_loop().time()
        await asyncio.wait_for(agent._serve(hub), timeout=2.0)
        return asyncio.get_running_loop().time() - start
    elapsed = asyncio.run(run())
    assert hub.aborted is True and agent.connected is False
    assert elapsed < 0.5


def test_slow_hub_does_not_reset_the_backoff(monkeypatch):
    """A hub that welcomes and then answers too late: every session ends at the deadline,
    and the backoff keeps doubling instead of churning at 1 s."""
    import websockets
    monkeypatch.setattr(agent_mod, "HEARTBEAT_PERIOD_S", 0.01)
    agent = _agent()
    agent.reply_timeout_s = 0.05
    hubs = [FakeHub(delay=0.2) for _ in range(5)]
    monkeypatch.setattr(websockets, "connect", lambda _url, **_o: hubs.pop(0))
    sleeps = []
    _record_backoff(monkeypatch, agent, sleeps)
    asyncio.run(asyncio.wait_for(agent._run("ws://hub.invalid/", "pair-token"), timeout=5.0))
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


def test_stable_session_resets_the_backoff(monkeypatch):
    import websockets
    monkeypatch.setattr(agent_mod, "HEARTBEAT_PERIOD_S", 0.01)
    agent = _agent()
    agent.reply_timeout_s = 0.2
    # first two sessions die young, the third survives 3 answered heartbeats then dies
    hubs = [FakeHub(delay=1.0), FakeHub(delay=1.0), FakeHub(answered_limit=3), FakeHub(delay=1.0)]
    monkeypatch.setattr(websockets, "connect", lambda _url, **_o: hubs.pop(0))
    sleeps = []
    _record_backoff(monkeypatch, agent, sleeps)
    asyncio.run(asyncio.wait_for(agent._run("ws://hub.invalid/", "pair-token"), timeout=5.0))
    assert sleeps == [1.0, 2.0, 1.0, 2.0]


def test_event_is_kept_when_the_transport_fails():
    agent = _agent()
    agent._event_buffer.append(_event(1))

    class Gone:
        async def send(self, _text):
            raise OSError("connection reset")

    asyncio.run(asyncio.wait_for(agent._event_loop(Gone()), timeout=1.0))
    assert [e.seq for e in agent._event_buffer] == [1]


class _Unencodable:
    """An event whose data the bus never checked: not JSON-serialisable."""
    seq = 99

    def model_dump(self, mode="json"):
        return {"type": "x.bad", "seq": 99, "data": {"value": object()}}


def test_unencodable_event_is_dropped_and_the_session_survives(fast, caplog):
    """Round 4 HIGH: kept at the head, a bad event killed every session forever."""
    agent = _agent()
    agent.reply_timeout_s = 0.5
    agent._event_buffer.extend([_Unencodable(), _event(1), _event(2)])
    hub = FakeHub()

    async def run():
        serve = asyncio.create_task(agent._serve(hub))
        await asyncio.sleep(0.5)
        seen = agent.connected, serve.done()
        agent.enabled = False
        hub._abort()
        await serve
        return seen
    with caplog.at_level(logging.ERROR, logger="fleet_agent"):
        connected, ended = asyncio.run(run())
    assert connected is True and ended is False
    assert [p["seq"] for p in hub.events_sent()] == [1, 2]
    assert agent._event_buffer == []
    assert any("seq 99" in r.getMessage() and "cannot encode" in r.getMessage()
               for r in caplog.records)


def test_non_transport_send_error_drops_that_event_and_goes_on():
    agent = _agent()
    agent._event_buffer.extend([_event(1), _event(2)])
    delivered = []

    class Flaky:
        async def send(self, text):
            payload = Envelope.model_validate_json(text).payload
            if payload["seq"] == 1:
                raise RuntimeError("encoder exploded")
            delivered.append(payload["seq"])
            agent.enabled = False            # stop after the second event

    asyncio.run(asyncio.wait_for(agent._event_loop(Flaky()), timeout=1.0))
    assert delivered == [2] and agent._event_buffer == []
    # The failed send took back its entry: only the delivered EVENT awaits a reply.
    assert [(kind, ev.seq) for kind, ev in agent._awaiting] == [(EnvelopeType.EVENT, 2)]


def test_error_answering_an_event_does_not_wake_the_heartbeat():
    """Round 4 MEDIUM: an ERROR that the FIFO attributes to an EVENT is an event
    rejection — it must not satisfy a heartbeat deadline."""
    agent = _agent()

    class OneError:
        def __init__(self):
            self.replies = [envelope(EnvelopeType.ERROR, {"code": "EVENT_NOT_AUDITABLE"})]

        async def recv(self):
            if self.replies:
                return self.replies.pop(0)
            raise OSError("closed")

    async def run():
        agent._hb_reply = asyncio.Event()
        agent._awaiting.extend([(EnvelopeType.EVENT, None), (EnvelopeType.HEARTBEAT, None)])
        await agent._reader_loop(OneError())
        return agent._hb_reply.is_set(), list(agent._awaiting)
    woken, left = asyncio.run(run())
    assert woken is False and left == [(EnvelopeType.HEARTBEAT, None)]


@pytest.mark.parametrize("code", ["SESSION_NOT_PAIRED", "EVENT_NOT_AUDITABLE"])
def test_error_answering_an_event_keeps_the_session(fast, caplog, code):
    """hub.py answers an EVENT it cannot validate with SESSION_NOT_PAIRED; that is an event
    rejection, not a pairing failure: the session goes on, heartbeats stay answered, and
    the rejection is logged per event, apart from the rate-limited heartbeat ERROR log."""
    agent = _agent()
    agent.reply_timeout_s = 0.4
    hub = FakeHub(event_error=code, heartbeat_error="TASK_PROJECTION_UNAVAILABLE")

    async def run():
        serve = asyncio.create_task(agent._serve(hub))
        for i in range(5):
            agent._event_buffer.append(_event(i))
            await asyncio.sleep(0.06)
        seen = agent.connected, serve.done()
        agent.enabled = False
        hub._abort()
        stable = await serve
        return seen, stable
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        (connected, ended), stable = asyncio.run(run())
    assert connected is True and ended is False and stable is True
    messages = [r.getMessage() for r in caplog.records]
    assert any("event seq" in m and code in m for m in messages)
    assert not any("degraded" in m and code in m for m in messages)
    assert sum("degraded" in m and "TASK_PROJECTION_UNAVAILABLE" in m for m in messages) == 1


def test_recently_heard_debounces_on_last_rx():
    agent = _agent()
    assert agent.recently_heard(now=100.0) is False
    agent.last_rx = 100.0
    assert agent.recently_heard(now=100.0 + agent.link_fresh_s - 0.01) is True
    assert agent.recently_heard(now=100.0 + agent.link_fresh_s + 0.01) is False


def test_envelope_helper_round_trips():
    assert Envelope.model_validate_json(envelope(EnvelopeType.ACK)).type is EnvelopeType.ACK


# ---- D-407: one reader drains every hub reply (Gazebo re-run 2026-10-02) ---------------
# The hub answers each heartbeat AND each event (accepted or ERROR). The agent used to read
# one reply per heartbeat, so event replies piled up; the websocket client stopped reading,
# keepalive pongs went unread and the link dropped mid-stuck (`no_console` after ~10 s).
class State:
    def snapshot(self):
        from core_common.protocol.schemas import StateSnapshot
        return StateSnapshot(robot_id="rosy_01")


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


def _bus_event(seq):
    return EventMessage(seq=seq, robot_id="rosy_01", type="nav.line_stuck_answered",
                        source="line_follow_manager", data={"stuck_id": "stuck-1"})


@pytest.mark.parametrize("reject", [False, True])
def test_every_reply_is_drained_and_a_refused_event_keeps_the_link(reject, caplog):
    agent = FleetAgent(State(), Bus(), CONFIG, IDENTITY)
    agent.enabled = True
    agent._event_buffer = [_bus_event(i) for i in range(1, 41)]   # a burst, faster than heartbeats
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
        async def recv(self):
            if self.read:                     # WELCOME first, then the socket drops
                raise websockets.exceptions.ConnectionClosedError(None, None)
            return await super().recv()

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
    agent = _agent_with([_bus_event(1), _bus_event(2)])
    ws = ScriptedHub({(1, 1): "EVENT_STORAGE_UNAVAILABLE", (2, 1): "TASK_PROJECTION_UNAVAILABLE"})
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        _session_for(agent, ws)
    assert ws.attempts == {1: 2, 2: 2}                          # each re-sent once, then taken
    assert agent._event_buffer == [] and agent._tries == {}
    assert "will re-send" in caplog.text


def test_a_permanent_refusal_drops_the_event_with_its_seq_and_type(caplog):
    agent = _agent_with([_bus_event(7)])
    ws = ScriptedHub({(7, 1): "EVENT_NOT_AUDITABLE"})
    with caplog.at_level(logging.WARNING, logger="fleet_agent"):
        _session_for(agent, ws)
    assert ws.attempts == {7: 1} and agent._event_buffer == []
    assert "seq 7 (nav.line_stuck_answered)" in caplog.text and "dropped" in caplog.text


def test_transient_retries_are_bounded():
    agent = _agent_with([_bus_event(3)])
    ws = ScriptedHub({(3, n): "EVENT_STORAGE_UNAVAILABLE" for n in range(1, 10)})
    _session_for(agent, ws)
    assert ws.attempts == {3: 3} and agent._event_buffer == []


def test_an_event_cancelled_mid_send_is_kept():
    """M2: cancelling the event loop while ws.send is awaited must not lose the event."""
    agent = _agent_with([_bus_event(5)])
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
    agent = _agent_with([_bus_event(1), _bus_event(2)])

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
