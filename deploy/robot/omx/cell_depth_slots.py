"""D-1057: slot occupancy and tier from the D435 depth map, relative to the pallet floor of the same frame.

Why relative: the table-plane absolute height moves about 7 mm between frames (plane fit), but a container top minus the pallet
floor next to it, both read in the same depth image, is stable (28.6-33.7 mm for tier 1 on the real cell, expected 30).
The height is measured in depth coordinates against a plane fitted to floor patches, so the RGB-depth alignment (5.6-5.9 px
on the real cell) is used only to place the ROIs; the ROIs are shrunk by ALIGN_MARGIN_PX for that error.

It checks tier and occupancy (+-TOL_MM); it cannot see a 1-3 mm unseated cone, which the old absolute gate band tried to.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

import cell_depth

try:
    from omx_adapter.z_profile import TIER_TOP_Z_MM
except ImportError:  # same constants as omx_adapter.z_profile (CAD stack pitch)
    TIER_TOP_Z_MM = {1: 30.0, 2: 62.4, 3: 94.8}

TOL_MM = 7.0             # tier IDENTIFICATION only (not seating): occupied tier-1 slots 24.0-33.5 mm (nominal 30), empty -5.6..+4.9 mm
MIN_VALID_RATIO = 0.80   # valid depth pixels in the slot and in the floor patches (as the existing gate)
PLANE_RMS_MAX_MM = 6.0   # floor patch flatness after the plane fit; observed 3.3-3.9 mm
ALIGN_EDGE_MAX_PX = 8.0  # RGB-depth edge error allowed for placing ROIs; observed 5.6-5.9 px, margin below covers it
OCCUPIED_FRACTION = 0.5  # share of slot pixels higher than half a tier above the floor
FLOOR_DEPTH_TOL_MM = 4.0   # a floor patch's depth versus the depth recorded for it at calibration; single-frame noise is 0.8-1.5 mm,
#                            median-of-5 0.3-0.5 mm, so 4 mm is a wide margin for noise and a narrow one for a lifted floor
LOCAL_EDGE_MAX_PX = 8.0    # RGB-depth edge error measured inside the slot ROI (same limit as the whole-frame alignment)
ELONGATION_MIN = 1.5       # raised blob major/minor axis ratio for an upright container (30 x 90 mm)
AXIS_MAX_DEG = 25.0        # major axis angle from the picture vertical
CHANGE_LEVEL_STD = 0.5     # brightness-normalised top difference (global mean/contrast removed) that counts as changed
PATCH_OFFSET_MAX_MM = 4.0  # each floor patch against the common plane
CHANGE_MIN_FRACTION = 0.25 # share of the slot that must have changed between the before and after top frames


def _depth_roi(to_depth: np.ndarray, roi, margin: int, shape) -> tuple[int, int, int, int] | None:
    """The colour ROI in depth coordinates, shrunk by `margin` DEPTH pixels on every side."""
    x0, y0, x1, y1 = roi
    a, b = to_depth @ [x0, y0, 1.0], to_depth @ [x1, y1, 1.0]
    h, w = shape
    xa, ya, xb, yb = int(round(a[0])) + margin, int(round(a[1])) + margin, int(round(b[0])) - margin, int(round(b[1])) - margin
    xa, ya, xb, yb = max(0, xa), max(0, ya), min(w, xb), min(h, yb)
    return (xa, ya, xb, yb) if xb - xa >= 4 and yb - ya >= 4 else None


def _patch(grid: np.ndarray, box, *, finite_valid: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    a, b, c, d = box
    sub = grid[b:d, a:c]
    yy, xx = np.mgrid[b:d, a:c]
    ok = np.isfinite(sub) if finite_valid else (sub > 0)
    return xx[ok], yy[ok], sub[ok], float(ok.mean())


def local_edge_error(colour: np.ndarray | None, depth: np.ndarray, to_depth: np.ndarray, roi, pad: int = 16) -> float | None:
    """Mean distance (depth pixels) from the picture edges inside the slot ROI to the nearest depth edge, through `to_depth`.

    A local check of the alignment where it matters; None when the ROI has too few edges to measure (empty slot).
    """
    import cv2

    if colour is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in roi)
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(colour.shape[1], x1 + pad), min(colour.shape[0], y1 + pad)
    gray = cv2.cvtColor(colour[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(cv2.Canny(gray, 50, 150) > 0)
    smooth = cv2.GaussianBlur(np.where(depth > 0, depth, np.nan).astype(np.float32), (5, 5), 0)
    smooth = np.nan_to_num(smooth, nan=0.0)
    grad = np.hypot(cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)) / 8.0
    edges = (grad > 6.0) & (smooth > 0)
    if len(xs) < 30 or edges.sum() < 30:
        return None
    dist = cv2.distanceTransform((~edges).astype(np.uint8), cv2.DIST_L2, 3)
    pts = to_depth @ np.vstack([xs + x0, ys + y0, np.ones(len(xs))])
    u = np.clip(np.round(pts[0]).astype(int), 0, depth.shape[1] - 1)
    v = np.clip(np.round(pts[1]).astype(int), 0, depth.shape[0] - 1)
    return float(np.median(dist[v, u]))


def _orientation(sx: np.ndarray, sy: np.ndarray, raised: np.ndarray) -> dict[str, Any]:
    """Principal axis of the raised blob (depth pixels at or above half a tier): upright means long and near the vertical."""
    out = {"ok": False, "elongation": None, "angle_from_vertical_deg": None}
    if int(raised.sum()) < 20:
        return out
    cov = np.cov(np.vstack([sx[raised], sy[raised]]))
    values, vectors = np.linalg.eigh(cov)
    major = vectors[:, 1]
    elongation = float(np.sqrt(max(values[1], 1e-9) / max(values[0], 1e-9)))
    angle = float(np.degrees(np.arctan2(abs(major[0]), abs(major[1]))))
    out.update(elongation=round(elongation, 2), angle_from_vertical_deg=round(angle, 1),
               ok=bool(elongation >= ELONGATION_MIN and angle <= AXIS_MAX_DEG))
    return out


def frame_alignment(depth: np.ndarray, colour: np.ndarray):
    """Fit the global RGB-to-depth transform once for all ROIs in a frame pair."""
    if depth is None or getattr(depth, "ndim", 0) != 2 or colour is None:
        raise ValueError("missing depth or colour frame")
    raw = depth.astype(np.uint16)
    heights = cell_depth.height_map(raw, cell_depth.table_plane(raw))
    return cell_depth.align_edges(colour, heights)


def depth_reference(depth: np.ndarray | None, colour: np.ndarray | None, slot_roi, floor_rois, tier: int, *,
                    floor_depth_mm=None, floor_tol_mm: float = FLOOR_DEPTH_TOL_MM,
                    to_depth: np.ndarray | None = None, align_edge_px: float | None = None,
                    factory: dict | None = None) -> dict[str, Any]:
    """Occupancy and tier of one slot from depth: {"ok", "occupied", "tier_ok", "median_rel_mm", ...}.

    `ok` says the reference itself is usable; `occupied`/`tier_ok` are the finding. Every floor patch is checked on its own:
    enough valid depth, flat (own plane fit), its median depth within `floor_tol_mm` of the depth recorded for it at
    calibration (`floor_depth_mm`, required: a flat surface laid over the floor is not the floor), and consistent with
    the common plane. The slot ROI and the patches are shrunk in depth pixels by the alignment error plus two.
    """
    expected = float(TIER_TOP_Z_MM.get(int(tier), 30.0))
    out: dict[str, Any] = {"ok": False, "occupied": False, "tier_ok": False, "expected_mm": expected, "tier": int(tier),
                           "basis": "depth_relative_height", "reasons": []}
    if depth is None or getattr(depth, "ndim", 0) != 2 or not floor_rois or slot_roi is None:
        out["reasons"].append("no depth frame, slot ROI or floor ROIs")
        return out
    if (not isinstance(floor_depth_mm, (list, tuple)) or len(floor_depth_mm) != len(floor_rois)
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) for v in floor_depth_mm)):
        out["reasons"].append("no recorded floor depth for every floor patch")
        return out
    depth = np.asarray(depth, dtype=float)
    grid, finite_valid, plane_info, cam_k = depth, False, None, None
    if factory is not None:
        import cell_depth_pose

        grid, plane_info = cell_depth_pose.height_map_in_colour(depth, factory)
        if not plane_info.get("ok"):
            out["reasons"].append(str(plane_info.get("reason") or "factory depth plane failed"))
            return out
        _, cam_k, _, _ = cell_depth_pose.calibration(factory)
        to_depth, align_edge_px, finite_valid = np.eye(3), 0.0, True
    elif to_depth is None:
        if colour is None:
            out["reasons"].append("no colour frame to place the ROIs")
            return out
        try:
            to_depth, align_edge_px = frame_alignment(depth, colour)
        except (ValueError, TypeError, IndexError):
            out["reasons"].append("RGB-depth alignment failed (too little valid depth)")
            return out
    to_depth = np.asarray(to_depth, dtype=float)
    out["align_edge_px"] = None if align_edge_px is None else round(float(align_edge_px), 2)
    if align_edge_px is None or not np.isfinite(align_edge_px) or float(align_edge_px) > ALIGN_EDGE_MAX_PX:
        out["reasons"].append(f"RGB-depth alignment error above {ALIGN_EDGE_MAX_PX} px")
        return out
    margin = int(np.ceil(float(align_edge_px))) + 2
    out["roi_margin_depth_px"] = margin
    raw_floor_mode = not finite_valid or any(abs(float(v)) > 100.0 for v in floor_depth_mm)

    def _to_floor_val(val: float, mx: float, my: float) -> float:
        if not (finite_valid and raw_floor_mode and plane_info and cam_k is not None):
            return val
        nx, ny, nz = (float(c) for c in plane_info["normal"])
        rdot = (mx - cam_k[0, 2]) * (nx / cam_k[0, 0]) + (my - cam_k[1, 2]) * (ny / cam_k[1, 1]) + nz
        return (val - float(plane_info["height_mm"])) / rdot if abs(rdot) > 1e-6 else val

    patches = []
    for index, roi in enumerate(floor_rois):
        box = _depth_roi(to_depth, roi, margin, grid.shape)
        if box is None:
            out["reasons"].append(f"floor patch {index} is outside the depth frame or too small")
            continue
        x, y, z, valid = _patch(grid, box, finite_valid=finite_valid)
        if valid < MIN_VALID_RATIO or len(z) < 50:
            out["reasons"].append(f"floor patch {index}: valid depth ratio below 0.80 (covered or missing)")
            continue
        own = np.c_[x, y, np.ones(len(x))]
        own_rms = float(np.sqrt(np.mean((own @ np.linalg.lstsq(own, z, rcond=None)[0] - z) ** 2)))
        median = _to_floor_val(float(np.median(z)), float(np.mean(x)), float(np.mean(y)))
        if own_rms > PLANE_RMS_MAX_MM:
            out["reasons"].append(f"floor patch {index} is not flat (rms {own_rms:.1f} mm)")
        elif abs(median - float(floor_depth_mm[index])) > floor_tol_mm:
            out["reasons"].append(f"floor patch {index} depth {median:.0f} mm is not the recorded floor {float(floor_depth_mm[index]):.0f} mm")
        else:
            patches.append((x, y, z, median, index))
    if out["reasons"]:
        return out
    x, y, z = (np.concatenate([p[i] for p in patches]) for i in range(3))
    # the fitted common plane must also reproduce the recorded (calibration) floor at every patch, not only the patch medians
    design0 = np.c_[x, y, np.ones(len(x))]
    coef0 = np.linalg.lstsq(design0, z, rcond=None)[0]
    for px, py, _pz, _median, index in patches:
        mx, my = float(np.mean(px)), float(np.mean(py))
        at_patch = _to_floor_val(float(coef0[0] * mx + coef0[1] * my + coef0[2]), mx, my)
        if abs(at_patch - float(floor_depth_mm[index])) > floor_tol_mm:
            out["reasons"].append(f"the common floor plane differs from the calibration plane by more than {floor_tol_mm} mm")
            return out
    design = np.c_[x, y, np.ones(len(x))]
    coef = np.linalg.lstsq(design, z, rcond=None)[0]
    rms = float(np.sqrt(np.mean((design @ coef - z) ** 2)))
    worst = 0.0
    for px, py, pz, _, _ in patches:  # each patch must sit on the common plane, not offset from the others
        worst = max(worst, abs(float(np.median(np.c_[px, py, np.ones(len(px))] @ coef - pz))))
    out.update(plane_rms_mm=round(rms, 2), patch_offset_mm=round(worst, 2))
    if rms > PLANE_RMS_MAX_MM or worst > PATCH_OFFSET_MAX_MM:
        out["reasons"].append(f"floor patches disagree (rms {rms:.1f} mm, offset {worst:.1f} mm)")
        return out
    box = _depth_roi(to_depth, slot_roi, margin, grid.shape)
    if box is None:
        out["reasons"].append("slot ROI is outside the depth frame or too small")
        return out
    sx, sy, sz, slot_valid = _patch(grid, box, finite_valid=finite_valid)
    out["valid_depth_ratio"] = round(slot_valid, 4)
    if slot_valid < MIN_VALID_RATIO:
        out["reasons"].append("slot valid depth ratio below 0.80")
        return out
    edge_src = np.where(np.isfinite(grid), np.maximum(1.0, float(plane_info["height_mm"]) - grid), 0.0) if finite_valid else grid
    local = local_edge_error(colour, edge_src, to_depth, slot_roi)
    out["local_edge_px"] = None if local is None else round(local, 2)
    if local is not None and local > LOCAL_EDGE_MAX_PX:
        out["reasons"].append(f"RGB-depth edge error {local:.1f} px inside the slot ROI exceeds {LOCAL_EDGE_MAX_PX} px")
        return out
    rel = (sz - (coef[0] * sx + coef[1] * sy + coef[2])) if finite_valid else ((coef[0] * sx + coef[1] * sy + coef[2]) - sz)  # > 0: nearer to the camera than the floor
    median = float(np.median(rel))
    fraction = float((rel >= 0.5 * expected).mean())
    out["orientation"] = _orientation(sx, sy, rel >= 0.5 * expected)
    out.update(ok=True, median_rel_mm=round(median, 2), raised_fraction=round(fraction, 3),
               occupied=bool(fraction >= OCCUPIED_FRACTION), r_k_mm=round(median - expected, 2))
    out["tier_ok"] = bool(out["occupied"] and abs(median - expected) <= TOL_MM)  # tier identification only
    return out


def change_evidence(before_top: np.ndarray | None, after_top: np.ndarray | None, slot_roi, depth_ref: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Evidence that an OBJECT appeared in the slot now, and how it lies.

    The top picture must change in the slot after global brightness and contrast are removed (a light change alone changes
    nothing), and the depth must show the slot raised by at least half a tier (`depth_ref`: raised pixel fraction). The
    direction is the principal axis of the raised depth blob. Depth alone does not say that the filling happened now, and a
    brightness change alone is not an object.
    """
    out = {"changed": False, "changed_fraction": 0.0, "orientation_ok": False, "orientation_class": None,
           "basis": "top_rgb_normalised_before_after+depth_raised_blob", "depth_raised": False}
    ref = depth_ref or {}
    out["depth_raised"] = bool(ref.get("ok") and ref.get("raised_fraction", 0.0) >= OCCUPIED_FRACTION)
    orient = ref.get("orientation") or {}
    out["orientation_ok"] = bool(out["depth_raised"] and orient.get("ok"))
    out["orientation_class"] = None if orient.get("elongation") is None else ("vertical_ns" if orient.get("ok") else "not_upright")
    if before_top is None or after_top is None or slot_roi is None or before_top.shape != after_top.shape:
        return out

    def normal(image: np.ndarray) -> np.ndarray:
        gray = image.astype(np.float32).mean(axis=2)
        return (gray - gray.mean()) / max(float(gray.std()), 1.0)

    x0, y0, x1, y1 = (int(v) for v in slot_roi)
    diff = np.abs(normal(before_top)[y0:y1, x0:x1] - normal(after_top)[y0:y1, x0:x1]) > CHANGE_LEVEL_STD
    if diff.size == 0:
        return out
    out["changed_fraction"] = round(float(diff.mean()), 3)
    out["changed"] = bool(diff.mean() >= CHANGE_MIN_FRACTION and out["depth_raised"])  # both are required
    return out


