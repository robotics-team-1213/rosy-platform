"""Top-camera pixels <-> arm coordinates for one cell surface, measured by the arm itself (D-872).

The arm places the box at known arm points on a surface (the Pinky tray, the belt) and the top camera
measures where the box landed; an affine map per surface maps the box centre in the image to the arm's
x, y at that surface's height. Each surface has its own map: the tray and the belt sit at different
heights, so one map would carry the parallax of the other. The leave-one-out error says how far a box
seen by the camera may be from where the arm will reach for it.

  rosy.omx-cell-calibration.v1: {"schema", "sites": {"<site>": {"homography": 3x3, "points": [...],
                                 "loo_error_mm": {"max", "mean"}, "measured": "<utc>"}},
                                 "surfaces": {"<name>": {"kind": "fixture" | "object", "points": [[x, y, z]],
                                 "measured": "<utc>"}}}

The camera has no depth, so heights come from the arm too: closed jaws descend until the contact hold stops
them, and the forward kinematics of that pose is the surface height there (2026-10-27). A fixture (Pinky
tray, belt) keeps its heights between sessions; an object is measured again whenever it may have moved.
Where nothing was measured, surface_z returns None and the caller probes there instead of guessing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

SCHEMA = "rosy.omx-cell-calibration.v1"
MIN_POINTS = 5  # an affine map needs 3; more leave a real leave-one-out check


def fit(points) -> np.ndarray:
    """points: [((px, py), (x_m, y_m)), ...] -> 3x3 pixel -> metre map, affine (last row 0 0 1).

    The top camera looks straight down at a few centimetres of surface, so perspective across one surface
    is small; a full homography's two extra terms fitted noise instead. On a 10 mm grid with half a pixel
    of detection noise it put a box found just outside the grid several millimetres off (2026-10-25 test)."""
    if len(points) < 3:
        raise ValueError("a map needs at least 3 points")
    a = np.array([[u, v, 1.0] for (u, v), _ in points])
    b = np.array([[x, y] for _, (x, y) in points])
    if np.linalg.matrix_rank(a, tol=1e-6 * max(1.0, float(np.abs(a).max()))) < 3:
        raise ValueError("points are degenerate (collinear or repeated)")
    coef, *_ = np.linalg.lstsq(a, b, rcond=None)
    return np.vstack([coef.T, [0.0, 0.0, 1.0]])


def anchored(h, pairs) -> np.ndarray:
    """Re-anchor map `h` on touched points: pairs [((px, py), (x_m, y_m)), ...], at least 2. The turn and
    mirroring stay h's; the scale comes from the touched pairs' spacing, the offset from their centres. A
    box that moved a few cm was found with one touch this way (2026-10-27); 2 points cannot fit shear."""
    if len(pairs) < 2:
        raise ValueError("anchoring needs at least 2 touched points")
    h = np.asarray(h, float)
    lin = h[:2, :2] / h[2, 2]
    px, arm = np.array([p for p, _ in pairs], float), np.array([a for _, a in pairs], float)
    dpx, darm = px - px.mean(0), arm - arm.mean(0)
    scale = float(np.linalg.norm(darm) / np.linalg.norm(dpx @ lin.T))
    out = np.eye(3)
    out[:2, :2] = lin * scale
    out[:2, 2] = arm.mean(0) - out[:2, :2] @ px.mean(0)
    return out


def to_arm(h, pixel) -> tuple[float, float]:
    x, y, w = np.asarray(h, float) @ [pixel[0], pixel[1], 1.0]
    return float(x / w), float(y / w)


def to_pixel(h, point) -> tuple[float, float]:
    return to_arm(np.linalg.inv(np.asarray(h, float)), point)


def yaw_sign(h, pixel) -> int:
    """+1 when a turn in the image is the same turn about the arm's z axis, -1 when the map mirrors it."""
    origin, ex, ey = (np.asarray(to_arm(h, (pixel[0] + du, pixel[1] + dv))) for du, dv in ((0, 0), (1, 0), (0, 1)))
    return 1 if float(np.cross(ex - origin, ey - origin)) > 0 else -1


