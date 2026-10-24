"""Owned stop-request execution; durable claims precede every local or child send."""

import asyncio
import logging

from core_common.protocol.integrated_control import (
    ControlDispatchFence, ControlStopIngress, ControlStopUnitResult,
)
from fleet.server.control_stop_store import StopAssignment


_LOG = logging.getLogger(__name__)


class ControlUnitStops:
    def __init__(self, config, store, peer, local_stop, *, signal_ids=()):
        self.config, self.store, self.peer, self.local_stop = config, store, peer, local_stop
        self.unit = config.topology.unit(config.unit_id)
        self.signal_ids = frozenset(signal_ids)
        self.jobs = {}
        self.reconciliations = set()
        self.live_work_gate = asyncio.Lock()
        self.closing = False

    def _scope(self, root):
        self.config.topology.unit(root)
        result = {root}
        for unit in self.config.topology.units.values():
            if unit.unit_id == root:
                continue
            try:
                self.config.topology.next_hop(root, unit.unit_id)
            except ValueError:
                continue
            result.add(unit.unit_id)
        return result

    def _assign(self, body):
        if body.config_revision != self.config.topology.revision:
            raise ValueError("CONTROL_UNIT_CONFIGURATION_CHANGED")
        if body.target_unit != self.unit.unit_id:
            self.config.topology.next_hop(self.unit.unit_id, body.target_unit)
        scope = self._scope(body.target_unit)
        if not set(body.expected_controls) <= scope:
            raise ValueError("CONTROL_UNIT_STOP_FENCE_OUTSIDE_SCOPE")
        if body.target_unit == self.unit.unit_id:
            children = sorted(u.unit_id for u in self.config.topology.units.values()
                              if u.parent == self.unit.unit_id)
        else:
            children = [self.config.topology.next_hop(self.unit.unit_id, body.target_unit)]
        assignments = {}
        for child in children:
            target = child if body.target_unit == self.unit.unit_id else body.target_unit
            assigned = self._scope(target)
            fences = {unit: fence for unit, fence in body.expected_controls.items() if unit in assigned}
            request = ControlStopIngress(**(body.model_dump() | {
                "target_unit": target, "expected_controls": fences,
            })) if fences else None
            assignments[child] = StopAssignment(request=request, units=tuple(sorted(assigned)))
        return tuple(sorted(scope)), assignments

    def is_live(self, origin, identity):
        return any(not task.done() for task in tuple(self.jobs.get((origin, identity), ())))

    def _retire(self, key, task):
        jobs = self.jobs.get(key)
        if jobs is not None:
            jobs.discard(task)
            if not jobs:
                self.jobs.pop(key, None)
        if not task.cancelled():
            task.exception()  # A disconnected HTTP waiter must not leave an unobserved exception.

    async def submit(self, body, *, actor_id):
        ingress = ControlStopIngress(**body.model_dump(), origin_id=self.unit.unit_id)
        return await self.receive(ingress, actor_id=actor_id)

    async def receive(self, body, *, actor_id):
        scope, assignments = self._assign(body)
        key = body.origin_id, body.stop_id
        async with self.live_work_gate:
            if self.closing:
                raise ValueError("CONTROL_UNIT_STOP_SERVICE_CLOSING")
            job = asyncio.create_task(self._run(body, scope, assignments, actor_id))
            self.jobs.setdefault(key, set()).add(job)
            job.add_done_callback(lambda task: self._retire(key, task))
        return await asyncio.shield(job)

    async def _run(self, body, scope, assignments, actor_id):
        claim = await asyncio.to_thread(self.store.claim, body, scope=scope,
                                        assignments=assignments, actor_id=actor_id)
        await asyncio.gather(*(self._deliver(body, ticket, assignments, actor_id)
                               for ticket in claim.tickets))
        return await asyncio.to_thread(self.store.snapshot, body.origin_id, body.stop_id)

    async def _deliver(self, body, ticket, assignments, actor_id):
        destination = ticket.delivery_unit
        try:
            if destination == self.unit.unit_id:
                snapshot = await asyncio.to_thread(self.store.snapshot, body.origin_id, body.stop_id)
                local = next(row for row in snapshot.results if row.unit_id == self.unit.unit_id)
                if local.dispatch is None:
                    raise ValueError("CONTROL_UNIT_STOP_TICKET_WITHOUT_FENCE")
                result = await self.local_stop(local.dispatch.model_dump(), actor_id)
                result = self._local_result(result, local.dispatch)
            else:
                request = assignments[destination].request
                if request is None:
                    raise ValueError("CONTROL_UNIT_STOP_WITHOUT_ASSIGNMENT")
                result = await self.peer(destination, "POST", "stop-inbox", request.model_dump(mode="json"))
            await asyncio.to_thread(self.store.finish, body.origin_id, body.stop_id,
                                    destination, ticket.ticket, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.error("Control-unit stop delivery or journal receipt unavailable unit=%s", destination)
            try:
                await asyncio.to_thread(self.store.fail, body.origin_id, body.stop_id,
                                        destination, ticket.ticket)
            except Exception:
                _LOG.error("Control-unit stop uncertainty could not be persisted unit=%s", destination)

    def _local_result(self, value, dispatch):
        robots = {resource[6:] for resource in self.unit.resources if resource.startswith("robot:")}
        rows = value.get("robots", []) if isinstance(value, dict) else []
        acknowledged = {row.get("robot_id") for row in rows if isinstance(row, dict)
                        and row.get("robot_id") in robots and row.get("stopped") is True}
        unknown = len(robots - acknowledged)
        omx = value.get("omx_local_stop", {}).get("state", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN"
        if omx not in {"NOT_CONFIGURED", "REQUESTED", "LOCAL_LATCHED", "UNKNOWN", "PARTIAL"}:
            omx = "UNKNOWN"
        signals = value.get("signals") if isinstance(value, dict) else None
        signal_rows = signals.get("signals", []) if isinstance(signals, dict) else []
        signal_ack = {row.get("signal_id") for row in signal_rows if isinstance(row, dict)
                      and row.get("signal_id") in self.signal_ids and row.get("all_red") is True
                      and not row.get("error")}
        signals_ok = (not self.signal_ids or (
            isinstance(signals, dict) and not signals.get("error") and signal_ack == self.signal_ids))
        certain = unknown == 0 and omx in {"NOT_CONFIGURED", "REQUESTED", "LOCAL_LATCHED"} and signals_ok
        state = "ACKNOWLEDGED" if certain else "PARTIAL" if acknowledged or signal_ack or omx == "LOCAL_LATCHED" else "UNKNOWN"
        return ControlStopUnitResult(
            unit_id=self.unit.unit_id, state=state, dispatch=ControlDispatchFence.model_validate(dispatch),
            acknowledged_robots=len(acknowledged), unknown_robots=unknown, omx_state=omx,
            physical_stop="UNVERIFIED", error=None if certain else (
                "CONTROL_UNIT_SIGNAL_STOP_UNCONFIRMED" if not signals_ok else "CONTROL_UNIT_STOP_UNCONFIRMED"),
        )

    async def read(self, origin, identity):
        assigned = await asyncio.to_thread(self.store.assigned, origin, identity)

        async def observe(child, assignment):
            if assignment["request"] is None:
                return
            try:
                result = await self.peer(child, "GET", "stops/" + origin + "/" + identity)
                await asyncio.to_thread(self.store.observe_child, origin, identity, child, result)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Keep the durable UNKNOWN receipt; readback never replays a stop.

        await asyncio.gather(*(observe(child, assignment)
                               for child, assignment in assigned["assignments"].items()))
        return await asyncio.to_thread(self.store.snapshot, origin, identity)

    async def reconcile(self, origin, identity, body, *, actor_id):
        if body.affected_units != [self.unit.unit_id]:
            raise ValueError("CONTROL_UNIT_LOCAL_RECONCILIATION_ONLY")
        job = asyncio.create_task(self._reconcile(origin, identity, body, actor_id))
        self.reconciliations.add(job)

        def retire(task):
            self.reconciliations.discard(task)
            if not task.cancelled():
                task.exception()

        job.add_done_callback(retire)
        return await asyncio.shield(job)

    async def _reconcile(self, origin, identity, body, actor_id):
        key = origin, identity
        async with self.live_work_gate:
            if self.closing:
                raise ValueError("CONTROL_UNIT_STOP_SERVICE_CLOSING")
            if self.is_live(*key):
                raise ValueError("CONTROL_UNIT_STOP_WORK_STILL_ALIVE")
            return await asyncio.to_thread(
                self.store.reconcile, origin, identity, body,
                actor_id=actor_id, live_work=lambda *_: self.is_live(*key),
            )

    async def aclose(self):
        self.closing = True
        drain = asyncio.gather(*tuple(self.reconciliations),
                               *(task for jobs in tuple(self.jobs.values()) for task in tuple(jobs)),
                               return_exceptions=True)
        cancelled = False
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
