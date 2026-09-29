"""At-most-one-submit worker for the transcript-free ER 2 outbox."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from core_common.protocol.schemas import MissionFeedbackContext, MissionFeedbackTurnScope

from .mission_model_turn_store import MissionModelTurnStore


class MissionModelTurnWorker:
    """Consume one outbox row; never admits or dispatches a Mission."""

    def __init__(self, *, store: MissionModelTurnStore, adapter: Any,
                 dispatcher: Any,
                 context_loader: Callable[[Mapping[str, Any]],
                                          MissionFeedbackContext | Mapping[str, Any]],
                 egress_policy: Any,
                 authorization_check: Callable[[MissionFeedbackTurnScope], bool] | None = None) -> None:
        self.store = store
        self.adapter = adapter
        self.dispatcher = dispatcher
        self.context_loader = context_loader
        self.egress_policy = egress_policy
        self.authorization_check = authorization_check

    async def consume(self, turn_id: str, *, worker_id: str) -> dict[str, Any] | None:
        turn = self.store.claim(turn_id, worker_id=worker_id)
        if turn is None:
            return None
        return await self._consume_claimed(turn, worker_id=worker_id)

    async def consume_next(self, *, worker_id: str) -> dict[str, Any] | None:
        """Recover expired work and consume the oldest pending durable turn."""
        self.store.expire_claims()
        turn = self.store.claim_next(worker_id=worker_id)
        if turn is None:
            return None
        return await self._consume_claimed(turn, worker_id=worker_id)

    async def _consume_claimed(self, turn: Mapping[str, Any], *,
                               worker_id: str) -> dict[str, Any] | None:
        turn_id = turn["turn_id"]
        scope_fields = {
            name: turn[name] for name in (
                "principal_id", "workcell_id", "mission_id", "action_id", "attempt_id",
                "dispatch_generation", "event_watermark", "model_policy_revision",
                "outcome_policy",
            )
        }
        scope = MissionFeedbackTurnScope.model_validate(scope_fields)

        try:
            context = self.context_loader(turn)
            context = (context if isinstance(context, MissionFeedbackContext)
                       else MissionFeedbackContext.model_validate(context))
        except Exception:
            return self.store.release_preflight(
                turn_id, worker_id=worker_id, reason_code="CONTEXT_UNAVAILABLE",
            )
        if context.stop_state != "DISPATCH_ENABLED":
            return self.store.suppress_claim(
                turn_id, worker_id=worker_id, reason_code="STOP_FENCE_CLOSED",
            )
        if context.stop_generation != scope.dispatch_generation:
            return self.store.suppress_claim(
                turn_id, worker_id=worker_id, reason_code="STOP_GENERATION_CHANGED",
            )
        if context.dispatch_generation != scope.dispatch_generation:
            return self.store.suppress_claim(
                turn_id, worker_id=worker_id, reason_code="TURN_SCOPE_STALE",
            )
        if (context.mission_id != scope.mission_id
                or context.workcell_id != scope.workcell_id
                or context.action_id != scope.action_id
                or context.attempt_id != scope.attempt_id
                or context.snapshot_event_id != scope.event_watermark
                or context.policy_revision != scope.model_policy_revision
                or context.outcome_policy != scope.outcome_policy):
            return self.store.suppress_claim(
                turn_id, worker_id=worker_id, reason_code="TURN_SCOPE_STALE",
            )
        try:
            if (self.authorization_check is None
                    or self.authorization_check(scope) is not True):
                raise PermissionError("current principal authorization is unavailable")
            self.egress_policy.validate_for(scope=scope, task_class="PICK_PLACE")
        except Exception:
            return self.store.release_preflight(
                turn_id, worker_id=worker_id, reason_code="EGRESS_POLICY_REJECTED",
            )

        submitting = self.store.begin_submission_fenced(turn_id, worker_id=worker_id)
        if submitting is None or submitting["state"] != "SUBMITTING":
            return None
        try:
            await self.adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=self.dispatcher,
                egress_policy=self.egress_policy, turn_id=turn_id,
            )
        except Exception:
            return self.store.mark_unknown(
                turn_id, reason_code="PROVIDER_OUTCOME_UNKNOWN",
            )
        return self.store.mark_responded(turn_id)


__all__ = ["MissionModelTurnWorker"]
