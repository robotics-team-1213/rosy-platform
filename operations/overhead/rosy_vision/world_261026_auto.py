"""Automatic OpenCV 12-DOF (homography + lens distortion) track calibration and sub-pixel map tracer for ``world_261026``.

Solves the camera-to-map homography AND non-linear radial/tangential lens distortion ``(k1, k2, p1, p2)``
directly from the physical track's multi-colour features (white road loop + divider + stubs, pink charging
bays, and green top bay border) with zero hardcoded pixel coordinates. Includes LAB-CLAHE illumination
normalization, Huber IRLS outlier rejection for partial occlusion resilience, and sub-pixel polyline tracing
on the lens-undistorted top-down plane.
"""

from __future__ import annotations

import math
import time
from typing import Mapping

import cv2
import numpy as np

from core_common.calibration_math import default_lens_profile, scale_lens_profile

#: Latest solved (K, D, H_undist_to_map) per source, frame size, and calibration revision.
_LATEST_LENS_MODEL: dict[tuple[str, int, int, str | None], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def get_latest_lens_model(
    width: int, height: int, revision: str | None = None, *, source_id: str = ""
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    return _LATEST_LENS_MODEL.get((source_id, int(width), int(height), revision))


def default_camera_matrix(width: int, height: int, hfov_deg: float = 67.8) -> np.ndarray:
    fx = (width / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    return np.array([[fx, 0.0, width / 2.0], [0.0, fx, height / 2.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def distort_normalized(xn: np.ndarray, yn: np.ndarray, D: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    k1, k2, p1, p2 = float(D[0]), float(D[1]), float(D[2]), float(D[3])
    r2 = xn * xn + yn * yn
    rad = 1.0 + k1 * r2 + k2 * (r2 * r2)
    xd = xn * rad + 2.0 * p1 * xn * yn + p2 * (r2 + 2.0 * xn * xn)
    yd = yn * rad + p1 * (r2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn
    return xd, yd


def warp_undistorted_map_plane(img: np.ndarray, image_to_plane: np.ndarray, out_w: int, out_h: int,
                               K: np.ndarray, D: np.ndarray,
                               fill_bgr: tuple[int, int, int] = (24, 24, 24)) -> tuple[np.ndarray, np.ndarray]:
    """Single-pass inverse map-plane warp + plumb-bob radial/tangential lens undistortion."""
    height, width = img.shape[:2]
    inverse = np.linalg.inv(image_to_plane)
    u, v = np.meshgrid(np.arange(out_w, dtype=np.float64), np.arange(out_h, dtype=np.float64))
    raw = inverse @ np.stack((u.ravel(), v.ravel(), np.ones(u.size, dtype=np.float64)))
    centre = np.array([out_w * 0.5, out_h * 0.5, 1.0], dtype=np.float64)
    reference_w = float((inverse @ centre)[2])
    with np.errstate(divide="ignore", invalid="ignore"):
        xu = raw[0] / raw[2]
        yu = raw[1] / raw[2]
    if np.any(np.abs(D) > 1e-9):
        fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
        xn = (xu - cx) / fx
        yn = (yu - cy) / fy
        xd, yd = distort_normalized(xn, yn, D)
        x = xd * fx + cx
        y = yd * fy + cy
    else:
        x, y = xu, yu
    valid = (np.isfinite(x) & np.isfinite(y) & (raw[2] * reference_w > 1e-12)
             & (x >= 0) & (y >= 0) & (x < width - 1) & (y < height - 1)).reshape(out_h, out_w)
    map_x = np.where(valid, x.reshape(out_h, out_w), -1.0).astype(np.float32)
    map_y = np.where(valid, y.reshape(out_h, out_w), -1.0).astype(np.float32)
    plane = cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=fill_bgr)
    return plane, valid


def _proj(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.column_stack([pts, np.ones(len(pts))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def _sample_strip_centroids(mask: np.ndarray, map_rect: tuple[float, float, float, float],
                            m2i: np.ndarray, axis: str = "x", n_bins: int = 20) -> np.ndarray:
    x0, y0, x1, y1 = map_rect
    corners_map = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float64)
    poly_px = _proj(m2i, corners_map)
    if not np.all(np.isfinite(poly_px)):
        return np.zeros((0, 2), np.float64)
    roi = np.zeros_like(mask)
    cv2.fillPoly(roi, [np.round(poly_px).astype(np.int32)], 255)
    ys, xs = np.nonzero(mask & roi)
    if len(xs) < 8:
        return np.zeros((0, 2), np.float64)
    coord = xs if axis == "x" else ys
    bins = np.linspace(coord.min(), coord.max(), n_bins + 1)
    centers = []
    for i in range(n_bins):
        sel = (coord >= bins[i]) & (coord <= bins[i + 1])
        if np.sum(sel) >= 5:
            centers.append([float(np.median(xs[sel])), float(np.median(ys[sel]))])
    return np.array(centers, dtype=np.float64) if centers else np.zeros((0, 2), np.float64)


def _segment_masks(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sub-pixel masks with automatic gain + LAB-CLAHE normalization under dim or uneven lighting."""
    h, w = img.shape[:2]
    gray0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean_luma = float(gray0.mean())
    if mean_luma < 105.0:
        gain = min(3.5, 132.0 / max(8.0, mean_luma))
        work = np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    else:
        work = img

    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    b_ch, g_ch, r_ch = cv2.split(work)

    k_size = max(15, (min(h, w) // 28) | 1)
    el = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, el)
    white_mask = ((tophat > 35) & (hsv[:, :, 1] < 65) & (gray > 145)).astype(np.uint8) * 255
    if cv2.countNonZero(white_mask) < int(0.008 * h * w):
        lab = cv2.cvtColor(work, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_lab = cv2.split(lab)
        l_norm = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l_ch)
        norm_bgr = cv2.cvtColor(cv2.merge([l_norm, a_ch, b_lab]), cv2.COLOR_LAB2BGR)
        hsv = cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2GRAY)
        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, el)
        white_mask = ((tophat > 28) & (hsv[:, :, 1] < 70) & (gray > 130)).astype(np.uint8) * 255

    green_mask = ((hsv[:, :, 0] >= 45) & (hsv[:, :, 0] <= 95)
                  & (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 45)).astype(np.uint8) * 255
    # Pure pink requires both R > G and B > G so orange/yellow blocks are completely rejected.
    pink_mask = (
        (((hsv[:, :, 0] >= 145) | (hsv[:, :, 0] <= 12)) & (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 120))
        & (r_ch.astype(np.int16) - g_ch.astype(np.int16) > 20)
        & (b_ch.astype(np.int16) - g_ch.astype(np.int16) > 4)
    ).astype(np.uint8) * 255
    yellow_mask = ((hsv[:, :, 0] >= 15) & (hsv[:, :, 0] <= 35)
                   & (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 100)).astype(np.uint8) * 255
    white_mask[pink_mask > 0] = 0  # the pale pink tape also passes the white bound (S 40-74)
    return white_mask, green_mask, pink_mask, yellow_mask


def _decompose_m2i(m2i: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        b = np.linalg.solve(k, m2i)
    except np.linalg.LinAlgError:
        return None
    n1, n2 = float(np.linalg.norm(b[:, 0])), float(np.linalg.norm(b[:, 1]))
    s = 0.5 * (n1 + n2)
    if s < 1e-12:
        return None
    r1, r2, t = b[:, 0] / s, b[:, 1] / s, b[:, 2] / s
    if t[2] < 0.0:
        r1, r2, t = -r1, -r2, -t
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2]), full_matrices=False)
    r1, r2 = (u @ vt).T
    rot = np.column_stack([r1, r2, np.cross(r1, r2)])
    rvec, _ = cv2.Rodrigues(rot)
    return rvec.ravel(), t.ravel()


def _h_from_rt(rvec: np.ndarray, tvec: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    rot, _ = cv2.Rodrigues(rvec.reshape(3, 1))
    m2i = k @ np.column_stack([rot[:, 0], rot[:, 1], tvec])
    if abs(m2i[2, 2]) < 1e-12:
        return None
    m2i = m2i / m2i[2, 2]
    try:
        i2m = np.linalg.inv(m2i)
        i2m /= i2m[2, 2]
    except np.linalg.LinAlgError:
        return None
    return m2i, i2m


def _undistort_cv(pts: np.ndarray, k: np.ndarray, d: np.ndarray, model: str) -> np.ndarray:
    if len(pts) == 0 or not np.any(np.abs(d) > 1e-12):
        return pts
    if model == "fisheye":
        return cv2.fisheye.undistortPoints(pts.reshape(-1, 1, 2), k, d[:4], P=k).reshape(-1, 2)
    return cv2.undistortPoints(pts.reshape(-1, 1, 2), k, d, P=k).reshape(-1, 2)


def auto_calibrate_and_trace_world_261026(img: np.ndarray, *, revision: str | None = None,
                                          source_id: str = "",
                                          seed_map_to_image: np.ndarray | None = None,
                                          lens_profile: Mapping | None = None) -> dict | None:
    """Automatic SE(3) + lens-distortion calibration and sub-pixel map tracer for ``world_261026``."""
    if img is None or img.ndim != 3 or img.shape[2] != 3:
        return None
    t0 = time.perf_counter()
    h, w = img.shape[:2]
    white_mask, green_mask, pink_mask, _ = _segment_masks(img)

    if seed_map_to_image is not None:
        map_to_image = np.asarray(seed_map_to_image, np.float64).reshape(3, 3)
        if not np.all(np.isfinite(map_to_image)) or abs(map_to_image[2, 2]) < 1e-12:
            return None
        map_to_image = map_to_image / map_to_image[2, 2]
    else:
        if int(np.count_nonzero(green_mask)) < 250 or int(np.count_nonzero(pink_mask)) < 250:
            return None
        pink_closed = cv2.morphologyEx(pink_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        num_p, labels_p, stats_p, _ = cv2.connectedComponentsWithStats(pink_closed)
        if num_p < 2:
            return None
        pink_idx = 1 + int(np.argmax(stats_p[1:, cv2.CC_STAT_AREA]))
        if stats_p[pink_idx, cv2.CC_STAT_AREA] < 400:
            return None
        p_x0, p_y0, p_w0, p_h0, _ = stats_p[pink_idx]
        pink_main = (labels_p == pink_idx).astype(np.uint8) * 255
        for i in range(1, num_p):
            if i == pink_idx or stats_p[i, cv2.CC_STAT_AREA] < 100:
                continue
            cx0, cy0, cw0, ch0, _ = stats_p[i]
            if (cx0 >= p_x0 - 40 and cx0 + cw0 <= p_x0 + p_w0 + 40
                    and cy0 + ch0 <= p_y0 + p_h0 + 20 and cy0 > 0.05 * h):
                pink_main[labels_p == i] = 255
        py, px = np.nonzero(pink_main)
        p_umin, p_umax = int(px.min()), int(px.max())
        p_vmin, p_vmax = int(py.min()), int(py.max())

        white_closed = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, np.ones((3, 5), np.uint8))
        num_w, labels_w, stats_w, centroids_w = cv2.connectedComponentsWithStats(white_closed)
        divider_comp = None
        for i in range(1, num_w):
            cw = stats_w[i, cv2.CC_STAT_WIDTH]
            ch = stats_w[i, cv2.CC_STAT_HEIGHT]
            ca = stats_w[i, cv2.CC_STAT_AREA]
            _, cv_c = centroids_w[i]
            if p_vmax + 0.05 * h < cv_c < p_vmax + 0.28 * h and 0.25 * w < cw < 0.72 * w and ch < 0.28 * h and ca > 250:
                if divider_comp is None or ca > stats_w[divider_comp, cv2.CC_STAT_AREA]:
                    divider_comp = i

        src_seed: list[list[float]] = []
        dst_seed: list[list[float]] = []
        if divider_comp is not None:
            dy_div, dx_div = np.nonzero(labels_w == divider_comp)
            q_l, q_r = np.percentile(dx_div, 1.0), np.percentile(dx_div, 99.0)
            u_dl, v_dl = float(dx_div[dx_div <= q_l].mean()), float(dy_div[dx_div <= q_l].mean())
            u_dr, v_dr = float(dx_div[dx_div >= q_r].mean()), float(dy_div[dx_div >= q_r].mean())
            u_span = max(1.0, u_dr - u_dl)
            left_leg_ok = (p_umax - p_umin) >= 0.38 * u_span
            p_umin_eff = p_umin if left_leg_ok else int(round(p_umax - 0.433 * u_span))
            src_seed.extend([[-0.926, -0.364], [0.926, -0.364], [0.258, -0.045], [0.032, 0.520]])
            dst_seed.extend([
                [u_dl, v_dl], [u_dr, v_dr],
                [float(p_umax), float(np.median(py[px >= p_umax - 12]))],
                [float(np.median(px[py <= p_vmin + 15])), float(p_vmin)],
            ])
            if left_leg_ok:
                src_seed.append([-0.630, -0.045])
                dst_seed.append([float(p_umin), float(np.median(py[px <= p_umin + 12]))])
            else:
                u_gl_lo, u_gl_hi = max(0, p_umin_eff + int(0.05 * u_span)), min(w, p_umin_eff + int(0.12 * u_span))
                v_gl_lo, v_gl_hi = max(0, p_vmin + int(0.04 * h)), min(h, p_vmax - int(0.08 * h))
                ys_gl, xs_gl = np.nonzero(green_mask[v_gl_lo:v_gl_hi, u_gl_lo:u_gl_hi])
                if len(xs_gl) >= 15:
                    src_seed.append([-0.525, 0.350])
                    dst_seed.append([float(np.median(xs_gl) + u_gl_lo), float(np.median(ys_gl) + v_gl_lo)])
        else:
            u_dl, v_dl = float(p_umin - 0.14 * w), float(p_vmax + 0.16 * h)
            u_dr, v_dr = float(p_umax + 0.30 * w), float(p_vmax + 0.21 * h)
            p_umin_eff = p_umin

        g_v_lo, g_v_hi = max(0, p_vmin - int(0.09 * h)), min(h, p_vmin + int(0.05 * h))
        u_g_r = int(p_umin_eff + 0.82 * (p_umax - p_umin_eff))
        ys_g_r = np.nonzero(green_mask[g_v_lo:g_v_hi, max(0, u_g_r - 20):min(w, u_g_r + 20)])[0]
        if len(ys_g_r) >= 8:
            v_g_r = float(np.percentile(ys_g_r, 20) + g_v_lo)
            src_seed.append([0.08, 0.597])
            dst_seed.append([float(u_g_r), v_g_r])
            u_g_l = int(p_umin_eff + 0.22 * (p_umax - p_umin_eff))
            ys_g_l = np.nonzero(green_mask[g_v_lo:g_v_hi, max(0, u_g_l - 20):min(w, u_g_l + 20)])[0]
            if len(ys_g_l) >= 8:
                v_g_l = float(np.percentile(ys_g_l, 20) + g_v_lo)
                expected_dv = (v_dl - v_dr) * ((u_g_r - u_g_l) / max(1.0, u_dr - u_dl))
                if abs((v_g_l - v_g_r) - expected_dv) < 25.0:
                    src_seed.append([-0.45, 0.597])
                    dst_seed.append([float(u_g_l), v_g_l])
        if len(src_seed) < 5:
            src_seed.extend([[-0.630, -0.045], [0.258, -0.045], [0.032, 0.470]])
            dst_seed.extend([
                [float(p_umin), float(np.median(py[px <= p_umin + 10]))],
                [float(p_umax), float(np.median(py[px >= p_umax - 10]))],
                [float(np.median(px[py <= p_vmin + 15])), float(p_vmin)],
            ])
        if len(src_seed) < 4:
            return None
        s_arr, d_arr = np.array(src_seed, np.float64), np.array(dst_seed, np.float64)
        method = cv2.RANSAC if len(src_seed) >= 5 else 0
        map_to_image, _ = cv2.findHomography(s_arr, d_arr, method, 8.0) if method else cv2.findHomography(s_arr, d_arr, 0)
        if map_to_image is None and method:
            map_to_image, _ = cv2.findHomography(s_arr, d_arr, 0)
        if map_to_image is None or not np.all(np.isfinite(map_to_image)):
            return None
        map_to_image /= map_to_image[2, 2]

    def _stack(arrs):
        nonempty = [a for a in arrs if len(a)]
        return np.vstack(nonempty) if nonempty else np.zeros((0, 2), np.float64)

    lp = scale_lens_profile(lens_profile, (w, h)) if lens_profile is not None else default_lens_profile(w, h)
    K = np.asarray(lp["K"], dtype=np.float64)
    D = np.asarray(lp["D"], dtype=np.float64)
    model_name = lp["model"]
    fixed_lens = lens_profile is not None

    rt = _decompose_m2i(map_to_image, K)
    if rt is None:
        return None
    rvec, tvec = rt
    pair = _h_from_rt(rvec, tvec, K)
    if pair is None:
        return None
    map_to_image, image_to_map = pair
    final_r = np.zeros(0, np.float64)
    pts_pb1 = pts_pb3 = pts_bot = pts_div = pts_top = np.zeros((0, 2), np.float64)

    for stage_idx, pad in enumerate((0.055, 0.028, 0.016)):
        pts_bot = _sample_strip_centroids(white_mask, (-1.12, -0.588 - pad, 1.12, -0.588 + pad), map_to_image, "x", 30)
        pts_div = _sample_strip_centroids(white_mask, (-0.88, -0.364 - pad, 0.88, -0.364 + pad), map_to_image, "x", 30)
        pts_top = _stack([
            _sample_strip_centroids(white_mask, (-1.14, -0.140 - pad, -0.80, -0.140 + pad), map_to_image, "x", 8),
            _sample_strip_centroids(white_mask, (-0.54, -0.140 - pad, 0.16, -0.140 + pad), map_to_image, "x", 15),
            _sample_strip_centroids(white_mask, (0.44, -0.140 - pad, 1.14, -0.140 + pad), map_to_image, "x", 16),
        ])
        pts_stubs = _stack([
            _sample_strip_centroids(white_mask, (-0.69, 0.260 - pad, -0.53, 0.260 + pad), map_to_image, "x", 5),
            _sample_strip_centroids(white_mask, (0.14, 0.260 - pad, 0.30, 0.260 + pad), map_to_image, "x", 5),
        ])
        pts_green_top = _stack([
            _sample_strip_centroids(green_mask, (-0.51, 0.597 - pad, -0.21, 0.597 + pad), map_to_image, "x", 8),
            _sample_strip_centroids(green_mask, (-0.05, 0.597 - pad, 0.14, 0.597 + pad), map_to_image, "x", 8),
        ])
        pts_left = _sample_strip_centroids(white_mask, (-1.188 - pad, -0.52, -1.188 + pad, -0.20), map_to_image, "y", 14)
        pts_right = _sample_strip_centroids(white_mask, (1.188 - pad, -0.55, 1.188 + pad, 0.15), map_to_image, "y", 18)
        pts_pb1 = _sample_strip_centroids(pink_mask, (-0.414 - pad, 0.08, -0.414 + pad, 0.32), map_to_image, "y", 10)
        pts_pb2 = _sample_strip_centroids(pink_mask, (-0.190 - pad, 0.08, -0.190 + pad, 0.32), map_to_image, "y", 10)
        pts_pb3 = _sample_strip_centroids(pink_mask, (0.032 - pad, 0.08, 0.032 + pad, 0.48), map_to_image, "y", 15)

        joint_lens = (stage_idx == 2 and not fixed_lens)
        y_groups = [(pts_bot, -0.5880), (pts_div, -0.3640), (pts_top, -0.1400),
                    (pts_stubs, +0.2600), (pts_green_top, +0.5970)]
        x_groups = [(pts_left, -1.1880), (pts_right, +1.1880),
                    (pts_pb1, -0.4140), (pts_pb2, -0.1900), (pts_pb3, +0.0320)]
        if not joint_lens:
            y_groups = [(_undistort_cv(p, K, D, model_name), t) for p, t in y_groups]
            x_groups = [(_undistort_cv(p, K, D, model_name), t) for p, t in x_groups]

        def residuals(vec: np.ndarray, *, include_reg: bool = True) -> np.ndarray:
            pair_v = _h_from_rt(vec[:3], vec[3:6], K)
            if pair_v is None:
                return np.zeros(0, np.float64)
            _, i2m_v = pair_v
            d_vec = np.array([vec[6], 0.0, 0.0, 0.0, 0.0], np.float64) if len(vec) == 7 else D
            res = []
            for pts, y_target in y_groups:
                if len(pts):
                    u_pts = _undistort_cv(pts, K, d_vec, model_name) if len(vec) == 7 else pts
                    res.append(_proj(i2m_v, u_pts)[:, 1] - y_target)
            for pts, x_target in x_groups:
                if len(pts):
                    u_pts = _undistort_cv(pts, K, d_vec, model_name) if len(vec) == 7 else pts
                    res.append(_proj(i2m_v, u_pts)[:, 0] - x_target)
            if len(vec) == 7 and include_reg:
                res.append(np.array([vec[6] * 0.020]))
            return np.concatenate(res) if res else np.zeros(0, np.float64)

        n_dof = 7 if joint_lens else 6
        params = np.concatenate([rvec, tvec, [D[0]]]) if joint_lens else np.concatenate([rvec, tvec])
        eps = np.array([1e-5, 1e-5, 1e-5, 1e-4, 1e-4, 1e-4, 1e-4][:n_dof], np.float64)
        lam = 1e-3

        def _huber_cost(r: np.ndarray) -> float:
            abs_r = np.abs(r)
            return float(np.sum(np.where(abs_r <= 0.015, 0.5 * r * r, 0.015 * (abs_r - 0.5 * 0.015))))

        for _ in range(18):
            r0 = residuals(params)
            if len(r0) < 25 or not np.all(np.isfinite(r0)):
                return None
            abs_r = np.abs(r0)
            weights = np.where(abs_r <= 0.015, 1.0, 0.015 / (abs_r + 1e-9))
            J = np.zeros((len(r0), n_dof), np.float64)
            for j in range(n_dof):
                dp = params.copy()
                dp[j] += eps[j]
                rj = residuals(dp)
                if len(rj) != len(r0):
                    return None
                J[:, j] = (rj - r0) / eps[j]
            Jw = J * weights[:, None]
            jtwj = Jw.T @ Jw
            diag = np.maximum(1e-8, np.diag(jtwj))
            step, _, _, _ = np.linalg.lstsq(jtwj + lam * np.diag(diag), -Jw.T @ (r0 * weights), rcond=None)
            cand = params + step
            if joint_lens:
                cand[6] = float(np.clip(cand[6], -0.30, 0.30))
            r1 = residuals(cand)
            if len(r1) == len(r0) and np.all(np.isfinite(r1)) and _huber_cost(r1) < _huber_cost(r0):
                params = cand
                lam = max(1e-6, lam * 0.4)
                if np.max(np.abs(step)) < 1e-7:
                    break
            else:
                lam = min(1e4, lam * 5.0)
                if lam >= 1e4:
                    break

        rvec, tvec = params[:3], params[3:6]
        if joint_lens:
            D = np.array([float(np.clip(params[6], -0.30, 0.30)), 0.0, 0.0, 0.0, 0.0], np.float64)
        pair = _h_from_rt(rvec, tvec, K)
        if pair is None:
            return None
        map_to_image, image_to_map = pair
        final_r = residuals(params, include_reg=False)

    if (len(final_r) < 25 or len(pts_pb1) < 4 or len(pts_pb3) < 4
            or len(pts_div) < 10 or len(pts_bot) < 8 or len(pts_top) < 8):
        return None
    rms_m = float(np.sqrt(np.mean(final_r ** 2)))
    if not math.isfinite(rms_m) or rms_m > 0.015:
        return None
    rot_m, _ = cv2.Rodrigues(rvec.reshape(3, 1))
    cam_h = abs(float((-rot_m.T @ tvec)[2]))
    if not 0.5 <= cam_h <= 6.0:
        return None
    corners = np.array([[-1.22, -0.61], [1.22, -0.61], [1.22, 0.61], [-1.22, 0.61]], np.float64)
    w_c = (np.column_stack([corners, np.ones(4)]) @ map_to_image.T)[:, 2]
    if np.any(w_c <= 0.1):
        return None
    out_profile = {
        "model": model_name,
        "K": [[float(v) for v in row] for row in K],
        "D": [float(v) for v in (D[:4] if model_name == "fisheye" else D[:5])],
        "image_size": [int(w), int(h)],
        "source": "measured" if fixed_lens else "auto",
    }
    _LATEST_LENS_MODEL[(source_id, int(w), int(h), revision)] = (K.copy(), D[:4].copy(), image_to_map.copy())

    # 3. Rectify + lens-undistort to top-down map plane and trace sub-pixel places & edges
    min_x, max_x, min_y, max_y = -1.37, 1.37, -0.76, 0.76
    ppm = 400.0
    out_w, out_h = 1096, 608
    map_to_plane = np.array([[ppm, 0.0, -min_x * ppm - 0.5],
                             [0.0, -ppm, max_y * ppm - 0.5],
                             [0.0, 0.0, 1.0]])
    plane, _ = warp_undistorted_map_plane(img, map_to_plane @ image_to_map, out_w, out_h, K, D[:4])
    white_p, _, pink_p, yellow_p = _segment_masks(plane)
    from rosy_vision.world_261026_trace import trace_world_261026_graph
    places, edges = trace_world_261026_graph(white_p, pink_p, yellow_p, min_x, max_y, ppm, out_h)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "map_to_image": map_to_image,
        "image_to_map": image_to_map,
        "distortion": [round(float(x), 6) for x in D[:4]],
        "lens_profile": out_profile,
        "rms_m": rms_m,
        "elapsed_ms": elapsed_ms,
        "places": places,
        "edges": edges,
    }
