"""Async replan flow for non-executable ER 2 feedback tools."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from typing import Any

from core_common.protocol.schemas import ER2ToolResult, MissionFeedbackTurnScope
from fleet.server.proposal_store import ProposalConflict, ProposalRejected
from rosy.decision.model_tool_contract import ModelToolCall, ModelToolResult


class MissionFeedbackReplanMixin:
    """Acquire one trusted post-action frame, ask ER 2 for selectors, then fence write."""

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
            from rosy.decision.candidate import ImageObservation
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


__all__ = ["MissionFeedbackReplanMixin"]
