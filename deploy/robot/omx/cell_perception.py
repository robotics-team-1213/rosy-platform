#!/usr/bin/env python3
"""Box measurement and the start gate of one OMX cell, driven by a cell profile (rosy.omx-cell-profile.v1).

Everything cell-specific lives in the profile: the tray region and the box colour as the top camera
reads it, the wrist-camera colour, the references taken right before a successful grasp, the home
pose and the tolerances. The same code then serves another cell with another profile.

The start gate refuses to begin a cycle when the arm is not at home or the box is not where the taught
chunks expect it (2026-10-24: a box moved 5 cm and turned 38 degrees made the replayed grasp miss).

  cell_perception.py top <profile> <top.jpg>       -> {"found", "cx", "cy", "yaw", ...}
  cell_perception.py wrist <profile> <front.jpg>   -> {"found", "cx", "cy", "area", ...}
  cell_perception.py start <profile> <top.jpg> <state json>  -> {"ok", "issues"}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA = "rosy.omx-cell-profile.v1"


def load_profile(path) -> dict:
    profile = json.loads(Path(path).read_text())
    if profile.get("schema") != SCHEMA:
        raise SystemExit(f"cell profile needs schema {SCHEMA}")
    top, wrist, ref = profile.get("top_box"), profile.get("wrist_box"), profile.get("reference")
    if not (isinstance(top, dict) and isinstance(wrist, dict) and isinstance(ref, dict)):
        raise SystemExit("cell profile needs top_box, wrist_box and reference")
    x0, y0, x1, y1 = top["roi"]
    if not (0 <= x0 < x1 and 0 <= y0 < y1):
        raise SystemExit("top_box.roi must be x0 < x1, y0 < y1 inside the frame")
    if len(profile.get("home", [])) != 5:
        raise SystemExit("cell profile needs the five-joint home pose")
    return profile


def _largest(mask, min_area):
    import cv2
    import numpy as np

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    if n < 2 or stats[1:, cv2.CC_STAT_AREA].max() < min_area:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == i, stats[i], centroids[i]


def top_box(img, profile, roi=None) -> dict:
    """The box seen from above inside `roi` (default: the tray): centre (px) and yaw (0..90 deg, 0 = square)."""
    import cv2
    import numpy as np

    spec = profile["top_box"]
    x0, y0, x1, y1 = roi or spec["roi"]
    roi = img[y0:y1, x0:x1].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    lo, hi, below = spec["bgr_min"], spec["bgr_max"], spec.get("green_below", 0)
    mask = ((b >= lo[0]) & (b <= hi[0]) & (g >= lo[1]) & (g <= hi[1]) & (r >= lo[2]) & (r <= hi[2])
            & (g < b - below) & (g < r - below)).astype(np.uint8) * 255
    found = _largest(mask, spec.get("min_area", 300))
    if found is None:
        return {"found": False}
    blob, stats, _ = found
    pts = np.column_stack(np.nonzero(blob))[:, ::-1].astype(np.float32)
    (cx, cy), (w, h), angle = cv2.minAreaRect(pts)
    return {"found": True, "cx": round(cx + x0, 1), "cy": round(cy + y0, 1), "w": round(w), "h": round(h),
            "yaw": round(float(angle) % 90, 1), "area": int(stats[4])}


def wrist_box(img, profile) -> dict:
    """The box in the wrist camera: centre (px) and area (bigger = closer)."""
    import cv2

    import numpy as np

    spec = profile["wrist_box"]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, tuple(spec["hsv_min"]), tuple(spec["hsv_max"]))
    shade = spec.get("shade")
    if shade:  # in the arm's shadow the brown box reads dark mauve: low saturation, green below red and blue
        b, g, r = (c.astype(int) for c in cv2.split(img))
        s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
        dark = ((s >= shade["s"][0]) & (s <= shade["s"][1]) & (v >= shade["v"][0]) & (v <= shade["v"][1])
                & (g < r - shade["green_below_red"]) & (g < b - shade["green_below_blue"]))
        mask = cv2.bitwise_or(mask, (dark * 255).astype(np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    found = _largest(mask, spec.get("min_area", 300))
    if found is None:
        return {"found": False}
    blob, stats, centroid = found
    x, y, w, h = (int(v) for v in stats[:4])
    return {"found": True, "cx": round(float(centroid[0]), 1), "cy": round(float(centroid[1]), 1),
            "area": int(stats[4]), "bbox": [x, y, w, h], "tilt": _lower_edge_tilt(blob, x, w),
            "cut_top": y <= 2}


def _lower_edge_tilt(blob, x, w):
    """Tilt (deg) of the box's lower edge: a line through the lowest box pixel of each middle column.
    The wrist camera sees the box obliquely, so a rectangle fit is not informative (2026-10-25)."""
    import numpy as np

    if w < 40:
        return None
    columns = range(x + w // 6, x + w - w // 6)
    lows = [(c, int(np.nonzero(blob[:, c])[0].max())) for c in columns if blob[:, c].any()]
    if len(lows) < 20:
        return None
    xs, ys = np.array(lows, dtype=float).T
    return round(float(np.degrees(np.arctan(np.polyfit(xs, ys, 1)[0]))), 1)


def place_check(img, profile, site: str) -> dict:
    """After a release: is the box inside the zone the next grasp at `site` can reach? 2026-10-25 a box set
    down on the belt's far edge could not be picked again and later fell off; catching that right after the
    release lets the judge re-place it instead. The site's `search` roi finds the box, `reach` bounds it."""
    zone = profile["sites"][site]
    if "hsv_min" in zone:  # against the dark belt the box reads bright and unsaturated, not mauve as on the tray
        import cv2
        import numpy as np

        x0, y0, x1, y1 = zone["search"]
        mask = cv2.inRange(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV),
                           tuple(zone["hsv_min"]), tuple(zone["hsv_max"]))
        found = _largest(mask, zone.get("min_area", 600))
        box = {"found": False}
        if found is not None:
            _, stats, centroid = found
            box = {"found": True, "cx": round(float(centroid[0]) + x0, 1), "cy": round(float(centroid[1]) + y0, 1),
                   "area": int(stats[4])}
    else:
        box = top_box(img, profile, roi=zone["search"])
    if not box.get("found"):
        return {"found": False, "inside": False}
    x0, y0, x1, y1 = zone["reach"]
    return dict(box, inside=bool(x0 <= box["cx"] <= x1 and y0 <= box["cy"] <= y1))


