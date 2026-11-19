"""Candidate schema validation, hashing, and error types for ``ProposalStore``."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from core_common.protocol.schemas import ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS
from rosy.decision.model_tool_contract import ModelToolCall


class ProposalConflict(ValueError):
    """A proposal identity was reused or a state transition conflicts."""


class ProposalRejected(ValueError):
    """A candidate cannot be resolved against current trusted evidence."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            raise ValueError("proposal rejection must use a stable uppercase reason code")
        self.code = code
        super().__init__(code)


_ALLOWED_FIELDS = {
    "request_id", "source", "model_id", "instruction", "provider_interaction_id",
    "provider_call_id", "source_observation", "target_selector", "destination_selector",
}
_SOURCE_FIELDS = {
    "observation_id", "camera_id", "frame_id", "observed_at", "image_sha256",
    "coordinate_space", "image_transform", "calibration_revision", "transform_revision",
}
_TRANSFORM_FIELDS = {
    "source_width", "source_height", "crop_xyxy", "model_width", "model_height",
    "rotation_quadrants_clockwise",
}
_SELECTOR_FIELDS = {"label", "point_yx_1000", "box_yxyx_1000"}
_MAX_CANDIDATE_BYTES = 32 * 1024
_MAX_CELL_JOB_CANDIDATE_BYTES = 64 * 1024
_MAX_POST_ACTION_OBSERVATION_AGE = timedelta(
    seconds=ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS,
)


def _text(name: str, value: object, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {limit} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal data must be finite JSON") from exc


def _check_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("candidate must be a JSON object")
    document = dict(value)

    if document.get("kind") == "cell_job":
        required = {"kind", "recipe", "cell", "recipe_sha256", "cell_sha256", "job"}
        if set(document) != required:
            raise ValueError("cell_job candidate requires recipe, cell, hashes, and compiled Job")
        for field in ("recipe", "cell", "job"):
            if not isinstance(document[field], Mapping):
                raise ValueError(f"cell_job candidate {field} must be an object")
        for field in ("recipe_sha256", "cell_sha256"):
            digest = document[field]
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)):
                raise ValueError(f"cell_job candidate {field} must be lowercase SHA-256")
        encoded = _json(document)
        if len(encoded.encode("utf-8")) > _MAX_CELL_JOB_CANDIDATE_BYTES:
            raise ValueError("cell_job candidate metadata exceeds 64 KiB")
        return json.loads(encoded)

    if set(document) - _ALLOWED_FIELDS:
        forbidden = set(document) - _ALLOWED_FIELDS
        if forbidden & {"principal_id", "actor_id"}:
            raise ValueError("authenticated principal cannot come from candidate data")
        if forbidden & {"image", "image_bytes", "image_data", "raw_image", "frame_bytes",
                        "jpeg", "png", "base64"}:
            raise ValueError("candidate image bytes must not be persisted")
        raise ValueError("candidate contains fields outside the selector metadata contract")
    for field, limit in (("request_id", 160), ("source", 96), ("model_id", 128),
                         ("instruction", 2000), ("provider_interaction_id", 160),
                         ("provider_call_id", 160)):
        if field in document:
            _text(field, document[field], limit=limit)
    source = document.get("source_observation")
    if not isinstance(source, Mapping) or set(source) - _SOURCE_FIELDS:
        raise ValueError("candidate source_observation has unsupported fields")
    for field in _SOURCE_FIELDS - {"image_transform"}:
        if field in source:
            _text(f"source_observation.{field}", source[field],
                  limit=160 if field in {"observation_id", "camera_id", "frame_id"} else 96)
    transform = source.get("image_transform")
    if transform is not None and (
            not isinstance(transform, Mapping) or set(transform) - _TRANSFORM_FIELDS):
        raise ValueError("candidate image transform has unsupported fields")
    for selector_name in ("target_selector", "destination_selector"):
        selector = document.get(selector_name)
        if not isinstance(selector, Mapping) or set(selector) - _SELECTOR_FIELDS:
            raise ValueError(f"candidate {selector_name} has unsupported fields")
        if "label" in selector:
            _text(f"{selector_name}.label", selector["label"], limit=160)
    encoded = _json(document)
    if len(encoded.encode("utf-8")) > _MAX_CANDIDATE_BYTES:
        raise ValueError("candidate metadata exceeds 32 KiB")
    return json.loads(encoded)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _tool_call_digest(call: ModelToolCall) -> str:
    material = f"{call.tool_name}\n{call.ordinal}\n{call.arguments_json}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
