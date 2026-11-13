"""One belt-region reading from one fresh top frame: occupied / empty / unknown. Reads only, moves nothing.

S asks before loading (anything but `empty` holds), A/B before picking (only `occupied` goes); not wired to either yet
(three-arm panel, Rosy/docs/workspace-records/2026-11-13/three-arm-scheduling-panel.md). Whatever the frame cannot prove is
`unknown`: a receipt that is missing or old, a camera whose calibration is not confirmed, an arm state that is missing or
over the belt, a region not wholly in the frame, a container across the region edge, or a belt the detector cannot see.
Detection is the existing orange-mask detector; this adds only the gate around it.
"""
from __future__ import annotations

import math
import time

import numpy as np

from cell_camera_invariant_top import detect_top_containers_invariant, is_arm_clear_of_belt

FRESH_S = 2.0  # the camera server's own fresh window, as FifoCell.frame_receipt
INSIDE = 0.85  # a container this much inside the region is in it; anything between 0 and this is edge ambiguity


def _inside_fraction(blob: dict, roi) -> float:
    import cv2

    x0, y0, x1, y1 = (float(v) for v in roi)
    rect = (tuple(float(v) for v in blob["centroid_px"]), (float(blob["major_px"]), float(blob["minor_px"])), float(blob["theta_img_deg"]))
    region = (((x0 + x1) / 2, (y0 + y1) / 2), (x1 - x0, y1 - y0), 0.0)
    status, points = cv2.rotatedRectangleIntersection(rect, region)
    if status == cv2.INTERSECT_NONE or points is None:
        return 0.0
    # numerator and denominator are both the fitted rectangle, not the contour
    return min(1.0, cv2.contourArea(np.asarray(points, np.float32).reshape(-1, 2)) / max(1.0, rect[1][0] * rect[1][1]))


def read_belt_occupancy(receipt: dict | None, roi_px, *, camera_moved: bool | None, joint_state_norm, now: float | None = None) -> dict:
    """`receipt` is FifoCell.frame_receipt()'s dict; `roi_px` the region's calibrated pixel box (x0, y0, x1, y1), valid only while
    `camera_moved` is exactly False. `joint_state_norm` is arm_s's measured joints: the occlusion table is arm_s's (standby/home),
    so A/B have no proof of a clear view yet and must not call this until theirs is measured."""
    out = {"occupancy": "unknown", "reason": "", "region_px": [float(v) for v in roi_px]}
    if camera_moved is not False:
        return {**out, "reason": "calibration_moved" if camera_moved else "calibration_unverified"}
    if not receipt or receipt.get("image") is None:
        return {**out, "reason": "no_frame"}
    stamp = receipt.get("source_stamp")
    if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= 0:
        return {**out, "reason": "no_source_stamp"}
    age = (time.time() if now is None else now) - stamp
    out.update(source_seq=receipt.get("source_seq"), age_s=round(age, 3))
    if not -0.25 <= age <= FRESH_S:
        return {**out, "reason": "stale_frame"}
    if joint_state_norm is None or len(joint_state_norm) < 5:
        return {**out, "reason": "arm_state_unknown"}
    if not is_arm_clear_of_belt(joint_state_norm):
        return {**out, "reason": "arm_occluding_belt"}
    image = receipt["image"]
    h, w = image.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in roi_px)
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        return {**out, "reason": "roi_out_of_frame"}

    seen = detect_top_containers_invariant(image, joint_state_norm=joint_state_norm, require_arm_clear=True)
    inside, edge = [], []
    for blob in seen.get("containers", []) + seen.get("floor_containers", []):
        fraction = _inside_fraction(blob, roi_px)
        if fraction >= INSIDE:
            inside.append({**blob, "inside": round(fraction, 3)})
        elif fraction > 0:
            edge.append({**blob, "inside": round(fraction, 3)})
    out.update(containers_in_region=inside, edge_containers=edge)
    if inside:
        return {**out, "occupancy": "occupied", "reason": "container_in_region"}
    if edge:
        return {**out, "reason": "container_at_region_edge"}
    if not (seen.get("belt_frame") or {}).get("found"):
        return {**out, "reason": "belt_not_seen"}  # nothing seen is not proof of empty when the belt itself is not seen
    return {**out, "occupancy": "empty", "reason": "region_clear"}
