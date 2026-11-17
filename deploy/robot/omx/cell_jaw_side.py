"""One visible jaw in the top view, for the pivot's jaw marks over a cluttered site (panel r8, 2026-11-17).

When the jaws open, the top camera sees one white jaw; the other hides under the gripper body, and which one shows
changes with the pose. The two-sided pair (`jaw_centre`) was found in 2 of 85 saved tries, a pivot whose visible jaw
switched read "marks split" (arm_a), and on arm_b's far points the other jaw stood 50 mm from the reference one.

From the measured joints' FK yaw this module predicts where each jaw shows: the reference jaw (the one the maps and
the pivot circle follow: the TCP, plus `pivot.geometry` when stated) and the other one `jaw_side.other_mm` from it at
FK yaw + `jaw_side.other_deg` (measured once from the remap tries). The open-closed difference is kept only in discs
of `jaw_side.roi_px` around those places, and, with the top depth camera, only where the height is within the jaws'
band (no depth return stays in). A blob is the jaw whose predicted place is nearest, and that jaw's predicted offset
moves it to where the reference jaw shows (or to the jaws' middle with `jaw_mark.centre`), so a switch of the
visible jaw no longer splits the marks. Both jaws seen as one pair: their middle, moved the same way. Nothing
outside the discs is ever a mark; the circle fit and every pivot guard downstream are unchanged.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_params as prm

_PLACE_ERRORS = (np.linalg.LinAlgError, KeyError, TypeError, ValueError, ZeroDivisionError, IndexError)


def near_tcp(record: dict, config: dict, site: str, point, z_view: float, radius_px: float):
    """The pivot's `near`: where the commanded TCP shows at the view height, or None when the map cannot say."""
    import cell_pivot

    H = record.get("homography")
    if not (isinstance(H, list) and len(H) == 3 and "top" in (config.get("cameras") or {})):
        return None
    try:
        return [cell_pivot.mark_pixel(record, config, site, point, z_view)], radius_px
    except _PLACE_ERRORS:
        return None


def jaw_places(record: dict, config: dict, site: str, tcp_xy, yaw_deg: float, z: float) -> list:
    """[reference jaw px, other jaw px] in the top view for the TCP at `tcp_xy` (map's raw frame) and FK yaw."""
    import cell_pivot

    p, geo = config.get("params"), (config.get("pivot") or {}).get("geometry") or {}
    a = math.radians(yaw_deg + geo.get("phase_deg", 0.0))
    ref = (tcp_xy[0] + geo.get("radius_mm", 0.0) / 1000 * math.cos(a), tcp_xy[1] + geo.get("radius_mm", 0.0) / 1000 * math.sin(a))
    b, r = math.radians(yaw_deg + prm.get(p, "jaw_side.other_deg")), prm.get(p, "jaw_side.other_mm") / 1000
    other = (ref[0] + r * math.cos(b), ref[1] + r * math.sin(b))
    return [tuple(float(v) for v in cell_pivot.mark_pixel(record, config, site, q, z)) for q in (ref, other)]


def discs(shape, places, radius_px: float) -> np.ndarray:
    import cv2

    mask = np.zeros(shape[:2], np.uint8)
    for c in places:
        cv2.circle(mask, (int(round(c[0])), int(round(c[1]))), int(round(radius_px)), 255, -1)
    return mask


def heights_in_colour(depth, colour) -> tuple[np.ndarray, float]:
    """mm above the table (cell_depth plane) at each colour pixel, NaN where the depth camera had no return, and the
    camera's own height above the table (the plane's offset)."""
    import cv2
    import cell_depth

    plane = cell_depth.table_plane(depth)
    heights = cell_depth.height_map(depth, plane).astype(np.float32)
    to_depth, _ = cell_depth.align_edges(colour, heights)
    h, w = colour.shape[:2]
    out = cv2.warpAffine(heights, to_depth, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=float("nan"))
    return out, float(plane[1])


