"""One belt-region reading from one fresh top frame: occupied / empty / unknown. Reads only, moves nothing.

S asks before loading (anything but `empty` holds), A/B before picking (only `occupied` goes); not wired to either yet
(three-arm panel, Rosy/docs/workspace-records/2026-11-13/three-arm-scheduling-panel.md). Whatever the frame cannot prove is
`unknown`: a receipt that is missing or old, a camera not confirmed against its reference frame, an arm state that is
missing or over the belt, a region not wholly in the frame, a container across the region edge, a region not on the seen belt,
or orange in the region the detector did not explain (its size filter drops some contours).
Detection is the existing orange-mask detector; this adds only the gate around it. `occupied` means an orange object of at least
the detector's 250 px floor in the region, not a pickable container: for S that errs safe, and A/B still pick through catalogue
matching (cell_auto_pick), which refuses what it cannot match.
"""
from __future__ import annotations

import math
import time

import numpy as np

from cell_camera_invariant_top import detect_top_containers_invariant, is_arm_clear_of_belt, orange_dual_band_mask

FRESH_S = 2.0  # the camera server's own fresh window, as FifoCell.frame_receipt
INSIDE = 0.85  # a container this much inside the region is in it; anything between 0 and this is edge ambiguity
BELT_DARK = 0.5  # the detector merges orange into the belt outline, so the outline must still be mostly dark belt
STRAY_PX = 30  # an orange blob touching an empty-looking region and larger than this is something the detector dropped, not noise


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


def _dark_fraction(image, outline) -> float:
    """Share of the outline that is dark belt, by the detector's own colour bounds (cell_camera_invariant_top)."""
    import cv2

    hsv, lab = cv2.cvtColor(image, cv2.COLOR_BGR2HSV), cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.int16)
    dark = ((hsv[..., 2] >= 12) & (hsv[..., 2] <= 105) & (hsv[..., 1] <= 165)
            & (np.abs(lab[..., 1] - 128) <= 16) & (np.abs(lab[..., 2] - 128) <= 26))
    inside = np.zeros(image.shape[:2], np.uint8)
    cv2.fillConvexPoly(inside, np.int32(outline), 1)
    return float(dark[inside > 0].mean()) if inside.any() else 0.0


def read_belt_occupancy(receipt: dict | None, roi_px, *, calibration: dict | None, joint_state_norm, now: float | None = None) -> dict:
    """`receipt` is FifoCell.frame_receipt()'s dict; `roi_px` the region's calibrated pixel box (x0, y0, x1, y1), valid only while
    `calibration` (cell_calibrate.check() on this frame) compared against a reference and found the camera unmoved: with no
    reference, check() also says camera_moved False. `joint_state_norm` is arm_s's measured joints: the occlusion table is arm_s's (standby/home),
    so A/B have no proof of a clear view yet and must not call this until theirs is measured."""
    out = {"occupancy": "unknown", "reason": "", "region_px": [float(v) for v in roi_px]}
    if (calibration or {}).get("camera_moved") is True:
        return {**out, "reason": "calibration_moved"}
    if (calibration or {}).get("camera_moved") is not False or not calibration.get("camera_shift") or calibration.get("no_reference"):
        return {**out, "reason": "calibration_unverified"}
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
    belt = seen.get("belt_frame") or {}
    if not belt.get("found"):
        return {**out, "reason": "belt_not_seen"}  # neither reading is proof while the belt itself is not seen
    import cv2

    outline = np.asarray(belt["box_points_px"], np.float32)
    if _dark_fraction(image, outline) < BELT_DARK:
        return {**out, "reason": "belt_not_seen"}
    if any(cv2.pointPolygonTest(outline, corner, False) < 0 for corner in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))):
        return {**out, "reason": "region_off_belt"}
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
    # no detected container touches the region, so any orange blob that does is one the detector dropped;
    # sized by the whole blob, so one reaching in by a few pixels still counts
    count, labels, stats, _ = cv2.connectedComponentsWithStats(orange_dual_band_mask(image, reject_yellow_table=True))
    touching = {int(v) for v in np.unique(labels[int(y0):int(y1), int(x0):int(x1)])} - {0}
    stray = max((int(stats[v, cv2.CC_STAT_AREA]) for v in touching), default=0)
    if stray > STRAY_PX:
        return {**out, "reason": "unexplained_orange", "orange_px": stray}
    return {**out, "occupancy": "empty", "reason": "region_clear"}
