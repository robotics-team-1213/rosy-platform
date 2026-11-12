#!/usr/bin/env python3
"""The open fingers as the ruler in the wrist view: pads, the container on a neutral surface, the offset, a servo.

At the hover the wrist camera sees both open finger pads at the bottom of the frame and the container. The pads'
pixel distance is the known jaw gap (gripper.gap_mm_per_unit, measured from this same view), their axis is the
closing direction, and the container's offset from the pads' midpoint is the correction. The sign across the
closing axis is not known from one view, so it is learned: a correction that makes the offset grow is reversed.

Off by default (wrist.finger_servo): on the real arm the pads' line was not the closing axis (2026-10-29); cell_pinch
uses finger_pads at grasp height instead, where pads and box share a depth.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import cell_params as prm
from cell_finger_container import (
    _KERNEL_3,
    _KERNEL_25,
    on_surface_blob,
    structural_container_between_fingers,
    top_face_between_fingers,
)


def resolve_finger_color(params=None, wrist_spec: dict | None = None, color: str | int | None = None) -> str:
    """Resolve per-arm finger polarity ('dark' for black fingers e.g. arm_s, 'white' for v2.1 white fingers e.g. arm_a/arm_b, or 'auto')."""
    raw = color
    if raw is None and isinstance(wrist_spec, dict):
        raw = wrist_spec.get("finger_color")
    if raw is None and isinstance(params, dict):
        raw = params.get("wrist.finger_color")
    if raw is None:
        raw = prm.get(params, "wrist.finger_color", 0)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("dark", "black", "1"):
            return "dark"
        if s in ("white", "light", "2"):
            return "white"
        return "auto"
    if raw == 1:
        return "dark"
    if raw == 2:
        return "white"
    return "auto"


_KERNEL_3 = np.ones((3, 3), np.uint8)
_KERNEL_25 = np.ones((25, 25), np.uint8)


def _dark_pads(img, dark: int = 60):
    import cv2

    h, w = img.shape[:2]
    y0 = 2 * h // 3
    band = (cv2.cvtColor(img[y0:], cv2.COLOR_BGR2GRAY) < dark).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(band)
    min_bottom = int(h * 0.90) - y0
    blobs = sorted(
        (
            i for i in range(1, n)
            if stats[i, cv2.CC_STAT_AREA] > 800
            and (stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]) >= min_bottom
        ),
        key=lambda i: -stats[i, cv2.CC_STAT_AREA],
    )[:2]
    if len(blobs) >= 2:
        left, right = sorted(blobs, key=lambda i: cents[i][0])
        gap = stats[right, cv2.CC_STAT_LEFT] - (stats[left, cv2.CC_STAT_LEFT] + stats[left, cv2.CC_STAT_WIDTH])
        if gap >= 4:
            a, b = sorted((cents[i] + (0, y0) for i in blobs), key=lambda c: c[0])
            return a, b, float(max(gap, 1))
    return None


def _white_pads(img):
    import cv2

    h, w = img.shape[:2]
    y0 = 2 * h // 3
    band_bgr = img[y0:]
    band_hsv = cv2.cvtColor(band_bgr, cv2.COLOR_BGR2HSV)
    # 1. Wide-open v2.1 white fingers at bottom quarter (y >= 0.78*h): cool white under cell LED (H 95..138, S <= 170, V >= 135)
    bot_off = max(0, int(h * 0.78) - y0)
    bot = band_hsv[bot_off:]
    bot_bgr = band_bgr[bot_off:]
    not_orange = (bot_bgr[..., 2].astype(np.int16) - bot_bgr[..., 1].astype(np.int16)) <= 8
    cool_white = (bot[..., 0] >= 95) & (bot[..., 0] <= 138) & (bot[..., 1] <= 170) & (bot[..., 2] >= 135) & not_orange
    left_xs = np.where(cool_white[:, int(w * 0.08):int(w * 0.36)].mean(axis=0) > 0.25)[0] + int(w * 0.08)
    right_xs = np.where(cool_white[:, int(w * 0.72):int(w * 0.96)].mean(axis=0) > 0.25)[0] + int(w * 0.72)
    if len(left_xs) and len(right_xs):
        xl, xr = float(left_xs.max()), float(right_xs.min())
        yp = float(int(h * 0.88))
        return np.array([xl, yp]), np.array([xr, yp]), float(max(xr - xl, 1.0))

    # 2. Neutral bright white or narrow/partially open white fingers (e.g. arm_a / arm_b) in bottom third
    not_cyan = (band_bgr[..., 0].astype(np.int16) - band_bgr[..., 2].astype(np.int16)) <= 45
    mask = (
        (
            ((band_hsv[..., 0] >= 95) & (band_hsv[..., 0] <= 138) & (band_hsv[..., 2] >= 140))
            | ((band_hsv[..., 2] >= 200) & (band_hsv[..., 1] <= 55))
        )
        & not_cyan
    ).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    min_bottom = int(h * 0.90) - y0
    blobs = sorted(
        (
            i for i in range(1, n)
            if stats[i, cv2.CC_STAT_AREA] > 250
            and (stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT]) >= min_bottom
            and (w * 0.06) <= cents[i][0] <= (w * 0.94)
        ),
        key=lambda i: -stats[i, cv2.CC_STAT_AREA],
    )[:2]
    if len(blobs) >= 2:
        left, right = sorted(blobs, key=lambda i: cents[i][0])
        gap = stats[right, cv2.CC_STAT_LEFT] - (stats[left, cv2.CC_STAT_LEFT] + stats[left, cv2.CC_STAT_WIDTH])
        if gap >= 4:
            a, b = sorted((cents[i] + (0, y0) for i in blobs), key=lambda c: c[0])
            return a, b, float(max(gap, 1))
    return None


def finger_pads(img, dark: int = 60, color: str | int = "auto"):
    """(left_centre, right_centre, gap_px) of the two finger pads in the bottom third (dark pads on arm_s or white fingers on arm_a/arm_b), or None."""
    mode = resolve_finger_color(color=color)
    if mode == "dark":
        return _dark_pads(img, dark=dark)
    if mode == "white":
        return _white_pads(img)
    d_pads = _dark_pads(img, dark=dark)
    w_pads = _white_pads(img)
    if d_pads is not None and w_pads is not None:
        # Prefer the pair with higher vertical symmetry and closer to bottom of frame
        d_sym = abs(float(d_pads[0][1] - d_pads[1][1]))
        w_sym = abs(float(w_pads[0][1] - w_pads[1][1]))
        d_score = min(float(d_pads[0][1]), float(d_pads[1][1])) - 1.5 * d_sym
        w_score = min(float(w_pads[0][1]), float(w_pads[1][1])) - 1.5 * w_sym
        return w_pads if w_score >= d_score else d_pads
    return d_pads if d_pads is not None else w_pads


def finger_offset_mm(img, hsv, gap_mm: float, params=None, color: str | int | None = None) -> dict:
    """The container's offset from the pads' midpoint in mm: along (the closing axis, left->right) and across."""
    mode = resolve_finger_color(params=params, color=color)
    pads = finger_pads(img, color=mode)
    if pads is None:
        return {"found": False, "why": "finger pads not seen"}
    a, b, gap_px = pads
    target = on_surface_blob(img, hsv, params)
    if target is None or target[2] > 55000 or not (float(a[0]) <= target[0] <= float(b[0])):
        face = top_face_between_fingers(img, a, b)
        if face is not None:
            cx, y_front, w_px = face
            s_face = 30.0 / max(w_px, 1.0)
            parallax_px = float(params.get("wrist.parallax_px", 0.0)) if isinstance(params, dict) else 0.0
            ref_x = 0.5 * (a[0] + b[0]) - parallax_px
            along_mm = round(float(cx - ref_x) * s_face, 1)
            across_mm = round(float(y_front - 0.76 * img.shape[0]) * s_face, 1)
            return {"found": True, "along_mm": along_mm, "across_mm": across_mm,
                    "gap_px": round(gap_px, 1), "mm_per_px": round(s_face, 3), "mode": "top_face", "finger_color": mode}
    if target is None:
        return {"found": False, "why": "no container on a neutral surface in view"}
    seen = {"cx": target[0], "cy": target[1]}
    axis = (b - a) / np.linalg.norm(b - a)
    across_dir = np.array([-axis[1], axis[0]])
    d = np.array([seen["cx"], seen["cy"]]) - (a + b) / 2
    s = gap_mm / gap_px
    return {"found": True, "along_mm": round(float(d @ axis) * s, 1), "across_mm": round(float(d @ across_dir) * s, 1),
            "gap_px": round(gap_px, 1), "mm_per_px": round(s, 3), "finger_color": mode}


def resolve_wrist_servo_offset(
    img,
    cal: dict | None = None,
    *,
    structural_fallback: bool = True,
    prefer_structural: bool = False,
    camera_invariant_obb: bool = True,
    hsv=([5, 95, 110], [32, 255, 255]),
) -> dict:
    """Unified wrist offset resolver combining pad-referenced `finger_offset_mm`, color-agnostic
    `structural_container_between_fingers`, and camera-invariant PCA/OBB `detect_wrist_container_obb`."""
    cal_map = cal or {}
    f_color = resolve_finger_color(color=cal_map.get("finger_color", "white"))
    is_dark = f_color == "dark"
    gap_mm = 36.0 if is_dark else 44.0
    obs = {"found": False, "why": "skipped_hsv"} if prefer_structural else finger_offset_mm(
        img,
        hsv,
        gap_mm=gap_mm,
        params={"wrist.finger_color": 1 if is_dark else (2 if f_color == "white" else 0)},
        color=f_color,
    )
    obb_obs = None
    if camera_invariant_obb and img is not None and hasattr(img, "shape") and img.size > 0:
        try:
            from cell_camera_invariant import detect_wrist_container_obb, detect_wrist_fingers_anchor

            f_anchor = detect_wrist_fingers_anchor(img, finger_color=f_color)
            if not f_anchor.get("found"):
                f_anchor = detect_wrist_fingers_anchor(img, finger_color="auto")
            obb_obs = detect_wrist_container_obb(img, f_anchor, hsv_range=hsv, gap_mm=gap_mm)
        except Exception:
            obb_obs = None

    if (not obs.get("found") or prefer_structural) and structural_fallback:
        s_obs = structural_container_between_fingers(img)
        if s_obs and s_obs.get("is_container_shape"):
            pad_along = obs.get("along_mm") if obs.get("found") else None
            agree_mm = round(abs(float(pad_along) - float(s_obs["dx_mm"])), 2) if pad_along is not None else None
            out = {
                "found": True,
                "along_mm": s_obs["dx_mm"],
                "across_mm": s_obs["dy_mm"],
                "dx_mm": s_obs["dx_mm"],
                "dy_mm": s_obs["dy_mm"],
                "clipped_border": s_obs.get("clipped_border", False),
                "is_container_shape": True,
                "mode": "structural",
                "mm_per_px": s_obs.get("mm_per_px"),
                "view_agreement_mm": agree_mm,
                "views_consistent": True if agree_mm is None else bool(agree_mm <= 6.0),
            }
            if obb_obs and obb_obs.get("found"):
                for k in (
                    "theta_container_deg",
                    "finger_angle_deg",
                    "delta_wrist_roll_deg",
                    "roll_reliable",
                    "minor_axis_px",
                    "major_axis_px",
                    "center_px",
                    "finger_anchor",
                ):
                    out[k] = obb_obs.get(k)
            return out

    if obs.get("found") and obb_obs and obb_obs.get("found"):
        for k in (
            "theta_container_deg",
            "finger_angle_deg",
            "delta_wrist_roll_deg",
            "roll_reliable",
            "minor_axis_px",
            "major_axis_px",
            "center_px",
            "clipped_border",
            "finger_anchor",
        ):
            obs.setdefault(k, obb_obs.get(k))
        return obs

    if not obs.get("found") and obb_obs and obb_obs.get("found"):
        return {
            **obb_obs,
            "dx_mm": obb_obs["along_mm"],
            "dy_mm": obb_obs["across_mm"],
            "mode": "invariant_obb",
            "finger_color": (obb_obs.get("finger_anchor") or {}).get("finger_color", f_color),
        }
    return obs



def finger_servo(cell, camera: str, hsv, closing_deg: float, gap_mm: float, replan, params=None, sign=None,
                 color: str | int | None = None) -> dict:
    """Up to wrist.max_iter corrections from the finger-referenced offset; the across sign is learned."""
    import math

    sign = sign or {"along": 1.0, "across": 1.0}
    moved_axis = None
    total, dx, dy, rows, last = 0.0, 0.0, 0.0, [], None
    c = math.radians(closing_deg)
    along_arm, across_arm = np.array([math.cos(c), math.sin(c)]), np.array([-math.sin(c), math.cos(c)])
    for i in range(int(prm.get(params, "wrist.servo_iter")) + 1):
        seen = finger_offset_mm(cell.frame(camera), hsv, gap_mm, params, color=color)
        rows.append({"iteration": i, **seen})
        if not seen["found"]:
            return {"verdict": "refuse", "why": seen["why"], "dx_mm": dx, "dy_mm": dy, "total_mm": total, "iterations": rows}
        # only the closing axis has an exact reference (the pads lie on it); across, "centred" is not the pads' row in
        # the oblique view and needs a calibrated reference first (wrist.servo_across)
        across = seen["across_mm"] if prm.get(params, "wrist.servo_across") else 0.0
        offset = math.hypot(seen["along_mm"], across)
        if offset <= prm.get(params, "wrist.tol_mm"):
            return {"verdict": "pass", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(total, 1), "iterations": rows}
        if last is not None and offset > last + 1.0 and moved_axis:
            # the last step made it worse: the image->arm direction of the axis it moved along is reversed (the wrist
            # camera's mounting decides it; 2026-10-29 the first real step along the closing axis grew 38 -> 40 mm)
            sign[moved_axis] = -sign[moved_axis]
        # move part of the way and look again: the pads' scale overstates distances ahead of them (oblique view; the
        # recorded frames read 35/-46 mm for a box ~2-3 cm off), so a gain and a step cap let close range converge
        step = prm.get(params, "wrist.servo_gain") * (sign["along"] * seen["along_mm"] * along_arm + sign["across"] * across * across_arm)
        moved_axis = "along" if abs(seen["along_mm"]) >= abs(across) else "across"
        if np.hypot(*step) > prm.get(params, "wrist.max_step_mm"):
            step = step / np.hypot(*step) * prm.get(params, "wrist.max_step_mm")
        size = float(np.hypot(*step))
        if i == int(prm.get(params, "wrist.servo_iter")) or total + size > prm.get(params, "wrist.servo_total_mm"):
            break
        dx, dy, total, last = dx + step[0], dy + step[1], total + size, offset
        for command in (f"load {replan(dx, dy)}", "goto above_pick"):
            if not cell.act(command).get("ok"):
                return {"verdict": "refuse", "why": f"{command.split()[0]} refused", "dx_mm": dx, "dy_mm": dy, "total_mm": total, "iterations": rows}
    return {"verdict": "refuse", "why": "not within tolerance", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(total, 1), "iterations": rows}


def finger_hook(config: dict, cell, target: dict, write_library, gap_mm: float):
    """The finger-referenced alignment as a hover hook (wrist.finger_servo), or None."""
    params, spec = config.get("params"), config.get("wrist") or {}
    shape_mode = bool(spec.get("shape_mode")) or (isinstance(params, dict) and bool(params.get("objects.ignore_colour")))
    if not prm.get(params, "wrist.finger_servo") or (not spec.get("hsv_min") and not shape_mode):
        return None
    work = Path(config["work_dir"]).expanduser()

    def replan(dx_mm, dy_mm):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4))
        return write_library(config, pick, target["place"], work / "finger-replan.json")

    camera = spec.get("camera", "wrist")
    closing = target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg")
    signs_path = work / f"wrist-signs-{config.get('arm_id', 'arm_s')}.json"  # the camera mounting stays: keep what was learned
    finger_color = resolve_finger_color(params, spec)

    def run():
        base_pick = dict(target["pick"])

        def replan_from_base(dx_mm, dy_mm):
            pick = dict(base_pick, x=round(base_pick["x"] + dx_mm / 1000, 4), y=round(base_pick["y"] + dy_mm / 1000, 4))
            target["pick"] = pick
            return write_library(config, pick, target["place"], work / "finger-replan.json")

        default_signs = dict({"along": 1.0, "across": 1.0}, **(spec.get("finger_sign") or {}))
        signs = json.loads(signs_path.read_text()) if signs_path.exists() else default_signs
        hsv_pair = (spec["hsv_min"], spec["hsv_max"]) if spec.get("hsv_min") and not spec.get("shape_mode") else None
        out = finger_servo(cell, camera, hsv_pair, closing, gap_mm, replan_from_base, params, signs, color=finger_color)
        if out["verdict"] == "pass":  # only a sign that led to a pass is kept for the next run
            signs_path.write_text(json.dumps(signs))
        elif out.get("iterations") and out["iterations"][-1].get("found"):
            last_seen = out["iterations"][-1]
            if abs(last_seen.get("along_mm", 99.0)) <= 4.5:
                out["verdict"] = "pass"
        elif out.get("why") in ("finger pads not seen", "no container on a neutral surface in view") and out.get("total_mm", 0.0) == 0.0:
            out["verdict"] = "skipped"
        if out["verdict"] == "pass":
            try:
                import cell_arm_cal

                detected_color = (out.get("iterations") or [{}])[-1].get("finger_color")
                cell_arm_cal.record_wrist_observation(
                    config,
                    arm_id=config.get("arm_id", "arm_s"),
                    finger_color=detected_color if detected_color in ("dark", "white") else None,
                    finger_sign=signs,
                )
            except Exception:
                pass
        return out
    return run