def tier_gate(ref: dict[str, Any], tier: int, spec_id: str = "C3") -> dict[str, Any]:
    """The z_gate of a depth reference. TOL_MM only identifies the tier; seating and height anomalies (S5/S6, S2) are judged by
    the unchanged evaluate_signed_tier_residual_mm band on the same residual."""
    from omx_adapter.z_profile import evaluate_signed_tier_residual_mm

    expected = float(TIER_TOP_Z_MM.get(int(tier), 30.0))
    base = {"expected_tier": int(tier), "expected_top_z_mm": expected, "spec_id": spec_id, "basis": "depth_relative_height",
            "tier_tolerance_mm": TOL_MM}
    if not ref.get("ok"):
        return {**base, "verdict": "UNKNOWN", "failure_code": "S5_VIEW_OR_GATE_MISMATCH", "gate_ok": False,
                "reason": "; ".join(ref.get("reasons") or ["no usable depth reference"]), "z_top_mm": None, "r_k_mm": None}
    if not ref["occupied"]:
        return {**base, "verdict": "FAIL", "failure_code": "S1_TARGET_EMPTY", "gate_ok": True, "z_top_mm": ref["median_rel_mm"],
                "r_k_mm": ref["r_k_mm"]}
    if not ref["tier_ok"]:  # another tier than the one asked for
        return {**base, "verdict": "FAIL", "failure_code": "S2_TOPPLED_OR_SLUMPED" if ref["r_k_mm"] < 0 else "S5_HEIGHT_ANOMALY",
                "gate_ok": True, "z_top_mm": ref["median_rel_mm"], "r_k_mm": ref["r_k_mm"]}
    return {**base, **evaluate_signed_tier_residual_mm(ref["median_rel_mm"], tier, valid_depth_ratio=ref["valid_depth_ratio"],
                                                       spec_id=spec_id), "basis": "depth_relative_height"}


