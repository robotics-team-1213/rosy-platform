"""Gemini Robotics ER 2 standard-endpoint adapter; proposal-only, no tool execution."""

from __future__ import annotations

import base64
import asyncio
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .candidate import ER2ProposalError, ImageObservation, PickPlaceProposalCandidate
from core_common.protocol.schemas import (
    ER2_FEEDBACK_CONTEXT_MAX_BYTES, ER2_MAX_ESTIMATED_TURN_COST_USD,
    ER2_MAX_FUNCTION_CALLS_PER_TURN, ER2_REPLAY_MAX_BYTES, ER2_REPLAY_MAX_STEPS,
    ER2_RESPONSE_MAX_BYTES, ER2_TOOL_RESULT_MAX_BYTES, MissionFeedbackContext,
    MissionFeedbackTurnScope,
)


MODEL_ID = "gemini-robotics-er-2-preview"
INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
TOOL_NAME = "propose_pick_place"
MAX_RESPONSE_BYTES = ER2_RESPONSE_MAX_BYTES


class ER2RequestError(RuntimeError):
    """The remote ER 2 request failed; no candidate is returned."""


_TOOL = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "Propose one pick-and-place target selection for Fleet review. This function "
        "does not move a robot. Select one point or box in the supplied image for each item."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "point_yx_1000": {"type": "array", "items": {"type": "integer"},
                                      "minItems": 2, "maxItems": 2},
                    "box_yxyx_1000": {"type": "array", "items": {"type": "integer"},
                                      "minItems": 4, "maxItems": 4},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
            "destination": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "point_yx_1000": {"type": "array", "items": {"type": "integer"},
                                      "minItems": 2, "maxItems": 2},
                    "box_yxyx_1000": {"type": "array", "items": {"type": "integer"},
                                      "minItems": 4, "maxItems": 4},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
        },
        "required": ["target", "destination"],
        "additionalProperties": False,
    },
}

_FEEDBACK_TOOLS = [
    {"type": "function", "name": "get_mission_status",
     "description": "Read current Fleet evidence for the already scoped Mission.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "propose_replan",
     "description": "Submit a non-executable replan candidate for Fleet review.",
     "parameters": {"type": "object", "properties": {
         "based_on_event_id": {"type": "integer", "minimum": 0},
         "rationale": {"type": "string", "maxLength": 512},
     }, "required": ["based_on_event_id", "rationale"],
         "additionalProperties": False}},
]


@dataclass(frozen=True)
class ER2FeedbackEgressPolicy:
    """Trusted server configuration required before a feedback POST is allowed."""

    approved: bool
    project_id: str
    service_tier: str
    approved_data_classes: frozenset[str]
    approved_workcell_ids: frozenset[str]
    approved_task_classes: frozenset[str]
    estimated_cost_usd: float

    def validate(self) -> None:
        if (self.approved is not True
                or not isinstance(self.project_id, str) or not self.project_id.strip()
                or not isinstance(self.service_tier, str) or not self.service_tier.strip()
                or not isinstance(self.approved_data_classes, frozenset)
                or not {"mission_progress", "mission_instruction"}.issubset(
                    self.approved_data_classes)
                or not isinstance(self.approved_workcell_ids, frozenset)
                or not self.approved_workcell_ids
                or not isinstance(self.approved_task_classes, frozenset)
                or not self.approved_task_classes):
            raise ER2RequestError("Gemini ER 2 feedback egress policy is not approved")
        if (type(self.estimated_cost_usd) not in (int, float)
                or not math.isfinite(self.estimated_cost_usd)
                or not 0 <= self.estimated_cost_usd <= ER2_MAX_ESTIMATED_TURN_COST_USD):
            raise ER2RequestError("Gemini ER 2 feedback cost preflight was rejected")

    def validate_for(self, *, scope: MissionFeedbackTurnScope,
                     task_class: str) -> None:
        """Check the immutable server allowlist against this trusted turn."""
        self.validate()
        if (scope.workcell_id not in self.approved_workcell_ids
                or task_class not in self.approved_task_classes):
            raise ER2RequestError("Gemini ER 2 feedback scope is outside approved egress")


