"""Fleet-owned allowlist for non-executable ER 2 feedback tools."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core_common.protocol.schemas import (
    ER2_TOOL_ARGUMENT_MAX_BYTES,
    ER2ToolResult,
    MissionFeedbackContext,
    MissionFeedbackTurnScope,
)
from fleet.server.proposal_store import ProposalConflict, ProposalRejected
from rosy.decision.model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass
from rosy.decision.model_tool_contract import ModelToolCall, ModelToolResult

from .model_feedback_replan import MissionFeedbackReplanMixin


def _json_size(value: object) -> int | None:
    try:
        return len(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8"))
    except (TypeError, ValueError):
        return None


class MissionFeedbackToolDispatcher(MissionFeedbackReplanMixin):
    """Validate tool calls against trusted turn scope and current Fleet state."""

    def __init__(self, *, mission_service: Any, progress_service: Any,
                 proposal_store: Any,
                 authorization_check: Any = None,
                 post_action_observation_source: Any = None) -> None:
        if mission_service is None or progress_service is None or proposal_store is None:
            raise ValueError("ER 2 tools require configured Fleet Mission services")
        self.mission_service = mission_service
        self.progress_service = progress_service
        self.proposal_store = proposal_store
        self.authorization_check = authorization_check
        self.post_action_observation_source = post_action_observation_source

    def _complete_call_result(self, call: ModelToolCall, *, outcome: str,
                              reason_code: str) -> None:
        self.proposal_store.complete_model_tool_call(
            call, result=ModelToolResult.for_call(
                call, outcome=outcome, reason_code=reason_code, payload={},
            ),
        )

    def _complete_call_effect(self, call: ModelToolCall, effect: ER2ToolResult) -> None:
        self.proposal_store.complete_model_tool_call(
            call, result=ModelToolResult.from_effect_result(call, effect),
        )

    @staticmethod
    def _effect_result(result: ModelToolResult) -> ER2ToolResult:
        return ER2ToolResult(
            tool_name=result.tool_name, status=result.outcome,
            reason_code=result.reason_code, event_id=result.event_id,
            proposal_id=result.proposal_id, payload=result.payload,
        )

    def dispatch(self, *, scope: MissionFeedbackTurnScope | Mapping[str, Any],
                 call_id: str, tool_name: str,
                 arguments: Mapping[str, Any],
                 model_tool_call: ModelToolCall | None = None) -> ER2ToolResult:
        definition = MODEL_TOOL_CATALOG.get(tool_name)
        valid_name = tool_name if definition is not None and definition.scope == 'mission' else "unsupported"
        try:
            trusted_scope = (scope if isinstance(scope, MissionFeedbackTurnScope)
                             else MissionFeedbackTurnScope.model_validate(scope))
        except Exception:
            return self._result(valid_name, "rejected", "TURN_SCOPE_INVALID")
        if (not isinstance(call_id, str) or not call_id or call_id != call_id.strip()
                or len(call_id) > 128 or any(ord(char) < 32 for char in call_id)):
            return self._result(valid_name, "rejected", "INVALID_CALL_ID")
        if definition is None or definition.scope != 'mission' or not definition.feedback_enabled:
            return self._result(valid_name, "rejected", "TOOL_NOT_ALLOWED")
        try:
            authorized = (self.authorization_check is not None
                          and self.authorization_check(trusted_scope) is True)
        except Exception:
            authorized = False
        if not authorized:
            return self._result(tool_name, "rejected", "PRINCIPAL_NOT_AUTHORIZED")
        if (not isinstance(arguments, Mapping)
                or _json_size(dict(arguments)) is None
                or _json_size(dict(arguments)) > ER2_TOOL_ARGUMENT_MAX_BYTES):
            return self._result(tool_name, "rejected", "INVALID_TOOL_ARGUMENTS")
        if model_tool_call is not None and (
                model_tool_call.provider_call_id != call_id
                or model_tool_call.tool_name != tool_name
                or model_tool_call.arguments != dict(arguments)):
            return self._result(tool_name, "rejected", "TOOL_CALL_SCOPE_MISMATCH")
        if (model_tool_call is not None
                and definition.effect_class is ToolEffectClass.CANDIDATE_WRITING):
            return self._result(tool_name, "rejected", "ASYNC_TOOL_DISPATCH_REQUIRED")
        if model_tool_call is not None:
            try:
                claim = self.proposal_store.begin_model_tool_call(model_tool_call)
            except ProposalConflict:
                return self._result(tool_name, "rejected", "PROVIDER_CALL_ID_REUSE")
            except ProposalRejected as exc:
                return self._result(tool_name, "rejected", exc.code)
            if claim["state"] == "COMPLETED":
                return self._effect_result(ModelToolResult.model_validate(claim["result"]))
            if claim["state"] == "UNKNOWN":
                return self._result(tool_name, "unavailable", "TOOL_CALL_OUTCOME_UNKNOWN")
            if not claim["created"]:
                return self._result(tool_name, "unavailable", "TOOL_CALL_IN_PROGRESS")

        current = self._current_context(trusted_scope)
        if current is None:
            result = self._result(tool_name, "rejected", "TURN_SCOPE_FORBIDDEN")
            if model_tool_call is not None:
                self._complete_call_effect(model_tool_call, result)
            return result
        context, mission = current

        if definition.effect_class is ToolEffectClass.READ_ONLY:
            if arguments:
                result = self._result(tool_name, "rejected", "INVALID_TOOL_ARGUMENTS")
                if model_tool_call is not None:
                    self._complete_call_effect(model_tool_call, result)
                return result
            result = self._result(
                tool_name, "accepted", "STATUS_CURRENT",
                event_id=context.snapshot_event_id,
                payload=context.model_dump(mode="json"),
            )
            if model_tool_call is not None:
                self._complete_call_effect(model_tool_call, result)
            return result

        if (set(arguments) != {"based_on_event_id", "rationale"}
                or type(arguments.get("based_on_event_id")) is not int
                or not isinstance(arguments.get("rationale"), str)
                or not arguments["rationale"].strip()
                or arguments["rationale"] != arguments["rationale"].strip()
                or len(arguments["rationale"]) > 512):
            return self._result(tool_name, "rejected", "INVALID_TOOL_ARGUMENTS")
        if arguments["based_on_event_id"] != trusted_scope.event_watermark:
            return self._result(tool_name, "rejected", "EVENT_WATERMARK_STALE")

        if trusted_scope.outcome_policy != "STATUS_AND_REPLAN":
            return self._result(tool_name, "rejected", "REPLAN_NOT_ALLOWED")
        if context.stop_state != "DISPATCH_ENABLED":
            return self._result(tool_name, "rejected", "STOP_FENCE_CLOSED")
        if context.stop_generation != trusted_scope.dispatch_generation:
            return self._result(tool_name, "rejected", "STOP_GENERATION_CHANGED")
        if context.snapshot_event_id != trusted_scope.event_watermark:
            return self._result(tool_name, "rejected", "EVENT_WATERMARK_STALE")
        if (mission.get("status") != "HOLD"
                or mission.get("reason") != "GOAL_NOT_SATISFIED"):
            return self._result(tool_name, "rejected", "REPLAN_NOT_ELIGIBLE")
        if (context.goal_evidence_state != "UNSATISFIED"
                or context.goal_evidence_freshness != "FRESH"
                or context.action_state != "SUCCEEDED"
                or context.action_freshness != "FRESH"):
            return self._result(tool_name, "rejected", "REPLAN_EVIDENCE_NOT_FRESH")
        # No fresh post-action image/evidence resolver is currently wired into
        # the feedback context, so a spatial successor proposal cannot be made.
        # Never fall back to a separate, unfenced ProposalStore write.
        return self._result(tool_name, "unavailable", "REPLAN_OBSERVATION_UNAVAILABLE")

    def _current_context(self, scope: MissionFeedbackTurnScope):
        snapshot = self.progress_service.snapshot(scope.mission_id)
        if snapshot is None:
            return None
        mission = snapshot["mission"]
        if (mission["principal_id"] != scope.principal_id
                or mission["workcell_id"] != scope.workcell_id
                or mission.get("action_id") != scope.action_id
                or mission.get("attempt_id") != scope.attempt_id
                or mission.get("dispatch_generation") != scope.dispatch_generation):
            return None
        context = self.progress_service.model_context_from_snapshot(
            snapshot, principal_id=scope.principal_id,
            workcell_id=scope.workcell_id,
        )
        if context is None:
            return None
        plan = mission.get("plan") or {}
        task_summary = plan.get("instruction")
        if not isinstance(task_summary, str) or not task_summary.strip():
            task_summary = f"Review the accepted {mission['action_kind']} Mission outcome."
        try:
            feedback = MissionFeedbackContext.model_validate({
                **context,
                "action_id": scope.action_id,
                "attempt_id": scope.attempt_id,
                "dispatch_generation": scope.dispatch_generation,
                "policy_revision": scope.model_policy_revision,
                "outcome_policy": scope.outcome_policy,
                "task_summary": task_summary[:10_000],
            })
        except (TypeError, ValueError):
            return None
        # A turn can still read current status after harmless later journal events,
        # but replan calls separately require an exact event watermark match.
        return feedback, mission

    @staticmethod
    def _result(tool_name: str, status: str, reason_code: str, *,
                event_id: int | None = None, proposal_id: str | None = None,
                payload: Mapping[str, Any] | None = None) -> ER2ToolResult:
        return ER2ToolResult(
            tool_name=tool_name, status=status, reason_code=reason_code,
            event_id=event_id, proposal_id=proposal_id,
            payload=dict(payload or {}),
        )


__all__ = ["MissionFeedbackToolDispatcher"]