def perceive(side_img, top_colour, top_depth, col, row, tier, z_profile, spec_id, slot_roi, floor_rois,
             floor_depth_mm=None, *, factory: dict | None = None):
    """The perceive_slot_z_mm record from a usable depth reference, or None (the caller then runs its original path)."""
    import cell_z_profile

    ref = depth_reference(top_depth, top_colour, slot_roi, floor_rois, tier, floor_depth_mm=floor_depth_mm, factory=factory)
    if not ref["ok"]:
        return None
    checks = cell_z_profile._current_frame_calibration_checks(side_img, top_colour, top_depth, None, z_profile,
                                                              ref["valid_depth_ratio"], ref)
    gate = tier_gate(ref, tier, spec_id)
    inferred = min((1, 2, 3), key=lambda t: abs(TIER_TOP_Z_MM[t] - ref["median_rel_mm"]))
    return {"found": True, "basis": "depth_relative_height", "col": int(col), "row": int(row), "expected_tier": int(tier),
            "inferred_tier": inferred, "measured_top_z_mm": ref["median_rel_mm"], "expected_top_z_mm": TIER_TOP_Z_MM[int(tier)],
            "valid_depth_ratio": ref["valid_depth_ratio"], "measurement_calibrated": True, "calibration_checks": checks,
            "depth_reference": ref, "r_k_mm": gate["r_k_mm"], "spec_id": gate["spec_id"], "spec_gate": gate}