class GeminiER2StandardAdapter:
    """Call the standard Interactions API and parse one non-executable proposal."""

    def __init__(self, *, api_key: str, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 45.0) -> None:
        if not isinstance(api_key, str) or not api_key or api_key != api_key.strip():
            raise ValueError("api_key must be configured as a non-empty secret")
        if type(timeout_s) not in (int, float) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(float(timeout_s), connect=min(float(timeout_s), 5.0)),
        )

    async def __aenter__(self) -> "GeminiER2StandardAdapter":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def reason_about_mission(
        self, *, scope: MissionFeedbackTurnScope,
        context: MissionFeedbackContext | Mapping[str, Any], dispatcher: Any,
        egress_policy: ER2FeedbackEgressPolicy | None,
        turn_id: str | None = None,
    ) -> str:
        """Run one bounded, stateless status/tool-result turn.

        Only the trusted Fleet dispatcher executes the two declared tools. The
        exact provider steps are kept in this method's memory and never stored
        by this adapter or included in errors.
        """
        if egress_policy is None:
            raise ER2RequestError("Gemini ER 2 feedback egress policy is not approved")
        egress_policy.validate_for(scope=scope, task_class="PICK_PLACE")
        if not isinstance(scope, MissionFeedbackTurnScope):
            raise ValueError("feedback turns require a validated trusted scope")
        feedback = (context if isinstance(context, MissionFeedbackContext)
                    else MissionFeedbackContext.model_validate(context))
        if (feedback.mission_id != scope.mission_id
                or feedback.workcell_id != scope.workcell_id
                or feedback.action_id != scope.action_id
                or feedback.attempt_id != scope.attempt_id
                or feedback.dispatch_generation != scope.dispatch_generation
                or feedback.snapshot_event_id != scope.event_watermark
                or feedback.policy_revision != scope.model_policy_revision
                or feedback.outcome_policy != scope.outcome_policy):
            raise ValueError("feedback context does not match the trusted turn scope")
        initial = json.dumps(feedback.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
        if len(initial) > ER2_FEEDBACK_CONTEXT_MAX_BYTES:
            raise ValueError("feedback context exceeds 8 KiB")
        if dispatcher is None or not callable(getattr(dispatcher, "dispatch", None)):
            raise ValueError("feedback tool dispatcher is unavailable")

        replay: list[dict[str, Any]] = [{
            "type": "user_input",
            "text": ("Review the Fleet evidence below. Report only the Fleet-backed "
                     "Mission, Action, goal-evidence, and stop states. A provider "
                     "response is not proof of physical completion or stop. Use only "
                     "the declared Fleet tools.\n\n" + initial.decode("utf-8")),
        }]
        function_calls = 0
        seen_call_ids: set[str] = set()
        deadline = time.monotonic() + 45.0
        for _step in range(ER2_REPLAY_MAX_STEPS):
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise ER2RequestError("Gemini ER 2 feedback turn deadline exceeded")
            request_body = {
                "model": MODEL_ID, "store": False, "input": replay,
                "tools": _FEEDBACK_TOOLS,
            }
            try:
                response = await asyncio.wait_for(
                    self._feedback_post(request_body), timeout=remaining_s,
                )
            except asyncio.TimeoutError as exc:
                raise ER2RequestError(
                    "Gemini ER 2 feedback outcome is unknown after request invocation"
                ) from exc
            steps = response.get("steps", response.get("outputs"))
            if not isinstance(steps, list) or not steps:
                raise ER2ProposalError("Gemini ER 2 feedback returned no steps")
            if len(steps) > ER2_REPLAY_MAX_STEPS:
                raise ER2ProposalError("Gemini ER 2 feedback returned too many steps")
            model_steps: list[dict[str, Any]] = []
            calls: list[tuple[dict[str, Any], str, str, Mapping[str, Any]]] = []
            for model_step in steps:
                if not isinstance(model_step, Mapping):
                    raise ER2ProposalError("Gemini ER 2 feedback step is invalid")
                step = dict(model_step)
                if step.get("type") not in {"function_call", "thought", "text"}:
                    raise ER2ProposalError("Gemini ER 2 feedback returned an unsupported step")
                model_steps.append(step)
                if step.get("type") == "function_call":
                    function_calls += 1
                    if function_calls > ER2_MAX_FUNCTION_CALLS_PER_TURN:
                        raise ER2ProposalError("Gemini ER 2 feedback tool-call budget exceeded")
                    name, call_id, arguments = step.get("name"), step.get("id"), step.get("arguments")
                    if (not isinstance(name, str) or not isinstance(call_id, str)
                            or not call_id or not isinstance(arguments, Mapping)):
                        raise ER2ProposalError("Gemini ER 2 feedback function call is invalid")
                    if call_id in seen_call_ids:
                        raise ER2ProposalError("Gemini ER 2 feedback repeated a function call ID")
                    seen_call_ids.add(call_id)
                    calls.append((step, name, call_id, arguments))
                elif step.get("type") == "text" and not isinstance(step.get("text"), str):
                    raise ER2ProposalError("Gemini ER 2 feedback text step is invalid")
            if not calls:
                replay.extend(model_steps)
                replay_size = len(json.dumps(
                    replay, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode("utf-8"))
                if replay_size > ER2_REPLAY_MAX_BYTES:
                    raise ER2ProposalError("Gemini ER 2 feedback replay exceeds 64 KiB")
                final_text = next((step["text"] for step in reversed(model_steps)
                                   if step.get("type") == "text"), None)
                if not isinstance(final_text, str):
                    raise ER2ProposalError("Gemini ER 2 feedback returned no final text")
                return final_text[:4_000]
            replay.extend(model_steps)
            for _step, name, call_id, arguments in calls:
                if name == "propose_replan" and callable(
                        getattr(dispatcher, "dispatch_replan", None)):
                    result = await dispatcher.dispatch_replan(
                        scope=scope, turn_id=turn_id, call_id=call_id,
                        arguments=dict(arguments), candidate_adapter=self,
                        egress_policy=egress_policy,
                    ) if turn_id is not None else dispatcher.dispatch(
                        scope=scope, call_id=call_id, tool_name=name,
                        arguments=dict(arguments),
                    )
                else:
                    result = dispatcher.dispatch(
                        scope=scope, call_id=call_id, tool_name=name,
                        arguments=dict(arguments),
                    )
                result_json = result.model_dump(mode="json")
                result_bytes = json.dumps(result_json, sort_keys=True,
                                          separators=(",", ":"), allow_nan=False).encode()
                if len(result_bytes) > ER2_TOOL_RESULT_MAX_BYTES:
                    raise ER2ProposalError("Fleet feedback tool result exceeds 4 KiB")
                replay.append({"type": "function_result", "call_id": call_id,
                               "name": name, "result": result_json})
            replay_size = len(json.dumps(replay, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode("utf-8"))
            if replay_size > ER2_REPLAY_MAX_BYTES:
                raise ER2ProposalError("Gemini ER 2 feedback replay exceeds 64 KiB")
        raise ER2ProposalError("Gemini ER 2 feedback replay-step budget exceeded")

    async def _feedback_post(self, request_body: Mapping[str, Any]) -> Mapping[str, Any]:
        response_body = bytearray()
        try:
            async with self._client.stream(
                "POST", INTERACTIONS_URL,
                headers={"x-goog-api-key": self._api_key}, json=dict(request_body),
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise ER2RequestError(
                        f"Gemini ER 2 feedback returned HTTP {response.status_code}"
                    )
                async for chunk in response.aiter_bytes():
                    if len(response_body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ER2ProposalError("Gemini ER 2 response exceeds the 64 KiB limit")
                    response_body.extend(chunk)
        except httpx.HTTPError as exc:
            raise ER2RequestError(
                "Gemini ER 2 feedback outcome is unknown after request invocation"
            ) from exc
        try:
            payload = json.loads(response_body)
        except ValueError as exc:
            raise ER2ProposalError("Gemini ER 2 feedback returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ER2ProposalError("Gemini ER 2 feedback response must be an object")
        return payload

    async def propose_pick_place(
        self, *, request_id: str, instruction: str, observation: ImageObservation,
    ) -> PickPlaceProposalCandidate:
        if (not isinstance(request_id, str) or not request_id.strip()
                or request_id != request_id.strip() or len(request_id) > 128):
            raise ValueError(
                "request_id must be non-empty, trimmed, and no longer than 128 characters"
            )
        if (not isinstance(instruction, str) or not instruction.strip()
                or instruction != instruction.strip() or len(instruction) > 2000):
            raise ValueError(
                "instruction must be non-empty, trimmed, and no longer than 2000 characters"
            )
        prompt = (
            "Interpret the requested tabletop task from this single image. Return exactly one "
            "propose_pick_place function call only when both target and destination are visible "
            "and unambiguous. For each selector, choose exactly one image-relative point or box. "
            "Coordinates are normalized integers in [y,x] or [ymin,xmin,ymax,xmax] order, "
            "each from 0 to 1000. These are image selectors, not robot/world coordinates. "
            "Do not invent object IDs, poses, trajectories, grasp success, or task completion. "
            "If either selector is unclear, return no function call.\n\n"
            f"User task: {instruction}"
        )
        request_body = {
            "model": MODEL_ID,
            "store": False,
            "input": {"parts": [
                {"inlineData": {
                    "mimeType": observation.mime_type,
                    "data": base64.b64encode(observation.image_bytes).decode("ascii"),
                }},
                {"text": prompt},
            ]},
            "tools": [_TOOL],
        }
        try:
            async with self._client.stream(
                "POST", INTERACTIONS_URL,
                headers={"x-goog-api-key": self._api_key},
                json=request_body,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise ER2RequestError(
                        f"Gemini ER 2 returned HTTP {response.status_code}"
                    )
                response_body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(response_body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ER2ProposalError(
                            "Gemini ER 2 response exceeds the 64 KiB limit"
                        )
                    response_body.extend(chunk)
        except httpx.HTTPError as exc:
            raise ER2RequestError(
                "Gemini ER 2 request failed before a proposal was received"
            ) from exc
        try:
            payload = json.loads(response_body)
        except ValueError as exc:
            raise ER2ProposalError("Gemini ER 2 returned invalid JSON") from exc
        return self._parse_response(
            payload, request_id=request_id, instruction=instruction, observation=observation,
        )

    @staticmethod
    def _parse_response(
        payload: Any, *, instruction: str, observation: ImageObservation,
        request_id: str,
    ) -> PickPlaceProposalCandidate:
        if not isinstance(payload, Mapping):
            raise ER2ProposalError("Gemini ER 2 response must be an object")
        outputs = payload.get("outputs")
        # The robotics orchestration guide also documents the same call under `steps`.
        documented_steps = payload.get("steps")
        if outputs is not None and documented_steps is not None and outputs != documented_steps:
            raise ER2ProposalError("Gemini ER 2 response has conflicting outputs and steps")
        if outputs is None:
            outputs = documented_steps
        if not isinstance(outputs, list):
            raise ER2ProposalError("Gemini ER 2 response has no output list")
        if (len(outputs) != 1 or not isinstance(outputs[0], Mapping)
                or outputs[0].get("type") != "function_call"):
            raise ER2ProposalError("Gemini ER 2 must return exactly one proposal function call")
        call = outputs[0]
        try:
            return PickPlaceProposalCandidate.from_function_call(
                request_id=request_id, interaction_id=payload.get("id"), call_id=call.get("id"),
                name=call.get("name"), arguments=call.get("arguments"),
                instruction=instruction, observation=observation, model_id=MODEL_ID,
            )
        except ER2ProposalError:
            raise
        except (TypeError, ValueError) as exc:
            raise ER2ProposalError("Gemini ER 2 proposal could not be validated") from exc


__all__ = [
    "ER2FeedbackEgressPolicy", "ER2ProposalError", "ER2RequestError",
    "GeminiER2StandardAdapter", "ImageObservation",
]
