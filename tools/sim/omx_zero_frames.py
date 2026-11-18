"""Read a joint-zero capture directory into one averaged observation per pose (no arm access).

Layout (a superset of cell_checkerboard capture's view-N.json/.jpg): per frame `view-<pose>-<n>.(jpg|png)` plus
`view-<pose>-<n>.json` with {"q": [5 joints], "unit": "norm"|"deg"} (default norm). Without "q", the mean of
motion_evidence.state_before/after (the existing receipt) is used. Frames of a pose share its `pose` key, else the number
in the file name. An optional `touch.json` {"q": [...], "unit": ...} is the jaw-tip-on-the-ruler pose for the table offset.
Corners come from cell_frame.corners (ArUco), refined with cv2.cornerSubPix; the camera is re-solved from the base
markers (cell_frame.camera_pose) in every frame (its spread is reported) and once from the pooled corners for the fit.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from omx_zero_model import cf, to_deg

IMAGE_EXT = (".png", ".jpg", ".jpeg")


def refine(grey, quad):
    """cornerSubPix on the four corners of one marker; the window stays well inside a small marker."""
    import cv2

    side = float(np.mean([np.linalg.norm(quad[k] - quad[k - 1]) for k in range(4)]))
    half = int(max(2, min(5, side / 5)))
    pts = quad.astype(np.float32).reshape(-1, 1, 2).copy()
    cv2.cornerSubPix(grey, pts, (half, half), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-3))
    return pts.reshape(4, 2).astype(np.float64)


def seen_refined(img):
    import cv2

    grey = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {i: refine(grey, c) for i, c in cf.corners(grey).items()}


def _q_deg(meta):
    q, unit = meta.get("q"), meta.get("unit", "norm")
    if q is None:
        ev = meta.get("motion_evidence") or {}
        q = (np.asarray(ev["state_before"], float) + np.asarray(ev["state_after"], float)) / 2
    q = np.asarray(q, float)[:5]
    if q.shape != (5,) or not np.isfinite(q).all():
        raise ValueError("frame json has no usable 5 joint values")
    return to_deg(q, unit)


def read_groups(folder):
    """{pose key: {"q_deg": 5-vector, "frames": [image paths]}} in pose order."""
    groups = {}
    for meta_path in sorted(Path(folder).glob("view-*.json")):
        img = next((meta_path.with_suffix(e) for e in IMAGE_EXT if meta_path.with_suffix(e).is_file()), None)
        if img is None:
            continue
        meta, m = json.loads(meta_path.read_text()), re.match(r"view-(\d+)[-_]\d+$", meta_path.stem)
        key = meta.get("pose", int(m.group(1)) if m else None)
        if key is None:
            raise ValueError(f"{meta_path.name}: no pose key (put \"pose\" in the json or name it view-<pose>-<n>)")
        q = _q_deg(meta)
        g = groups.setdefault(key, {"q_deg": q, "frames": []})
        if np.abs(g["q_deg"] - q).max() > 0.5:  # 0.28 norm: a settled arm; more means two poses under one key
            raise ValueError(f"{meta_path.name}: joints differ from the other frames of pose {key} by > 0.5 deg")
        g["frames"].append(img)
    return dict(sorted(groups.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else str(kv[0])))


def read_touch(folder):
    p = Path(folder) / "touch.json"
    return _q_deg(json.loads(p.read_text())) if p.is_file() else None


def session_camera(record, poses):
    """One camera for the whole capture: the base markers' corners averaged over every kept frame, solved once.
    A single frame's base-marker solve is only good to ~20 mm sideways (rotation and shift of a narrow top view trade
    off), which parallaxes a gripper marker 100 mm up by ~3 px; the camera does not move between frames. Returns
    (camera_in_base, rms px, pooled base corners)."""
    pooled = {}
    for i in record["base"]:
        rows = [(p["base_mean"][i], p["n"]) for p in poses if i in p["base_mean"]]
        if rows:
            pooled[i] = sum(c * n for c, n in rows) / sum(n for _, n in rows)
    return (*cf.camera_pose(record, pooled), pooled)


def summarise(group, record, marker_id, min_frames=5, outlier_px=3.0):
    """One pose: mean gripper-marker corners, their pooled std (px, the measured noise), the camera from the base
    markers (only their per-frame spread is kept here; see session_camera). None with the reason when it cannot be used."""
    import cv2

    seen_all, cams = [], []
    for path in group["frames"]:
        img = cv2.imread(str(path))
        if img is None or [img.shape[1], img.shape[0]] != record["size"]:
            return None, f"{path.name}: unreadable or size differs from the camera record"
        seen = seen_refined(img)
        cam, _ = cf.camera_pose(record, seen)
        if marker_id in seen and cam is not None:
            seen_all.append(seen)
            cams.append(cam)
    if len(seen_all) < min_frames:
        return None, f"marker {marker_id} and a base marker together in only {len(seen_all)} of {len(group['frames'])} frames"
    stack = np.array([s[marker_id] for s in seen_all])
    med = np.median(stack, 0)
    keep = np.linalg.norm(stack - med, axis=2).max(1) <= outlier_px
    if keep.sum() < min_frames:
        return None, f"only {int(keep.sum())} frames within {outlier_px} px of the median corners"
    seen_all, cams, stack = [s for s, k in zip(seen_all, keep) if k], [c for c, k in zip(cams, keep) if k], stack[keep]
    mean = {i: np.mean([s[i] for s in seen_all], 0) for i in seen_all[0] if all(i in s for s in seen_all)}
    n = len(stack)
    return {"q_deg": group["q_deg"], "corners": stack.mean(0), "n": n, "dropped": int((~keep).sum()), "base_mean": mean,
            "std_px": float(np.sqrt((stack.std(0, ddof=1) ** 2).mean())) if n > 1 else None,
            "camera_t_std_mm": float(1000 * np.linalg.norm(np.array([c[1] for c in cams]).std(0)))}, None