def loo_error_mm(points) -> dict:
    errors = []
    for i, ((u, v), (x, y)) in enumerate(points):
        h = fit(points[:i] + points[i + 1:])
        errors.append(1000 * math.dist(to_arm(h, (u, v)), (x, y)))
    return {"max": round(max(errors), 2), "mean": round(sum(errors) / len(errors), 2)}


def grid(center, spacing_m: float, n: int = 3) -> list:
    """n x n arm points around `center` (x, y), in a serpentine order so each step is one spacing."""
    half = (n - 1) / 2
    out = []
    for row in range(n):
        cols = range(n) if row % 2 == 0 else reversed(range(n))
        out += [(round(center[0] + (row - half) * spacing_m, 4), round(center[1] + (c - half) * spacing_m, 4))
                for c in cols]
    return out


def site_record(points, measured: str, camera_id: str | None = None) -> dict:
    if len(points) < MIN_POINTS:
        raise ValueError(f"need at least {MIN_POINTS} measured points, got {len(points)}")
    return {"homography": fit(points).round(9).tolist(), "loo_error_mm": loo_error_mm(points), "measured": measured,
            **({"camera_id": camera_id} if camera_id else {}), "points": [{"pixel": [round(u, 2), round(v, 2)], "arm_m": [x, y]} for (u, v), (x, y) in points]}


def load(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != SCHEMA or not isinstance(data.get("sites"), dict):
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    return data


SURFACE_KINDS = ("fixture", "object")
NEAR_M = 0.008  # a touch lands 3-9 mm from the commanded point; within this radius it tells the height


def surface_record(points, kind: str, measured: str) -> dict:
    if kind not in SURFACE_KINDS or not points:
        raise ValueError(f"a surface needs a kind in {SURFACE_KINDS} and at least one touched point")
    return {"kind": kind, "measured": measured, "points": [[round(float(v), 4) for v in p[:3]] for p in points]}


def surface_z(data: dict, x: float, y: float, kinds=SURFACE_KINDS):
    """(highest touched z within NEAR_M of x, y, surface name), or None where nothing was measured. The
    highest, because that is what a descent there meets first."""
    found = [(p[2], name) for name, s in (data.get("surfaces") or {}).items() if s["kind"] in kinds
             for p in s["points"] if math.hypot(p[0] - x, p[1] - y) <= NEAR_M]
    return max(found) if found else None


def save_surface(path: Path, name: str, record: dict) -> None:
    data = load(path) if Path(path).exists() else {"schema": SCHEMA, "sites": {}}
    data.setdefault("surfaces", {})[name] = record
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def save(path: Path, site: str, record: dict) -> None:
    data = load(path) if Path(path).exists() else {"schema": SCHEMA, "sites": {}}
    data["sites"][site] = record
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def jaw_pixel(closed, opened, threshold: int = 30, min_area: int = 40):
    """Where the jaws are in the top view: only the fingers move between a closed and an open frame, so
    the changed pixels are the jaws. Returns (cx, cy) or None."""
    import cv2

    diff = cv2.absdiff(cv2.cvtColor(closed, cv2.COLOR_BGR2GRAY), cv2.cvtColor(opened, cv2.COLOR_BGR2GRAY))
    mask = cv2.morphologyEx((diff > threshold).astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(mask)
    if len(xs) < min_area:
        return None
    return float(xs.mean()), float(ys.mean())


def parallax(pixel, from_z: float, to_z: float, camera: dict):
    """The pixel a point at height `from_z` would have at `to_z` straight below or above it, for a camera
    looking down from camera["height_m"] with its optical centre at camera["center_px"]."""
    cx, cy = camera["center_px"]
    scale = (camera["height_m"] - from_z) / (camera["height_m"] - to_z)
    return cx + (pixel[0] - cx) * scale, cy + (pixel[1] - cy) * scale
