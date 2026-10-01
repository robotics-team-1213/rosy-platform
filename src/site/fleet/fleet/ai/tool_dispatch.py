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
from fleet.ai.model_tool_contract import ModelToolCall, ModelToolResult
from fleet.ai.model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass
from fleet.server.proposal_store import ProposalConflict, ProposalRejected


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
                              egress_policy: Any,
                              model_tool_call: ModelToolCall | None = None) -> ER2ToolResult:
        """Acquire one trusted post-action frame, ask ER 2 for selectors, then fence write."""
        if model_tool_call is not None and (
                model_tool_call.turn_id != turn_id
                or model_tool_call.provider_call_id != call_id
                or model_tool_call.tool_name != "propose_replan"
                or model_tool_call.arguments != dict(arguments)):
            return self._result("propose_replan", "rejected", "TOOL_CALL_SCOPE_MISMATCH")
        call_started = False
        checked = self.dispatch(
            scope=scope, call_id=call_id, tool_name="propose_replan",
            arguments=arguments,
        )
        if model_tool_call is not None:
            # The synchronous validation above confirms the trusted scope and
            # authorization before a durable call identity is claimed. Persist
            # every known result, including early policy/fence rejections.
            if checked.reason_code not in {"TURN_SCOPE_INVALID", "PRINCIPAL_NOT_AUTHORIZED"}:
                try:
                    claim = self.proposal_store.begin_model_tool_call(model_tool_call)
                except ProposalConflict:
                    return self._result("propose_replan", "rejected", "PROVIDER_CALL_ID_REUSE")
                except ProposalRejected as exc:
                    return self._result("propose_replan", "rejected", exc.code)
                if claim["state"] == "COMPLETED":
                    return self._effect_result(ModelToolResult.model_validate(claim["result"]))
                if claim["state"] == "UNKNOWN":
                    return self._result("propose_replan", "unavailable",
                                        "TOOL_CALL_OUTCOME_UNKNOWN")
                if not claim["created"]:
                    return self._result("propose_replan", "unavailable",
                                        "TOOL_CALL_IN_PROGRESS")
                call_started = True
                if checked.reason_code != "REPLAN_OBSERVATION_UNAVAILABLE":
                    self._complete_call_effect(model_tool_call, checked)
                    return checked
            else:
                return checked
        elif checked.reason_code != "REPLAN_OBSERVATION_UNAVAILABLE":
            return checked
        if self.post_action_observation_source is None:
            if call_started and model_tool_call is not None:
                self._complete_call_effect(model_tool_call, checked)
            return checked
        candidate_invoked = False
        try:
            trusted_scope = (scope if isinstance(scope, MissionFeedbackTurnScope)
                             else MissionFeedbackTurnScope.model_validate(scope))
            if (not isinstance(turn_id, str) or not turn_id.strip()
                    or turn_id != turn_id.strip() or len(turn_id) > 96):
                raise ValueError("invalid turn id")
            validate_egress = getattr(egress_policy, "validate_for", None)
            if not callable(validate_egress):
                result = self._result("propose_replan", "rejected",
                                      "REPLAN_EGRESS_NOT_APPROVED")
                if call_started and model_tool_call is not None:
                    self._complete_call_effect(model_tool_call, result)
                return result
            try:
                validate_egress(scope=trusted_scope, task_class="PICK_PLACE")
            except Exception:
                result = self._result("propose_replan", "rejected",
                                      "REPLAN_EGRESS_NOT_APPROVED")
                if call_started and model_tool_call is not None:
                    self._complete_call_effect(model_tool_call, result)
                return result
            approved = getattr(egress_policy, "approved_data_classes", frozenset())
            if "camera_observation" not in approved:
                result = self._result("propose_replan", "rejected",
                                      "REPLAN_EGRESS_NOT_APPROVED")
                if call_started and model_tool_call is not None:
                    self._complete_call_effect(model_tool_call, result)
                return result
            current = self._current_context(trusted_scope)
            if current is None:
                if call_started and model_tool_call is not None:
                    self._complete_call_result(
                        model_tool_call, outcome="rejected", reason_code="TURN_SCOPE_STALE",
                    )
                return self._result("propose_replan", "rejected", "TURN_SCOPE_STALE")
            feedback, _mission = current
            if feedback.action_observed_at is None:
                if call_started and model_tool_call is not None:
                    self._complete_call_result(
                        model_tool_call, outcome="unavailable",
                        reason_code="REPLAN_OBSERVATION_UNAVAILABLE",
                    )
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
            expected_observation_scope = {
                "mission_id": trusted_scope.mission_id,
                "workcell_id": trusted_scope.workcell_id,
                "action_id": trusted_scope.action_id,
                "attempt_id": trusted_scope.attempt_id,
                "dispatch_generation": trusted_scope.dispatch_generation,
                "based_on_event_id": trusted_scope.event_watermark,
                "observation_id": observation.observation_id,
                "observed_at": observation.observed_at,
                "image_sha256": observation.sha256,
            }
            if dict(observation_scope) != expected_observation_scope:
                raise ValueError("observation source scope does not match the durable turn")
            # Frame acquisition can take time. Re-read current Fleet authority and
            # the data-egress policy immediately before sending image bytes onward.
            checked = self.dispatch(
                scope=trusted_scope, call_id=call_id, tool_name="propose_replan",
                arguments=arguments,
            )
            if (checked.status != "unavailable"
                    or checked.reason_code != "REPLAN_OBSERVATION_UNAVAILABLE"):
                if call_started and model_tool_call is not None:
                    self._complete_call_effect(model_tool_call, checked)
                return checked
            try:
                validate_egress(scope=trusted_scope, task_class="PICK_PLACE")
            except Exception:
                if call_started and model_tool_call is not None:
                    self._complete_call_result(
                        model_tool_call, outcome="rejected",
                        reason_code="REPLAN_EGRESS_NOT_APPROVED",
                    )
                return self._result("propose_replan", "rejected", "REPLAN_EGRESS_NOT_APPROVED")
            approved = getattr(egress_policy, "approved_data_classes", frozenset())
            if "camera_observation" not in approved:
                if call_started and model_tool_call is not None:
                    self._complete_call_result(
                        model_tool_call, outcome="rejected",
                        reason_code="REPLAN_EGRESS_NOT_APPROVED",
                    )
                return self._result("propose_replan", "rejected", "REPLAN_EGRESS_NOT_APPROVED")
            request_id = "feedback-" + hashlib.sha256(
                f"{turn_id}:{call_id}".encode("utf-8"),
            ).hexdigest()
            instruction = (feedback.task_summary[:1400]
                           + "; Replan rationale: " + arguments["rationale"][:512])[:2000]
            candidate_invoked = True
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
                observation=observation_scope, tool_call=model_tool_call,
            )
            return self._result(
                "propose_replan", "accepted", "CANDIDATE_RECORDED",
                event_id=trusted_scope.event_watermark,
                proposal_id=saved["proposal"]["proposal_id"],
                payload={"successor_of_mission_id": trusted_scope.mission_id,
                         "executable": False},
            )
        except ProposalRejected as exc:
            if call_started and model_tool_call is not None:
                self._complete_call_result(
                    model_tool_call, outcome="rejected", reason_code=exc.code,
                )
            return self._result("propose_replan", "rejected", exc.code)
        except ProposalConflict:
            if call_started and model_tool_call is not None:
                self._complete_call_result(
                    model_tool_call, outcome="rejected", reason_code="PROVIDER_CALL_ID_REUSE",
                )
            return self._result("propose_replan", "rejected", "PROVIDER_CALL_ID_REUSE")
        except asyncio.CancelledError:
            if call_started and model_tool_call is not None:
                self.proposal_store.mark_model_tool_call_unknown(model_tool_call)
            raise
        except Exception:
            if call_started and model_tool_call is not None:
                if candidate_invoked:
                    self.proposal_store.mark_model_tool_call_unknown(model_tool_call)
                    return self._result("propose_replan", "unavailable",
                                        "TOOL_CALL_OUTCOME_UNKNOWN")
                self._complete_call_result(
                    model_tool_call, outcome="unavailable",
                    reason_code="REPLAN_OBSERVATION_UNAVAILABLE",
                )
            return self._result("propose_replan", "unavailable",
                                "REPLAN_OBSERVATION_UNAVAILABLE")

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
        valid_name = tool_name if definition is not None else "unsupported"
        try:
            trusted_scope = (scope if isinstance(scope, MissionFeedbackTurnScope)
                             else MissionFeedbackTurnScope.model_validate(scope))
        except Exception:
            return self._result(valid_name, "rejected", "TURN_SCOPE_INVALID")
        if (not isinstance(call_id, str) or not call_id or call_id != call_id.strip()
                or len(call_id) > 128 or any(ord(char) < 32 for char in call_id)):
            return self._result(valid_name, "rejected", "INVALID_CALL_ID")
        if definition is None or not definition.feedback_enabled:
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
