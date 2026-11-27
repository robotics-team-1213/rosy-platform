"""The arm's own body and the unmeasured gap in the top view, for the multi-site fold corridor (2026-11-27).

arm_a stopped extended over the belt with torque OFF and every fold candidate read ALL_PATHS_BLOCKED; no fold had ever
passed on this arm. Between the measured surfaces and the arm's base lie the base plate, the table and the arm itself.
None of them is a surface with one colour, so the gap's median-colour rule called the whole gap an object, and the
gripper resting at a surface's edge counted its own footprint as unseen. Two measured facts replace that guess:
- `own_mask`: the arm's links from its measured joints (FK, the top camera's parallax). The arm is not an obstacle to
  itself and nothing else can be where its links are. Only the fold asks for it (`build_multi_site_look(own_state=)`):
  it holds the arm's space reservation and runs supervised. shortcut: a hand holding the limp arm, the other arm
  within the band, or what lies under a raised link is not seen; upgrade with the top camera's depth.
- `gap_foreground`: the gap against the reference top frame the calibration is bound to (`preflight.reference_top`,
  `reference_top_sha256`). What changed is an object, what did not is the cell's own furniture. A moved camera or
  changed light reads as changed, so it refuses. shortcut: an object the colour of what it covers, or one already in
  the reference, is not seen; upgrade with depth. No bound reference: the colour rule.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

import cell_params as prm

OWN_HALF_MM = 40.0  # a link's half width from above with its wrist camera; arm_a's real silhouette, 2026-11-27


def measured_joints(cell) -> list | None:
    """The arm's joints as the runner measures them now, or None: without them nothing is excused."""
    status = cell.act("state")
    state = status.get("state") if isinstance(status, dict) and status.get("ok") is True else None
    if not isinstance(state, list) or len(state) < 5 or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in state[:5]):
        return None
    return list(state)


def own_mask(config: dict, site: str, to_px, poses, shape, roi, tcp_x_m: float | None = None,
             half_mm: float = OWN_HALF_MM) -> np.ndarray:
    """0/1 mask (ROI-sized) of the arm's links at each pose. Empty when the site height, the top camera or a link's
    pixel is unknown: then nothing is excused."""
    import cv2

    import cell_calibration as cal
    import cell_corridor
    import grasp_planner as gp

    out = np.zeros(shape[:2], np.uint8)
    site_z = ((config.get("sites") or {}).get(site) or {}).get("z")
    camera = (config.get("cameras") or {}).get("top") or {}
    if site_z is None or camera.get("height_m") is None:
        return out
    kin = gp.load_kinematics(None, tcp_x_m)[0]
    for pose in poses:
        if pose is None or len(pose) < 5:
            continue
        points = [(0.0, 0.0, 0.0), *kin.link_points([gp.norm_to_rad(v) for v in pose[:5]])[0]]
        flat = [to_px(p[:2]) for p in points]
        radius = cell_corridor._px_radius(points[-1][:2], to_px, half_mm)
        if radius is None or any(p is None for p in flat):
            continue
        seen = [cal.parallax(p, site_z, point[2], camera) for p, point in zip(flat, points)]
        line = np.round(np.asarray(seen, float) - [roi[0], roi[1]]).astype(np.int32)
        cv2.polylines(out, [line], False, 1, max(1, int(round(2 * radius))))
        for p in line:
            cv2.circle(out, (int(p[0]), int(p[1])), int(round(radius)), 1, -1)
    return out


def _reference(config: dict, calibration: dict | None, shape):
    """The reference top frame, only when it is the file the calibration is bound to and of this frame's size."""
    import cv2

    path = (config.get("preflight") or {}).get("reference_top")
    bound = (calibration or {}).get("reference_top_sha256")
    try:
        raw = Path(str(path)).expanduser().read_bytes() if path and isinstance(bound, str) else b""
    except OSError:
        raw = b""
    if not raw or hashlib.sha256(raw).hexdigest() != bound:
        return None
    ref = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return ref if ref is not None and ref.shape == tuple(shape) else None


def gap_foreground(config: dict, calibration: dict | None, img, roi, gap: np.ndarray, params=None) -> np.ndarray:
    """0/255 mask of what stands in `gap` (bool, ROI-sized), the hull between the measured surfaces."""
    import cv2

    import cell_objects

    x0, y0, x1, y1 = roi
    gap_lab = config.get("transit_surface_lab")
    ref = None if gap_lab else _reference(config, calibration, img.shape)
    if ref is not None:  # exposure moves between frames: each channel's median shift is taken out (cell_scene_guard)
        blur = lambda frame: cv2.GaussianBlur(frame[y0:y1, x0:x1], (5, 5), 0).astype(np.int16)  # noqa: E731
        diff = blur(img) - blur(ref)
        diff -= np.median(diff.reshape(-1, 3), axis=0).astype(np.int16)
        changed = (np.abs(diff).max(axis=2) > prm.get(params, "scene.diff")).astype(np.uint8)
        changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) * 255
        changed[~gap] = 0
        return changed
    if not gap_lab:
        gap_lab = np.median(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2LAB)[gap], axis=0).tolist()
    first_lab = gap_lab[0] if isinstance(gap_lab[0], (list, tuple)) else gap_lab
    patch = img[y0:y1, x0:x1].copy()
    patch[~gap] = cv2.cvtColor(np.array([[first_lab]], np.uint8), cv2.COLOR_LAB2BGR)[0, 0]
    gap_fg = cell_objects.foreground(patch, (0, 0, x1 - x0, y1 - y0), params=params, surface_lab=gap_lab)
    gap_fg[~gap] = 0
    if not config.get("transit_surface_lab") and int((gap_fg > 0).sum()) >= 0.20 * int(gap.sum()):
        gap_fg[gap] = 255
    return gap_fg
