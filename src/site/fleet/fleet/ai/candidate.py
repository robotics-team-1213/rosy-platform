"""Typed, provenance-carrying proposals returned by embodied models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping


class ER2ProposalError(ValueError):
    """The model response is not a valid, unambiguous Fleet proposal."""


def _text(name: str, value: Any, *, limit: int = 160) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ER2ProposalError(
            f"{name} must be a non-empty trimmed string no longer than {limit} characters"
        )
    return value


@dataclass(frozen=True)
class ImageObservation:
    observation_id: str
    camera_id: str
    frame_id: str
    observed_at: str
    image_bytes: bytes
    mime_type: str = "image/jpeg"

    def __post_init__(self) -> None:
        _text("observation_id", self.observation_id)
        _text("camera_id", self.camera_id)
        _text("frame_id", self.frame_id)
        _text("observed_at", self.observed_at)
        if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
            raise ER2ProposalError("image_bytes must be non-empty bytes")
        if len(self.image_bytes) > 14 * 1024 * 1024:
            raise ER2ProposalError("image frame exceeds the 14 MiB inline input budget")
        if self.mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ER2ProposalError("image mime_type must be JPEG, PNG, or WebP")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.image_bytes).hexdigest()


@dataclass(frozen=True)
class SpatialSelector:
    label: str
    point_yx_1000: tuple[int, int] | None = None
    box_yxyx_1000: tuple[int, int, int, int] | None = None

    @classmethod
    def from_mapping(cls, name: str, raw: Any) -> "SpatialSelector":
        if not isinstance(raw, Mapping):
            raise ER2ProposalError(f"{name} selector must be an object")
        allowed = {"label", "point_yx_1000", "box_yxyx_1000"}
        if set(raw) - allowed or "label" not in raw:
            raise ER2ProposalError(f"{name} selector has unexpected or missing fields")
        label = _text(f"{name}.label", raw["label"])
        point = raw.get("point_yx_1000")
        box = raw.get("box_yxyx_1000")
        if (point is None) == (box is None):
            raise ER2ProposalError(f"{name} selector requires exactly one point or box")
        if point is not None:
            point = _coordinates(f"{name}.point_yx_1000", point, 2)
            return cls(label=label, point_yx_1000=point)
        box = _coordinates(f"{name}.box_yxyx_1000", box, 4)
        if box[0] > box[2] or box[1] > box[3]:
            raise ER2ProposalError(f"{name} box corners are reversed")
        return cls(label=label, box_yxyx_1000=box)


def _coordinates(name: str, value: Any, length: int) -> tuple[int, ...]:
    if (not isinstance(value, (list, tuple)) or len(value) != length
            or any(type(item) is not int or not 0 <= item <= 1000 for item in value)):
        raise ER2ProposalError(f"{name} must contain {length} integers from 0 to 1000")
    return tuple(value)


@dataclass(frozen=True)
class PickPlaceProposalCandidate:
    request_id: str
    provider_interaction_id: str
    provider_call_id: str
    model_id: str
    instruction: str
    source_observation_id: str
    source_camera_id: str
    source_frame_id: str
    source_observed_at: str
    source_image_sha256: str
    target: SpatialSelector
    destination: SpatialSelector

    @classmethod
    def from_function_call(
        cls,
        *,
        request_id: Any,
        interaction_id: Any,
        call_id: Any,
        name: Any,
        arguments: Any,
        instruction: Any,
        observation: ImageObservation,
        model_id: str,
    ) -> "PickPlaceProposalCandidate":
        if name != "propose_pick_place":
            raise ER2ProposalError(
                "model requested a function outside the Fleet proposal allowlist"
            )
        if not isinstance(arguments, Mapping) or set(arguments) != {"target", "destination"}:
            raise ER2ProposalError("proposal arguments must contain only target and destination")
        return cls(
            request_id=_text("request_id", request_id, limit=128),
            provider_interaction_id=_text("interaction_id", interaction_id),
            provider_call_id=_text("provider_call_id", call_id),
            model_id=model_id,
            instruction=_text("instruction", instruction, limit=2000),
            source_observation_id=observation.observation_id,
            source_camera_id=observation.camera_id,
            source_frame_id=observation.frame_id,
            source_observed_at=observation.observed_at,
            source_image_sha256=observation.sha256,
            target=SpatialSelector.from_mapping("target", arguments["target"]),
            destination=SpatialSelector.from_mapping("destination", arguments["destination"]),
        )

    @property
    def request_key(self) -> str:
        """Stable caller identity for a later idempotent Fleet proposal write."""
        return f"gemini-er2:{self.request_id}"

    def to_candidate_record(self) -> dict[str, Any]:
        """Return unresolved image selectors; this is not a Fleet Mission or device plan."""
        return {
            "request_id": self.request_id,
            "source": "gemini_robotics_er2",
            "model_id": self.model_id,
            "instruction": self.instruction,
            "provider_interaction_id": self.provider_interaction_id,
            "provider_call_id": self.provider_call_id,
            "source_observation": {
                "observation_id": self.source_observation_id,
                "camera_id": self.source_camera_id,
                "frame_id": self.source_frame_id,
                "observed_at": self.source_observed_at,
                "image_sha256": self.source_image_sha256,
                "coordinate_space": "image_normalized_yx_0_1000",
            },
            "target_selector": _selector_dict(self.target),
            "destination_selector": _selector_dict(self.destination),
        }


def _selector_dict(selector: SpatialSelector) -> dict[str, Any]:
    return {
        "label": selector.label,
        "point_yx_1000": list(selector.point_yx_1000) if selector.point_yx_1000 else None,
        "box_yxyx_1000": list(selector.box_yxyx_1000) if selector.box_yxyx_1000 else None,
    }
