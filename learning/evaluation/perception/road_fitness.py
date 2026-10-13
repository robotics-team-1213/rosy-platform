"""D-665 paired offline diagnostics; truth is never an input to region estimation."""
from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from control.sensing.perception.learned.road_region import observed_road_region, road_masks
from core_common.observation import road_region_input_errors


def _boundary_metrics(pred, target, valid) -> dict:
    cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8)
    known = cv2.erode(valid.astype(np.uint8), cross, borderType=cv2.BORDER_CONSTANT,
                      borderValue=0).astype(bool)
    def boundary(mask):
        return mask & ~cv2.erode(mask.astype(np.uint8), cross, borderType=cv2.BORDER_CONSTANT,
                                borderValue=0).astype(bool)
    raw_truth = boundary(target)
    expected = raw_truth & known
    raw_predicted = boundary(pred) if pred is not None else np.zeros_like(target)
    actual = raw_predicted & known
    nt, npred = int(expected.sum()), int(actual.sum())
    result = {"boundary_truth_pixels": nt, "boundary_predicted_pixels": npred,
              "boundary_excluded_truth_pixels": int((raw_truth & ~known).sum()),
              "boundary_excluded_predicted_pixels": int((raw_predicted & ~known).sum()),
              "boundary_distance_sum_px": None, "boundary_mean_error_px": None}
    if pred is None:
        status = "abstained"
    elif not nt and not npred:
        status = "no_known_boundary"
    elif not npred:
        status = "missing_predicted_boundary"
    elif not nt:
        status = "missing_truth_boundary"
    else:
        to_actual = cv2.distanceTransform((~actual).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        to_expected = cv2.distanceTransform((~expected).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        distance = float(to_actual[expected].sum(dtype=np.float64) +
                         to_expected[actual].sum(dtype=np.float64))
        result.update(boundary_distance_sum_px=distance, boundary_mean_error_px=distance / (nt + npred))
        status = "ok"
    return {**result, "boundary_status": status}


def _metrics(pred, truth: np.ndarray, shape) -> dict:
    if truth.shape != shape or truth.ndim != 2 or not np.isin(truth, [0, 1, 255]).all():
        raise ValueError("truth must match labels and contain only 0, 1, 255")
    valid = truth != 255
    target = truth == 1
    result = {"valid_truth_pixels": int(valid.sum()), "unknown_truth_pixels": int((~valid).sum()),
              "truth_pixels": int(target.sum()), "outside_truth_pixels": int((valid & ~target).sum()),
              "roi_excluded_valid_truth_pixels": 0, "roi_excluded_target_truth_pixels": 0,
              "prediction_available": pred is not None, "scored_pixels": 0,
              "scored_truth_pixels": 0, "scored_outside_truth_pixels": 0,
              "true_positive_pixels": None, "iou": None,
              "false_positive_pixels": None, "false_negative_pixels": None,
              "outside_false_positive_rate": None, "missed_fraction": None,
              **_boundary_metrics(pred, target, valid)}
    if pred is None:
        return result
    hit = int((pred & target).sum())
    fp = int((pred & valid & ~target).sum())
    fn = int((~pred & target).sum())
    outside = int((valid & ~target).sum())
    result.update(scored_pixels=int(valid.sum()), scored_truth_pixels=int(target.sum()),
                  scored_outside_truth_pixels=outside, true_positive_pixels=hit,
                  false_positive_pixels=fp, false_negative_pixels=fn,
                  iou=hit / (hit + fp + fn) if hit + fp + fn else None,
                  outside_false_positive_rate=fp / outside if outside else None,
                  missed_fraction=fn / result["truth_pixels"] if result["truth_pixels"] else None)
    return result


def evaluate_frame(labels, classes, image, anchor, seed_pixels, road_truth, region_truth, *,
                   domain: str, conditions, now_ns: int, max_age_ns: int) -> dict:
    if domain not in ("real", "simulation"):
        raise ValueError("domain must be real or simulation")
    if not isinstance(conditions, (list, tuple)) or any(
            not isinstance(c, str) or not c.strip() for c in conditions):
        raise ValueError("conditions must be named strings")
    road, _ = road_masks(labels, classes)
    errors = road_region_input_errors(image, anchor, now_ns=now_ns, max_age_ns=max_age_ns)
    region, reason = (None, "invalid_inputs") if errors else observed_road_region(labels, classes, seed_pixels)
    surface_metrics = _metrics(None if any(e in ("image_invalid", "image_stale", "image_future") for e in errors) else road,
                               road_truth, labels.shape)
    region_metrics = _metrics(region, region_truth, labels.shape)
    if ((region_truth == 1) & (road_truth == 0)).any():
        raise ValueError("current region truth lies outside declared road truth")
    other = (road_truth == 1) & (region_truth == 0)
    region_metrics.update(other_region_truth_pixels=int(other.sum()),
                          scored_other_region_truth_pixels=int(other.sum()) if region is not None else 0,
                          other_region_included_pixels=int((region & other).sum()) if region is not None else None,
                          self_region_missed_pixels=region_metrics["false_negative_pixels"])
    return {"domain": domain, "conditions": sorted(set(conditions)),
            "image_snapshot_id": image.snapshot_id, "anchor_snapshot_id": anchor.snapshot_id,
            "road_surface": surface_metrics, "current_region": region_metrics,
            "region_reason": reason, "input_errors": list(errors), "fitness_verdict": "HOLD"}


def evaluate_model_frame(model, bgr, image, anchor, seed_pixels, road_truth, region_truth, *,
                         domain: str, conditions, now_ns: int, max_age_ns: int) -> dict:
    """Replay an opened model; truth and anchors use the original camera image grid."""
    if (not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] != 3
            or not bgr.size or bgr.dtype != np.uint8):
        raise ValueError("expected a non-empty uint8 HxWx3 BGR frame")
    if model.manifest.task != "lane_seg":
        raise ValueError("road replay needs a lane_seg model")
    if not isinstance(seed_pixels, (list, tuple)) or any(
            not isinstance(p, (list, tuple)) or len(p) != 2 or any(
                isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) for v in p)
            for p in seed_pixels):
        raise ValueError("anchors must be integer (row, col) pixels")
    spec = model.manifest.input
    height = spec.crop[0] if spec.crop is not None else spec.height
    lo, hi = spec.crop[2:] if spec.crop is not None else (0, height)
    truth_masks, excluded, excluded_targets = [], {}, {}
    for name, truth in (("road_surface", road_truth), ("current_region", region_truth)):
        _metrics(None, truth, bgr.shape[:2])
        resized = cv2.resize(truth.astype(np.uint8), (spec.width, height), interpolation=cv2.INTER_NEAREST)
        outside = np.ones(resized.shape, dtype=bool)
        outside[lo:hi] = False
        excluded[name] = int((outside & (resized != 255)).sum())
        excluded_targets[name] = int((outside & (resized == 1)).sum())
        resized[outside] = 255
        truth_masks.append(resized)
    if ((region_truth == 1) & (road_truth == 0)).any():
        raise ValueError("current region truth lies outside declared road truth")
    labels, _ = model.infer_road_surface(bgr)
    classes = model.manifest.raw["output"]["classes"]
    seeds = [[int(np.floor((r + .5) * height / bgr.shape[0])),
              int(np.floor((c + .5) * spec.width / bgr.shape[1]))] for r, c in seed_pixels]
    report = evaluate_frame(labels, classes, image, anchor, seeds, *truth_masks, domain=domain,
                            conditions=conditions, now_ns=now_ns, max_age_ns=max_age_ns)
    for name in excluded:
        # Known truth outside the predicted ROI is excluded, not unknown ground truth.
        report[name]["unknown_truth_pixels"] -= excluded[name]
        report[name].update(roi_excluded_valid_truth_pixels=excluded[name],
                            roi_excluded_target_truth_pixels=excluded_targets[name])
    report.update(model_revision=model.model_revision,
                  preprocessing={"source_shape": list(bgr.shape[:2]), "evaluation_shape": [height, spec.width],
                                 "predicted_rows": [lo, hi], "seed_pixels": seeds,
                                 "excluded_truth_pixels": excluded})
    return report


