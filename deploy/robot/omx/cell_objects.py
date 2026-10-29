"""Catalogue-driven objects in the top view, measured in arm millimetres (rosy.omx-object-catalog.v1).

Foreground is whatever differs from the surface's median colour inside a region of interest (Lab chroma
distance, plus a large lightness step for black/white objects), so no object colour is built in. Each blob is
measured through the pixel -> arm map with parallax from the object's top height, matched to a catalogue entry
by width and length, and a blob 2 or 3 widths wide is split along its long axis into strips measured again.
Anything matching nothing is `unmatched` and never a grasp target: measurement vetoes.

  python cell_objects.py IMAGE --map map.json --camera camera.json --roi x0 y0 x1 y1 --catalog object-catalog.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_calibration as cal  # noqa: E402
import cell_params as prm  # noqa: E402

SCHEMA = "rosy.omx-object-catalog.v1"
SPLIT_FILL, SPLIT_AXIS_DEG = prm.default("objects.split_fill"), prm.default("objects.split_axis_deg")  # a split piece must fill its rectangle and lie parallel to the others
CHROMA, LIGHT, MIN_PX = (prm.default(f"objects.{k}") for k in ("chroma", "light", "min_px"))  # Lab (OpenCV 0-255) chroma and lightness steps; smallest blob in pixels


def load_catalog(path) -> list:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} file")
    for o in data["objects"]:
        for key in ("id", "length_mm", "width_mm", "top_height_mm", "tolerance_mm", "grasp"):
            if key not in o:
                raise ValueError(f"catalogue entry {o.get('id')!r} lacks {key}")
    return data["objects"]


def foreground(img, roi, chroma: float | None = None, light: float | None = None, params=None, surface_px=None,
               surface_lab=None):
    """Mask (ROI-sized) of pixels far from the surface's median colour; a shadow moves lightness only a little.
    Thresholds not given come from `params` (a white floor line passes the lightness test, 2026-10-28).
    `surface_px`, a polygon of the site's surface in the image, drops what lies beyond it (the board next to the
    floor joined a container into one blob along the ROI's edge, 2026-10-28). `surface_lab`: the site's own surface
    colour (OpenCV Lab), or a list of them where a box overhangs more than one surface (the board and its white
    line); without it the ROI median is used, which on the board was a mix of the white line, the belt and the box
    (173, 121, 139 against the board's 199, 130, 162), so the box's shadow did not read as a shadow."""
    chroma = prm.get(params, "objects.chroma", CHROMA) if chroma is None else chroma
    light = prm.get(params, "objects.light", LIGHT) if light is None else light
    x0, y0, x1, y1 = roi
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.int16)[y0:y1, x0:x1]
    colours = np.atleast_2d(np.asarray(surface_lab, float)) if surface_lab is not None else [np.median(lab.reshape(-1, 3), axis=0)]
    far = np.ones(lab.shape[:2], bool)
    for bg in colours:  # background when close to any of the site's surfaces, or a shadow on one
        near = (np.hypot(lab[..., 1] - bg[1], lab[..., 2] - bg[2]) <= chroma) & (np.abs(lab[..., 0] - bg[0]) <= light)
        if prm.get(params, "objects.drop_shadow"):
            near |= shadow_of(lab, bg, params)
        far &= ~near
    mask = far.astype(np.uint8) * 255
    if surface_px:
        keep = np.zeros_like(mask)
        cv2.fillPoly(keep, [np.asarray(surface_px, np.int32) - [x0, y0]], 255)
        mask &= keep
    o, c = (int(prm.get(params, f"objects.{k}")) for k in ("open_px", "close_px"))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((o, o), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))


def shadow_of(lab, bg, params=None):
    """Pixels that are the surface's own colour, only darker: the chroma vector a shrunk copy of the surface's and the
    lightness 45-100 % of it. On the yellow board a box's shadow (dark yellow) passed the chroma test and stood next to
    the box as a fragment, so no finger gap was left (2026-10-29). A black object (darker than that) or another
    colour is never a shadow."""
    c0 = np.array([bg[1] - 128.0, bg[2] - 128.0])
    c = np.stack([lab[..., 1] - 128.0, lab[..., 2] - 128.0], axis=-1)
    tol, lo = prm.get(params, "objects.shadow_tol"), prm.get(params, "objects.shadow_min_light")
    darker = (lab[..., 0] < bg[0]) & (lab[..., 0] >= lo * bg[0])
    n2 = float(c0 @ c0)
    if n2 < 64:  # a grey surface: its shadow is grey too
        return darker & (np.hypot(c[..., 0], c[..., 1]) < tol)
    k = (c @ c0) / n2
    resid = np.hypot(*(c - k[..., None] * c0).transpose(2, 0, 1))
    return darker & (k > 0.2) & (k < 1.15) & (resid < tol)


def to_mm(pixels, record: dict, camera: dict, top_z: float):
    """Pixels of points at height top_z (m) -> arm mm: parallax down/up to the map's z_view, then the map."""
    z_view = record.get("z_view", top_z)
    pts = np.array([cal.parallax(p, top_z, z_view, camera) for p in pixels])
    a = np.c_[pts, np.ones(len(pts))] @ np.asarray(record["homography"], float).T
    return a[:, :2] / a[:, 2:] * 1000.0


def measure(mm) -> dict:
    (cx, cy), (w, h), ang = cv2.minAreaRect(np.asarray(mm, np.float32))
    if w < h:
        w, h, ang = h, w, ang + 90.0
    return {"centre_mm": [round(cx, 1), round(cy, 1)], "length_mm": round(w, 1), "width_mm": round(h, 1),
            "long_axis_deg": round((ang + 90) % 180 - 90, 1)}


def _fits(m: dict, o: dict, k: int = 1, strict: bool = False) -> bool:
    # lengths come in whole cells, so a lone blob's length may stray up to half a cell; the real top camera read a
    # 60 mm container 47-56 mm long (dark end frames drop out of the mask) while its 30 mm width held within 9
    # (2026-10-28). Pieces split from a merged blob stay strict: with the loose length a tangled cluster's
    # piece matched and would have become a grasp target.
    t = o["tolerance_mm"]
    return (abs(m["width_mm"] - k * o["width_mm"]) <= t
            and abs(m["length_mm"] - o["length_mm"]) <= (t if strict else o.get("length_tolerance_mm", t)))


def match(m: dict, catalog: list, strict: bool = False):
    """The nearest entry within tolerance, or None."""
    ok = [o for o in catalog if _fits(m, o, strict=strict)]
    return min(ok, key=lambda o: abs(m["width_mm"] - o["width_mm"]) + abs(m["length_mm"] - o["length_mm"])) if ok else None


def _strips(mm, m: dict, k: int):
    u = math.radians(m["long_axis_deg"])
    across = (mm - m["centre_mm"]) @ np.array([-math.sin(u), math.cos(u)])
    edges = np.linspace(across.min(), across.max(), k + 1)
    return [(across >= edges[i]) & (across <= edges[i + 1]) for i in range(k)]


def classify(mm, catalog: list, px_mm2: float | None = None, params=None) -> list:
    """One blob's arm-mm points -> results: matched objects (a wide blob split into strips) or one unmatched.
    `px_mm2`: the area of one pixel in mm, to check that each strip fills its own rectangle. A wide blob is
    split only into parallel strips that each match a catalogue entry and fill their rectangle; anything else
    is tangled (2026-10-28: two side by side plus a third touching at an angle gave a 25 degree axis and wrong
    pieces) and is never a grasp target."""
    m = measure(mm)
    o = match(m, catalog)
    if o:
        return [{**m, "object": o["id"], "grasp": o["grasp"], "matched": True}]
    for k in (2, 3):
        for o in catalog:
            if _fits(m, o, k, strict=True):
                strips = [(g, measure(mm[g])) for g in _strips(mm, m, k)]
                found = [(match(s, catalog, strict=True), s, g) for g, s in strips]
                ok = all(e for e, _, _ in found) and all(
                    abs((s["long_axis_deg"] - m["long_axis_deg"] + 90) % 180 - 90) <= prm.get(params, "objects.split_axis_deg", SPLIT_AXIS_DEG)
                    and (px_mm2 is None or g.sum() * px_mm2 >= prm.get(params, "objects.split_fill", SPLIT_FILL) * s["length_mm"] * s["width_mm"])
                    for _, s, g in found)
                if ok:
                    return [{**s, "object": e["id"], "grasp": e["grasp"], "matched": True, "split_from": k} for e, s, _ in found]
                return [{**m, "object": None, "grasp": None, "matched": False, "tangled": True}]
    return [{**m, "object": None, "grasp": None, "matched": False}]


def top_face(px, height_mm: float, camera: dict, surface_z: float, params=None):
    """The top camera also sees an object's side faces: a 30 mm cube at the image edge measured 44 x 39 mm
    (2026-10-28). The blob is the top face swept toward the principal point by r*h/(H-h) px (r the radius of
    the blob's inner edge, H the camera above the surface), so the top face is the blob eroded by that sweep."""
    if "center_px" not in camera or "height_m" not in camera:
        return px
    c = np.asarray(camera["center_px"], float)
    h, big_h = height_mm / 1000.0, camera["height_m"] - surface_z
    radial = px - c
    d = float(np.linalg.norm(radial.mean(axis=0)))
    if d < 1e-6 or big_h <= h:
        return px
    u = radial.mean(axis=0) / d
    sweep = float((radial @ u).min()) * h / (big_h - h)
    n = int(math.ceil(sweep))
    if n < 1:
        return px
    lo = px.min(axis=0).astype(int) - n - 1
    size = (px.max(axis=0).astype(int) - lo + n + 2)[::-1]
    mask = np.zeros(size, np.uint8)
    mask[(px[:, 1] - lo[1]).astype(int), (px[:, 0] - lo[0]).astype(int)] = 255
    kernel = np.zeros((2 * n + 1, 2 * n + 1), np.uint8)  # offsets from a pixel toward the principal point
    cv2.line(kernel, (n, n), (round(n - sweep * u[0]), round(n - sweep * u[1])), 1, 1)
    eroded = cv2.erode(mask, kernel, anchor=(n, n))
    ys, xs = np.nonzero(eroded)
    keep = np.column_stack([xs, ys]) + lo
    return keep.astype(float) if len(keep) >= prm.get(params, "objects.min_px", MIN_PX) else px


def _px_mm2(px, mm) -> float | None:
    """Area of one pixel in arm mm (the map is affine, so the hulls' ratio is its determinant)."""
    if len(px) < 5:
        return None
    a_px = cv2.contourArea(cv2.convexHull(px.astype(np.float32)))
    return None if a_px < 1 else cv2.contourArea(cv2.convexHull(np.asarray(mm, np.float32))) / a_px


def _measure_blob(px, record: dict, camera: dict, catalog: list, surface_z: float, params) -> list:
    """One blob's image pixels -> classify results. Blob height is unknown before matching, so each catalogue top
    height is tried and the tallest-first full match kept; a blob matching none is measured at the first height."""
    best = None
    for h in sorted({o["top_height_mm"] for o in catalog}, reverse=True):
        top = top_face(px.astype(float), h, camera, surface_z, params)
        mm = to_mm(top, record, camera, surface_z + h / 1000.0)
        res = classify(mm, catalog, _px_mm2(top, mm), params)
        if all(r["matched"] for r in res):
            return res
        best = best or res
    return best


def object_mask(img, roi, hsv, surface_px=None, params=None):
    """Mask (ROI-sized) of the objects by their own colour (OpenCV HSV range, e.g. the green containers): the
    surface, its shadows, white lines and belts do not matter. On the board the green boxes read hue 78-80, the board
    20, a box's shadow 34 and the white line saturation 25 (2026-10-29)."""
    x0, y0, x1, y1 = roi
    mask = cv2.inRange(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), np.array(hsv[0]), np.array(hsv[1]))
    if surface_px:
        keep = np.zeros_like(mask)
        cv2.fillPoly(keep, [np.asarray(surface_px, np.int32) - [x0, y0]], 255)
        mask &= keep
    o, c = (int(prm.get(params, f"objects.{k}")) for k in ("open_px", "close_px"))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((o, o), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))


