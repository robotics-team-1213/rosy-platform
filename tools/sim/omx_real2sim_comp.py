"""Closed-loop Real-to-Sim and Sim-to-Real compensation for the two-arm OMX cell.

Bridges runtime gaps when reality and simulation diverge during execution:
1. Camera extrinsic drift / angle-position perturbation (G-19, G-24):
   - `perturbed_camera_dict` / `apply_world_camera`: injects a controlled 6-DoF position/angle shift into the top camera.
   - `calibrate_top_camera` & `perceive_container`: recovers the 6-DoF top-camera extrinsics online from in-frame cell
     anchors (unclipped `+x` ends of v11 temporary-plate dark pads at `deck_z`, seated temporary-lane containers at known
     pocket coordinates, and the belt strip stop/centreline/slope at `belt_top`), segments containers per colour so
     adjacent or multi-tier containers never merge, and restores bottom-clipped (`row 479`) containers on the v11 plates.
2. Physical servo dynamics / friction / gravity-sag / joint-zero differences (G-20, G-23):
   - `ServoCompensator`: paces trajectories to each joint's physical torque/damping terminal speed (`pace_seconds`),
     applies uncompensated-gravity feedforward, bounded waypoint integral trim (`settle_g`), and hand-eye joint-zero
     offset compensation (`calibrate_zero_offset`).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

import omx_real2sim as r2s

BELT_STOP_EDGE_OFFSET_M = 0.0080  # 2 mm belt_stop half-width + 3 mm perspective occlusion of 8 mm stop + 3 mm 1st-percentile offset
DEFAULT_CAM_JITTER = dict(eye_shift_m=(0.012, -0.010, 0.008), focus_shift_m=(0.015, -0.012, 0.0), roll_deg=1.2)


def rodrigues(rvec: np.ndarray) -> np.ndarray:
    """3x3 rotation matrix from a 3-vector axis-angle `rvec` (rad)."""
    theta = float(np.linalg.norm(rvec))
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    K = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * (K @ K)


def perturbed_camera_dict(
    base_cam: dict[str, Any],
    eye_shift_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
    focus_shift_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
    roll_deg: float = 0.0,
) -> dict[str, Any]:
    """Return a copy of `base_cam` with shifted `eye`, shifted `focus`, and rolled `up` vector."""
    eye = np.array(base_cam["eye"], float) + np.asarray(eye_shift_m, float)
    focus = np.array(base_cam["focus"], float) + np.asarray(focus_shift_m, float)
    fwd = focus - eye
    fwd /= np.linalg.norm(fwd)
    up0 = np.array(base_cam["up"], float)
    up0 = up0 - fwd * (up0 @ fwd)
    up0 /= np.linalg.norm(up0)
    up = rodrigues(fwd * math.radians(roll_deg)) @ up0
    return dict(base_cam, eye=eye.tolist(), focus=focus.tolist(), up=up.tolist())


def apply_world_camera(world: Any, cam_name: str, cam_dict: dict[str, Any]) -> None:
    """Update a compiled MuJoCo camera's `cam_pos` and `cam_quat` in `world.model` from `cam_dict`."""
    import mujoco

    cid = world.model.camera(cam_name).id
    eye = np.array(cam_dict["eye"], float)
    focus = np.array(cam_dict["focus"], float)
    fwd = focus - eye
    fwd /= np.linalg.norm(fwd)
    up = np.array(cam_dict["up"], float)
    up = up - fwd * (up @ fwd)
    up /= np.linalg.norm(up)
    right = np.cross(fwd, up)
    R = np.column_stack([right, up, -fwd])
    quat = np.empty(4)
    mujoco.mju_mat2Quat(quat, R.flatten())
    world.model.cam_pos[cid] = eye
    world.model.cam_quat[cid] = quat


def _camera_from_params(base_cam: dict[str, Any], size: tuple[int, int], p: np.ndarray) -> r2s.Camera:
    """Build an `r2s.Camera` with extrinsic perturbation `p = [dx, dy, dz, rx, ry, rz]` applied to `base_cam`."""
    cam = r2s.Camera(base_cam, size)
    R = rodrigues(p[3:6])
    cam.eye = cam.eye + p[:3]
    cam.fwd = R @ cam.fwd
    cam.up = R @ cam.up
    cam.right = R @ cam.right
    return cam


