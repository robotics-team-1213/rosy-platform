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

SCHEMA = "rosy.omx-object-catalog.v1"
CHROMA, LIGHT, MIN_PX = 25.0, 60.0, 150  # Lab (OpenCV 0-255) chroma and lightness steps; smallest blob in pixels


def load_catalog(path) -> list:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} file")
    for o in data["objects"]:
        for key in ("id", "length_mm", "width_mm", "top_height_mm", "tolerance_mm", "grasp"):
            if key not in o:
                raise ValueError(f"catalogue entry {o.get('id')!r} lacks {key}")
    return data["objects"]


def foreground(img, roi, chroma: float = CHROMA, light: float = LIGHT):
    """Mask (ROI-sized) of pixels far from the surface's median colour; a shadow moves lightness only a little."""
    x0, y0, x1, y1 = roi
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.int16)[y0:y1, x0:x1]
    bg = np.median(lab.reshape(-1, 3), axis=0)
    far = (np.hypot(lab[..., 1] - bg[1], lab[..., 2] - bg[2]) > chroma) | (np.abs(lab[..., 0] - bg[0]) > light)
    mask = far.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


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


def _fits(m: dict, o: dict, k: int = 1) -> bool:
    t = o["tolerance_mm"]
    return abs(m["width_mm"] - k * o["width_mm"]) <= t and abs(m["length_mm"] - o["length_mm"]) <= t


def match(m: dict, catalog: list):
    """The nearest entry within tolerance, or None."""
    ok = [o for o in catalog if _fits(m, o)]
    return min(ok, key=lambda o: abs(m["width_mm"] - o["width_mm"]) + abs(m["length_mm"] - o["length_mm"])) if ok else None


def _strips(mm, m: dict, k: int):
    u = math.radians(m["long_axis_deg"])
    across = (mm - m["centre_mm"]) @ np.array([-math.sin(u), math.cos(u)])
    edges = np.linspace(across.min(), across.max(), k + 1)
    return [(across >= edges[i]) & (across <= edges[i + 1]) for i in range(k)]


def classify(mm, catalog: list) -> list:
    """One blob's arm-mm points -> results: matched objects (a wide blob split into strips) or one unmatched."""
    m = measure(mm)
    o = match(m, catalog)
    if o:
        return [{**m, "object": o["id"], "grasp": o["grasp"], "matched": True}]
    for k in (2, 3):
        for o in catalog:
            if _fits(m, o, k):
                strips = [(g, measure(mm[g])) for g in _strips(mm, m, k)]
                found = [(match(s, catalog), s) for _, s in strips]
                if all(e for e, _ in found):
                    return [{**s, "object": e["id"], "grasp": e["grasp"], "matched": True, "split_from": k} for e, s in found]
    return [{**m, "object": None, "grasp": None, "matched": False}]


def detect(img, roi, record: dict, camera: dict, catalog: list, surface_z: float = 0.0) -> list:
    """All objects in the ROI. Blob height is unknown before matching, so each catalogue top height is tried
    and the tallest-first best match kept; a blob matching none is measured at the first entry's height."""
    x0, y0, _, _ = roi
    n, labels, stats, _ = cv2.connectedComponentsWithStats(foreground(img, roi))
    out = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < MIN_PX:
            continue
        px = np.column_stack(np.nonzero(labels == i))[:, ::-1] + [x0, y0]
        best = None
        for h in sorted({o["top_height_mm"] for o in catalog}, reverse=True):
            res = classify(to_mm(px, record, camera, surface_z + h / 1000.0), catalog)
            if all(r["matched"] for r in res):
                best = res
                break
            best = best or res
        out += best
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
