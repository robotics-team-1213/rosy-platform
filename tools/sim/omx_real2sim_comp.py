"""Closed-loop Real-to-Sim and Sim-to-Real compensation for the two-arm OMX cell.

Bridges two runtime gaps when reality and simulation diverge during execution:
1. Camera extrinsic drift / angle-position perturbation (G-19, G-24):
   - `perturbed_camera_dict` / `apply_world_camera`: injects a controlled 6-DoF position/angle shift into the top camera.
   - `calibrate_top_camera` & `perceive_container`: recovers the 6-DoF top-camera extrinsics online from in-frame static
     cell anchors (the v11 temporary plate lane pads at `deck_z` and the belt strip stop/centreline/slope at `belt_top`)
     before back-projecting a picked container's pose.
2. Physical servo dynamics / friction / gravity-sag differences (G-20, G-23):
   - `ServoCompensator`: paces trajectories to each joint's physical torque/damping terminal speed (`pace_seconds`),
     applies uncompensated-gravity feedforward and bounded waypoint integral trim to cancel Coulomb friction deadbands
     (`frictionloss`), low-gain servo droop (`registers-20261109`, `servo-friction-20261109`), payload weight sag,
     and small joint-zero offsets (`zero_error`), paired with closed-loop waypoint settling (`settle_g`).
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


def _extract_anchors(bgr: np.ndarray, layout: Any, cam_nom: r2s.Camera) -> tuple[list[dict[str, Any]], np.ndarray | None]:
    """Find temporary-plate pad blobs (including bottom-clipped v11 pads) and dark belt pixels in `bgr`."""
    import cv2

    pad_z = layout.deck_z + 0.0006
    pad_l = 0.096
    raw_pads: dict[str, list[dict[str, Any]]] = {"a": [], "b": []}
    for kind, px in r2s.blobs(bgr):
        if kind != "pad":
            continue
        xy, yaw, sz = r2s.rect(cam_nom.to_plane(px, pad_z))
        if not (0.038 <= sz[0] <= 0.118 and 0.020 <= sz[1] <= 0.042):
            continue
        at_bottom = int(px[:, 1].max()) >= bgr.shape[0] - 2 and int(px[:, 1].min()) > 2
        if at_bottom and sz[0] < pad_l:
            sh = (pad_l - sz[0]) / 2.0
            xy = (xy[0] - sh * math.cos(yaw), xy[1] - sh * math.sin(yaw))
        partial = sz[0] < 0.082 and not at_bottom
        raw_pads["a" if xy[1] < 0.0 else "b"].append(dict(xy=xy, yaw=yaw, partial=partial))

    matched_pads: list[dict[str, Any]] = []
    for tag in ("a", "b"):
        items = sorted(raw_pads[tag], key=lambda item: item["xy"][1])
        lanes = [(k, layout.sites[f"tmp-{tag}-{k}"]["xy"], r2s.fold(layout.sites[f"tmp-{tag}-{k}"]["yaw"])) for k in (1, 2, 3)]
        if len(items) == 3:
            pairs = list(zip(items, lanes))
        else:
            pairs = []
            for item in items:
                lane = min(lanes, key=lambda ln: math.dist(item["xy"], ln[1]))
                if math.dist(item["xy"], lane[1]) < 0.048:
                    pairs.append((item, lane))
        for item, (k, true_xy, true_yaw) in pairs:
            uv_c = np.asarray(cam_nom.project((*item["xy"], pad_z)), float)
            u_end = np.asarray(cam_nom.project((item["xy"][0] + 0.035 * math.cos(item["yaw"]),
                                                item["xy"][1] + 0.035 * math.sin(item["yaw"]), pad_z)), float)
            matched_pads.append(dict(tag=tag, lane=k, uv_c=uv_c, uv_end=u_end, true_xy=true_xy,
                                     true_yaw=true_yaw, partial=item["partial"], z=pad_z))

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
    return matched_pads, belt_uv


def calibrate_top_camera(bgr: np.ndarray, layout: Any) -> tuple[r2s.Camera, dict[str, Any]]:
    """Estimate online 6-DoF top-camera extrinsic correction from visible cell anchors (pads + belt)."""
    base_cam = layout.fixture["real_cameras"]["top"]
    size = (bgr.shape[0], bgr.shape[1])
    cam_nom = r2s.Camera(base_cam, size)
    pads, belt_uv = _extract_anchors(bgr, layout, cam_nom)
    belt_nom = _measure_belt_fiducial(belt_uv, cam_nom, layout) if belt_uv is not None else None
    n_anchors = len(pads) + int(belt_nom is not None)
    if n_anchors < 1:
        return cam_nom, dict(moved=False, anchors_used=0, raw_err_mm=0.0, cal_err_mm=0.0)

    def anchor_errors(cam: r2s.Camera) -> list[float]:
        errs: list[float] = []
        for pad in pads:
            xy_c = cam.to_plane(pad["uv_c"], pad["z"])[0]
            xy_e = cam.to_plane(pad["uv_end"], pad["z"])[0]
            yaw = r2s.fold(math.atan2(xy_e[1] - xy_c[1], xy_e[0] - xy_c[0]))
            w_pos = 0.4 if pad["partial"] else 1.0
            errs.extend([w_pos * (xy_c[0] - pad["true_xy"][0]), w_pos * (xy_c[1] - pad["true_xy"][1]), 0.045 * r2s.fold(yaw - pad["true_yaw"])])
        if belt_uv is not None:
            bf = _measure_belt_fiducial(belt_uv, cam, layout)
            if bf is not None:
                errs.extend([bf["dx"] * 2.0, bf["dy"] * 2.0, 0.090 * bf["dyaw"] * 2.0])
        return errs

    raw_res = np.array(anchor_errors(cam_nom), float)
    raw_err_mm = float(np.sqrt(np.mean(raw_res ** 2)) * 1000.0)
    if raw_err_mm <= 1.8:
        return cam_nom, dict(moved=False, anchors_used=n_anchors, raw_err_mm=round(raw_err_mm, 2), cal_err_mm=round(raw_err_mm, 2),
                             belt_residual=dict(dx=0.0, dy=0.0, dyaw=0.0))

    def objective(p: np.ndarray) -> np.ndarray:
        cam = _camera_from_params(base_cam, size, p)
        reg = np.array([p[0] * 0.05, p[1] * 0.05, p[2] * 0.25, p[3] * 0.05, p[4] * 0.05, p[5] * 0.05])
        return np.concatenate([anchor_errors(cam), reg])

    lo = np.array([-0.045, -0.045, -0.030, -0.08, -0.08, -0.10])
    hi = np.array([0.045, 0.045, 0.030, 0.08, 0.08, 0.10])
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
        step = -np.linalg.solve(J.T @ J + 1e-3 * np.eye(6), J.T @ r)
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
    return cam_cal, dict(
        moved=True,
        anchors_used=n_anchors,
        raw_err_mm=round(raw_err_mm, 2),
        cal_err_mm=round(cal_err_mm, 2),
        eye_shift_mm=[round(float(v) * 1000.0, 2) for v in p[:3]],
        rot_shift_deg=[round(math.degrees(float(v)), 2) for v in p[3:6]],
        belt_residual=belt_res,
    )


def _box_on_plane(cam: r2s.Camera, px: np.ndarray, top_z: float, box_l: float, box_w: float) -> tuple[tuple[float, float], float, tuple[float, float]]:
    xy, yaw, sz = r2s.rect(cam.to_plane(px, top_z))
    for idx, ref, vec in ((0, box_l, (math.cos(yaw), math.sin(yaw))), (1, box_w, (-math.sin(yaw), math.cos(yaw)))):
        if sz[idx] > ref:  # oblique end/side wall widens the contour toward the camera eye
            sh = (0.5 if (cam.eye[0] - xy[0]) * vec[0] + (cam.eye[1] - xy[1]) * vec[1] >= 0 else -0.5) * (sz[idx] - ref)
            xy = (xy[0] - sh * vec[0], xy[1] - sh * vec[1])
            sz = (ref, sz[1]) if idx == 0 else (sz[0], ref)
    return xy, yaw, sz


def perceive_container(bgr: np.ndarray, sa: dict[str, Any], true_xy: Any, true_yaw: float, layout: Any) -> tuple[tuple[float, float], float, dict[str, Any]] | None:
    """Detect a container at `sa` in `bgr` after online 6-DoF anchor calibration of the top camera."""
    import cv2

    cam_nom = r2s.Camera(layout.fixture["real_cameras"]["top"], (bgr.shape[0], bgr.shape[1]))
    cam, cam_comp = calibrate_top_camera(bgr, layout)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    top_z, box_l, box_w = sa["z"] + layout.box[2] / 2, layout.box[0], layout.box[1]
    bres = cam_comp.pop("belt_residual", dict(dx=0.0, dy=0.0, dyaw=0.0))
    cands = []
    for kind, px in r2s.blobs(bgr):
        if kind != "container":
            continue
        xy, yaw, sz = _box_on_plane(cam, px, top_z, box_l, box_w)
        if cam_comp.get("moved") and sa["kind"] == "belt":
            xy = (xy[0] - bres["dx"], xy[1] - bres["dy"])
            yaw = r2s.fold(yaw - bres["dyaw"])
        if math.dist(xy, sa["xy"]) <= 0.045 and 0.040 <= sz[0] <= 0.125:
            cx, cy = int(round(px[:, 0].mean())), int(round(px[:, 1].mean()))
            h = float(np.median(hsv[max(0, cy - 2):cy + 3, max(0, cx - 2):cx + 3, 0]))
            col = "red" if h < 6 or h >= 160 else "orange" if h < 22 else "green" if h < 90 else "purple"
            cands.append((math.dist(xy, true_xy), xy, yaw, sz, col, px))
    if not cands:
        return None
    _, xy, yaw, sz, col, best_px = min(cands, key=lambda x: x[0])
    if cam_comp.get("moved"):
        raw_xy, raw_yaw, _ = _box_on_plane(cam_nom, best_px, top_z, box_l, box_w)
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
    """Closed-loop joint tracking compensator for low-gain servos, Coulomb friction, and uncompensated gravity sag."""

    def __init__(self, world: Any, fps: int = 15):
        self.world = world
        self.fps = fps
        self.trim: dict[str, np.ndarray] = {arm: np.zeros(5) for arm in world.q}
        self.prev_ref: dict[str, np.ndarray] = {}
        self.max_trim_rad: dict[str, float] = {arm: 0.0 for arm in world.q}

    def reset_arm(self, arm: str) -> None:
        self.trim[arm] = np.zeros(5)
        self.max_trim_rad[arm] = 0.0

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

            # 2. Waypoint integral trim for Coulomb friction (`frictionloss`), payload sag, and joint-zero error
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