def yaw_gap(a: float, b: float) -> float:
    """Difference of two box yaws in degrees; a square box repeats every 90."""
    d = abs(a - b) % 90
    return min(d, 90 - d)


def start_check(state, top: dict, profile) -> dict:
    """Is the cell where the taught chunks begin? Arm at home and the box at the reference."""
    tol, ref, issues = profile["tolerance"], profile["reference"]["top"], []
    far = [round(s - h, 1) for s, h in zip(state[:5], profile["home"])]
    if max(abs(v) for v in far) > tol["home"]:
        issues.append({"kind": "arm_not_home", "offset": far})
    if not top.get("found"):
        issues.append({"kind": "box_not_seen"})
    else:
        shift = round(((top["cx"] - ref["cx"]) ** 2 + (top["cy"] - ref["cy"]) ** 2) ** 0.5, 1)
        if shift > tol["box_px"]:
            issues.append({"kind": "box_moved", "px": shift, "at": [top["cx"], top["cy"]]})
        turn = yaw_gap(top["yaw"], ref["yaw"])
        if turn > tol["box_yaw"]:
            issues.append({"kind": "box_turned", "deg": round(turn, 1)})
    return {"ok": not issues, "issues": issues}


def main(argv=None):
    import cv2

    args = argv if argv is not None else sys.argv[1:]
    verb, profile = args[0], load_profile(args[1])
    image = cv2.imread(args[2])
    if image is None:
        raise SystemExit(f"cannot read {args[2]}")
    if verb == "top":
        result = top_box(image, profile)
    elif verb == "wrist":
        result = wrist_box(image, profile)
    elif verb == "start":
        result = start_check(json.loads(args[3]), top_box(image, profile), profile)
    else:
        raise SystemExit("verbs: top | wrist | start")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
