"""D-665: image-local road membership from projected anchors, without drive policy."""
from __future__ import annotations

import cv2
import numpy as np

from .manifest import ROLES, validate_label_semantic


def road_masks(labels: np.ndarray, classes: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Visible road floor and connectivity through explicitly identified road paint."""
    if not isinstance(classes, (list, tuple)) or any(
            not isinstance(c, dict) or c.get("role") not in ROLES for c in classes):
        raise ValueError("classes must be manifest class entries with known roles")
    roads = [c for c in classes if c.get("role") == "drivable"]
    if len(roads) != 1 or roads[0].get("semantic") != "road_surface/1":
        raise ValueError("region logic needs one road_surface/1 drivable class")
    if (not isinstance(labels, np.ndarray) or labels.ndim != 2 or not labels.size
            or not np.issubdtype(labels.dtype, np.integer)):
        raise ValueError("labels must be a non-empty 2D integer image")
    indices = [c.get("index") for c in classes]
    if any(type(i) is not int or i < 0 or i >= 255 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("class indices must be distinct integers in [0, 255)")
    if not np.isin(labels, [*indices, 255]).all():
        raise ValueError("labels contain an undeclared class")
    for c in classes:
        validate_label_semantic(c)
    road = labels == roads[0]["index"]
    paint = [c["index"] for c in classes if c.get("role") == "stop_line"
             or (c.get("name") == "crosswalk" and c.get("role") == "ignore")]
    return road, road | np.isin(labels, paint)


def observed_road_region(labels: np.ndarray, classes: list[dict], seed_pixels) -> tuple[np.ndarray | None, str]:
    road, passable = road_masks(labels, classes)
    if not isinstance(seed_pixels, (list, tuple)):
        raise ValueError("anchors must be a list or tuple of integer (row, col) pixels")
    if not seed_pixels:
        return None, "no_anchor"
    _, components = cv2.connectedComponents(passable.astype(np.uint8), connectivity=4)
    ids = set()
    for point in seed_pixels:
        if (not isinstance(point, (list, tuple)) or len(point) != 2 or any(isinstance(v, (bool, np.bool_))
                                  or not isinstance(v, (int, np.integer)) for v in point)):
            raise ValueError("anchors must be integer (row, col) pixels")
        row, col = point
        if not (0 <= row < labels.shape[0] and 0 <= col < labels.shape[1]):
            return None, "anchor_out_of_frame"
        component = int(components[row, col])
        if not component:
            return None, "anchor_not_on_observed_road"
        ids.add(component)
    if len(ids) != 1:
        return None, "ambiguous_region"
    return (components == next(iter(ids))) & road, "ok"
