"""Validate and dispatch operator or policy navigation through one task path."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

from fleet.hub.hub import HubError
from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.transport import RobotApiError


class FleetTaskService:
    POLICY_DISPATCH_ENABLED = False

    def __init__(self, store: FleetTaskStore, *, robot_ids: set[str],
                 worker_id: str | None = None) -> None:
        self.store = store
        self.robot_ids = frozenset(robot_ids)
        self.scheduler = FleetTaskScheduler(store, worker_id=worker_id or f"fleet-{uuid4()}")
        self.scheduler.recover()

    async def submit_navigation(
        self, *, robot_id: str, x: float, y: float, yaw: float = 0.0,
        source: str, actor_id: str, request_key: str,
        evidence: Mapping | None = None,
    ) -> dict:
        if source not in {"operator", "policy"}:
            raise ValueError("INVALID_TASK_SOURCE")
        if not actor_id or len(actor_id) > 96:
            raise ValueError("INVALID_ACTOR_ID")
        if not request_key or len(request_key) > 160:
            raise ValueError("INVALID_IDEMPOTENCY_KEY")
        if robot_id not in self.robot_ids:
            raise ValueError("UNKNOWN_ROBOT")
        coordinates = (x, y, yaw)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in coordinates):
            raise ValueError("INVALID_GOAL")
        if evidence is not None and not isinstance(evidence, Mapping):
            raise ValueError("INVALID_EVIDENCE")

        created = self.store.create_task(
            task_id=str(uuid4()), robot_id=robot_id, task_type="navigate",
            source=source, actor_id=actor_id, request_key=request_key,
            request={"goal": {"x": float(x), "y": float(y), "yaw": float(yaw)}},
            evidence=evidence,
        )
        task = created["task"]
        if not created["created"]:
            return task

        if source == "policy" and not self.POLICY_DISPATCH_ENABLED:
            return self.store.transition(task["task_id"], "HOLD", actor_id=actor_id,
                                         source=source, reason="POLICY_NOT_ACCEPTED")

        priority_class = 0 if source == "operator" else 1
        return self.scheduler.enqueue(
            task["task_id"], priority_class=priority_class, actor_id=actor_id, source=source
        )

    async def dispatch_next(
        self, available_robot_ids: set[str], *,
        dispatch: Callable[[dict], Awaitable[Mapping]],
    ) -> dict | None:
        task = self.scheduler.claim_next(available_robot_ids)
        if task is None:
            return None
        attempt = self.scheduler.begin_dispatch(task["task_id"])

        try:
            raw_receipt = await dispatch(attempt)
            if not isinstance(raw_receipt, Mapping):
                raise RuntimeError("invalid robot receipt")
            accepted = raw_receipt.get("accepted")
            if accepted is True and raw_receipt.get("queued") is not True:
                receipt = {key: raw_receipt[key] for key in ("accepted", "queued")
                           if key in raw_receipt and isinstance(raw_receipt[key], bool)}
                return self.store.transition(task["task_id"], "ACCEPTED", actor_id=task["actor_id"],
                                             source=task["source"], receipt=receipt)
            # The legacy console may report a memory-only traffic queue after sending/canceling.
            # Until task identity is integrated with that queue, preserve ambiguity and do not replay.
            if accepted is True:
                return self.store.transition(
                    task["task_id"], "UNKNOWN", actor_id=task["actor_id"],
                    source=task["source"], reason="TRAFFIC_QUEUE_RESULT_UNRECONCILED",
                )
            # An explicit negative acknowledgement proves rejection; never persist raw text.
            if accepted is False:
                return self.store.transition(task["task_id"], "FAILED", actor_id=task["actor_id"],
                                             source=task["source"], reason="COMMAND_REJECTED",
                                             receipt={"accepted": False})
            raise RuntimeError("missing robot acknowledgement")
        except HubError:
            return self.store.transition(task["task_id"], "FAILED", actor_id=task["actor_id"],
                                         source=task["source"], reason="COMMAND_REJECTED")
        except RobotApiError as exc:
            if exc.status < 500:
                return self.store.transition(task["task_id"], "FAILED", actor_id=task["actor_id"],
                                             source=task["source"], reason="COMMAND_REJECTED")
            return self.store.transition(task["task_id"], "UNKNOWN", actor_id=task["actor_id"],
                                         source=task["source"], reason="COMMAND_RESULT_UNKNOWN")
        except Exception:
            # Once dispatch begins, any unclassified result is ambiguous. Do not retry it.
            return self.store.transition(task["task_id"], "UNKNOWN", actor_id=task["actor_id"],
                                         source=task["source"], reason="COMMAND_RESULT_UNKNOWN")
