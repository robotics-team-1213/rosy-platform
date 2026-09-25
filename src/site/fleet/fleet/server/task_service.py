"""Validate and dispatch operator or policy navigation through one task path."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

from fleet.hub.hub import HubError
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.transport import RobotApiError


class FleetTaskService:
    POLICY_DISPATCH_ENABLED = False

    def __init__(self, store: FleetTaskStore, *, robot_ids: set[str]) -> None:
        self.store = store
        self.robot_ids = frozenset(robot_ids)
        self.store.recover_interrupted_requests()

    async def submit_navigation(
        self, *, robot_id: str, x: float, y: float, yaw: float = 0.0,
        source: str, actor_id: str, request_key: str,
        dispatch: Callable[[], Awaitable[Mapping]], evidence: Mapping | None = None,
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

        try:
            raw_receipt = await dispatch()
            if not isinstance(raw_receipt, Mapping):
                raise RuntimeError("invalid robot receipt")
            accepted = raw_receipt.get("accepted")
            if accepted is True:
                receipt = {key: raw_receipt[key] for key in ("accepted", "queued")
                           if key in raw_receipt and isinstance(raw_receipt[key], bool)}
                return self.store.transition(task["task_id"], "ACCEPTED", actor_id=actor_id,
                                             source=source, receipt=receipt)
            # An explicit negative acknowledgement proves rejection; never persist raw text.
            if accepted is False:
                return self.store.transition(task["task_id"], "FAILED", actor_id=actor_id,
                                             source=source, reason="COMMAND_REJECTED",
                                             receipt={"accepted": False})
            raise RuntimeError("missing robot acknowledgement")
        except HubError:
            return self.store.transition(task["task_id"], "FAILED", actor_id=actor_id,
                                         source=source, reason="COMMAND_REJECTED")
        except RobotApiError as exc:
            if exc.status < 500:
                return self.store.transition(task["task_id"], "FAILED", actor_id=actor_id,
                                             source=source, reason="COMMAND_REJECTED")
            return self.store.transition(task["task_id"], "UNKNOWN", actor_id=actor_id,
                                         source=source, reason="COMMAND_RESULT_UNKNOWN")
        except Exception:
            # Once dispatch begins, any unclassified result is ambiguous. Do not retry it.
            return self.store.transition(task["task_id"], "UNKNOWN", actor_id=actor_id,
                                         source=source, reason="COMMAND_RESULT_UNKNOWN")
