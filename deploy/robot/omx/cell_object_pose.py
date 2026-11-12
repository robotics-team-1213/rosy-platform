"""3D homography/parallax pose measurement, colour tagging, and OpenCV/Decision-AI structural container verification.

Split out from `cell_objects.py` so both 3D pose/geometry helpers (`cell_object_pose.py`) and 2D catalogue/contour
detection (`cell_objects.py`) stay compact and single-responsibility (< 400 lines each).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402

MIN_PX = prm.default("objects.min_px")


def to_mm(pixels, record: dict, camera: dict, top_z: float):
    """Pixels of points at height top_z (m) -> arm mm: parallax down/up to the map's z_view, then the map."""
    z_view = record.get("z_view", top_z)
    pts = np.asarray(pixels, float)
    if top_z != z_view and "center_px" in camera and "height_m" in camera:
        c = np.asarray(camera["center_px"], float)
        scale = (camera["height_m"] - top_z) / (camera["height_m"] - z_view)
        pts = c + (pts - c) * scale
    h = np.asarray(record["homography"], float)
    a = pts @ h[:, :2].T + h[:, 2]
    return a[:, :2] / a[:, 2:] * 1000.0


def measure(mm) -> dict:
    (cx, cy), (w, h), ang = cv2.minAreaRect(np.asarray(mm, np.float32))
    if w < h:
        w, h, ang = h, w, ang + 90.0
    return {
        "centre_mm": [round(cx, 1), round(cy, 1)],
        "length_mm": round(w, 1),
        "width_mm": round(h, 1),
        "long_axis_deg": round((ang + 90) % 180 - 90, 1),
    }


def _colour_set(spec) -> set:
    if not spec:
        return set()
    items = spec.split(",") if isinstance(spec, str) else spec
    return {str(c).strip().lower() for c in items if str(c).strip()}


def colour_name(hsv) -> str:
    """Human-readable colour name from OpenCV HSV (H in 0..179, S and V in 0..255)."""
    h, s, v = float(hsv[0]), float(hsv[1]), float(hsv[2])
    if s < 35:
        return "black" if v < 65 else ("white" if v > 200 else "grey")
    for hi, name in ((8, "red"), (22, "orange"), (35, "yellow"), (88, "green"), (135, "blue"), (165, "purple")):
        if h < hi:
            return name
    return "red"


