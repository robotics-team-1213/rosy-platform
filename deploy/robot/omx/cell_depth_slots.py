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
FLOOR_DEPTH_TOL_MM = 15.0  # a floor patch's depth versus the depth recorded for it at calibration (tilt and mounting drift)
PATCH_OFFSET_MAX_MM = 4.0  # each floor patch against the common plane
CHANGE_LEVEL = 60          # summed RGB difference that counts as a changed pixel
CHANGE_MIN_FRACTION = 0.25 # share of the slot that must have changed between the before and after top frames


def _depth_roi(to_depth: np.ndarray, roi, margin: int, shape) -> tuple[int, int, int, int] | None:
    """The colour ROI in depth coordinates, shrunk by `margin` DEPTH pixels on every side."""
    x0, y0, x1, y1 = roi
    a, b = to_depth @ [x0, y0, 1.0], to_depth @ [x1, y1, 1.0]
    h, w = shape
    xa, ya, xb, yb = int(round(a[0])) + margin, int(round(a[1])) + margin, int(round(b[0])) - margin, int(round(b[1])) - margin
    xa, ya, xb, yb = max(0, xa), max(0, ya), min(w, xb), min(h, yb)
    return (xa, ya, xb, yb) if xb - xa >= 4 and yb - ya >= 4 else None


def _patch(depth: np.ndarray, box) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    a, b, c, d = box
    sub = depth[b:d, a:c]
    yy, xx = np.mgrid[b:d, a:c]
    ok = sub > 0
    return xx[ok], yy[ok], sub[ok], float(ok.mean())


def depth_reference(depth: np.ndarray | None, colour: np.ndarray | None, slot_roi, floor_rois, tier: int, *,
                    floor_depth_mm=None, floor_tol_mm: float = FLOOR_DEPTH_TOL_MM,
                    to_depth: np.ndarray | None = None, align_edge_px: float | None = None) -> dict[str, Any]:
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
    if to_depth is None:
        if colour is None:
            out["reasons"].append("no colour frame to place the ROIs")
            return out
        try:
            heights = cell_depth.height_map(depth.astype(np.uint16), cell_depth.table_plane(depth.astype(np.uint16)))
            to_depth, align_edge_px = cell_depth.align_edges(colour, heights)
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
    patches = []
    for index, roi in enumerate(floor_rois):
        box = _depth_roi(to_depth, roi, margin, depth.shape)
        if box is None:
            out["reasons"].append(f"floor patch {index} is outside the depth frame or too small")
            continue
        x, y, z, valid = _patch(depth, box)
        if valid < MIN_VALID_RATIO or len(z) < 50:
            out["reasons"].append(f"floor patch {index}: valid depth ratio below 0.80 (covered or missing)")
            continue
        own = np.c_[x, y, np.ones(len(x))]
        own_rms = float(np.sqrt(np.mean((own @ np.linalg.lstsq(own, z, rcond=None)[0] - z) ** 2)))
        median = float(np.median(z))
        if own_rms > PLANE_RMS_MAX_MM:
            out["reasons"].append(f"floor patch {index} is not flat (rms {own_rms:.1f} mm)")
        elif abs(median - float(floor_depth_mm[index])) > floor_tol_mm:
            out["reasons"].append(f"floor patch {index} depth {median:.0f} mm is not the recorded floor {float(floor_depth_mm[index]):.0f} mm")
        else:
            patches.append((x, y, z, median))
    if out["reasons"]:
        return out
    x, y, z = (np.concatenate([p[i] for p in patches]) for i in range(3))
    design = np.c_[x, y, np.ones(len(x))]
    coef = np.linalg.lstsq(design, z, rcond=None)[0]
    rms = float(np.sqrt(np.mean((design @ coef - z) ** 2)))
    worst = 0.0
    for px, py, pz, _ in patches:  # each patch must sit on the common plane, not offset from the others
        worst = max(worst, abs(float(np.median(np.c_[px, py, np.ones(len(px))] @ coef - pz))))
    out.update(plane_rms_mm=round(rms, 2), patch_offset_mm=round(worst, 2))
    if rms > PLANE_RMS_MAX_MM or worst > PATCH_OFFSET_MAX_MM:
        out["reasons"].append(f"floor patches disagree (rms {rms:.1f} mm, offset {worst:.1f} mm)")
        return out
    box = _depth_roi(to_depth, slot_roi, margin, depth.shape)
    if box is None:
        out["reasons"].append("slot ROI is outside the depth frame or too small")
        return out
    sx, sy, sz, slot_valid = _patch(depth, box)
    out["valid_depth_ratio"] = round(slot_valid, 4)
    if slot_valid < MIN_VALID_RATIO:
        out["reasons"].append("slot valid depth ratio below 0.80")
        return out
    rel = (coef[0] * sx + coef[1] * sy + coef[2]) - sz  # > 0: nearer to the camera than the floor
    median = float(np.median(rel))
    fraction = float((rel >= 0.5 * expected).mean())
    out.update(ok=True, median_rel_mm=round(median, 2), raised_fraction=round(fraction, 3),
               occupied=bool(fraction >= OCCUPIED_FRACTION), r_k_mm=round(median - expected, 2))
    out["tier_ok"] = bool(out["occupied"] and abs(median - expected) <= TOL_MM)  # tier identification only
    return out