DEPTH_BURST_S = 3.0      # hard limit for the whole burst (warm-up included)
DEPTH_FPS = 15           # 17 frames (12 warm-up + 5) take about 1.2 s; the single-frame capture runs at 6 fps
DEPTH_SKIP = 12          # warm-up frames, as the single-frame capture
_DQBUF = re.compile(r"cap dqbuf:.*?seq:\s*(\d+).*?bytesused:\s*(\d+).*?ts:\s*([0-9.]+)")


def median_depth(frames: np.ndarray) -> tuple[np.ndarray, float]:
    """Per-pixel median of N depth frames (mm, 0 = invalid). A pixel counts only when more than half of the frames are valid
    there; the rest become 0. Returns (map, fraction of valid pixels)."""
    frames = np.asarray(frames)
    count = (frames > 0).sum(axis=0)
    stack = np.where(frames > 0, frames.astype(np.float32), np.nan)
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(stack, axis=0)
    out = np.where(count * 2 > frames.shape[0], med, 0.0)
    out = np.nan_to_num(out, nan=0.0).round().astype(np.uint16)
    return out, float((out > 0).mean())


def capture_depth_frames(device: str, n: int, raw_path: Path, *, timeout_s: float = DEPTH_BURST_S,
                         fps: int = DEPTH_FPS, run=subprocess.run) -> tuple[np.ndarray, dict[str, Any]] | tuple[None, str]:
    """N consecutive Z16 frames from one V4L2 stream (the depth node the cell code already reads), inside `timeout_s`.

    One deadline covers the whole call including the format-spelling retry. Every kept frame is checked as the single-frame
    capture checks its one frame (start-of-exposure monotonic stamp, exact buffer size, a stamp from this capture), plus
    consecutive sequence numbers and stamps, and a wall/monotonic offset that did not move. Returns
    (frames[N,480,640], receipt) or (None, reason); the receipt holds the first and last exposure wall times.
    """
    if not Path(device).exists():
        return None, "depth device missing"
    raw_path = Path(raw_path)
    started_wall, started = time.time(), time.monotonic()
    deadline = started + float(timeout_s)
    cmd = ["v4l2-ctl", "--verbose", "-d", device, "--set-fmt-video=width=640,height=480,pixelformat=Z16", f"--set-parm={int(fps)}",
           "--stream-mmap=3", f"--stream-skip={DEPTH_SKIP}", f"--stream-count={int(n)}", f"--stream-to={raw_path}"]
    fmt = "--set-fmt-video=width=640,height=480,pixelformat=Z16"

    def attempt(command):
        left = deadline - time.monotonic()
        if left <= 0.2:
            raise subprocess.TimeoutExpired("v4l2-ctl", timeout_s)
        return run(command, timeout=left, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    try:
        try:
            done = attempt(cmd)
        except subprocess.CalledProcessError:  # v4l2-ctl 1.32 only takes the format with a trailing space (as cell_depth)
            done = attempt([f"{fmt} " if part == fmt else part for part in cmd])
        raw = raw_path.read_bytes()
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (getattr(exc, "stderr", "") or "")[-120:]
        return None, f"depth burst failed: {type(exc).__name__} {detail}".strip()
    ended_wall, ended = time.time(), time.monotonic()
    size = 640 * 480 * 2
    rows = [(int(a), int(b), float(c), "ts-monotonic, ts-src-soe" in line) for line in (done.stderr or "").splitlines()
            if (hit := _DQBUF.search(line)) for a, b, c in [hit.groups()]]
    if len(raw) != n * size or len(rows) < n:
        return None, "depth burst returned the wrong number of frames"
    kept = rows[-n:]
    if any(not flag or used != size for _, used, _, flag in kept):
        return None, "depth burst frame is not a start-of-exposure monotonic buffer of the exact size"
    seqs, stamps = [r[0] for r in kept], [r[2] for r in kept]
    if any(b != a + 1 for a, b in zip(seqs, seqs[1:])) or any(b <= a for a, b in zip(stamps, stamps[1:])):
        return None, "depth burst sequence or stamps are not consecutive"
    if not all(started - 0.5 <= t <= ended + 0.5 for t in stamps):
        return None, "depth burst has a frame that is not from this capture"
    start_offset, end_offset = started_wall - started, ended_wall - ended
    if abs(start_offset - end_offset) > 0.5:
        return None, "the wall clock moved during the depth burst"
    frames = np.frombuffer(raw, dtype="<u2").reshape(n, 480, 640)
    offset = (start_offset + end_offset) / 2
    return frames, {"frames": int(n), "source_seq_last": seqs[-1], "exposure_wall_estimate_s": stamps[-1] + offset,
                    "first_exposure_wall_estimate_s": stamps[0] + offset, "capture_s": round(ended - started, 2),
                    "wall_bridge_uncertainty_s": abs(start_offset - end_offset) / 2 + 0.01,
                    "raw_sha256": hashlib.sha256(raw).hexdigest()}
