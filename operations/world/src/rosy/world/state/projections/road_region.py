"""D-665: validity of camera-local membership evidence; no geometry or drive policy."""
from __future__ import annotations

from rosy.world.api import ObservationSnapshot, SnapshotValidity


def road_region_input_errors(image: ObservationSnapshot, anchor: ObservationSnapshot, *,
                             now_ns: int, max_age_ns: int) -> tuple[str, ...]:
    if any(type(v) is not int or v <= 0 for v in (now_ns, max_age_ns)):
        raise ValueError("now_ns and max_age_ns must be positive integer nanoseconds")
    if not isinstance(image, ObservationSnapshot) or not isinstance(anchor, ObservationSnapshot):
        raise ValueError("image and anchor must be observation snapshots")
    errors = []
    for name, snapshot in (("image", image), ("anchor", anchor)):
        if snapshot.validity is not SnapshotValidity.VALID:
            errors.append(f"{name}_invalid")
        if snapshot.captured_at_ns > now_ns:
            errors.append(f"{name}_future")
        elif now_ns - snapshot.captured_at_ns > max_age_ns:
            errors.append(f"{name}_stale")
    if image.frame_id != anchor.frame_id:
        errors.append("frame_mismatch")
    if image.calibration_revision != anchor.calibration_revision:
        errors.append("calibration_mismatch")
    if image.transform_revision is None or anchor.transform_revision is None:
        errors.append("transform_unverified")
    elif image.transform_revision != anchor.transform_revision:
        errors.append("transform_mismatch")
    if image.snapshot_id not in anchor.evidence_refs:
        errors.append("image_reference_missing")
    return tuple(errors)
