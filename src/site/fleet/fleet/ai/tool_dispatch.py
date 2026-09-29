"""Fleet-owned allowlist for non-executable ER 2 feedback tools."""

from __future__ import annotations

import json
import asyncio
import hashlib
from collections.abc import Mapping
from typing import Any

from core_common.protocol.schemas import (
    ER2_TOOL_ARGUMENT_MAX_BYTES,
    ER2ToolResult,
    MissionFeedbackContext,
    MissionFeedbackTurnScope,
)
from fleet.server.proposal_store import ProposalRejected


def _json_size(value: object) -> int | None:
    try:
        return len(json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8"))
    except (TypeError, ValueError):
        return None


class MissionFeedbackToolDispatcher:
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

    async def dispatch_replan(self, *, scope: MissionFeedbackTurnScope | Mapping[str, Any],
                              turn_id: str, call_id: str,
                              arguments: Mapping[str, Any], candidate_adapter: Any,
                              egress_policy: Any) -> ER2ToolResult:
        """Acquire one trusted post-action frame, ask ER 2 for selectors, then fence write."""
        checked = self.dispatch(
            scope=scope, call_id=call_id, tool_name="propose_replan",
            arguments=arguments,
        )
        if checked.reason_code != "REPLAN_OBSERVATION_UNAVAILABLE":
            return checked
        if self.post_action_observation_source is None:
            return checked
        try:
            trusted_scope = (scope if isinstance(scope, MissionFeedbackTurnScope)
                             else MissionFeedbackTurnScope.model_validate(scope))
            if (not isinstance(turn_id, str) or not turn_id.strip()
                    or turn_id != turn_id.strip() or len(turn_id) > 96):
                raise ValueError("invalid turn id")
            approved = getattr(egress_policy, "approved_data_classes", frozenset())
            if "camera_observation" not in approved:
                return self._result("propose_replan", "rejected", "REPLAN_EGRESS_NOT_APPROVED")
            current = self._current_context(trusted_scope)
            if current is None:
                return self._result("propose_replan", "rejected", "TURN_SCOPE_STALE")
            feedback, _mission = current
            if feedback.action_observed_at is None:
                return self._result("propose_replan", "unavailable",
                                    "REPLAN_OBSERVATION_UNAVAILABLE")
            capture = self.post_action_observation_source.capture_after(
                scope=trusted_scope,
                based_on_event_id=arguments["based_on_event_id"],
                after_action_at=feedback.action_observed_at,
            )
            captured = await asyncio.wait_for(capture, timeout=5.0)
            if (not isinstance(captured, Mapping)
                    or set(captured) != {"observation", "scope"}):
                raise ValueError("invalid observation capture envelope")
            observation = captured["observation"]
            observation_scope = captured["scope"]
            from fleet.ai.candidate import ImageObservation
            if not isinstance(observation, ImageObservation):
                raise ValueError("trusted source did not return an image observation")
            if not isinstance(observation_scope, Mapping):
                raise ValueError("observation scope is invalid")
            request_id = "feedback-" + hashlib.sha256(
                f"{turn_id}:{call_id}".encode("utf-8"),
            ).hexdigest()
            instruction = (feedback.task_summary[:1400]
                           + "; Replan rationale: " + arguments["rationale"][:512])[:2000]
            pending = candidate_adapter.propose_pick_place(
                request_id=request_id, instruction=instruction,
                observation=observation,
            )
            candidate = await asyncio.wait_for(pending, timeout=25.0)
            if (candidate.source_observation_id != observation.observation_id
                    or candidate.source_image_sha256 != observation.sha256):
                raise ValueError("proposal provenance did not match captured frame")
            saved = self.proposal_store.create_feedback_candidate_fenced(
                turn_id=turn_id, candidate=candidate.to_candidate_record(),
                observation=observation_scope,
            )
            return self._result(
                "propose_replan", "accepted", "CANDIDATE_RECORDED",
                event_id=trusted_scope.event_watermark,
                proposal_id=saved["proposal"]["proposal_id"],
                payload={"successor_of_mission_id": trusted_scope.mission_id,
                         "executable": False},
            )
        except ProposalRejected as exc:
            return self._result("propose_replan", "rejected", exc.code)
        except Exception:
            return self._result("propose_replan", "unavailable",
                                "REPLAN_OBSERVATION_UNAVAILABLE")

    def dispatch(self, *, scope: MissionFeedbackTurnScope | Mapping[str, Any],
                 call_id: str, tool_name: str,
                 arguments: Mapping[str, Any]) -> ER2ToolResult:
        valid_name = tool_name if tool_name in {
            "get_mission_status", "propose_replan",
        } else "unsupported"
        try:
            trusted_scope = (scope if isinstance(scope, MissionFeedbackTurnScope)
                             else MissionFeedbackTurnScope.model_validate(scope))
        except Exception:
            return self._result(valid_name, "rejected", "TURN_SCOPE_INVALID")
        if (not isinstance(call_id, str) or not call_id or call_id != call_id.strip()
                or len(call_id) > 128 or any(ord(char) < 32 for char in call_id)):
            return self._result(valid_name, "rejected", "INVALID_CALL_ID")
        if tool_name not in {"get_mission_status", "propose_replan"}:
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

        current = self._current_context(trusted_scope)
        if current is None:
            return self._result(tool_name, "rejected", "TURN_SCOPE_FORBIDDEN")
        context, mission = current

        if tool_name == "get_mission_status":
            if arguments:
                return self._result(tool_name, "rejected", "INVALID_TOOL_ARGUMENTS")
            return self._result(
                tool_name, "accepted", "STATUS_CURRENT",
                event_id=context.snapshot_event_id,
                payload=context.model_dump(mode="json"),
            )

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
        mission = self.mission_service.get(scope.mission_id)
        if mission is None:
            return None
        if (mission["principal_id"] != scope.principal_id
                or mission["workcell_id"] != scope.workcell_id
                or mission.get("action_id") != scope.action_id
                or mission.get("attempt_id") != scope.attempt_id
                or mission.get("dispatch_generation") != scope.dispatch_generation):
            return None
        snapshot = self.progress_service.snapshot(scope.mission_id)
        context = self.progress_service.model_context(
            scope.mission_id, principal_id=scope.principal_id,
            workcell_id=scope.workcell_id,
        )
        if snapshot is None or context is None:
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
