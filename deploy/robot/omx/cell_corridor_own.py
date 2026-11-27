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
- `low_cargo` (the fold only, when the config names a `catalog_path`): a catalogue object whose top the depth camera
  measures well under the travel floor may pass under high travel, as in the placement check; cargo on the ship lies
  under every fold path (2026-11-27 runs 7-9). A catalogue match alone cannot tell a stack's height (a two-tier stack
  matched as one container), so no depth, no match or a tall top excuses nothing.
- `with_outside` (the fold only): a lane that leaves the ROI is unseen there, not clear.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

import cell_params as prm

PAD_PX = 1024  # wider than any top frame; shortcut: a lane further than this from the ROI is not counted
KNOWN_MARGIN_M = 0.015  # a known object's measured top stays this far under the travel floor (corridor.clear_z_m)
DEPTH_FRAMES = 3  # every one must agree; taken fresh at each look
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


def low_cargo(config: dict, calibration: dict, img, roi, shape, params=None):
    """0/1 mask (ROI-sized) of catalogue objects whose top, by the depth camera, is at least KNOWN_MARGIN_M under the
    travel floor on every frame; None without `config["catalog_path"]` or a usable depth read. The top is an absolute
    height (the camera's calibrated height less its measured distance), so a deck covered by cargo needs no bare patch
    of its own; but some measured surface must show its bare height where the calibration puts it on every frame
    (`cell_free_source`'s own check), or the depth and the calibration disagree and nothing is excused. The depth is
    registered to the colour image by the D435 factory record only: the edge-aligned fallback of
    `cell_depth_pose.cal_eval_depth_setup` read a 29 mm container top 20-30 mm low on 7 of 18 live frames (2026-11-28)."""
    import cv2

    import cell_corridor
    import cell_depth_pose
    import cell_free_source as fs
    import cell_objects
    import cell_pivot

    try:
        path = config.get("catalog_path")
        frames = fs._depth_frames(config, DEPTH_FRAMES)[0] if path else None
        if frames is None or not len(frames):
            return None
        camera, catalog = config["cameras"]["top"], cell_objects.load_catalog(Path(str(path)).expanduser())
        factory = fs._load(Path(str(camera["d435_factory"])).expanduser())  # no edge-aligned fallback: see the docstring
        if not isinstance(factory, dict):
            return None
        if "stream.depth" in factory:
            # shortcut: cell_depth_pose.calibration does not read the cell record's flat keys, so every other depth
            # caller still falls back to edge alignment; move this there once those callers are checked against it
            factory = {**factory, "stream": {"depth": factory["stream.depth"], "color": factory["stream.color"]}}
        depth_roi = {"roi": tuple(camera["depth_roi"])} if camera.get("depth_roi") else {}
        maps = [(h, np.eye(3), plane, float(plane["height_mm"]) if plane.get("ok") else None)
                for h, plane in (cell_depth_pose.height_map_in_colour(f, factory, **depth_roi) for f in frames)]
        if any(m[3] is None or m[0].shape != img.shape[:2] for m in maps):  # no table plane, or not the colour grid
            return None
        floor_mm = (prm.get(params, "corridor.clear_z_m", cell_corridor.CLEAR_Z_M) - KNOWN_MARGIN_M) * 1000.0
        camera_mm = float(camera["height_m"]) * 1000.0
        out, surfaces = np.zeros(shape[:2], np.uint8), {}
        for name, site in (config.get("sites") or {}).items():
            poly = site.get("surface_px") if isinstance(site, dict) else None
            if poly and poly not in [s["surface_px"] for _, s in surfaces.values()]:
                surfaces[name] = (name, site)

        def agrees(site) -> bool:  # this surface's bare height sits where the calibration puts it, on every frame
            over_mm = camera_mm - float(site["surface_z"]) * 1000.0
            bare = [fs._mode(fs._sample(m[0], m[1], fs._polygon_pts(site["surface_px"], img.shape))) for m in maps]
            return all(h is not None and share >= fs.MODE_SHARE and abs(m[3] - h - over_mm) <= fs.REF_TOL_MM
                       for (h, share), m in zip(bare, maps))

        if not any(agrees(site) for _, site in surfaces.values()):
            return out
        for name, site in surfaces.values():
            for o in cell_objects.detect(img, roi, cell_pivot.map_record(calibration, name), camera, catalog,
                                         site.get("surface_z", 0.0), params, site["surface_px"], site.get("surface_lab")):
                if not (o.get("matched") and o.get("hull_px")):
                    continue
                hull = np.asarray(o["hull_px"], np.int32)
                face = np.zeros(img.shape[:2], np.uint8)
                cv2.fillPoly(face, [hull], 1)
                ys, xs = np.nonzero(face)
                tops = [fs._sample(m[0], m[1], np.c_[xs, ys].astype(float)) for m in maps]
                if any(len(t) < max(fs.MIN_FACE_PX, len(xs) // 4) for t in tops):
                    continue  # depth holes: not measured (the factory projection fills about 0.4 of colour pixels)
                # the 95th percentile: a hand or a taller neighbour over part of the outline counts as its top
                if max(float(np.percentile(t, 95)) + camera_mm - m[3] for t, m in zip(tops, maps)) <= floor_mm:
                    cv2.fillPoly(out, [hull - [roi[0], roi[1]]], 1)
        return out
    except Exception:  # noqa: BLE001 - a broken catalogue, map or depth read excuses nothing; the fold judges as before
        return None


def fold_view(config: dict, calibration: dict, site: str, to_px, pose, img, shape, roi, tcp_x_m=None, params=None) -> dict:
    """What only the fold tells `cell_corridor.check`: its own links and the cargo measured low enough to pass over."""
    return {"own": own_mask(config, site, to_px, (pose,), shape, roi, tcp_x_m),
            "known": low_cargo(config, calibration, img, roi, shape, params)}


def with_outside(verdict: dict, tcp, to_px, shape, roi, params=None) -> dict:
    """The verdict with the lane's pixels outside the ROI counted as unseen. `cell_corridor.corridor` draws only inside
    the ROI, so what leaves it was never looked at: arm_a's fold on 2026-11-27 16:51 passed a belt-sized ROI with
    95 % of its lane outside it."""
    import cell_corridor

    get = lambda k, d: prm.get(params, k, d)  # noqa: E731
    low, high = cell_corridor.runs(tcp, get("corridor.clear_z_m", cell_corridor.CLEAR_Z_M),
                                   get("corridor.base_m", cell_corridor.BASE_M))
    h, w = shape[:2]
    lane = cell_corridor.corridor(low + high, to_px, (h + 2 * PAD_PX, w + 2 * PAD_PX),
                                  (roi[0] - PAD_PX, roi[1] - PAD_PX),
                                  get("corridor.half_width_mm", cell_corridor.HALF_WIDTH_MM))
    lane[PAD_PX:PAD_PX + h, PAD_PX:PAD_PX + w] = 0
    outside = int(lane.sum())
    return dict(verdict, clear=False, off_surface=verdict["off_surface"] + outside) if outside else verdict


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
