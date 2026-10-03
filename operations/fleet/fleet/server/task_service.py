"""Validate and dispatch operator or policy navigation through one task path."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

from fleet.hub.hub import HubError
from fleet.server.cancel_all import DispatchCanceled, DispatchWithdrawn
from fleet.server.cancel_all_store import CANCEL_ALL_REASON
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.task_scheduler import FleetTaskScheduler
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.transport import RobotApiError


_LOG = logging.getLogger(__name__)


class FleetTaskService:
    POLICY_DISPATCH_ENABLED = False

    def __init__(self, store: FleetTaskStore, *, robot_ids: set[str],
                 worker_id: str | None = None,
                 policy_evidence: PolicyEvidenceStore | None = None,
                 max_evidence_age_s: float | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.robot_ids = frozenset(robot_ids)
        self.scheduler = FleetTaskScheduler(store, worker_id=worker_id or f"fleet-{uuid4()}")
        self.store.close_dispatch_for_startup()
        self.scheduler.recover()
        self._policy_evidence = policy_evidence
        self._max_evidence_age_s = max_evidence_age_s
        self._clock = clock

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
        policy_evidence_id: str | None = None
        if source == "policy":
            if (not isinstance(evidence, Mapping) or set(evidence) != {"evidence_id"}
                    or not isinstance(evidence.get("evidence_id"), str)
                    or not evidence["evidence_id"].strip()):
                raise ValueError("INVALID_EVIDENCE_REFERENCE")
            policy_evidence_id = evidence["evidence_id"]

        created = self.store.create_task(
            task_id=str(uuid4()), robot_id=robot_id, task_type="navigate",
            source=source, actor_id=actor_id, request_key=request_key,
            request={"goal": {"x": float(x), "y": float(y), "yaw": float(yaw)}},
            evidence=evidence,
        )
        task = created["task"]
        if not created["created"]:
            return self.store.get_task(task["task_id"]) or task

        if source == "policy":
            admission = self._policy_admission_reason(policy_evidence_id, robot_id=robot_id)
            if admission is not None or not self.POLICY_DISPATCH_ENABLED:
                return self.store.transition(task["task_id"], "HOLD", actor_id=actor_id,
                                             source=source,
                                             reason=admission or "POLICY_NOT_ACCEPTED")

        priority_class = 0 if source == "operator" else 1
        queued = self.scheduler.enqueue(
            task["task_id"], priority_class=priority_class, actor_id=actor_id, source=source
        )
        return self.store.get_task(task["task_id"]) or queued

    def _policy_admission_reason(self, evidence_id: str, *, robot_id: str) -> str | None:
        """Binding check for policy submissions; None means admissible."""
        if self._policy_evidence is None:
            return "EVIDENCE_NOT_CONFIGURED"
        record = self._policy_evidence.get(evidence_id)
        if record is None:
            return "EVIDENCE_NOT_FOUND"
        if record["outcome"] != "accepted":
            return record["reason"] or "EVIDENCE_OBSERVATION_KIND_UNKNOWN"
        payload = record["payload"]
        if payload.get("asset_kind") != "robot" or payload.get("asset_id") != robot_id:
            return "EVIDENCE_ASSET_MISMATCH"
        if payload.get("task_kind") != "navigate":
            return "EVIDENCE_TASK_KIND_NOT_REGISTERED"
        if self._max_evidence_age_s is None:
            return "EVIDENCE_STALE"
        age = self._clock() - float(record["received_at"])
        if age < 0 or age > self._max_evidence_age_s:
            return "EVIDENCE_STALE"
        return None

    async def dispatch_next(
        self, available_robot_ids: set[str], *,
        dispatch: Callable[[dict], Awaitable[Mapping]],
    ) -> dict | None:
        result = await self._dispatch_next(available_robot_ids, dispatch=dispatch)
        if (result is not None and result.get("status") == "HOLD"
                and result.get("reason") == CANCEL_ALL_REASON):
            # D-421: CORE confirmed a cancel-all before this receipt; the late receipt is
            # not applied (transition() keeps HOLD). Say so instead of dropping it silently.
            _LOG.warning("late dispatch result for task %s after HOLD(FLEET_CANCEL_ALL) ignored",
                         result.get("task_id"))
        return result

    async def _dispatch_next(
        self, available_robot_ids: set[str], *,
        dispatch: Callable[[dict], Awaitable[Mapping]],
    ) -> dict | None:
        task = self.scheduler.claim_next(available_robot_ids)
        if task is None:
            return None
        attempt = self.scheduler.begin_dispatch(task["task_id"])

        try:
            if not self.store.dispatch_generation_is_current(attempt["dispatch_generation"]):
                return self.store.abort_dispatch_before_send(
                    task["task_id"], attempt_id=attempt["attempt_id"],
                )
            raw_receipt = await dispatch(attempt)
            if not isinstance(raw_receipt, Mapping):
                raise RuntimeError("invalid robot receipt")
            accepted = raw_receipt.get("accepted")
            if raw_receipt.get("queued") is True:
                dispatch_attempted = raw_receipt.get("dispatch_attempted") is True
                cancel_confirmed = raw_receipt.get("cancel_confirmed") is True
                if dispatch_attempted and not cancel_confirmed:
                    return self.store.transition(
                        task["task_id"], "UNKNOWN", actor_id=task["actor_id"],
                        source=task["source"], reason="TRAFFIC_CANCEL_UNCONFIRMED",
                    )
                reason = raw_receipt.get("reason")
                allowed_reasons = {"YIELDED", "ROUTE_CONFLICT", "YIELDING", "NO_YIELD_SPACE"}
                if reason not in allowed_reasons:
                    reason = "TRAFFIC_WAIT"
                blocked_by = raw_receipt.get("blocked_by")
                if blocked_by not in self.robot_ids:
                    blocked_by = None
                waiting_on = [robot_id for robot_id in raw_receipt.get("waiting_on", [])
                              if robot_id in self.robot_ids][:32]
                return self.store.wait_for_traffic(
                    task["task_id"], worker_id=self.scheduler.worker_id,
                    reason=reason, blocked_by=blocked_by, waiting_on=waiting_on,
                    dispatch_attempted=dispatch_attempted,
                    cancel_confirmed=cancel_confirmed,
                )
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
        except DispatchCanceled as exc:
            # D-421: the goal may have reached CORE during a cancel-all; Fleet sent
            # navigation/cancel again. Only CORE's correlated event may settle it.
            return self.store.transition(task["task_id"], "UNKNOWN", actor_id=task["actor_id"],
                                         source=task["source"], reason=exc.reason)
        except DispatchWithdrawn as exc:
            # D-421: still in Fleet's own traffic queue with no live CORE goal.
            return self.store.transition(task["task_id"], "CANCELED", actor_id=task["actor_id"],
                                         source=task["source"], reason=exc.reason)
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

    def traffic_queue_released(self, task_id: str) -> dict:
        return self.store.release_traffic_wait(task_id)

    def project_core_event(self, event: Mapping[str, object]) -> dict | None:
        """Project only CORE navigation events carrying the current Fleet attempt ID."""
        data = event.get("data")
        if not isinstance(data, Mapping):
            return None
        correlation_id = data.get("correlation_id")
        if not isinstance(correlation_id, str):
            return None
        robot_id = event.get("robot_id")
        event_id = event.get("event_id")
        seq = event.get("seq")
        event_type = event.get("type")
        if not all(isinstance(value, str) for value in (robot_id, event_id, event_type)):
            return None
        source = data.get("source")
        return self.store.project_core_event(
            robot_id=robot_id, event_id=event_id, seq=seq,
            event_type=event_type, correlation_id=correlation_id,
            source=source if isinstance(source, str) else None,
        )

    def cancel_queued_task(self, task_id: str, *, actor_id: str = "site-console") -> dict:
        return self.store.cancel_queued(task_id, actor_id=actor_id)

    def cancel_queued_for_robot(self, robot_id: str, *, actor_id: str = "site-console") -> list[str]:
        return self.store.cancel_queued_for_robot(robot_id, actor_id=actor_id)

    def cancel_all_queued(self, *, actor_id: str = "site-console",
                          reason: str | None = None) -> list[str]:
        return self.store.cancel_all_queued(actor_id=actor_id, reason=reason)
