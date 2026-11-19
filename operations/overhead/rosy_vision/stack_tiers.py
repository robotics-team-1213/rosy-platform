"""Container tier count (1 or 2) from the front camera: height of the orange blob against the height each
tier count would have at the measured distance. Rule based; abstains whenever the picture is not clear.
Vision owns it (D-136 3: Fleet decodes no image); Fleet's pipeline_observer takes only its JSON verdict through
app.state.observer_judge. Not wired to a Vision endpoint yet, so the Fleet look skips NO_JUDGE."""
import math

import cv2
import numpy as np

ORANGE_HSV = ((8, 90, 70), (22, 255, 255))  # OpenCV H 8..22 is "orange" in cell_object_pose.colour_name
DIST_RANGE_M = (0.10, 0.60)
MIN_MARGIN = 0.25
MIN_BLOB_PX = 30


def _abstain(reason, evidence=None):
    return {"tiers": None, "confidence": 0.0, "evidence": {"abstain": reason, **(evidence or {})}}


def classify_tiers(img_bgr, cam, dist_m, *, hsv=None, tier_mm=(30.0, 65.0)):
    """cam: {hfov_rad, width, height}. tier_mm: container height for 1 and 2 tiers."""
    if dist_m is None or not (DIST_RANGE_M[0] <= dist_m <= DIST_RANGE_M[1]):
        return _abstain("distance")
    lo, hi = hsv if hsv is not None else ORANGE_HSV
    mask = cv2.inRange(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV), np.array(lo), np.array(hi))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return _abstain("no_blob")
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, area = (int(v) for v in stats[i])
    bbox = [x, y, w, h]
    if area < MIN_BLOB_PX:
        return _abstain("no_blob", {"blob_bbox": bbox})
    f_px = cam["width"] / (2.0 * math.tan(cam["hfov_rad"] / 2.0))
    exp = [f_px * t / 1000.0 / dist_m for t in tier_mm]
    ev = {"h_px": h, "expected_px": {"1": exp[0], "2": exp[1]}, "blob_bbox": bbox}
    if y <= 0 or y + h >= img_bgr.shape[0]:
        return _abstain("border", ev)
    d1, d2 = abs(h - exp[0]), abs(h - exp[1])
    margin = abs(d1 - d2) / (exp[1] - exp[0])  # 0 at the midpoint, 1 at a tier's expected height
    if margin < MIN_MARGIN:
        return _abstain("margin", {**ev, "margin": margin})
    return {"tiers": 1 if d1 < d2 else 2, "confidence": min(1.0, margin), "evidence": {**ev, "margin": margin}}