def colour_tag(img, px) -> dict:
    """Median OpenCV HSV and colour name of image pixels `px` (N x 2 [x, y])."""
    if img is None or len(px) == 0:
        return {}
    pts = np.asarray(px, int)
    xs = np.clip(pts[:, 0], 0, img.shape[1] - 1)
    ys = np.clip(pts[:, 1], 0, img.shape[0] - 1)
    hsv_px = cv2.cvtColor(img[ys, xs].reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    med = [int(round(float(v))) for v in np.median(hsv_px, axis=0)]
    return {"colour": colour_name(med), "hsv": med}


def container_structure(img, px) -> dict:
    """Color-agnostic OpenCV structural analysis of a candidate blob `px` (N x 2 [x, y]):
    measures rectangularity, Canny/Sobel parallel-edge alignment along the minAreaRect axes,
    and corrugation-rib / end-wall texture periodicity to judge whether the shape is a container."""
    if px is None or len(px) < 12:
        return {
            "rectangularity": 0.0,
            "edge_parallelism": 0.0,
            "rib_score": 0.0,
            "shape_score": 0.0,
            "is_container_shape": False,
        }
    pts = np.asarray(px, dtype=np.float32)
    (_, _), (rw, rh), ang = cv2.minAreaRect(pts)
    box_area = float(rw * rh)
    if box_area < 16.0:
        return {
            "rectangularity": 0.0,
            "edge_parallelism": 0.0,
            "rib_score": 0.0,
            "shape_score": 0.0,
            "is_container_shape": False,
        }
    hull_area = float(cv2.contourArea(cv2.convexHull(pts)))
    rectangularity = float(min(1.0, max(hull_area, float(len(pts))) / box_area))
    edge_parallelism = 0.75
    rib_score = 0.5
    if img is not None and img.size > 0:
        h, w = img.shape[:2]
        x0 = max(0, int(np.floor(pts[:, 0].min())) - 4)
        y0 = max(0, int(np.floor(pts[:, 1].min())) - 4)
        x1 = min(w, int(np.ceil(pts[:, 0].max())) + 5)
        y1 = min(h, int(np.ceil(pts[:, 1].max())) + 5)
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            gray = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            mag = np.hypot(gx, gy)
            thresh = float(np.percentile(mag, 75))
            strong = mag > max(thresh, 12.0)
            if np.any(strong):
                theta = np.arctan2(gy[strong], gx[strong])
                rect_rad = math.radians(float(ang))
                align = np.cos(2.0 * (theta - rect_rad)) ** 2
                edge_parallelism = float(np.mean(align))
            lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
            rib_score = float(min(1.0, float(np.std(lap)) / 28.0))
    shape_score = round(0.55 * rectangularity + 0.35 * edge_parallelism + 0.10 * rib_score, 3)
    is_container = bool(rectangularity >= 0.65 and edge_parallelism >= 0.42 and shape_score >= 0.55)
    return {
        "rectangularity": round(rectangularity, 3),
        "edge_parallelism": round(edge_parallelism, 3),
        "rib_score": round(rib_score, 3),
        "shape_score": shape_score,
        "is_container_shape": is_container,
    }


def decision_ai_verify(img, candidates: list, roi=None, judge=None, config: dict | None = None) -> list:
    """Verify color-agnostic OpenCV container candidates using Decision AI (`judge_seat` / VLM / GLM)
    when available, falling back to deterministic OpenCV structural verification (`container_structure`)."""
    if not candidates:
        return candidates
    if judge is None and config and (config.get("judge") or config.get("decision_ai")):
        try:
            import judge_seat
            judge = judge_seat.from_config(config.get("judge") or config.get("decision_ai"))
        except Exception:
            judge = None
    out = []
    for cand in candidates:
        struct = cand.get("structure") or {}
        shape_ok = bool(struct.get("is_container_shape", True)) and bool(cand.get("matched", False))
        ai_verdict = {
            "mode": "opencv_structure",
            "verified": shape_ok,
            "confidence": float(struct.get("shape_score", 0.85 if shape_ok else 0.3)),
            "reason": (
                f"OpenCV container geometry {cand.get('length_mm')}x{cand.get('width_mm')}mm "
                f"(rect={struct.get('rectangularity', 1.0)}, edge={struct.get('edge_parallelism', 1.0)})"
            ),
        }
        if judge is not None and img is not None:
            try:
                _, png = cv2.imencode(".png", img)
                prompt = (
                    "Evaluate whether this candidate object is a valid graspable shipping container block "
                    "(regardless of color) based on its 3D rectangular box structure and rib geometry. "
                    f"Candidate measurement: object={cand.get('object')}, "
                    f"length_mm={cand.get('length_mm')}, width_mm={cand.get('width_mm')}, "
                    f"colour={cand.get('colour')}, centre_mm={cand.get('centre_mm')}, "
                    f"structure={json.dumps(struct)}. "
                    'Reply with JSON: {"verified": true/false, "object": "<id>", "reason": "<one sentence>"}'
                )
                reply = judge(png.tobytes(), prompt)
                parsed = json.loads(reply) if isinstance(reply, str) else dict(reply)
                ai_verdict = {
                    "mode": "decision_ai",
                    "verified": bool(parsed.get("verified", shape_ok)),
                    "object": parsed.get("object") or cand.get("object"),
                    "confidence": float(parsed.get("confidence", ai_verdict["confidence"])),
                    "reason": str(parsed.get("reason") or ai_verdict["reason"]),
                }
            except Exception as exc:
                ai_verdict["ai_fallback_error"] = str(exc)
        out.append({**cand, "decision_ai": ai_verdict})
    return out


def want_reason(want: dict | None, o: dict) -> str | None:
    """None when `o` satisfies `want` ({'object': ..., 'colour': ...}), else why it was filtered out."""
    if not want:
        return None
    objs = _colour_set(want.get("object") or want.get("objects"))
    if objs and "any" not in objs and "*" not in objs and str(o.get("object") or "").lower() not in objs:
        return f"wanted object {','.join(sorted(objs))}, got {o.get('object')}"
    cols = _colour_set(want.get("colour") or want.get("color") or want.get("colours"))
    if cols and "any" not in cols and "*" not in cols and str(o.get("colour") or "").lower() not in cols:
        return f"wanted colour {','.join(sorted(cols))}, got {o.get('colour')}"
    return None


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
    kernel = np.zeros((2 * n + 1, 2 * n + 1), np.uint8)
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


def outline(px, results: list, catalog: list, camera: dict, surface_z: float):
    """Convex outline of an object's own image area: the pixels found plus where their tops meet the surface, so the
    side faces the camera sees belong to the object."""
    pts = np.asarray(px, float)
    heights = [o["top_height_mm"] for o in catalog if o["id"] in {r.get("object") for r in results}] or [
        o["top_height_mm"] for o in catalog
    ]
    if "center_px" in camera and "height_m" in camera:
        c, big_h = np.asarray(camera["center_px"], float), camera["height_m"] - surface_z
        base = c + (pts - c) * (big_h - max(heights) / 1000.0) / big_h
        pts = np.vstack([pts, base])
    return cv2.convexHull(pts.astype(np.int32)).reshape(-1, 2)