def change_evidence(before_top: np.ndarray | None, after_top: np.ndarray | None, slot_roi) -> dict[str, Any]:
    """Separate evidence that something was placed in the slot: the top picture changed there, and what changed is upright.

    Depth says which tier is filled; it does not say that the filling happened now or how the container lies. The same frame
    given as before and after changes nothing and is refused.
    """
    out = {"changed": False, "changed_fraction": 0.0, "orientation_ok": False, "orientation_class": None, "basis": "top_rgb_before_after"}
    if before_top is None or after_top is None or slot_roi is None or before_top.shape != after_top.shape:
        return out
    x0, y0, x1, y1 = (int(v) for v in slot_roi)
    diff = np.abs(before_top[y0:y1, x0:x1].astype(int) - after_top[y0:y1, x0:x1].astype(int)).sum(axis=2) > CHANGE_LEVEL
    if diff.size == 0:
        return out
    fraction = float(diff.mean())
    ys, xs = np.where(diff)
    out["changed_fraction"] = round(fraction, 3)
    out["changed"] = bool(fraction >= CHANGE_MIN_FRACTION)
    if out["changed"] and len(xs) > 20:
        span_u, span_v = np.percentile(xs, 95) - np.percentile(xs, 5), np.percentile(ys, 95) - np.percentile(ys, 5)
        aspect = float(span_u) / max(float(span_v), 1.0)
        out["orientation_class"] = "vertical_ns" if aspect <= 1.20 else "horizontal_ew"  # as cell_area_zones for yaw -90
        out["orientation_ok"] = aspect <= 1.20
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


def perceive(side_img, top_colour, top_depth, col, row, tier, z_profile, spec_id, slot_roi, floor_rois, floor_depth_mm=None):
    """The perceive_slot_z_mm record from a usable depth reference, or None (the caller then runs its original path)."""
    import cell_z_profile

    ref = depth_reference(top_depth, top_colour, slot_roi, floor_rois, tier, floor_depth_mm=floor_depth_mm)
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

    (frames[N,480,640], receipt) or (None, reason). The receipt carries the last frame's start-of-exposure wall time.
    """
    if not Path(device).exists():
        return None, "depth device missing"
    raw_path = Path(raw_path)
    started_wall, started = time.time(), time.monotonic()
    cmd = ["v4l2-ctl", "--verbose", "-d", device, "--set-fmt-video=width=640,height=480,pixelformat=Z16", f"--set-parm={int(fps)}",
           "--stream-mmap=3", f"--stream-skip={DEPTH_SKIP}", f"--stream-count={int(n)}", f"--stream-to={raw_path}"]
    fmt = "--set-fmt-video=width=640,height=480,pixelformat=Z16"
    try:
        try:
            done = run(cmd, timeout=float(timeout_s), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError:  # v4l2-ctl 1.32 only takes the format with a trailing space (as cell_depth)
            done = run([f"{fmt} " if part == fmt else part for part in cmd], timeout=float(timeout_s), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        raw = raw_path.read_bytes()
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (getattr(exc, "stderr", "") or "")[-120:]
        return None, f"depth burst failed: {type(exc).__name__} {detail}".strip()
    ended_wall, ended = time.time(), time.monotonic()
    size = 640 * 480 * 2
    lines = _DQBUF.findall(done.stderr or "")
    if len(raw) != n * size or len(lines) < n:
        return None, "depth burst returned the wrong number of frames"
    stamps = [float(t) for _, _, t in lines[-n:]]
    if any(b <= a for a, b in zip(stamps, stamps[1:])) or not started - 0.5 <= stamps[-1] <= ended + 0.5:
        return None, "depth burst frame stamps are not consecutive or not from this capture"
    frames = np.frombuffer(raw, dtype="<u2").reshape(n, 480, 640)
    offset = ((started_wall - started) + (ended_wall - ended)) / 2
    return frames, {"frames": int(n), "source_seq_last": int(lines[-1][0]), "exposure_wall_estimate_s": stamps[-1] + offset,
                    "first_exposure_wall_estimate_s": stamps[0] + offset, "capture_s": round(ended - started, 2),
                    "raw_sha256": hashlib.sha256(raw).hexdigest()}
