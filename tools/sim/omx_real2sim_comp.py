"""Closed-loop Real-to-Sim and Sim-to-Real compensation for the two-arm OMX cell.

1. Camera extrinsic drift / angle-position perturbation (G-19, G-24):
   - `perturbed_camera_dict` / `apply_world_camera`: injects 6-DoF position/angle shift into the top camera.
   - `calibrate_top_camera` & `perceive_container`: recovers 6-DoF top-camera extrinsics online from cell anchors (`+x` ends of v11 pads, seated lane containers, and belt stop/centreline/slope), segments containers per colour, and restores bottom-clipped (`row 479`) containers.
2. Physical servo dynamics / friction / gravity-sag / jitter damping / joint-zero differences (G-20, G-23):
   - `ServoCompensator`: paces trajectories (`pace_seconds`), applies gravity feedforward, waypoint integral trim (`settle_g`), active jitter damping (`jitter_state`, `is_settled`, `settled_q`), 3D Z-sag compensation (`compensate_z_target`), and joint-zero offset compensation (`calibrate_zero_offset`).
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_real2sim as r2s  # noqa: E402
from omx_real2sim_comp_helpers import (  # noqa: E402, F401
    BELT_STOP_EDGE_OFFSET_M,
    DEFAULT_CAM_JITTER,
    _box_on_plane,
    _camera_from_params,
    _extract_anchors,
    _measure_belt_fiducial,
    _raw_plus_end_and_width,
    apply_world_camera,
    container_blobs,
    perturbed_camera_dict,
    rodrigues,
)


def calibrate_top_camera(bgr: np.ndarray, layout: Any, here: dict[str, str] | None = None) -> tuple[r2s.Camera, dict[str, Any]]:
    """Estimate online 6-DoF top-camera extrinsic correction from visible cell anchors (`+x` lane ends + belt)."""
    base_cam = layout.fixture["real_cameras"]["top"]
    size = (bgr.shape[0], bgr.shape[1])
    cam_nom = r2s.Camera(base_cam, size)
    pads, belt_uv = _extract_anchors(bgr, layout, cam_nom, here=here)
    belt_nom = _measure_belt_fiducial(belt_uv, cam_nom, layout) if belt_uv is not None else None
    w_belt = 2.0
    if belt_nom is not None and len(pads) >= 2:
        p_dx = float(np.median([cam_nom.to_plane(p["uv_plus"], p["z"])[0][0] - p["true_plus"][0] for p in pads]))
        p_dy = float(np.median([cam_nom.to_plane(p["uv_plus"], p["z"])[0][1] - p["true_plus"][1] for p in pads]))
        if math.hypot(belt_nom["dx"] - p_dx, belt_nom["dy"] - p_dy) > 0.018:
            w_belt = 0.0
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
        if belt_uv is not None and w_belt > 0.0:
            bf = _measure_belt_fiducial(belt_uv, cam, layout)
            if bf is not None:
                errs.extend([bf["dx"] * w_belt, bf["dy"] * w_belt, 0.090 * bf["dyaw"] * w_belt])
        return errs

    raw_res = np.array(anchor_errors(cam_nom), float)
    raw_err_mm = float(np.sqrt(np.mean(raw_res ** 2)) * 1000.0) if len(raw_res) else 0.0
    if raw_err_mm <= 1.8:
        b_res = dict(dx=belt_nom["dx"], dy=belt_nom["dy"], dyaw=belt_nom["dyaw"]) if belt_nom is not None else dict(dx=0.0, dy=0.0, dyaw=0.0)
        b_moved = belt_nom is not None and math.hypot(belt_nom["dx"], belt_nom["dy"]) > 0.002
        return cam_nom, dict(moved=b_moved, anchors_used=n_anchors, raw_err_mm=round(raw_err_mm, 2), cal_err_mm=round(raw_err_mm, 2),
                             belt_residual=b_res, plate_residuals={})

    def objective(p: np.ndarray) -> np.ndarray:
        cam = _camera_from_params(base_cam, size, p)
        reg = np.array([p[0] * 0.15, p[1] * 0.15, p[2] * 0.30, p[3] * 0.15, p[4] * 0.15, p[5] * 0.15])
        return np.concatenate([anchor_errors(cam), reg])

    lo = np.array([-0.042, -0.042, -0.025, -0.06, -0.06, -0.08])
    hi = np.array([0.042, 0.042, 0.025, 0.06, 0.06, 0.08])
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
        moved=True, anchors_used=n_anchors, raw_err_mm=round(raw_err_mm, 2), cal_err_mm=round(cal_err_mm, 2),
        eye_shift_mm=[round(float(v) * 1000.0, 2) for v in p[:3]],
        rot_shift_deg=[round(math.degrees(float(v)), 2) for v in p[3:6]],
        belt_residual=belt_res, plate_residuals=plate_res,
    )


def perceive_container(bgr: np.ndarray, sa: dict[str, Any], true_xy: Any, true_yaw: float,
                       layout: Any, here: dict[str, str] | None = None) -> tuple[tuple[float, float], float, dict[str, Any]] | None:
    """Detect a container at `sa` in `bgr` after online 6-DoF anchor calibration of the top camera."""
    img_h = bgr.shape[0]
    cam_nom = r2s.Camera(layout.fixture["real_cameras"]["top"], (img_h, bgr.shape[1]))
    cam, cam_comp = calibrate_top_camera(bgr, layout, here=here)
    top_z, box_l, box_w = sa["z"] + layout.box[2] / 2, layout.box[0], layout.box[1]
    bres = cam_comp.pop("belt_residual", dict(dx=0.0, dy=0.0, dyaw=0.0))
    pres = cam_comp.pop("plate_residuals", {})
    exp_yaw = sa["yaw"] if sa["kind"] != "belt" else None
    exp_xy = sa["xy"] if sa["kind"] != "belt" else None
    cands = []
    for col, px in container_blobs(bgr):
        xy, yaw, sz = _box_on_plane(cam, px, top_z, box_l, box_w, img_h, exp_yaw, exp_xy)
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
        raw_xy, raw_yaw, _ = _box_on_plane(cam_nom, best_px, top_z, box_l, box_w, img_h, exp_yaw, exp_xy)
        cam_comp = dict(cam_comp, raw_xy_err_mm=round(math.dist(raw_xy, true_xy) * 1000.0, 2),
                        raw_yaw_err_deg=round(abs(math.degrees(r2s.fold(raw_yaw - true_yaw))), 2),
                        correction_mm=round(math.dist(xy, raw_xy) * 1000.0, 2))
    return xy, yaw, dict(
        colour=col, xy_err_mm=round(math.dist(xy, true_xy) * 1000.0, 2),
        yaw_err_deg=round(abs(math.degrees(r2s.fold(yaw - true_yaw))), 2),
        seen_xy=[round(xy[0], 4), round(xy[1], 4)], seen_yaw_deg=round(math.degrees(yaw), 1),
        size_mm=[round(sz[0] * 1000.0, 1), round(sz[1] * 1000.0, 1)], camera_comp=cam_comp,
    )


class ServoCompensator:
    """Closed-loop joint tracking compensator for low-gain servos, Coulomb friction, gravity/Z sag, jitter damping, and zero error."""

    def __init__(self, world: Any, fps: int = 15):
        self.world, self.fps = world, fps
        self.trim: dict[str, np.ndarray] = {arm: np.zeros(5) for arm in world.q}
        self.zero_est: dict[str, np.ndarray] = {arm: np.zeros(5) for arm in world.q}
        self.prev_ref: dict[str, np.ndarray] = {}
        self.prev_cmd: dict[str, np.ndarray] = {}
        self.err_hist: dict[str, list[np.ndarray]] = {arm: [] for arm in world.q}
        self.q_hist: dict[str, list[np.ndarray]] = {arm: [] for arm in world.q}
        self.max_trim_rad: dict[str, float] = {arm: 0.0 for arm in world.q}
        self.max_jitter_std_rad: dict[str, float] = {arm: 0.0 for arm in world.q}
        self.damped_frames: dict[str, int] = {arm: 0 for arm in world.q}
        self.z_sag_m: dict[str, float] = {arm: 0.0 for arm in world.q}

    def reset_arm(self, arm: str) -> None:
        self.trim[arm] = np.zeros(5)
        self.err_hist[arm], self.q_hist[arm] = [], []
        self.prev_cmd.pop(arm, None)
        self.max_trim_rad[arm], self.max_jitter_std_rad[arm], self.damped_frames[arm], self.z_sag_m[arm] = 0.0, 0.0, 0, 0.0

    def calibrate_zero_offset(self, arm: str, q_true: np.ndarray, q_reported: np.ndarray) -> np.ndarray:
        """Record 5-joint encoder zero offset (`q_true - q_reported`) from visual/FK arm pose observation."""
        self.zero_est[arm] = (np.asarray(q_true[:5], float) - np.asarray(q_reported[:5], float)).copy()
        return self.zero_est[arm]

    def jitter_state(self, arm: str) -> dict[str, Any]:
        """Compute rolling residual jitter metrics (`std_rad`, `std_deg`, `flips_hz`, `shaking`) for `arm`."""
        hist = self.err_hist.get(arm, [])
        if len(hist) < 4:
            return dict(shaking=False, std_rad=0.0, std_deg=0.0, flips_hz=0.0)
        arr = np.asarray(hist[-10:], float)
        std_j = np.std(arr, axis=0)
        max_std = float(np.max(std_j))
        diffs = np.diff(arr, axis=0)
        signs = np.where(np.abs(diffs) >= 0.0007, np.sign(diffs), 0.0)
        flips = np.sum(signs[1:] * signs[:-1] < 0.0, axis=0)
        flips_hz = float(np.max(flips)) * self.fps / max(1, len(arr) - 1)
        shaking = bool(max_std >= 0.0028 and flips_hz >= 2.2)
        return dict(shaking=shaking, std_rad=round(max_std, 5), std_deg=round(math.degrees(max_std), 3), flips_hz=round(flips_hz, 2))

    def settled_q(self, data: Any, arm: str) -> np.ndarray:
        """Return multi-sample averaged joint state (last 3 frames) when shaking is active, mirroring real `joint_jitter.settled_state`."""
        q_cur = data.qpos[self.world.q[arm]].copy()
        hist = self.q_hist.get(arm, [])
        if len(hist) >= 3 and self.jitter_state(arm)["shaking"]:
            q_cur[:5] = np.mean(np.asarray(hist[-3:], float), axis=0)
        return q_cur

    def is_settled(self, arm: str, q_err: float, q_vel: float, tcp_ok: bool) -> bool:
        """Oscillation-aware settle gate: prevents false settle exit at zero-velocity turnaround peaks while `shaking`."""
        return bool(q_err <= 0.0045 and q_vel <= 0.02 and tcp_ok and not self.jitter_state(arm)["shaking"])

    def compensate_z_target(self, data: Any, arm: str, pos_target: np.ndarray) -> np.ndarray:
        """Measure vertical TCP Z-sag (`pos_target[2] - tcp_z`) and return Z-compensated 3D waypoint target (`G-20`)."""
        p = np.asarray(pos_target, float).copy()
        if hasattr(self.world, "tcp"):
            tcp_z = float(self.world.tcp(data, arm)[0][2])
            dz = float(np.clip(p[2] - tcp_z, -0.012, 0.012))
            self.z_sag_m[arm] = 0.65 * self.z_sag_m.get(arm, 0.0) + 0.35 * dz
            p[2] += self.z_sag_m[arm]
        return p

    def pace_seconds(self, arm: str, q_from: np.ndarray, q_to: np.ndarray, base_seconds: float) -> float:
        """Scale spline duration so no joint demands more than 72% of its torque-limited passive damping speed."""
        m = self.world.model
        dofs, acts = self.world.arm_dof[arm][:5], self.world.act[arm][:5]
        v_terminal = np.maximum(0.05, (m.actuator_forcerange[acts, 1] - m.dof_frictionloss[dofs]) / np.maximum(m.dof_damping[dofs], 0.05))
        dq = np.abs(np.asarray(q_to[:5], float) - np.asarray(q_from[:5], float))
        return max(float(base_seconds), min(float(np.max((1.5 / 0.72) * dq / v_terminal)), 16.0))

    def apply(self, data: Any, targets: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Return compensated joint targets `{arm: q_cmd_6}` for one physics frame with gravity FF, friction trim, and active jitter damping."""
        m = self.world.model
        out: dict[str, np.ndarray] = {}
        for arm, target in targets.items():
            t = np.asarray(target, float).copy()
            t[:5] = t[:5] - self.zero_est[arm]
            q_act = data.qpos[self.world.q[arm][:5]].copy()
            dofs, acts = self.world.arm_dof[arm][:5], self.world.act[arm][:5]
            qvel = data.qvel[dofs]
            kp = np.maximum(m.actuator_gainprm[acts, 0], 1.0)
            force = m.actuator_forcerange[acts, 1]
            hold_set = set(int(d) for d in self.world.hold_dof[arm])

            grav_ff = np.array([0.0 if int(d) in hold_set else float(data.qfrc_bias[d]) / kp[j] for j, d in enumerate(dofs)])
            prev = self.prev_ref.get(arm, t[:5])
            ref_speed = np.abs(t[:5] - prev) * self.fps
            self.prev_ref[arm] = t[:5].copy()
            err = t[:5] - q_act
            self.err_hist.setdefault(arm, []).append(err.copy())
            self.q_hist.setdefault(arm, []).append(q_act.copy())
            if len(self.err_hist[arm]) > 12:
                self.err_hist[arm].pop(0)
                self.q_hist[arm].pop(0)
            jit = self.jitter_state(arm)
            self.max_jitter_std_rad[arm] = max(self.max_jitter_std_rad[arm], jit["std_rad"])

            max_auth = np.minimum(0.14, 0.85 * force / kp)
            for j in range(5):
                if ref_speed[j] < 0.03 and abs(err[j]) > 0.0008:
                    step = (0.14 if jit["shaking"] else 0.22) * err[j] - (0.065 if jit["shaking"] else 0.03) * float(qvel[j])
                    self.trim[arm][j] = float(np.clip(self.trim[arm][j] + step, -max_auth[j], max_auth[j]))
                elif ref_speed[j] > 0.12:
                    self.trim[arm][j] *= 0.5

            total_trim = np.clip(grav_ff + self.trim[arm], -max_auth, max_auth)
            self.max_trim_rad[arm] = max(self.max_trim_rad[arm], float(np.max(np.abs(total_trim))))
            cmd5 = t[:5] + total_trim
            if jit["shaking"] and arm in self.prev_cmd:
                cmd5 = 0.65 * cmd5 + 0.35 * self.prev_cmd[arm] - np.clip(0.025 * qvel, -0.015, 0.015)
                self.damped_frames[arm] += 1
            self.prev_cmd[arm] = cmd5.copy()
            t[:5] = cmd5
            out[arm] = t
        return out