def container_blobs(bgr: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Segment containers per colour so adjacent or stacked containers of different colours never merge."""
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colour_masks = (
        ("red", (((h < 6) | (h >= 160)) & (s > 120) & (v > 120))),
        ("orange", ((h >= 6) & (h < 22) & (s > 120) & (v > 120))),
        ("yellow", ((h >= 22) & (h < 32) & (s > 135) & (v > 135))),
        ("green", ((h >= 35) & (h < 88) & (s > 110) & (v > 120))),
        ("purple", ((h >= 125) & (h < 160) & (s > 100) & (v > 115))),
    )
    out: list[tuple[str, np.ndarray]] = []
    kernel = np.ones((3, 3), np.uint8)
    for col, mask in colour_masks:
        m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        for c in cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]:
            if cv2.contourArea(c) >= 110:
                out.append((col, c.reshape(-1, 2)))
    return out


def _raw_plus_end_and_width(
    cam: r2s.Camera,
    px: np.ndarray,
    z: float,
    ref_w: float,
    expected_yaw: float | None = None,
) -> tuple[tuple[float, float], float, tuple[float, float], tuple[float, float]]:
    """Return `(xy_w_corrected, yaw, sz_raw, plus_end_xy)` on plane `z` before any bottom-clipping length extension."""
    pts = cam.to_plane(px, z)
    xy, yaw, sz = r2s.rect(pts)
    raw_w = sz[1]
    if sz[1] > ref_w:
        vec_w = (-math.sin(yaw), math.cos(yaw))
        sh_w = (0.5 if (cam.eye[0] - xy[0]) * vec_w[0] + (cam.eye[1] - xy[1]) * vec_w[1] >= 0 else -0.5) * (sz[1] - ref_w)
        xy = (xy[0] - sh_w * vec_w[0], xy[1] - sh_w * vec_w[1])
    use_yaw = r2s.fold(expected_yaw) if (expected_yaw is not None and abs(r2s.fold(yaw - r2s.fold(expected_yaw))) < math.radians(12.0)) else yaw
    plus_xy = (xy[0] + 0.5 * sz[0] * math.cos(use_yaw), xy[1] + 0.5 * sz[0] * math.sin(use_yaw))
    return xy, use_yaw, (sz[0], raw_w), plus_xy


def _box_on_plane(
    cam: r2s.Camera,
    px: np.ndarray,
    top_z: float,
    box_l: float,
    box_w: float,
    img_h: int = 480,
    expected_yaw: float | None = None,
) -> tuple[tuple[float, float], float, tuple[float, float]]:
    """Back-project contour pixels `px` onto `top_z`, correcting side-wall overhang and bottom-clipped (`row 479`) length."""
    xy, yaw, sz_raw, plus_xy = _raw_plus_end_and_width(cam, px, top_z, box_w, expected_yaw)
    if sz_raw[1] < 0.021:  # reject thin side-wall slivers of occluded lower-tier (l0) containers
        return xy, yaw, (0.0, sz_raw[1])
    sz = (sz_raw[0], min(sz_raw[1], box_w))
    at_bottom = int(px[:, 1].max()) >= img_h - 2 and int(px[:, 1].min()) > 2
    if at_bottom and sz[0] < box_l:
        xy = (plus_xy[0] - 0.5 * box_l * math.cos(yaw), plus_xy[1] - 0.5 * box_l * math.sin(yaw))
        sz = (box_l, sz[1])
    elif not at_bottom and sz[0] > box_l:
        vec_l = (math.cos(yaw), math.sin(yaw))
        sh_l = (0.5 if (cam.eye[0] - xy[0]) * vec_l[0] + (cam.eye[1] - xy[1]) * vec_l[1] >= 0 else -0.5) * (sz[0] - box_l)
        xy = (xy[0] - sh_l * vec_l[0], xy[1] - sh_l * vec_l[1])
        sz = (box_l, sz[1])
    return xy, yaw, sz


def _measure_belt_fiducial(belt_uv: np.ndarray, cam: r2s.Camera, layout: Any) -> dict[str, float] | None:
    """Measure belt stop `end_x`, belt centreline `y_at_pick`, and belt angle `yaw` from unobstructed belt pixels."""
    pts = cam.to_plane(belt_uv, layout.belt_top)
    if len(pts) < 80:
        return None
    x_lo, x_hi = float(np.percentile(pts[:, 0], 45)), float(np.percentile(pts[:, 0], 93))
    if x_hi <= x_lo + 0.04:
        return None
    edges = np.linspace(x_lo, x_hi, 7)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        sub = pts[(pts[:, 0] >= a) & (pts[:, 0] < b), 1]
        if len(sub) >= 10:
            xs.append(0.5 * (a + b))
            ys.append(0.5 * (float(np.percentile(sub, 5)) + float(np.percentile(sub, 95))))
    if len(xs) < 3:
        return None
    slope, intercept = np.polyfit(np.array(xs), np.array(ys), 1)
    dyaw = float(math.atan(slope))
    pick_x = layout.sites["belt"]["xy"][0]
    y_at_pick = float(slope * pick_x + intercept)
    y_rel = pts[:, 1] - (slope * pts[:, 0] + intercept)
    outer = pts[(np.abs(y_rel) >= 0.025) & (np.abs(y_rel) <= 0.039)]
    if len(outer) < 20:
        outer = pts
    end_x = float(np.percentile(outer[:, 0], 1))
    return dict(
        end_x=end_x,
        y_at_pick=y_at_pick,
        yaw=dyaw,
        dx=end_x - (layout.belt_stop_x + BELT_STOP_EDGE_OFFSET_M),
        dy=y_at_pick - layout.belt_y,
        dyaw=dyaw,
    )


def _extract_anchors(
    bgr: np.ndarray,
    layout: Any,
    cam_nom: r2s.Camera,
    here: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], np.ndarray | None]:
    """Extract unclipped `+x` end keypoints of temporary-plate lanes (pads + seated containers) and dark belt pixels."""
    import cv2

    img_h = bgr.shape[0]
    pad_z = layout.deck_z + 0.0006
    pad_l = 0.096
    box_l, box_w, box_h = layout.box

    lane_top_z: dict[tuple[str, int], float] = {}
    if here:
        for site_name in here.values():
            if site_name.startswith("tmp-"):
                parts = site_name.split("-")
                tag, k = parts[1], int(parts[2])
                z_top = layout.sites[site_name]["z"] + box_h / 2.0
                if z_top > lane_top_z.get((tag, k), -1.0):
                    lane_top_z[(tag, k)] = z_top

    c_blobs = container_blobs(bgr)
    occupied_lanes: set[tuple[str, int]] = set(lane_top_z.keys())
    raw_seated: dict[tuple[str, int], dict[str, Any]] = {}
    for _, px in c_blobs:
        xy_rough, _, sz_r = r2s.rect(cam_nom.to_plane(px, pad_z + box_h))
        if xy_rough[0] > 0.02 or abs(xy_rough[1]) < 0.075 or sz_r[1] < 0.022 or sz_r[1] > 0.048:
            continue
        tag = "a" if xy_rough[1] < 0.0 else "b"
        lanes = [(k, layout.sites[f"tmp-{tag}-{k}"]["xy"], r2s.fold(layout.sites[f"tmp-{tag}-{k}"]["yaw"])) for k in (1, 2, 3)]
        lane = min(lanes, key=lambda ln: math.dist(xy_rough, ln[1]))
        k, true_xy, true_yaw = lane
        if math.dist(xy_rough, true_xy) < 0.045:
            occupied_lanes.add((tag, k))
            z_top = lane_top_z.get((tag, k), pad_z + box_h)
            _, yaw, sz_raw, plus_xy = _raw_plus_end_and_width(cam_nom, px, z_top, box_w, true_yaw)
            if 0.032 <= sz_raw[0] <= 0.115 and 0.022 <= sz_raw[1] <= 0.046:
                true_plus = (true_xy[0] + 0.5 * box_l * math.cos(true_yaw), true_xy[1] + 0.5 * box_l * math.sin(true_yaw))
                if math.dist(plus_xy, true_plus) < 0.042:
                    prev = raw_seated.get((tag, k))
                    if prev is None or len(px) > prev["area"]:
                        raw_seated[(tag, k)] = dict(
                            tag=tag, lane=k, plus_xy=plus_xy, yaw=yaw, true_plus=true_plus,
                            true_yaw=true_yaw, z=z_top, area=len(px), partial=False,
                        )

    raw_pads: dict[str, list[dict[str, Any]]] = {"a": [], "b": []}
    for kind, px in r2s.blobs(bgr):
        if kind != "pad":
            continue
        pts = cam_nom.to_plane(px, pad_z)
        xy, yaw, sz = r2s.rect(pts)
        if not (0.038 <= sz[0] <= 0.118 and 0.022 <= sz[1] <= 0.040):
            continue
        tag = "a" if xy[1] < 0.0 else "b"
        at_bottom = int(px[:, 1].max()) >= img_h - 2 and int(px[:, 1].min()) > 2
        plus_xy = (xy[0] + 0.5 * sz[0] * math.cos(yaw), xy[1] + 0.5 * sz[0] * math.sin(yaw))
        if at_bottom and sz[0] < pad_l:
            xy = (plus_xy[0] - 0.5 * pad_l * math.cos(yaw), plus_xy[1] - 0.5 * pad_l * math.sin(yaw))
        partial = sz[0] < 0.082 and not at_bottom
        raw_pads[tag].append(dict(xy=xy, plus_xy=plus_xy, yaw=yaw, partial=partial))

    matched_anchors: list[dict[str, Any]] = []
    for tag in ("a", "b"):
        lanes = [(k, layout.sites[f"tmp-{tag}-{k}"]["xy"], r2s.fold(layout.sites[f"tmp-{tag}-{k}"]["yaw"])) for k in (1, 2, 3)]
        found_lanes: set[int] = set()
        for item in sorted(raw_pads[tag], key=lambda it: it["xy"][1]):
            lane = min(lanes, key=lambda ln: math.dist(item["xy"], ln[1]))
            k, true_xy, true_yaw = lane
            if (tag, k) in occupied_lanes or k in found_lanes:
                continue
            true_plus = (true_xy[0] + 0.5 * pad_l * math.cos(true_yaw), true_xy[1] + 0.5 * pad_l * math.sin(true_yaw))
            if math.dist(item["plus_xy"], true_plus) < 0.045:
                found_lanes.add(k)
                uv_plus = np.asarray(cam_nom.project((*item["plus_xy"], pad_z)), float)
                in_xy = (item["plus_xy"][0] - 0.025 * math.cos(item["yaw"]), item["plus_xy"][1] - 0.025 * math.sin(item["yaw"]))
                uv_in = np.asarray(cam_nom.project((*in_xy, pad_z)), float)
                matched_anchors.append(dict(tag=tag, lane=k, uv_plus=uv_plus, uv_in=uv_in, true_plus=true_plus,
                                            true_yaw=true_yaw, partial=item["partial"], z=pad_z))
        for (t_key, k), item in sorted(raw_seated.items()):
            if t_key != tag or k in found_lanes:
                continue
            found_lanes.add(k)
            z_top = item["z"]
            uv_plus = np.asarray(cam_nom.project((*item["plus_xy"], z_top)), float)
            in_xy = (item["plus_xy"][0] - 0.025 * math.cos(item["yaw"]), item["plus_xy"][1] - 0.025 * math.sin(item["yaw"]))
            uv_in = np.asarray(cam_nom.project((*in_xy, z_top)), float)
            matched_anchors.append(dict(tag=tag, lane=k, uv_plus=uv_plus, uv_in=uv_in, true_plus=item["true_plus"],
                                        true_yaw=item["true_yaw"], partial=False, z=z_top))

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    dark = cv2.morphologyEx(((hsv[..., 2] < 95) & (hsv[..., 1] < 110)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark)
    belt_uv: np.ndarray | None = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < r2s.BELT_MIN_PX:
            continue
        ys, xs = np.nonzero(lab == i)
        uv = np.stack([xs, ys], 1)[::2]
        pts = cam_nom.to_plane(uv, layout.belt_top)
        if abs(np.median(pts[:, 1]) - layout.belt_y) < 0.075 and np.median(pts[:, 0]) > layout.belt_stop_x - 0.040:
            if belt_uv is None or len(uv) > len(belt_uv):
                belt_uv = uv
    return matched_anchors, belt_uv


def calibrate_top_camera(bgr: np.ndarray, layout: Any, here: dict[str, str] | None = None) -> tuple[r2s.Camera, dict[str, Any]]:
    """Estimate online 6-DoF top-camera extrinsic correction from visible cell anchors (`+x` lane ends + belt)."""
    base_cam = layout.fixture["real_cameras"]["top"]
    size = (bgr.shape[0], bgr.shape[1])
    cam_nom = r2s.Camera(base_cam, size)
    pads, belt_uv = _extract_anchors(bgr, layout, cam_nom, here=here)
    belt_nom = _measure_belt_fiducial(belt_uv, cam_nom, layout) if belt_uv is not None else None
    n_anchors = len(pads) + int(belt_nom is not None)
    if n_anchors < 1:
        return cam_nom, dict(moved=False, anchors_used=0, raw_err_mm=0.0, cal_err_mm=0.0,
                             belt_residual=dict(dx=0.0, dy=0.0, dyaw=0.0), plate_residuals={})

    def anchor_errors(cam: r2s.Camera) -> list[float]:
        errs: list[float] = []
        for pad in pads:
            xy_p = cam.to_plane(pad["uv_plus"], pad["z"])[0]
            xy_i = cam.to_plane(pad["uv_in"], pad["z"])[0]
            yaw = r2s.fold(math.atan2(xy_p[1] - xy_i[1], xy_p[0] - xy_i[0]))
            w_pos = 0.4 if pad["partial"] else 1.0
            errs.extend([w_pos * (xy_p[0] - pad["true_plus"][0]), w_pos * (xy_p[1] - pad["true_plus"][1]), 0.045 * r2s.fold(yaw - pad["true_yaw"])])
        if belt_uv is not None:
            bf = _measure_belt_fiducial(belt_uv, cam, layout)
            if bf is not None:
                errs.extend([bf["dx"] * 2.0, bf["dy"] * 2.0, 0.090 * bf["dyaw"] * 2.0])
        return errs

    raw_res = np.array(anchor_errors(cam_nom), float)
    raw_err_mm = float(np.sqrt(np.mean(raw_res ** 2)) * 1000.0)
    if raw_err_mm <= 1.8:
        return cam_nom, dict(moved=False, anchors_used=n_anchors, raw_err_mm=round(raw_err_mm, 2), cal_err_mm=round(raw_err_mm, 2),
                             belt_residual=dict(dx=0.0, dy=0.0, dyaw=0.0), plate_residuals={})

    def objective(p: np.ndarray) -> np.ndarray:
        cam = _camera_from_params(base_cam, size, p)
        reg = np.array([p[0] * 0.15, p[1] * 0.15, p[2] * 0.30, p[3] * 0.15, p[4] * 0.15, p[5] * 0.15])
        return np.concatenate([anchor_errors(cam), reg])

    lo = np.array([-0.035, -0.035, -0.025, -0.06, -0.06, -0.08])
    hi = np.array([0.035, 0.035, 0.025, 0.06, 0.06, 0.08])
    p = np.zeros(6, dtype=float)
    r = objective(p)
    cost = float(r @ r)
    eps = 1e-4
    for _ in range(12):
        J = np.empty((len(r), 6), dtype=float)
        for j in range(6):
            dp = p.copy()
            dp[j] += eps
            J[:, j] = (objective(dp) - r) / eps
        step = -np.linalg.solve(J.T @ J + 2e-3 * np.eye(6), J.T @ r)
        if float(np.linalg.norm(step)) < 1e-5:
            break
        improved = False
        for alpha in (1.0, 0.5, 0.25):
            cand = np.clip(p + alpha * step, lo, hi)
            r_cand = objective(cand)
            c_cand = float(r_cand @ r_cand)
            if c_cand < cost:
                p, r, cost, improved = cand, r_cand, c_cand, True
                break
        if not improved:
            break
    cam_cal = _camera_from_params(base_cam, size, p)
    cal_res = np.array(anchor_errors(cam_cal), float)
    cal_err_mm = float(np.sqrt(np.mean(cal_res ** 2)) * 1000.0)
    bf_cal = _measure_belt_fiducial(belt_uv, cam_cal, layout) if belt_uv is not None else None
    belt_res = dict(dx=bf_cal["dx"], dy=bf_cal["dy"], dyaw=bf_cal["dyaw"]) if bf_cal is not None else dict(dx=0.0, dy=0.0, dyaw=0.0)
    plate_res: dict[str, dict[str, float]] = {}
    for tag in ("a", "b"):
        tp = [pad for pad in pads if pad["tag"] == tag and not pad["partial"]]
        if tp:
            dxs = [float(cam_cal.to_plane(pad["uv_plus"], pad["z"])[0][0] - pad["true_plus"][0]) for pad in tp]
            dys = [float(cam_cal.to_plane(pad["uv_plus"], pad["z"])[0][1] - pad["true_plus"][1]) for pad in tp]
            plate_res[tag] = dict(dx=float(np.median(dxs)), dy=float(np.median(dys)))
    return cam_cal, dict(
        moved=True,
        anchors_used=n_anchors,
        raw_err_mm=round(raw_err_mm, 2),
        cal_err_mm=round(cal_err_mm, 2),
        eye_shift_mm=[round(float(v) * 1000.0, 2) for v in p[:3]],
        rot_shift_deg=[round(math.degrees(float(v)), 2) for v in p[3:6]],
        belt_residual=belt_res,
        plate_residuals=plate_res,
    )


def perceive_container(
    bgr: np.ndarray,
    sa: dict[str, Any],
    true_xy: Any,
    true_yaw: float,
    layout: Any,
    here: dict[str, str] | None = None,
) -> tuple[tuple[float, float], float, dict[str, Any]] | None:
    """Detect a container at `sa` in `bgr` after online 6-DoF anchor calibration of the top camera."""
    img_h = bgr.shape[0]
    cam_nom = r2s.Camera(layout.fixture["real_cameras"]["top"], (img_h, bgr.shape[1]))
    cam, cam_comp = calibrate_top_camera(bgr, layout, here=here)
    top_z, box_l, box_w = sa["z"] + layout.box[2] / 2, layout.box[0], layout.box[1]
    bres = cam_comp.pop("belt_residual", dict(dx=0.0, dy=0.0, dyaw=0.0))
    pres = cam_comp.pop("plate_residuals", {})
    exp_yaw = sa["yaw"] if sa["kind"] != "belt" else None
    cands = []
    for col, px in container_blobs(bgr):
        xy, yaw, sz = _box_on_plane(cam, px, top_z, box_l, box_w, img_h, exp_yaw)
        if cam_comp.get("moved"):
            if sa["kind"] == "belt":
                xy = (xy[0] - bres["dx"], xy[1] - bres["dy"])
                yaw = r2s.fold(yaw - bres["dyaw"])
            elif sa["kind"] == "temp":
                tag = "a" if sa["xy"][1] < 0.0 else "b"
                if tag in pres:
                    xy = (xy[0] - pres[tag]["dx"], xy[1] - pres[tag]["dy"])
        if math.dist(xy, sa["xy"]) <= 0.042 and 0.032 <= sz[0] <= 0.125:
            cands.append((math.dist(xy, sa["xy"]), xy, yaw, sz, col, px))
    if not cands:
        return None
    _, xy, yaw, sz, col, best_px = min(cands, key=lambda x: x[0])
    if cam_comp.get("moved"):
        raw_xy, raw_yaw, _ = _box_on_plane(cam_nom, best_px, top_z, box_l, box_w, img_h, exp_yaw)
        cam_comp = dict(
            cam_comp,
            raw_xy_err_mm=round(math.dist(raw_xy, true_xy) * 1000.0, 2),
            raw_yaw_err_deg=round(abs(math.degrees(r2s.fold(raw_yaw - true_yaw))), 2),
            correction_mm=round(math.dist(xy, raw_xy) * 1000.0, 2),
        )
    return xy, yaw, dict(
        colour=col,
        xy_err_mm=round(math.dist(xy, true_xy) * 1000.0, 2),
        yaw_err_deg=round(abs(math.degrees(r2s.fold(yaw - true_yaw))), 2),
        seen_xy=[round(xy[0], 4), round(xy[1], 4)],
        seen_yaw_deg=round(math.degrees(yaw), 1),
        size_mm=[round(sz[0] * 1000.0, 1), round(sz[1] * 1000.0, 1)],
        camera_comp=cam_comp,
    )


class ServoCompensator:
    """Closed-loop joint tracking compensator for low-gain servos, Coulomb friction, gravity sag, and joint-zero error."""

    def __init__(self, world: Any, fps: int = 15):
        self.world = world
        self.fps = fps
        self.trim: dict[str, np.ndarray] = {arm: np.zeros(5) for arm in world.q}
        self.zero_est: dict[str, np.ndarray] = {arm: np.zeros(5) for arm in world.q}
        self.prev_ref: dict[str, np.ndarray] = {}
        self.max_trim_rad: dict[str, float] = {arm: 0.0 for arm in world.q}

    def reset_arm(self, arm: str) -> None:
        self.trim[arm] = np.zeros(5)
        self.max_trim_rad[arm] = 0.0

    def calibrate_zero_offset(self, arm: str, q_true: np.ndarray, q_reported: np.ndarray) -> np.ndarray:
        """Record 5-joint encoder zero offset (`q_true - q_reported`) from visual/FK arm pose observation."""
        self.zero_est[arm] = (np.asarray(q_true[:5], float) - np.asarray(q_reported[:5], float)).copy()
        return self.zero_est[arm]

    def pace_seconds(self, arm: str, q_from: np.ndarray, q_to: np.ndarray, base_seconds: float) -> float:
        """Scale spline duration so no joint demands more than 72% of its torque-limited passive damping speed."""
        m = self.world.model
        dofs = self.world.arm_dof[arm][:5]
        acts = self.world.act[arm][:5]
        force = m.actuator_forcerange[acts, 1]
        damping = np.maximum(m.dof_damping[dofs], 0.05)
        friction = m.dof_frictionloss[dofs]
        v_terminal = np.maximum(0.05, (force - friction) / damping)
        dq = np.abs(np.asarray(q_to[:5], float) - np.asarray(q_from[:5], float))
        needed = float(np.max((1.5 / 0.72) * dq / v_terminal))
        return max(float(base_seconds), min(needed, 16.0))

    def apply(self, data: Any, targets: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Return compensated joint targets `{arm: q_cmd_6}` for one physics frame."""
        m = self.world.model
        out: dict[str, np.ndarray] = {}
        for arm, target in targets.items():
            t = np.asarray(target, float).copy()
            t[:5] = t[:5] - self.zero_est[arm]
            q_act = data.qpos[self.world.q[arm][:5]]
            dofs = self.world.arm_dof[arm][:5]
            acts = self.world.act[arm][:5]
            qvel = data.qvel[dofs]
            kp = np.maximum(m.actuator_gainprm[acts, 0], 1.0)
            force = m.actuator_forcerange[acts, 1]
            hold_set = set(int(d) for d in self.world.hold_dof[arm])

            # 1. Gravity feedforward for any arm joint without hardware I-gain (`gravity_hold != "all"`, e.g. registers-20261109)
            grav_ff = np.zeros(5)
            for j, dof in enumerate(dofs):
                if int(dof) not in hold_set:
                    grav_ff[j] = float(data.qfrc_bias[dof]) / kp[j]

            # 2. Waypoint integral trim for Coulomb friction (`frictionloss`), payload sag, and steady-state droop
            prev = self.prev_ref.get(arm, t[:5])
            ref_speed = np.abs(t[:5] - prev) * self.fps
            self.prev_ref[arm] = t[:5].copy()
            err = t[:5] - q_act
            max_auth = np.minimum(0.14, 0.85 * force / kp)
            for j in range(5):
                if ref_speed[j] < 0.03:
                    if abs(err[j]) > 0.0008:
                        step = 0.22 * err[j] - 0.03 * float(qvel[j])
                        self.trim[arm][j] = float(np.clip(self.trim[arm][j] + step, -max_auth[j], max_auth[j]))
                elif ref_speed[j] > 0.12:
                    self.trim[arm][j] *= 0.5

            total_trim = np.clip(grav_ff + self.trim[arm], -max_auth, max_auth)
            self.max_trim_rad[arm] = max(self.max_trim_rad[arm], float(np.max(np.abs(total_trim))))
            t[:5] = t[:5] + total_trim
            out[arm] = t
        return out
