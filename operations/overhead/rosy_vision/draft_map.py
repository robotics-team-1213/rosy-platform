"""Draft-map candidates read from the D-560 map plane, for operator review only.

The plane is already rectified to the map frame, so detection is pure image work: bright
paint strokes become two-point lane centrelines (v1: each stroke's minimum-area rectangle
long axis — straight lane paint; a curved stroke becomes its chord) and saturated colour
areas become four-corner exclusion-zone candidates, both in map metres. Nothing here is
applied to sightings, ``CameraMap`` or any map document; the caller reviews and admits.
"""

from __future__ import annotations

import cv2
import numpy as np

DRAFT_MAP_VERSION = "draft-map-1"

MIN_COMPONENT_PX = 200       # ~3.5 cm square at the plane's 400 px/m; smaller is noise
BRIGHT_MIN = 170             # lane paint is ~235 on the ~105 floor; the off-camera hatch is 24..40
SATURATION_MIN, VALUE_MIN = 120, 80


def _to_metres(points_px: np.ndarray, bounds_m, px_per_m: float) -> list[list[float]]:
    min_x, _, _, max_y = bounds_m
    return [[round(float(min_x + (u + 0.5) / px_per_m), 4), round(float(max_y - (v + 0.5) / px_per_m), 4)]
            for u, v in points_px]


def detect_draft_map(plane_bgr: np.ndarray, bounds_m, px_per_m: float,
                     valid: np.ndarray | None = None,
                     raw_bgr: np.ndarray | None = None) -> dict:
    """``{lanes:[{polyline_m, width_px}], zones:[{polygon_m, kind}], reason}`` on one plane."""
    try:
        from rosy_vision.world_261026_auto import auto_calibrate_and_trace_world_261026
        fit = auto_calibrate_and_trace_world_261026(raw_bgr if raw_bgr is not None else plane_bgr)
    except Exception:
        fit = None
    if fit is not None and fit.get("edges"):
        lanes = [
            {
                "polyline_m": [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in edge["polyline"]],
                "width_px": round(float(edge.get("width_m", 0.18)) * float(px_per_m), 1),
                "id": edge["id"],
                "name": edge.get("name") or edge["id"],
                "from_id": edge["from"],
                "to_id": edge["to"],
                "direction": edge.get("direction", "one_way"),
            }
            for edge in fit["edges"]
        ]
        return {
            "lanes": lanes,
            "zones": [],
            "places": fit.get("places") or [],
            "edges": fit.get("edges") or [],
            "map_id": "world_261026",
            "reason": "ok",
        }
    seen = np.ones(plane_bgr.shape[:2], bool) if valid is None else valid
    gray = cv2.cvtColor(plane_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(plane_bgr, cv2.COLOR_BGR2HSV)
    bright = (gray >= BRIGHT_MIN) & seen
    colour = (hsv[..., 1] >= SATURATION_MIN) & (hsv[..., 2] >= VALUE_MIN) & seen
    lanes: list[dict] = []
    zones: list[dict] = []
    for mask, out in ((bright, lanes), (colour, zones)):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_AREA] < MIN_COMPONENT_PX:
                continue
            contours, _ = cv2.findContours((labels == index).astype(np.uint8), cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            contour = max(contours, key=cv2.contourArea)
            box = cv2.minAreaRect(contour)
            if out is lanes:
                (cx, cy), (width_px, height_px), angle = box
                long_px = max(width_px, height_px)
                axis = (np.cos(np.radians(angle)), np.sin(np.radians(angle))) if width_px >= height_px \
                    else (-np.sin(np.radians(angle)), np.cos(np.radians(angle)))
                ends = np.array([(cx + axis[0] * long_px / 2, cy + axis[1] * long_px / 2),
                                 (cx - axis[0] * long_px / 2, cy - axis[1] * long_px / 2)])
                stroke_px = stats[index, cv2.CC_STAT_AREA] / max(long_px, 1.0)
                out.append({"polyline_m": sorted(_to_metres(ends, bounds_m, px_per_m)),
                            "width_px": round(float(stroke_px), 1)})
            else:
                corners = cv2.boxPoints(box)
                poly_m = _to_metres(corners, bounds_m, px_per_m)
                out.append({"polygon_m": poly_m,
                            "kind": "exclusion"})
    lanes.sort(key=lambda lane: lane["polyline_m"])
    zones.sort(key=lambda zone: zone["polygon_m"][0] if zone["polygon_m"] else [0.0, 0.0])
    return {"lanes": lanes, "zones": zones,
            "reason": "ok" if lanes or zones else "nothing detected"}
