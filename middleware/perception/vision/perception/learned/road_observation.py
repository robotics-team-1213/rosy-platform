"""D-670 internal road observations; no truth, destination, transport or actuation."""
from copy import deepcopy

import numpy as np

from core_common.observation import road_region_input_errors
from .road_region import observed_road_region, road_masks


def observe_model_frame(model, bgr, image, anchor, seed_pixels, *, now_ns: int, max_age_ns: int) -> dict:
    if (not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] != 3
            or not bgr.size or bgr.dtype != np.uint8):
        raise ValueError("expected a non-empty uint8 HxWx3 BGR frame")
    if not isinstance(seed_pixels, (list, tuple)) or any(
            not isinstance(p, (list, tuple)) or len(p) != 2 or any(
                isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) for v in p)
            for p in seed_pixels):
        raise ValueError("anchors must be integer (row, col) pixels")
    if model.manifest.task != "lane_seg":
        raise ValueError("road observation needs a lane_seg model")
    classes = model.manifest.raw["output"]["classes"]
    road_masks(np.full((1, 1), 255, np.uint8), classes)
    errors = road_region_input_errors(image, anchor, now_ns=now_ns, max_age_ns=max_age_ns)
    spec = model.manifest.input
    height = spec.crop[0] if spec.crop is not None else spec.height
    lo, hi = spec.crop[2:] if spec.crop is not None else (0, height)
    seeds = [[int(np.floor((r + .5) * height / bgr.shape[0])),
              int(np.floor((c + .5) * spec.width / bgr.shape[1]))] for r, c in seed_pixels]
    labels = road = region = latency = None
    reason = "invalid_inputs"
    if not any(e in ("image_invalid", "image_stale", "image_future") for e in errors):
        labels, latency = model.infer_road_surface(bgr)
        road, _ = road_masks(labels, classes)
        if not errors:
            region, reason = observed_road_region(labels, classes, seeds)
    return {"labels": labels, "road_surface": road, "current_region": region,
            "region_reason": reason, "input_errors": errors,
            "image_snapshot_id": image.snapshot_id, "anchor_snapshot_id": anchor.snapshot_id,
            "model_revision": model.model_revision,
            "camera_profile_revision": model.manifest.camera_profile_revision,
            "preprocessing": {"input": deepcopy(model.manifest.raw["input"]),
                              "source_shape": list(bgr.shape[:2]), "prediction_shape": [height, spec.width],
                              "predicted_rows": [lo, hi], "seed_pixels": seeds},
            "infer_latency_ms": latency, "fitness_verdict": "HOLD"}
