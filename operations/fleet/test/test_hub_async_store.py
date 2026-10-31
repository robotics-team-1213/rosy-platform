"""handle_async: a slow/locked event store never delays heartbeat replies (robot deadline 2 s)."""

import asyncio
import threading

from core_common.protocol.schemas import (
    Envelope, EnvelopeType, EventMessage, HeartbeatPayload, HelloPayload, StateSnapshot,
)
from fleet.hub.hub import SiteHub
from fleet.swarm.robots import RobotEndpoint


def _hub(**kw):
    ep = RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "rest-01", fleet_pairing_token="pair-01")
    return SiteHub([ep], **kw)


def _hello():
    return Envelope(type=EnvelopeType.HELLO, payload=HelloPayload(
        robot_id="rosy_01", pairing_token="pair-01").model_dump())


def _beat():
    snap = StateSnapshot(robot_id="rosy_01")
    return Envelope(type=EnvelopeType.HEARTBEAT, payload=HeartbeatPayload(state_snapshot=snap).model_dump())


def _event(event_id="e1", seq=1, **data):
    ev = EventMessage(event_id=event_id, seq=seq, robot_id="rosy_01", type="nav.completed", data=data)
    return Envelope(type=EnvelopeType.EVENT, payload=ev.model_dump(mode="json"))


class BlockingStore:
    """append_event/read_events block until released, like a SQLite lock wait."""

    def __init__(self):
        self.release = threading.Event()
        self.rows = {}

    def append_event(self, event):
        self.release.wait(10)
        prior = self.rows.get(event["event_id"])
        if prior is not None and prior != event:
            from fleet.server.core_event_store import EventRejected
            raise EventRejected("reused")
        self.rows[event["event_id"]] = event
        return prior is None

    def read_events(self, after_id=0, limit=100):
        self.release.wait(10)
        return []


def test_heartbeat_is_answered_while_event_write_is_blocked():
    async def scenario():
        store = BlockingStore()
        hub = _hub(event_store=store)
        session = hub.open_session()
        await hub.handle_async(_hello(), session=session)
        pending = asyncio.create_task(hub.handle_async(_event(), session=session))
        await asyncio.sleep(0.05)
        reply = await asyncio.wait_for(hub.handle_async(_beat(), session=session), timeout=1)
        assert reply.type is EnvelopeType.HEARTBEAT
        assert not pending.done()
        store.release.set()
        assert (await pending).payload == {"accepted": True}

    asyncio.run(scenario())


def test_heartbeat_does_not_wait_for_projection_recovery():
    async def scenario():
        store = BlockingStore()
        hub = _hub(event_store=store, event_callback=lambda e: None)
        session = hub.open_session()
        await hub.handle_async(_hello(), session=session)
        reply = await asyncio.wait_for(hub.handle_async(_beat(), session=session), timeout=1)
        assert reply.payload["code"] == "TASK_PROJECTION_UNAVAILABLE"
        store.release.set()
        await hub._recovery_task
        reply = await hub.handle_async(_beat(), session=session)
        assert reply.type is EnvelopeType.HEARTBEAT

    asyncio.run(scenario())


def test_async_event_replay_and_reuse_semantics_match_sync():
    async def scenario():
        store = BlockingStore()
        store.release.set()
        hub = _hub(event_store=store)
        session = hub.open_session()
        await hub.handle_async(_hello(), session=session)
        first = await hub.handle_async(_event(), session=session)
        replay = await hub.handle_async(_event(), session=session)
        reused = await hub.handle_async(_event(x=1), session=session)
        assert first.payload == replay.payload == {"accepted": True}
        assert reused.payload["code"] == "EVENT_NOT_AUDITABLE"
        assert len(hub.registry.record("rosy_01").events) == 1

    asyncio.run(scenario())


def test_async_event_storage_failure_is_not_acknowledged():
    class Broken:
        def append_event(self, _e):
            import sqlite3
            raise sqlite3.OperationalError("locked")

    async def scenario():
        hub = _hub(event_store=Broken())
        session = hub.open_session()
        await hub.handle_async(_hello(), session=session)
        reply = await hub.handle_async(_event(), session=session)
        assert reply.payload["code"] == "EVENT_STORAGE_UNAVAILABLE"

    asyncio.run(scenario())


def test_seen_event_hashes_do_not_grow_with_a_durable_store():
    store = BlockingStore()
    store.release.set()
    hub = _hub(event_store=store)
    hub.handle(_hello())
    hub.handle(_event())
    assert hub.registry.record("rosy_01").seen_event_hashes == {}
    assert len(hub.registry.record("rosy_01").events) == 1


def test_projection_callback_runs_on_the_loop_thread():
    class Store(BlockingStore):
        def append_event(self, event):
            self.append_thread = threading.get_ident()
            return super().append_event(event)

        def read_events(self, after_id=0, limit=100):
            rows = [{"audit_id": i + 1, "event": e} for i, e in enumerate(self.rows.values())]
            return [r for r in rows if r["audit_id"] > after_id][:limit]

    async def scenario():
        store = Store()
        store.release.set()
        seen = []
        hub = _hub(event_store=store, event_callback=lambda e: seen.append(threading.get_ident()))
        session = hub.open_session()
        await hub.handle_async(_hello(), session=session)
        await hub.handle_async(_beat(), session=session)  # kicks startup recovery
        await hub._recovery_task if hub._recovery_task else None
        reply = await hub.handle_async(_event(), session=session)
        assert reply.payload == {"accepted": True}
        assert store.append_thread != threading.get_ident()
        assert seen and set(seen) == {threading.get_ident()}

    asyncio.run(scenario())