def height_band(heights, jaw_mm: float, params=None) -> np.ndarray:
    """255 where the height is within [jaw - band, jaw + above + band] or unknown: shadows and changes on boxes and
    the table (45-60 mm under the jaws, depth noise p99 5.3 mm, 2026-11-17) drop out; the finger's thin edges, often
    without a return, stay. Widened by 5 px for the colour-depth alignment."""
    import cv2

    band, above = prm.get(params, "jaw_side.band_mm"), prm.get(params, "jaw_side.above_mm")
    with np.errstate(invalid="ignore"):
        keep = ~np.isfinite(heights) | ((heights >= jaw_mm - band) & (heights <= jaw_mm + above + band))
    return cv2.dilate(keep.astype(np.uint8) * 255, np.ones((11, 11), np.uint8))


def pivot_jaws(cell, config: dict, record: dict, site: str, fk, keep: Path) -> dict | None:
    """mark_jaws' `jaws` at this pivot yaw from the measured FK (x, y, z, yaw), or None (the old path) when the map
    cannot place the jaws. A top depth camera's frame is kept as `keep/depth.raw` and limits the discs to the band."""
    if fk is None:
        return None
    p = config.get("params")
    try:
        places = jaw_places(record, config, site, fk[:2], fk[3], fk[2])
    except _PLACE_ERRORS:
        return None
    jaws = {"places": places, "radius_px": prm.get(p, "jaw_side.roi_px"), "band": None,
            "to": "middle" if (config.get("jaw_mark") or {}).get("centre") else "reference"}
    top = (config.get("cameras") or {}).get("top") or {}
    keep.mkdir(parents=True, exist_ok=True)
    info = {"fk": [round(float(v), 4) for v in fk], "places": [[round(v, 1) for v in c] for c in places], "depth": None}
    import cell_cal_eval

    if top.get("height_m") is not None and cell_cal_eval.top_has_depth(config):
        import cell_depth

        depth = cell_depth.capture_top_depth_z16(out_raw=keep / "depth.raw")
        if depth is not None:
            import cv2

            colour = cell.frame("top")
            cv2.imwrite(str(keep / "depth-colour.jpg"), colour)
            heights, table_mm = heights_in_colour(depth, colour)
            jaw_mm = table_mm - 1000 * (float(top["height_m"]) - float(fk[2]))  # camera above the arm's zero
            jaws["band"] = height_band(heights, jaw_mm, p)
            info["depth"] = {"jaw_mm": round(jaw_mm, 1), "table_mm": round(table_mm, 1)}
    (keep / "jaws.json").write_text(json.dumps(info))
    return jaws


def _side(blob, places, radius_px):
    """0 inside the reference jaw's disc, else 1 inside the other's, else None. The reference wins where the discs
    meet: without pivot.geometry its place is the TCP, up to its own radius (about 20 mm) off, and nearest-place
    put 2 of 6 simulated pivot marks on the other jaw."""
    return next((k for k, c in enumerate(places) if math.dist(blob[:2], c) <= radius_px), None)


def marks(closed, opened, params=None, colour: bool = False, jaws: dict | None = None) -> list:
    """[(cx, cy, area)]: jaw marks found inside the jaws' discs (and band), each moved to the reference jaw's place
    (or the jaws' middle). A pair needs one side at each jaw; otherwise every single blob is the jaw nearest it."""
    import cv2
    import cell_pivot

    places, r = jaws["places"], jaws["radius_px"]
    within = discs(closed.shape, places, r)
    if jaws.get("band") is not None:
        within = cv2.bitwise_and(within, jaws["band"])
    mid = ((places[0][0] + places[1][0]) / 2, (places[0][1] + places[1][1]) / 2)
    to = mid if jaws.get("to") == "middle" else places[0]
    out = []
    for a, b in cell_pivot._jaw_pairs(closed, opened, params, colour, within=within):
        if {_side(a, places, r), _side(b, places, r)} == {0, 1}:
            out.append(((a[0] + b[0]) / 2 - mid[0] + to[0], (a[1] + b[1]) / 2 - mid[1] + to[1], a[2] + b[2]))
    if out:
        return out
    for blob in cell_pivot.jaw_blobs(closed, opened, params, colour, within=within):
        k = _side(blob, places, r)
        if k is not None:
            out.append((blob[0] - places[k][0] + to[0], blob[1] - places[k][1] + to[1], blob[2]))
    return out
