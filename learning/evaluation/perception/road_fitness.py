"""D-665 paired offline diagnostics; truth is never an input to region estimation."""
from __future__ import annotations

import numpy as np

from control.sensing.perception.learned.road_region import observed_road_region, road_masks
from rosy.world.state.projections.road_region import road_region_input_errors


def _metrics(pred, truth: np.ndarray, shape) -> dict:
    if truth.shape != shape or truth.ndim != 2 or not np.isin(truth, [0, 1, 255]).all():
        raise ValueError("truth must match labels and contain only 0, 1, 255")
    valid = truth != 255
    target = truth == 1
    result = {"valid_truth_pixels": int(valid.sum()), "unknown_truth_pixels": int((~valid).sum()),
              "truth_pixels": int(target.sum()), "scored_pixels": 0, "iou": None,
              "false_positive_pixels": None, "false_negative_pixels": None,
              "outside_false_positive_rate": None, "missed_fraction": None}
    if pred is None:
        return result
    hit = int((pred & target).sum())
    fp = int((pred & valid & ~target).sum())
    fn = int((~pred & target).sum())
    outside = int((valid & ~target).sum())
    result.update(scored_pixels=int(valid.sum()), false_positive_pixels=fp, false_negative_pixels=fn,
                  iou=hit / (hit + fp + fn) if hit + fp + fn else None,
                  outside_false_positive_rate=fp / outside if outside else None,
                  missed_fraction=fn / result["truth_pixels"] if result["truth_pixels"] else None)
    return result


def evaluate_frame(labels, classes, image, anchor, seed_pixels, road_truth, region_truth, *,
                   domain: str, conditions, now_ns: int, max_age_ns: int) -> dict:
    if domain not in ("real", "simulation"):
        raise ValueError("domain must be real or simulation")
    if any(not isinstance(c, str) or not c.strip() for c in conditions):
        raise ValueError("conditions must be named strings")
    road, _ = road_masks(labels, classes)
    errors = road_region_input_errors(image, anchor, now_ns=now_ns, max_age_ns=max_age_ns)
    region, reason = (None, "invalid_inputs") if errors else observed_road_region(labels, classes, seed_pixels)
    surface_metrics = _metrics(road, road_truth, labels.shape)
    region_metrics = _metrics(region, region_truth, labels.shape)
    other = (road_truth == 1) & (region_truth == 0)
    region_metrics.update(other_region_truth_pixels=int(other.sum()),
                          other_region_included_pixels=int((region & other).sum()) if region is not None else None,
                          self_region_missed_pixels=region_metrics["false_negative_pixels"])
    return {"domain": domain, "conditions": sorted(set(conditions)),
            "image_snapshot_id": image.snapshot_id, "anchor_snapshot_id": anchor.snapshot_id,
            "road_surface": surface_metrics, "current_region": region_metrics,
            "region_reason": reason, "input_errors": list(errors), "fitness_verdict": "HOLD"}