def detect(img, roi, record: dict, camera: dict, catalog: list, surface_z: float = 0.0, params=None,
           surface_px=None, surface_lab=None, object_hsv=None) -> list:
    """All objects in the ROI. A blob that matches nothing is tried as boxes that only touch (cell_split); each piece
    is judged on its own, and the pieces replace the blob when at least one matches the catalogue (2026-10-29: the
    1-cell matched, the 2-cell beside it read 63 x 47 mm with its side faces and stays an unmatched neighbour). Each
    object carries `hull_px`, the outline of its own pixels, so a finger check sees a touching neighbour as one."""
    import cell_split

    x0, y0, _, _ = roi
    # objects by their own colour when the cell names it; else anything far from the surface (any colour)
    seen = (object_mask(img, roi, object_hsv, surface_px, params) if object_hsv is not None
            else foreground(img, roi, params=params, surface_px=surface_px, surface_lab=surface_lab))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(seen)
    out = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < prm.get(params, "objects.min_px", MIN_PX):
            continue
        blob = labels == i
        pieces = [blob]
        found = _measure_blob(np.column_stack(np.nonzero(blob))[:, ::-1] + [x0, y0], record, camera, catalog, surface_z, params)
        if not all(r["matched"] for r in found) and prm.get(params, "objects.split_touching"):
            parts = cell_split.split_touching(blob, prm.get(params, "objects.split_peak_frac"), prm.get(params, "objects.min_px", MIN_PX))
            measured = [_measure_blob(np.column_stack(np.nonzero(q))[:, ::-1] + [x0, y0], record, camera, catalog, surface_z, params)
                        for q in parts]
            if parts and any(r["matched"] for res in measured for r in res):
                pieces, found = parts, None
                for q, res in zip(parts, measured):
                    hull = cv2.convexHull(np.column_stack(np.nonzero(q))[:, ::-1].astype(np.int32) + [x0, y0]).reshape(-1, 2)
                    out += [{**r, "split_from": "touching", "hull_px": hull.tolist()} for r in res]
        if found is not None:
            hull = cv2.convexHull(np.column_stack(np.nonzero(pieces[0]))[:, ::-1].astype(np.int32) + [x0, y0]).reshape(-1, 2)
            out += [{**r, "hull_px": hull.tolist()} for r in found]
    return out

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--map", required=True, help="map record JSON (homography, z_view); a {'record': ...} wrapper is fine")
    ap.add_argument("--camera", required=True, help='JSON {"height_m", "center_px"}')
    ap.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--surface-z", type=float, default=0.0, help="surface height in metres (default 0)")
    a = ap.parse_args(argv)
    img = cv2.imread(a.image)
    if img is None:
        print(f"cannot read {a.image}", file=sys.stderr)
        return 2
    rec = json.loads(Path(a.map).read_text())
    rec = rec.get("record", rec)
    found = detect(img, a.roi, rec, json.loads(Path(a.camera).read_text()), load_catalog(a.catalog), a.surface_z)
    print(json.dumps({"objects": found, "grasp_targets": [o for o in found if o["matched"]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