def _summarize(rows) -> dict:
    result = {"frames": len(rows), "unconditioned_frames": sum(not r["conditions"] for r in rows),
              "region_reasons": dict(Counter(r["region_reason"] for r in rows)),
              "input_errors": dict(Counter(e for r in rows for e in r["input_errors"]))}
    for target in ("road_surface", "current_region"):
        metrics = [r[target] for r in rows]
        counts = {k: sum(m[k] or 0 for m in metrics) for k in (
            "valid_truth_pixels", "unknown_truth_pixels", "truth_pixels", "outside_truth_pixels",
            "roi_excluded_valid_truth_pixels", "roi_excluded_target_truth_pixels",
            "scored_pixels", "scored_truth_pixels", "scored_outside_truth_pixels",
            "true_positive_pixels", "false_positive_pixels", "false_negative_pixels",
            "boundary_truth_pixels", "boundary_predicted_pixels", "boundary_excluded_truth_pixels",
            "boundary_excluded_predicted_pixels")}
        if target == "current_region":
            counts.update({k: sum(m[k] or 0 for m in metrics) for k in (
                "other_region_truth_pixels", "scored_other_region_truth_pixels",
                "other_region_included_pixels", "self_region_missed_pixels")})
        tp, fp, fn = (counts[k] for k in ("true_positive_pixels", "false_positive_pixels", "false_negative_pixels"))
        predicted = sum(m["prediction_available"] for m in metrics)
        scored = sum(m["scored_pixels"] > 0 for m in metrics)
        paired = [m for m in metrics if m["boundary_status"] == "ok"]
        boundary_pixels = sum(m["boundary_truth_pixels"] + m["boundary_predicted_pixels"] for m in paired)
        full_grid_valid = counts["valid_truth_pixels"] + counts["roi_excluded_valid_truth_pixels"]
        counts.update(prediction_frames=predicted, scored_frames=scored, abstained_frames=len(rows) - predicted,
                      unscorable_truth_frames=sum(m["prediction_available"] and not m["valid_truth_pixels"]
                                                 for m in metrics),
                      frame_coverage=scored / len(rows) if rows else None,
                      pixel_coverage=counts["scored_pixels"] / counts["valid_truth_pixels"]
                      if counts["valid_truth_pixels"] else None,
                      full_grid_pixel_coverage=counts["scored_pixels"] / full_grid_valid if full_grid_valid else None,
                      truth_pixel_coverage=counts["scored_truth_pixels"] / counts["truth_pixels"]
                      if counts["truth_pixels"] else None,
                      iou=tp / (tp + fp + fn) if tp + fp + fn else None,
                      outside_false_positive_rate=fp / counts["scored_outside_truth_pixels"]
                      if counts["scored_outside_truth_pixels"] else None,
                      missed_fraction=fn / counts["scored_truth_pixels"] if counts["scored_truth_pixels"] else None,
                      boundary_scored_frames=len(paired),
                      boundary_scored_pixels=boundary_pixels,
                      boundary_distance_sum_px=sum(m["boundary_distance_sum_px"] for m in paired),
                      boundary_statuses=dict(Counter(m["boundary_status"] for m in metrics)),
                      boundary_mean_error_px=sum(m["boundary_distance_sum_px"] for m in paired) / boundary_pixels
                      if boundary_pixels else None)
        result[target] = counts
    return result


def summarize_frames(reports) -> dict:
    """Aggregate evaluate_frame results without pooling real and simulation evidence."""
    rows = list(reports)
    if any(r["domain"] not in ("real", "simulation") for r in rows):
        raise ValueError("domain must be real or simulation")
    domains, conditions = {}, {}
    for domain in ("real", "simulation"):
        selected = [r for r in rows if r["domain"] == domain]
        domains[domain] = _summarize(selected)
        conditions[domain] = {c: _summarize([r for r in selected if c in r["conditions"]])
                              for c in sorted({c for r in selected for c in r["conditions"]})}
    return {"domains": domains, "conditions": conditions, "fitness_verdict": "HOLD"}
