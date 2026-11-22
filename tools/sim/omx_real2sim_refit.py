"""Refit the top camera's pose from a frame when it moved (USB reconnect): PnP on the printed pads' +x ends, whose world
positions the layout knows (the same anchors omx_real2sim_comp.calibrate_top_camera uses), with the D435's factory focal
length (f 618.5 px at 480 rows, not the surveyed 615) held fixed. Gates refuse a fit the anchors do not support (in-sample rms, an off-plane
hold-out, leave-one-out) or whose pad-size check through the fitted pose still fails;
the pose lands in the snapshot (camera.top, camera_fit) and Layout(top_camera="snapshot") renders from it."""
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_real2sim_helpers as h  # noqa: E402

FACTORY_F_PX = 618.5   # D435 colour intrinsics at 480 rows (memory d435-depth-via-v4l2: 618.5, not 615)
GATE_MM = 3.0          # rms of the anchors' plane error after the fit, and the pad-size check through it; above this the fit is refused
HOLDOUT_MM = 6.0       # a held-out or left-out anchor must land within twice the in-sample gate
ITERATIONS = 4        # re-extract and refit this many times per start pose
MIN_ANCHORS = 4        # a pose needs at least four non-partial pad ends


def solve_pose(world, pixels, start, size, f_px=FACTORY_F_PX):
    """-> (camera dict, rms_px) for world points (N,3) seen at pixels (N,2), seeded from the `start` camera dict."""
    import cv2

    cam0 = h.Camera(dict(start, f_px=f_px), size)
    rot0 = np.stack([cam0.right, -cam0.up, cam0.fwd])  # world -> camera, image y down
    rvec0, _ = cv2.Rodrigues(rot0)
    k = np.array([[cam0.f, 0, size[1] / 2], [0, cam0.f, size[0] / 2], [0, 0, 1]], float)
    ok, rvec, tvec = cv2.solvePnP(np.asarray(world, float), np.asarray(pixels, float), k, None, rvec0, (-rot0 @ cam0.eye).reshape(3, 1),
                                  useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("solvePnP did not converge")
    rot, _ = cv2.Rodrigues(rvec)
    eye = -rot.T @ tvec.ravel()
    reproj, _ = cv2.projectPoints(np.asarray(world, float), rvec, tvec, k, None)
    rms_px = float(np.sqrt(np.mean(np.sum((reproj.reshape(-1, 2) - pixels) ** 2, axis=1))))
    reach = float(np.linalg.norm(np.array(start["focus"], float) - np.array(start["eye"], float)))
    cam = dict(start, eye=[round(float(v), 4) for v in eye], focus=[round(float(v), 4) for v in eye + rot[2] * reach],
               up=[round(float(v), 4) for v in -rot[1]], f_px=f_px)
    return cam, rms_px


def fit_anchors(pads, start, size):
    """One fit of anchor dicts (true_plus, uv_plus, z) from `start`. Anchors above the pad plane (seated container tops) are held out
    when four pad-plane anchors remain: the fit never sees them, so their plane error at their own height is an off-plane check.
    -> dict(camera, rms_mm, rms_px, anchors, held_mm, loo_mm)."""
    z0 = min(p["z"] for p in pads)
    plane = [p for p in pads if p["z"] - z0 < 1e-3]
    held = [p for p in pads if p["z"] - z0 >= 1e-3] if len(plane) >= MIN_ANCHORS else []
    used = plane if held else pads
    err = lambda cam, p: float(np.linalg.norm(h.Camera(cam, size).to_plane(p["uv_plus"], p["z"])[0] - p["true_plus"])) * 1000  # noqa: E731
    cam, rms_px = solve_pose([(*p["true_plus"], p["z"]) for p in used], [p["uv_plus"] for p in used], start, size)
    rms_mm = math.sqrt(np.mean([err(cam, p) ** 2 for p in used]))
    loo = None
    if len(used) > MIN_ANCHORS:  # leave one out: a pose six anchors determine must still place the one it did not see
        loo = max(err(solve_pose([(*q["true_plus"], q["z"]) for q in used if q is not p], [q["uv_plus"] for q in used if q is not p],
                                 start, size)[0], p) for p in used)
    return dict(camera=cam, rms_mm=round(rms_mm, 2), rms_px=round(rms_px, 2), anchors=len(used),
                held_mm=round(max(err(cam, p) for p in held), 2) if held else None, loo_mm=round(loo, 2) if loo is not None else None)


def refit_top_camera(frame, layout, starts):
    """Fit from each start camera dict and keep the best. -> dict(ok, why, camera, rms_mm, rms_px, anchors, held_mm, loo_mm, start)."""
    from omx_real2sim_comp_helpers import _extract_anchors

    size, best = frame.shape[:2], None
    for name, start in starts.items():
        for _ in range(ITERATIONS):  # the pad ends are read through the pose being fitted: refit until they stop moving
            cam_nom = h.Camera(dict(start, f_px=FACTORY_F_PX), size)
            pads = [p for p in _extract_anchors(frame, layout, cam_nom)[0] if not p["partial"]]
            if len(pads) < MIN_ANCHORS:
                break
            try:
                got = fit_anchors(pads, start, size)
            except ValueError:
                break
            # shortcut: the best start is the lowest rms, and each start reads its own anchor set; the gates below judge it, not the ranking
            if best is None or got["rms_mm"] < best["rms_mm"]:
                best = dict(got, start=name)
            start = got["camera"]
    if best is None:
        return dict(ok=False, why=f"fewer than {MIN_ANCHORS} unclipped pad ends seen from any start pose", camera=None)
    why = ("" if best["rms_mm"] <= GATE_MM else f"anchor residual {best['rms_mm']} mm above the {GATE_MM} mm gate"
           ) or ("" if best["held_mm"] is None or best["held_mm"] <= HOLDOUT_MM else f"held-out container-top anchor {best['held_mm']} mm off, above {HOLDOUT_MM} mm"
                 ) or ("" if best["loo_mm"] is None or best["loo_mm"] <= HOLDOUT_MM else f"leave-one-out anchor {best['loo_mm']} mm off, above {HOLDOUT_MM} mm")
    return dict(best, ok=not why, why=why and f"{why}: not used", f_px=FACTORY_F_PX)


def apply_refit(top, layout, tp, prev_plates, motion, moved_ok, starts, *, anchor_lanes=None):
    """The measure() camera step: refit when the camera moved or the pad-size check failed, re-run that check through the fitted pose and
    keep the pose only when it passes. A refused refit stops the measurement (the old pose is already known to fail), unless
    moved_ok, which is recorded. -> (temp-plates result, camera_fit or None); `layout` carries the fitted pose when it was kept."""
    worst = lambda r: max((r.get("camera_check") or {}).get("worst_mm") or [99.0])  # noqa: E731
    if not (motion.get("moved") or motion.get("refit_required") or worst(tp) > GATE_MM):
        return tp, None
    fit_layout = layout
    if anchor_lanes is not None:
        from copy import copy

        fit_layout = copy(layout)
        fit_layout.sites = dict(layout.sites)
        for name, (x, y, yaw) in anchor_lanes.items():
            fit_layout.sites[name] = dict(layout.sites[name], xy=(x, y), yaw=yaw)
    fit = refit_top_camera(top, fit_layout, starts)
    if fit["ok"]:
        old = layout.fixture["real_cameras"]
        layout.fixture["real_cameras"] = dict(old, top=fit["camera"])
        after = h.measure_temp_plates(top, layout, prev_plates)
        if worst(after) <= GATE_MM:
            return after, dict(fit, pad_check_mm=worst(after))
        layout.fixture["real_cameras"] = old  # the fit passed its anchors but the pad sizes through it still fail
        fit = dict(fit, ok=False, why=f"pad-size check through the fitted pose {worst(after)} mm, above the {GATE_MM} mm gate: not used")
    if not moved_ok:
        raise SystemExit(f"top camera refit refused ({fit['why']}); measuring through the old pose (pad check {worst(tp)} mm, motion {motion}) "
                         "would put wrong lanes in the snapshot: re-survey it (G-19, calibration step 3); --camera-moved-ok measures anyway and records it")
    return tp, dict(fit, moved_ok=True)
