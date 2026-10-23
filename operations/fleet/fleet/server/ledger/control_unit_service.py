"""Durable direct-neighbor delegation; only local approval enters Fleet admission."""

from hashlib import sha256

import httpx

from core_common.protocol.control_units import ControlIngressRequest, ControlUnitReply
from fleet.server.control_unit_store import TERMINAL
from fleet.swarm.transport import RobotApiError


class ControlUnitService:
    def __init__(self, topology, store, tasks, console, *, peer):
        self.topology, self.store = topology, store
        self.tasks, self.console, self.peer = tasks, console, peer
        self.unit = topology.unit(store.unit_id)
        robots = {r[6:] for r in self.unit.resources if r.startswith("robot:")}
        if robots != tasks.robot_ids or store.path.resolve() != tasks.store.path.resolve():
            raise ValueError("CONTROL_UNIT_LOCAL_OWNER_MISMATCH")
        active = store.active()
        if any(row["config_revision"] != topology.revision for row in active):
            raise ValueError("CONTROL_UNIT_ACTIVE_CONFIGURATION_CHANGED")
        self._stale = {(row["origin_id"], row["delegation_id"]) for row in active
                       if row["owner_unit"] != self.unit.unit_id}

    def _key(self, row):
        return row["origin_id"], row["delegation_id"]

    def _owner(self, candidate):
        target = self.topology.unit(candidate.target_unit)
        if "robot:" + candidate.robot_id not in target.resources:
            raise ValueError("CONTROL_UNIT_RESOURCE_OUTSIDE_SCOPE")
        return (self.unit.unit_id if target == self.unit
                else self.topology.next_hop(self.unit.unit_id, target.unit_id))

    def _create(self, origin, request):
        owner = self._owner(request)
        body = request.model_dump(mode="json", include={"target_unit", "robot_id", "goal"})
        return self.store.create(origin, request.delegation_id, body, owner_unit=owner,
                                 config_revision=self.topology.revision)

    async def submit(self, request):
        row = self._create(self.unit.unit_id, request)
        await self._sync(row)
        return self.reply(*self._key(row))

    async def receive(self, request, *, parent_id):
        if parent_id != self.unit.parent or parent_id is None:
            raise ValueError("CONTROL_UNIT_NOT_DIRECT_PARENT")
        ancestor = self.topology.unit(parent_id)
        while ancestor.unit_id != request.origin_id and ancestor.parent is not None:
            ancestor = self.topology.unit(ancestor.parent)
        if ancestor.unit_id != request.origin_id:
            raise ValueError("CONTROL_UNIT_ORIGIN_OUTSIDE_SCOPE")
        if request.config_revision != self.topology.revision:
            raise ValueError("CONTROL_UNIT_CONFIGURATION_CHANGED")
        row = self._create(request.origin_id, request)
        await self._sync(row)
        return self.reply(*self._key(row))

    def reply(self, origin, identity):
        return ControlUnitReply(unit_id=self.unit.unit_id, config_revision=self.topology.revision,
                                stale=(origin, identity) in self._stale,
                                delegation=self.store.get(origin, identity)).model_dump(mode="json")

    def _peer_row(self, unit_id, row, response):
        reply = ControlUnitReply.model_validate(response)
        other = reply.delegation.model_dump(mode="json")
        if (reply.unit_id != unit_id or reply.config_revision != row["config_revision"]
                or reply.stale or other["config_revision"] != row["config_revision"]
                or self._key(other) != self._key(row) or other["request"] != row["request"]):
            raise ValueError("CONTROL_UNIT_PEER_RESULT_MISMATCH")
        return other

    async def _parent_current(self, row):
        if row["origin_id"] == self.unit.unit_id:
            return
        if self.unit.parent is None:
            raise ValueError("CONTROL_UNIT_PARENT_REQUIRED")
        response = await self.peer(self.unit.parent, "GET", "/".join(self._key(row)))
        parent = self._peer_row(self.unit.parent, row, response)
        if parent["owner_unit"] != self.unit.unit_id or parent["cancel_requested"] or parent["status"] in TERMINAL:
            raise ValueError("CONTROL_UNIT_PARENT_ADMISSION_REFUSED")

    async def read(self, origin, identity, *, for_child=None):
        row = self.store.get(origin, identity)
        if for_child is not None:
            self.topology.child(self.unit.unit_id, for_child)
            if row["owner_unit"] != for_child:
                raise ValueError("CONTROL_UNIT_CHILD_READ_OUTSIDE_SCOPE")
            await self._parent_current(row)
        return self.reply(origin, identity)

    async def approve(self, origin, identity, *, actor_id, expected_revision):
        row = self.store.get(origin, identity)
        if row["owner_unit"] != self.unit.unit_id:
            raise ValueError("CONTROL_UNIT_LOCAL_APPROVAL_REQUIRED")
        await self._parent_current(row)
        refusal = self.console.trip_refusal([row["request"]["robot_id"]])
        if refusal is not None:
            raise ValueError("CONTROL_UNIT_TRIP_BUSY")
        row = self.store.approve(origin, identity, actor_id=actor_id, expected_revision=expected_revision)
        # The stable key and binding run in the existing Task transaction before dispatch.
        key = sha256((origin + "\0" + identity).encode()).hexdigest()
        await self.tasks.submit_navigation(
            robot_id=row["request"]["robot_id"], **row["request"]["goal"], source="operator",
            actor_id=row["local_actor"], request_key="control:" + key,
            admission=self.store.task_admission(origin, identity, actor_id=row["local_actor"]))
        await self._sync(self.store.get(origin, identity))
        return self.reply(origin, identity)

    async def cancel(self, origin, identity):
        row = self.store.request_cancel(origin, identity)
        await self._sync(row)
        return self.reply(origin, identity)

    def _local_result(self, row, status, result):
        if row["status"] == status and row["result"] == result:
            return row
        return self.store.project(*self._key(row), owner_unit=self.unit.unit_id,
                                  owner_revision=row["owner_revision"] + 1, status=status, result=result)

    async def _local(self, row):
        if not row["local_task_id"]:
            if row["cancel_requested"]:
                self._local_result(row, "CANCELED", {"reason": "CANDIDATE_CANCELED_BEFORE_ADMISSION"})
            return
        task = self.tasks.store.get_task(row["local_task_id"])
        if task is None:
            raise ValueError("CONTROL_UNIT_BOUND_TASK_MISSING")
        if row["cancel_requested"] and task["status"] == "QUEUED":
            try:
                task = self.tasks.cancel_queued_task(task["task_id"], actor_id="control-unit:" + self.unit.unit_id)
                self.console.discard_task_queue_entries({task["task_id"]})
            except ValueError:
                task = self.tasks.store.get_task(task["task_id"])
        result = {key: task[key] for key in ("task_id", "status", "reason", "attempt_id", "receipt")}
        if "cancel_receipt" in row["result"]:
            result["cancel_receipt"] = row["result"]["cancel_receipt"]
        if row["cancel_requested"] and task["status"] not in TERMINAL and "cancel_receipt" not in result:
            operation = (task["receipt"] or {}).get("operation")
            if operation is not None:
                client = self.console._client(task["robot_id"])
                cancel = getattr(client, "navigation_cancel_scoped", None)
                if cancel is not None:
                    result["cancel_receipt"] = await cancel(expected_boot_id=operation["boot_id"],
                                                             run_id=operation["run_id"],
                                                             correlation_id=operation["correlation_id"])
        # A cancellation receipt does not release Task claims or establish physical stop.
        self._local_result(row, task["status"], result)

    async def _sync(self, row):
        if row["status"] in TERMINAL:
            return
        try:
            if row["owner_unit"] == self.unit.unit_id:
                await self._local(row)
            else:
                incoming = ControlIngressRequest(**row["request"], origin_id=row["origin_id"],
                                                  delegation_id=row["delegation_id"],
                                                  config_revision=row["config_revision"])
                response = await self.peer(row["owner_unit"], "POST", "inbox", incoming.model_dump(mode="json"))
                if row["cancel_requested"]:
                    response = await self.peer(row["owner_unit"], "POST", "/".join(self._key(row)), {})
                child = self._peer_row(row["owner_unit"], row, response)
                expected = (self.topology.next_hop(row["owner_unit"], row["request"]["target_unit"])
                            if row["owner_unit"] != row["request"]["target_unit"] else row["owner_unit"])
                if child["owner_unit"] != expected:
                    raise ValueError("CONTROL_UNIT_RESULT_OWNER_CHANGED")
                self.store.project(*self._key(row), owner_unit=row["owner_unit"], owner_revision=child["revision"],
                                   status=child["status"], result=child["result"])
            self._stale.discard(self._key(row))
        except (ConnectionError, OSError, ValueError, KeyError, RobotApiError, httpx.HTTPError):
            self._stale.add(self._key(row))

    async def refresh(self):
        for row in self.store.active():
            await self._sync(row)
