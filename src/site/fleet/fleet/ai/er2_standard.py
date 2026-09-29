"""Gemini Robotics ER 2 standard-endpoint adapter; proposal-only, no tool execution."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import httpx

from .candidate import ER2ProposalError, ImageObservation, PickPlaceProposalCandidate


MODEL_ID = "gemini-robotics-er-2-preview"
INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
TOOL_NAME = "propose_pick_place"
MAX_RESPONSE_BYTES = 64 * 1024


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


__all__ = ["ER2ProposalError", "ER2RequestError", "GeminiER2StandardAdapter", "ImageObservation"]
