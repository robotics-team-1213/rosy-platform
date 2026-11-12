"""Color-agnostic structural container geometry and neutral-surface blob detection between gripper fingers."""
from __future__ import annotations

import numpy as np

import cell_params as prm

_KERNEL_3 = np.ones((3, 3), np.uint8)
_KERNEL_25 = np.ones((25, 25), np.uint8)


def structural_container_between_fingers(img, a=None, b=None) -> dict | None:
    """Color-agnostic OpenCV structural detection of a container between the gripper fingers in the wrist view.
    Finds the container's parallel vertical walls (`left_seam`, `right_seam`), centre (`cx`), width (`w_px`),
    in-plane angle (`angle_deg`), and front end wall (`y_front`) by maximizing interior Lab uniformity + vertical
    top-to-mid continuity against exterior step contrast + Sobel wall/rib gradients, including off-center containers
    partially clipped by the wrist FOV boundary."""
    import cv2

    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    y0, y1, y2 = int(h * 0.03), int(h * 0.28), int(h * 0.50)
    band = lab[y0:y1]
    gy = np.abs(cv2.Sobel(gray[int(h * 0.08):int(h * 0.68)], cv2.CV_32F, 0, 1, ksize=3))
    gx_full = np.abs(cv2.Sobel(gray[int(h * 0.08):int(h * 0.68)], cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)

    prof = cv2.GaussianBlur(np.median(band, axis=0).reshape(1, -1, 3), (11, 1), 0).reshape(-1, 3)
    prof_mid = cv2.GaussianBlur(np.median(lab[y1:y2], axis=0).reshape(1, -1, 3), (11, 1), 0).reshape(-1, 3)
    x_min = max(int(a[0]) - 35, int(w * 0.03)) if a is not None else int(w * 0.03)
    x_max = min(int(b[0]) + 35, int(w * 0.99)) if b is not None else int(w * 0.99)
    w_lo, w_hi = max(140, int(w * 0.26)), min(400, int(w * 0.58))

    best = None
    for xL in range(x_min, max(x_min + 1, x_max - w_lo), 4):
        for w_px in range(w_lo, w_hi + 1, 6):
            xR = xL + w_px
            if xR > x_max:
                break
            inside = prof[xL:xR]
            in_med = np.median(inside, axis=0)
            if in_med[0] < 65.0:  # dark shadow / background void
                continue
            in_med_mid = np.median(prof_mid[xL:xR], axis=0)
            vert_diff = float(np.linalg.norm(in_med - in_med_mid))
            in_spread = float(np.mean(np.linalg.norm(inside - in_med, axis=1)))
            out_L = prof[max(2, xL - 60):max(4, xL - 8)]
            out_R = prof[min(w - 4, xR + 8):min(w - 2, xR + 60)]
            dL = float(np.linalg.norm(np.median(out_L, axis=0) - in_med)) if len(out_L) >= 6 else 0.0
            dR = float(np.linalg.norm(np.median(out_R, axis=0) - in_med)) if len(out_R) >= 6 else 0.0
            if len(out_L) < 6 and dR > 0.0:
                dL = 0.85 * dR
            if len(out_R) < 6 and dL > 0.0:
                dR = 0.85 * dL
            score = min(dL, dR) + 0.5 * (dL + dR) - 2.0 * in_spread - 0.8 * vert_diff
            if best is None or score > best[0]:
                best = (score, xL, xR, in_med)

    if best is None or best[0] < 25.0:
        return None
    score, left_seam, right_seam, proto_lab = best
    # Sub-pixel peak refinement on vertical Sobel gradient within +-6 px of the coarse seam
    gx_smooth = cv2.GaussianBlur(gx_full.reshape(1, -1), (5, 1), 0).reshape(-1)
    l_win = range(max(4, left_seam - 6), min(w - 4, left_seam + 7))
    r_win = range(max(4, right_seam - 6), min(w - 4, right_seam + 7))
    if l_win and float(gx_smooth[list(l_win)].max()) > 12.0:
        left_seam = int(max(l_win, key=lambda idx: float(gx_smooth[idx])))
    if r_win and float(gx_smooth[list(r_win)].max()) > 12.0:
        right_seam = int(max(r_win, key=lambda idx: float(gx_smooth[idx])))

    w_px = float(right_seam - left_seam)
    # If one seam is clipped against the camera FOV border, compensate nominal width (0.51 * w) for true centre
    clipped_right = right_seam >= int(w * 0.96) and w_px < 0.48 * w
    clipped_left = left_seam <= int(w * 0.04) and w_px < 0.48 * w
    eff_w_px = max(w_px, 0.51 * w) if (clipped_right or clipped_left) else w_px
    if clipped_right:
        cx = float(left_seam) + 0.5 * eff_w_px
    elif clipped_left:
        cx = float(right_seam) - 0.5 * eff_w_px
    else:
        cx = 0.5 * (left_seam + right_seam)

    # Estimate in-plane tilt angle (deg) from top vs mid horizontal slice centers
    band_top = np.median(lab[int(h * 0.05):int(h * 0.20)], axis=0)
    band_mid = np.median(lab[int(h * 0.25):int(h * 0.42)], axis=0)
    top_in = np.where(np.linalg.norm(band_top[max(0, left_seam - 20):min(w, right_seam + 20)] - proto_lab, axis=1) < 22.0)[0]
    mid_in = np.where(np.linalg.norm(band_mid[max(0, left_seam - 20):min(w, right_seam + 20)] - proto_lab, axis=1) < 22.0)[0]
    angle_deg = 0.0
    if len(top_in) >= 20 and len(mid_in) >= 20:
        dx_slice = float(np.mean(mid_in) - np.mean(top_in))
        dy_slice = float(max(1, int(h * 0.335) - int(h * 0.125)))
        angle_deg = float(np.degrees(np.arctan2(dx_slice, dy_slice)))

    # Detect bottom/front end wall of the container (where Lab colour/lightness steps off the container end)
    inner_x0 = max(left_seam + 12, 0)
    inner_x1 = min(right_seam - 12, w)
    if inner_x1 <= inner_x0:
        inner_x0, inner_x1 = left_seam, right_seam
    strip_lab = lab[:, inner_x0:inner_x1]
    row_dab = np.hypot(strip_lab[..., 1] - proto_lab[1], strip_lab[..., 2] - proto_lab[2]).mean(axis=1)
    row_l = strip_lab[..., 0].mean(axis=1)
    l_ref = float(np.median(row_l[int(h * 0.20):int(h * 0.55)]))
    y_front = float(int(h * 0.76))
    for y in range(int(h * 0.42), int(h * 0.96)):
        if row_dab[y] > 18.0 or row_l[y] < 0.82 * l_ref:
            y_front = float(y)
            break

    # Reject empty recessed gray tray pocket (low chroma + recessed shadow at top compared to raised lower rim)
    chroma = float(
        np.hypot(
            strip_lab[int(h * 0.05):int(h * 0.35), :, 1] - 128.0,
            strip_lab[int(h * 0.05):int(h * 0.35), :, 2] - 128.0,
        ).mean()
    )
    l_top_mean = float(row_l[int(h * 0.08):int(h * 0.28)].mean())
    l_bot_mean = float(row_l[int(h * 0.62):int(h * 0.86)].mean())
    empty_recessed_tray = bool(chroma < 6.0 and (l_bot_mean - l_top_mean) > 15.0)

    wall_strength = float(
        0.5
        * (
            gx_full[max(0, left_seam - 4):min(w, left_seam + 5)].max(initial=0.0)
            + gx_full[max(0, right_seam - 4):min(w, right_seam + 5)].max(initial=0.0)
        )
    )
    rib_strength = float(gy[:, inner_x0:inner_x1].mean())
    mm_per_px = 30.0 / max(eff_w_px, 1.0)
    open_mid_x = 0.5 * (float(a[0]) + float(b[0])) if (a is not None and b is not None) else 325.0
    dx_mm = round((cx - open_mid_x) * mm_per_px, 2)
    dy_mm = round((y_front - 416.0) * mm_per_px, 2)
    return {
        "cx": round(cx, 1),
        "y_front": round(y_front, 1),
        "w_px": round(w_px, 1),
        "eff_w_px": round(eff_w_px, 1),
        "left_seam": int(left_seam),
        "right_seam": int(right_seam),
        "clipped_border": bool(clipped_left or clipped_right),
        "empty_recessed_tray": empty_recessed_tray,
        "angle_deg": round(angle_deg, 2),
        "dx_mm": dx_mm,
        "dy_mm": dy_mm,
        "mm_per_px": round(mm_per_px, 4),
        "span_score": round(float(score), 1),
        "wall_edge_score": round(min(1.0, wall_strength / 45.0), 3),
        "rib_score": round(min(1.0, rib_strength / 18.0), 3),
        "is_container_shape": bool(140.0 <= w_px <= 420.0 and score >= 25.0 and not empty_recessed_tray),
    }


def top_face_between_fingers(img, a, b):
    """Detect the target container's top face between the two fingers in the wrist view when adjacent containers touch."""
    import cv2

    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    y0, y1 = int(h * 0.18), int(h * 0.73)
    mid = hsv[y0:y1]
    r_ch = img[y0:y1, :, 2].astype(int)
    g_ch = img[y0:y1, :, 1].astype(int)
    b_ch = img[y0:y1, :, 0].astype(int)
    warm = ((r_ch - g_ch) >= 6) | ((r_ch - b_ch) >= 12)
    top_face = (mid[..., 2] >= 132) & (mid[..., 1] <= 98) & warm
    col_ratio = top_face.mean(axis=0)
    x_min = max(int(a[0]) - 25, int(w * 0.05)) if a is not None else int(w * 0.05)
    x_max = min(int(b[0]) + 25, int(w * 0.95)) if b is not None else int(w * 0.95)
    s0 = max(int(a[0]) + 5, int(w * 0.25)) if a is not None else int(w * 0.30)
    s1 = min(int(b[0]) - 5, int(w * 0.75)) if b is not None else int(w * 0.70)
    if s1 <= s0:
        s0, s1 = int(w * 0.30), int(w * 0.70)
    search = col_ratio[s0:s1]
    if len(search) == 0 or float(search.max()) < 0.5:
        struct = structural_container_between_fingers(img, a, b)
        return (struct["cx"], struct["y_front"], struct["w_px"]) if struct else None
    c0 = int(np.argmax(search) + s0)
    left_seam = x_min
    for x in range(c0, x_min, -1):
        if col_ratio[x] < 0.45:
            left_seam = x
            break
    right_seam = x_max
    for x in range(c0, x_max):
        if col_ratio[x] < 0.45:
            right_seam = x
            break
    w_px = float(right_seam - left_seam)
    if not (120.0 <= w_px <= 440.0):
        struct = structural_container_between_fingers(img, a, b)
        return (struct["cx"], struct["y_front"], struct["w_px"]) if struct else None
    cx = 0.5 * (left_seam + right_seam)
    v_prof = hsv[:, max(left_seam + 10, 0):min(right_seam - 10, w), 2].mean(axis=1)
    v_top = float(np.median(v_prof[int(h * 0.40):int(h * 0.68)]))
    y_front = float(int(h * 0.76))
    for y in range(int(h * 0.68), int(h * 0.92)):
        if v_prof[y] < 0.93 * v_top:
            y_front = float(y)
            break
    return cx, y_front, w_px


def on_surface_blob(img, hsv, params=None):
    """The container standing on a neutral surface (floor, tray, belt: grey/white/black), not one on a coloured
    neighbour surface (the orange board): the ring just outside each green blob decides."""
    import cv2

    if hsv is None or not isinstance(hsv, (list, tuple)) or len(hsv) != 2 or hsv[0] is None:
        struct = structural_container_between_fingers(img)
        if struct is not None:
            return (float(struct["cx"]), float(0.5 * struct["y_front"]), int(struct["w_px"] * struct["y_front"]))
        return None
    h, w = img.shape[:2]
    hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.morphologyEx(cv2.inRange(hsv_img, np.array(hsv[0]), np.array(hsv[1])), cv2.MORPH_OPEN, _KERNEL_3)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    min_blob = prm.get(params, "wrist.min_blob_px")
    max_chroma = prm.get(params, "wrist.neutral_ring_chroma")
    candidates = sorted(
        (i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_blob),
        key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]),
    )
    for i in candidates:
        x0 = max(0, int(stats[i, cv2.CC_STAT_LEFT]) - 12)
        y0 = max(0, int(stats[i, cv2.CC_STAT_TOP]) - 12)
        x1 = min(w, int(stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH]) + 12)
        y1 = min(h, int(stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]) + 12)
        blob = (labels[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = (cv2.dilate(blob, _KERNEL_25) - blob) & (mask[y0:y1, x0:x1] == 0)
        if int(ring.sum()) < 200:
            continue
        sub_lab = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2LAB)
        ring_mask = ring > 0
        chroma = float(
            np.hypot(
                sub_lab[..., 1][ring_mask].astype(np.float32) - 128.0,
                sub_lab[..., 2][ring_mask].astype(np.float32) - 128.0,
            ).mean()
        )
        if chroma <= max_chroma:
            return (float(cents[i][0]), float(cents[i][1]), int(stats[i, cv2.CC_STAT_AREA]))
    return None
