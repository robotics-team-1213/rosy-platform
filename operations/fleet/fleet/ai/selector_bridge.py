"""Resolve ER 2 image selectors against candidates from the same camera frame.

The bridge produces pixel-level identity evidence only. It does not infer a 3D
pose, grasp, trajectory, or physical completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any

from core_common.protocol.schemas import ResolvedTargetEvidence

from .candidate import ImageTransform, PickPlaceProposalCandidate, SpatialSelector

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class TargetResolutionError(ValueError):
    """The selector cannot be resolved to one fresh, matching observation candidate."""


@dataclass(frozen=True)
class ResolvedPickPlaceCandidate:
    source: ResolvedTargetEvidence
    destination: ResolvedTargetEvidence


def _source_xy(x: float, y: float, transform: ImageTransform) -> tuple[float, float]:
    """Invert resize, clockwise quarter-turn, and crop using pixel-edge coordinates."""
    turns = transform.rotation_quadrants_clockwise
    if turns == 1:
        x, y = y, transform.model_height - x
    elif turns == 2:
        x, y = transform.model_width - x, transform.model_height - y
    elif turns == 3:
        x, y = transform.model_width - y, x
    crop_x1, crop_y1, crop_x2, crop_y2 = transform.crop_xyxy
    x = crop_x1 + x * (crop_x2 - crop_x1) / transform.model_width
    y = crop_y1 + y * (crop_y2 - crop_y1) / transform.model_height
    return x, y


def _resolve_selector(selector: SpatialSelector, transform: ImageTransform,
                      observation: Any) -> tuple[str, tuple[float, ...]]:
    model_width, model_height = transform.model_canvas_size
    if selector.point_yx_1000 is not None:
        y_norm, x_norm = selector.point_yx_1000
        x, y = _source_xy(x_norm * model_width / 1000, y_norm * model_height / 1000, transform)
        kind = "point"
        value = (x, y)
    else:
        y1_norm, x1_norm, y2_norm, x2_norm = selector.box_yxyx_1000
        corners = [
            _source_xy(x1_norm * model_width / 1000, y1_norm * model_height / 1000, transform),
            _source_xy(x2_norm * model_width / 1000, y1_norm * model_height / 1000, transform),
            _source_xy(x1_norm * model_width / 1000, y2_norm * model_height / 1000, transform),
            _source_xy(x2_norm * model_width / 1000, y2_norm * model_height / 1000, transform),
        ]
        xs, ys = [point[0] for point in corners], [point[1] for point in corners]
        kind = "bbox"
        value = (min(xs), min(ys), max(xs), max(ys))
    return kind, value


def _check_provenance(candidate: PickPlaceProposalCandidate,
                      observation: Any) -> ImageTransform:
    transform = candidate.source_image_transform
    if transform is None:
        raise TargetResolutionError("source image transform is required to resolve ER 2 selectors")
    if (candidate.source_observation_id != observation.observation_id
            or candidate.source_camera_id != observation.camera_identity
            or candidate.source_frame_id != observation.optical_frame_id
            or candidate.source_image_sha256 != observation.frame_sha256):
        raise TargetResolutionError(
            "ER 2 proposal observation, camera, frame, or image digest does not match provenance"
        )
    if (candidate.source_calibration_revision != observation.calibration_revision
            or candidate.source_transform_revision != observation.transform_revision):
        raise TargetResolutionError("ER 2 proposal calibration or transform revision does not match")
    try:
        captured = datetime.fromisoformat(candidate.source_observed_at.replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("timestamp is timezone-naive")
        captured = captured.astimezone(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        elapsed = captured - epoch
        captured_ns = (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + elapsed.microseconds * 1_000
    except (TypeError, ValueError, OverflowError) as exc:
        raise TargetResolutionError("ER 2 capture timestamp is invalid") from exc
    if captured_ns != observation.capture_time_ns:
        raise TargetResolutionError("ER 2 capture timestamp does not match the camera observation")
    if (transform.source_width != observation.width
            or transform.source_height != observation.height):
        raise TargetResolutionError("ER 2 transform source dimensions do not match the camera observation")
    return transform


def _resolve_one(selector: SpatialSelector, transform: ImageTransform,
                 observation: Any, candidates: list[Any],
                 *, now: float, max_frame_age_s: float) -> ResolvedTargetEvidence:
    if not _SHA256.fullmatch(observation.frame_sha256) or not observation.transform_revision.strip():
        raise TargetResolutionError("observation digest or transform revision is invalid")
    if (not math.isfinite(float(now)) or not math.isfinite(float(max_frame_age_s))
            or max_frame_age_s <= 0 or now < observation.received_at
            or now - observation.received_at > max_frame_age_s):
        raise TargetResolutionError("observation is stale or freshness is invalid")
    kind, value = _resolve_selector(selector, transform, observation)
    if kind == "point":
        x, y = value
        if not (0 <= x < observation.width and 0 <= y < observation.height):
            raise TargetResolutionError("point selector exceeds the source observation")
    else:
        x1, y1, x2, y2 = value
        if not (0 <= x1 < x2 <= observation.width and 0 <= y1 < y2 <= observation.height):
            raise TargetResolutionError("bbox selector exceeds the source observation")
    frame_candidates = [item for item in candidates
                        if item.observation_id == observation.observation_id]
    if not frame_candidates:
        raise TargetResolutionError("object candidates belong to a different source observation")
    if kind == "point":
        x, y = value
        matches = [item for item in frame_candidates
                   if item.bbox_xyxy[0] <= x < item.bbox_xyxy[2]
                   and item.bbox_xyxy[1] <= y < item.bbox_xyxy[3]]
    else:
        x1, y1, x2, y2 = value
        scored = []
        for item in frame_candidates:
            bx1, by1, bx2, by2 = item.bbox_xyxy
            intersection = max(0.0, min(x2, bx2) - max(x1, bx1)) * max(
                0.0, min(y2, by2) - max(y1, by1)
            )
            if intersection:
                area = (bx2 - bx1) * (by2 - by1) + (x2 - x1) * (y2 - y1) - intersection
                scored.append((item, intersection / area))
        if not scored:
            matches = []
        else:
            best = max(score for _, score in scored)
            matches = [item for item, score in scored if math.isclose(score, best, rel_tol=0, abs_tol=1e-12)]
    if not matches:
        raise TargetResolutionError("selector did not match an observed object")
    if len(matches) != 1:
        raise TargetResolutionError("selector is ambiguous across observed objects")
    selected = matches[0]
    if selected.label.casefold() != selector.label.casefold():
        raise TargetResolutionError("ER 2 selector label does not match the spatially selected object")
    x1, y1, x2, y2 = selected.bbox_xyxy
    if not (0 <= x1 < x2 <= observation.width and 0 <= y1 < y2 <= observation.height):
        raise TargetResolutionError("object candidate bounds exceed the source observation")
    return ResolvedTargetEvidence(
        object_id=selected.object_id,
        observation_id=observation.observation_id,
        frame_sha256=observation.frame_sha256,
        camera_identity=observation.camera_identity,
        optical_frame_id=observation.optical_frame_id,
        calibration_revision=observation.calibration_revision,
        transform_revision=observation.transform_revision,
        capture_time_ns=observation.capture_time_ns,
        selector_kind=kind,
        image_bbox_xyxy=selected.bbox_xyxy,
    )


def resolve_pick_place_candidate(
    candidate: PickPlaceProposalCandidate,
    observation: Any,
    objects: list[Any],
    *,
    now: float,
    max_frame_age_s: float,
) -> ResolvedPickPlaceCandidate:
    """Resolve both selectors against one fresh, exact source observation."""
    transform = _check_provenance(candidate, observation)
    if objects and not any(item.observation_id == observation.observation_id for item in objects):
        raise TargetResolutionError("object candidates belong to a different source observation")
    source = _resolve_one(candidate.target, transform, observation, objects,
                          now=now, max_frame_age_s=max_frame_age_s)
    destination = _resolve_one(candidate.destination, transform, observation, objects,
                               now=now, max_frame_age_s=max_frame_age_s)
    if source.object_id == destination.object_id:
        raise TargetResolutionError("ER 2 source and destination must resolve to distinct objects")
    return ResolvedPickPlaceCandidate(source=source, destination=destination)
