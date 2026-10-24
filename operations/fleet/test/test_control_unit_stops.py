import asyncio
import sqlite3
import threading

import pytest

from core_common.protocol.integrated_control import ControlStopIngress, ControlStopReconcile, ControlStopSnapshot
from fleet.server.control_stop_store import StopClaim, StopTicket
from fleet.server.control_unit_stops import ControlUnitStops
from test_control_unit_collection import config


def request(**changes):
    return ControlStopIngress.model_validate(dict(
        origin_id="R", stop_id="stop-1", target_unit="R", config_revision="v1",
        expected_controls={u: {"authority_epoch": 1, "generation": 2} for u in ["R", "A", "A1", "B"]},
    ) | changes)


class Store:
    def __init__(self):
        self.started, self.release = threading.Event(), threading.Event()
        self.assignments = None
        self.value = ControlStopSnapshot.model_validate(dict(
            unit_id="R", origin_id="R", stop_id="stop-1", target_unit="R", config_revision="v1", revision=1,
            results=[dict(unit_id="R", state="SENDING", dispatch={"authority_epoch": 1, "generation": 3},
                          acknowledged_robots=0, unknown_robots=0, omx_state="NOT_CONFIGURED",
                          physical_stop="UNVERIFIED")]))

    def claim(self, body, *, scope, assignments, actor_id):
        self.assignments = assignments
        self.started.set()
        assert self.release.wait(5.0), "test did not release the committing thread"
        return StopClaim(self.value, (StopTicket("R", "ticket"),))

    def snapshot(self, *args):
        return self.value

    def finish(self, origin, identity, unit, ticket, result):
        self.value = ControlStopSnapshot(**(self.value.model_dump() | {"revision": 2, "results": [result]}))
        return True


async def no_peer(*args):
    raise AssertionError("local-only fake ticket must not send to a child")


def test_cancelled_http_waiter_preserves_committing_thread_and_owned_execution():
    async def exercise():
        store, calls = Store(), []

        async def stop(control, actor):
            calls.append((control, actor))
            return {"robots": [], "omx_local_stop": {"state": "NOT_CONFIGURED"}}

        service = ControlUnitStops(config(), store, no_peer, stop)
        waiter = asyncio.create_task(service.receive(request(), actor_id="named-human"))
        assert await asyncio.to_thread(store.started.wait, 3.0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert service.is_live("R", "stop-1") and calls == []
        store.release.set()
        await service.aclose()
        assert calls == [({"authority_epoch": 1, "generation": 3}, "named-human")]
        assert store.value.results[0].state == "ACKNOWLEDGED"
        assert store.value.results[0].physical_stop == "UNVERIFIED"
        a = store.assignments["A"]
        assert a.request.target_unit == "A" and set(a.request.expected_controls) == {"A", "A1"}
        assert set(store.assignments["B"].request.expected_controls) == {"B"}

    asyncio.run(exercise())


def test_typed_journal_failure_never_falls_back_to_unconditional_stop():
    async def exercise():
        class Broken(Store):
            def claim(self, *args, **kwargs):
                raise sqlite3.OperationalError("private database detail")

        calls = []

        async def stop(*args):
            calls.append(args)

        service = ControlUnitStops(config(), Broken(), no_peer, stop)
        with pytest.raises(sqlite3.OperationalError):
            await service.receive(request(), actor_id="named-human")
        await service.aclose()
        assert calls == []

    asyncio.run(exercise())


def test_reconciliation_cannot_override_a_live_claim_thread():
    async def exercise():
        store = Store()

        async def stop(*args):
            return {"robots": [], "omx_local_stop": {"state": "NOT_CONFIGURED"}}

        service = ControlUnitStops(config(), store, no_peer, stop)
        waiter = asyncio.create_task(service.receive(request(), actor_id="human"))
        assert await asyncio.to_thread(store.started.wait, 3.0)
        body = ControlStopReconcile(expected_generation=3, receiver_channels_terminated=True,
                                    receivers_recommissioned=True, affected_units=["R"],
                                    evidence="Supervised isolated receiver recommissioning completed")
        with pytest.raises(ValueError, match="STILL_ALIVE"):
            await service.reconcile("R", "stop-1", body, actor_id="human")
        store.release.set()
        await waiter
        await service.aclose()

    asyncio.run(exercise())


def test_empty_child_fence_projection_is_explicitly_not_sent():
    service = ControlUnitStops(config(), Store(), no_peer, None)
    scope, assignments = service._assign(request(expected_controls={"R": {"authority_epoch": 1, "generation": 2}}))
    assert set(scope) == {"R", "A", "A1", "B"}
    assert assignments["A"].request is assignments["B"].request is None
    assert assignments["A"].units == ("A", "A1")


@pytest.mark.parametrize("phase", ["claim", "send"])
def test_cancelled_shutdown_keeps_threads_owned_until_drain_finishes(phase):
    async def exercise():
        store = Store()
        sending, sent = threading.Event(), threading.Event()
        if phase == "send":
            store.release.set()

        async def stop(*args):
            if phase == "send":
                sending.set()
                assert await asyncio.to_thread(sent.wait, 5.0)
            return {"robots": [], "omx_local_stop": {"state": "NOT_CONFIGURED"}}

        service = ControlUnitStops(config(), store, no_peer, stop)
        waiter = asyncio.create_task(service.receive(request(), actor_id="human"))
        started = sending if phase == "send" else store.started
        assert await asyncio.to_thread(started.wait, 3.0)
        close = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        assert not close.done() and service.is_live("R", "stop-1")
        store.release.set()
        sent.set()
        await waiter
        with pytest.raises(asyncio.CancelledError):
            await close
        assert store.value.results[0].state == "ACKNOWLEDGED"

    asyncio.run(exercise())


def test_signal_failure_is_not_reported_as_an_acknowledged_unit():
    service = ControlUnitStops(config(), Store(), no_peer, None, signal_ids=["s1", "s2"])
    value = {"robots": [], "omx_local_stop": {"state": "NOT_CONFIGURED"}, "signals": {
        "all_red": 1, "total": 2, "signals": [
            {"signal_id": "s1", "all_red": True}, {"signal_id": "s2", "all_red": False, "error": "private"}]}}
    result = service._local_result(value, {"authority_epoch": 1, "generation": 3})
    assert result.state == "PARTIAL" and result.physical_stop == "UNVERIFIED"
    assert result.error == "CONTROL_UNIT_SIGNAL_STOP_UNCONFIRMED"
    assert "private" not in result.model_dump_json()


def test_cancelled_reconciliation_waiter_keeps_live_work_gate_until_database_finishes():
    async def exercise():
        entered, release = threading.Event(), threading.Event()

        class Reconciling(Store):
            def reconcile(self, *args, **kwargs):
                entered.set()
                assert release.wait(5.0)
                return self.value

        store = Reconciling()
        store.release.set()

        async def stop(*args):
            return {"robots": [], "omx_local_stop": {"state": "NOT_CONFIGURED"}}

        service = ControlUnitStops(config(), store, no_peer, stop)
        body = ControlStopReconcile(expected_generation=3, receiver_channels_terminated=True,
                                    receivers_recommissioned=True, affected_units=["R"],
                                    evidence="Supervised isolated receiver recommissioning completed")
        waiter = asyncio.create_task(service.reconcile("R", "stop-1", body, actor_id="human"))
        assert await asyncio.to_thread(entered.wait, 3.0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        blocked = asyncio.create_task(service.receive(request(), actor_id="human"))
        await asyncio.sleep(0)
        assert not store.started.is_set()
        release.set()
        await blocked
        await service.aclose()

    asyncio.run(exercise())
