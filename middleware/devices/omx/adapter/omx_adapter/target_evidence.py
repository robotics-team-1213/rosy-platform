"""Resolve an operator/model selector to one observed object candidate.

This module handles identity at image-pixel level only. It does not estimate a
3D pose, grasp, reachable trajectory, object ownership, or physical success.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from .camera_contract import CameraFrameMetadata

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SELECTOR_KINDS = {"object_id", "inventory_id", "label", "relation", "point", "bbox"}


class TargetResolutionError(ValueError):
    """The selector cannot be resolved to exactly one fresh observed object."""


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value


def _box(name: str, value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError(f"{name} must contain x_min, y_min, x_max, y_max")
    if any(isinstance(item, bool) for item in value):
        raise ValueError(f"{name} coordinates must be finite numbers")
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} coordinates must be finite numbers") from exc
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)) or x1 >= x2 or y1 >= y2:
        raise ValueError(f"{name} must have finite increasing coordinates")
    return x1, y1, x2, y2


@dataclass(frozen=True)
class ObjectCandidate:
    observation_id: str
    object_id: str
    label: str
    descriptors: tuple[str, ...]
    bbox_xyxy: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        _text("observation_id", self.observation_id)
        _text("object_id", self.object_id)
        _text("label", self.label)
        descriptors = tuple(self.descriptors)
        if any(not isinstance(item, str) or not item.strip() or item != item.strip()
               for item in descriptors):
            raise ValueError("descriptors must contain non-empty trimmed strings")
        object.__setattr__(self, "descriptors", descriptors)
        object.__setattr__(self, "bbox_xyxy", _box("bbox_xyxy", self.bbox_xyxy))


@dataclass(frozen=True)
class TargetSelector:
    kind: Literal["object_id", "inventory_id", "label", "relation", "point", "bbox"]
    value: str | tuple[float, float] | tuple[float, float, float, float]
    observation_id: str
    coordinate_space: str = "observation_pixels"

    def __post_init__(self) -> None:
        if self.kind not in _SELECTOR_KINDS:
            raise ValueError("unsupported selector kind")
        _text("observation_id", self.observation_id)
        if self.coordinate_space != "observation_pixels":
            raise ValueError("coordinate_space must be observation_pixels")
        if self.kind in {"object_id", "inventory_id", "label", "relation"}:
            _text("selector value", self.value)
        elif self.kind == "point":
            if (not isinstance(self.value, (tuple, list)) or len(self.value) != 2
                    or any(isinstance(item, bool) for item in self.value)):
                raise ValueError("point selector requires two finite pixel coordinates")
            try:
                point = tuple(float(item) for item in self.value)
            except (TypeError, ValueError) as exc:
                raise ValueError("point selector requires two finite pixel coordinates") from exc
            if not all(math.isfinite(item) for item in point):
                raise ValueError("point selector requires two finite pixel coordinates")
            object.__setattr__(self, "value", point)
        else:
            object.__setattr__(self, "value", _box("bbox selector", self.value))


@dataclass(frozen=True)
class TargetEvidence:
    object_id: str
    observation_id: str
    frame_sha256: str
    camera_identity: str
    optical_frame_id: str
    calibration_revision: str
    transform_revision: str
    capture_time_ns: int
    selector_kind: str
    image_bbox_xyxy: tuple[float, float, float, float]


def _iou(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    ix1, iy1 = max(left[0], right[0]), max(left[1], right[1])
    ix2, iy2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if intersection == 0.0:
        return 0.0
    area_left = (left[2] - left[0]) * (left[3] - left[1])
    area_right = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / (area_left + area_right - intersection)


def _matches(candidates: list[ObjectCandidate], selector: TargetSelector) -> list[ObjectCandidate]:
    value = selector.value
    if selector.kind in {"object_id", "inventory_id"}:
        return [candidate for candidate in candidates if candidate.object_id == value]
    if selector.kind == "label":
        normalized = value.casefold()
        return [candidate for candidate in candidates if candidate.label.casefold() == normalized]
    if selector.kind == "relation":
        normalized = value.casefold()
        return [candidate for candidate in candidates
                if any(item.casefold() == normalized for item in candidate.descriptors)]
    if selector.kind == "point":
        x, y = value
        return [candidate for candidate in candidates
                if candidate.bbox_xyxy[0] <= x < candidate.bbox_xyxy[2]
                and candidate.bbox_xyxy[1] <= y < candidate.bbox_xyxy[3]]
    scored = [(candidate, _iou(candidate.bbox_xyxy, value)) for candidate in candidates]
    positive = [(candidate, score) for candidate, score in scored if score > 0.0]
    if not positive:
        return []
    best = max(score for _, score in positive)
    return [candidate for candidate, score in positive if math.isclose(score, best, rel_tol=0, abs_tol=1e-12)]


def resolve_target(observation: CameraFrameMetadata, candidates: list[ObjectCandidate],
                   selector: TargetSelector, *, now: float,
                   max_frame_age_s: float) -> TargetEvidence:
    """Return pixel-level identity evidence only for exactly one fresh candidate."""
    if not _SHA256.fullmatch(observation.frame_sha256):
        raise TargetResolutionError("observation frame digest is missing or invalid")
    if not observation.transform_revision.strip():
        raise TargetResolutionError("observation transform revision is missing")
    try:
        current = float(now)
        age_limit = float(max_frame_age_s)
    except (TypeError, ValueError) as exc:
        raise TargetResolutionError("observation freshness values are invalid") from exc
    age = current - observation.received_at
    if (isinstance(now, bool) or isinstance(max_frame_age_s, bool)
            or not math.isfinite(current) or not math.isfinite(age_limit) or age_limit <= 0
            or age < 0 or age > age_limit):
        raise TargetResolutionError("observation is stale or its freshness is invalid")
    if selector.observation_id != observation.observation_id:
        raise TargetResolutionError("selector observation does not match current observation")
    if selector.kind == "point":
        x, y = selector.value
        if not (0 <= x < observation.width and 0 <= y < observation.height):
            raise TargetResolutionError("point selector exceeds the source observation")
    elif selector.kind == "bbox":
        x1, y1, x2, y2 = selector.value
        if not (0 <= x1 < x2 <= observation.width and 0 <= y1 < y2 <= observation.height):
            raise TargetResolutionError("bbox selector exceeds the source observation")
    current_candidates = [item for item in candidates
                          if item.observation_id == observation.observation_id]
    matches = _matches(current_candidates, selector)
    if not matches:
        raise TargetResolutionError("selector did not match an observed object")
    if len(matches) != 1:
        raise TargetResolutionError("selector is ambiguous across observed objects")
    selected = matches[0]
    x1, y1, x2, y2 = selected.bbox_xyxy
    if not (0 <= x1 < x2 <= observation.width and 0 <= y1 < y2 <= observation.height):
        raise TargetResolutionError("candidate bounds exceed the source observation")
    return TargetEvidence(
        object_id=selected.object_id,
        observation_id=observation.observation_id,
        frame_sha256=observation.frame_sha256,
        camera_identity=observation.camera_identity,
        optical_frame_id=observation.optical_frame_id,
        calibration_revision=observation.calibration_revision,
        transform_revision=observation.transform_revision,
        capture_time_ns=observation.capture_time_ns,
        selector_kind=selector.kind,
        image_bbox_xyxy=selected.bbox_xyxy,
    )
