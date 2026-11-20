"""D-1057: slot occupancy and tier from the D435 depth map, relative to the pallet floor of the same frame.

Why relative: the table-plane absolute height moves about 7 mm between frames (plane fit), but a container top minus the pallet
floor next to it, both read in the same depth image, is stable (28.6-33.7 mm for tier 1 on the real cell, expected 30).
The height is measured in depth coordinates against a plane fitted to floor patches, so the RGB-depth alignment (5.6-5.9 px
on the real cell) is used only to place the ROIs; the ROIs are shrunk by ALIGN_MARGIN_PX for that error.

It checks tier and occupancy (+-TOL_MM); it cannot see a 1-3 mm unseated cone, which the old absolute gate band tried to.
"""
from __future__ import annotations

from typing import Any

import numpy as np

import cell_depth

try:
    from omx_adapter.z_profile import TIER_TOP_Z_MM
except ImportError:  # same constants as omx_adapter.z_profile (CAD stack pitch)
    TIER_TOP_Z_MM = {1: 30.0, 2: 62.4, 3: 94.8}

TOL_MM = 7.0             # observed occupied tier-1 slots: 24.0-33.5 mm (nominal 30); empty slots: -5.6..+4.9 mm
MIN_VALID_RATIO = 0.80   # valid depth pixels in the slot and in the floor patches (as the existing gate)
PLANE_RMS_MAX_MM = 6.0   # floor patch flatness after the plane fit; observed 3.3-3.9 mm
ALIGN_EDGE_MAX_PX = 8.0  # RGB-depth edge error allowed for placing ROIs; observed 5.6-5.9 px, margin below covers it
ALIGN_MARGIN_PX = 6      # ROI shrink in colour pixels
OCCUPIED_FRACTION = 0.5  # share of slot pixels higher than half a tier above the floor


def _depth_roi(to_depth: np.ndarray, roi, shrink: int, shape) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = roi
    a = to_depth @ [x0 + shrink, y0 + shrink, 1.0]
    b = to_depth @ [x1 - shrink, y1 - shrink, 1.0]
    h, w = shape
    xa, ya, xb, yb = int(round(a[0])), int(round(a[1])), int(round(b[0])), int(round(b[1]))
    xa, ya, xb, yb = max(0, xa), max(0, ya), min(w, xb), min(h, yb)
    return (xa, ya, xb, yb) if xb - xa >= 4 and yb - ya >= 4 else None


def depth_reference(depth: np.ndarray | None, colour: np.ndarray | None, slot_roi, floor_rois, tier: int, *,
                    to_depth: np.ndarray | None = None, align_edge_px: float | None = None) -> dict[str, Any]:
    """Occupancy and tier of one slot from depth: {"ok", "occupied", "tier_ok", "median_rel_mm", ...}.

    `ok` says the reference itself is usable (valid ratio, floor flatness, alignment); `occupied`/`tier_ok` are the finding.
    """
    expected = float(TIER_TOP_Z_MM.get(int(tier), 30.0))
    out: dict[str, Any] = {"ok": False, "occupied": False, "tier_ok": False, "expected_mm": expected, "tier": int(tier),
                           "basis": "depth_relative_height", "reasons": []}
    if depth is None or getattr(depth, "ndim", 0) != 2 or not floor_rois or slot_roi is None:
        out["reasons"].append("no depth frame, slot ROI or floor ROIs")
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
    xs, ys, ds, total, valid = [], [], [], 0, 0
    for roi in floor_rois:
        box = _depth_roi(to_depth, roi, ALIGN_MARGIN_PX, depth.shape)
        if box is None:
            continue
        a, b, c, d = box
        sub = depth[b:d, a:c]
        yy, xx = np.mgrid[b:d, a:c]
        ok = sub > 0
        total, valid = total + sub.size, valid + int(ok.sum())
        xs.append(xx[ok]), ys.append(yy[ok]), ds.append(sub[ok])
    if not xs or valid < 200 or total == 0:
        out["reasons"].append("floor patches have too few depth pixels")
        return out
    x, y, z = np.concatenate(xs), np.concatenate(ys), np.concatenate(ds)
    design = np.c_[x, y, np.ones(len(x))]
    coef = np.linalg.lstsq(design, z, rcond=None)[0]
    rms = float(np.sqrt(np.mean((design @ coef - z) ** 2)))
    box = _depth_roi(to_depth, slot_roi, ALIGN_MARGIN_PX, depth.shape)
    if box is None:
        out["reasons"].append("slot ROI is outside the depth frame")
        return out
    a, b, c, d = box
    sub = depth[b:d, a:c]
    yy, xx = np.mgrid[b:d, a:c]
    ok = sub > 0
    slot_valid = float(ok.mean())
    out.update(valid_depth_ratio=round(min(slot_valid, valid / total), 4), plane_rms_mm=round(rms, 2))
    if slot_valid < MIN_VALID_RATIO or valid / total < MIN_VALID_RATIO:
        out["reasons"].append("valid depth ratio below 0.80")
    if rms > PLANE_RMS_MAX_MM:
        out["reasons"].append(f"floor patches are not flat (rms {rms:.1f} mm)")
    if out["reasons"]:
        return out
    rel = (coef[0] * xx[ok] + coef[1] * yy[ok] + coef[2]) - sub[ok]  # > 0: nearer to the camera than the floor
    median = float(np.median(rel))
    fraction = float((rel >= 0.5 * expected).mean())
    out.update(ok=True, median_rel_mm=round(median, 2), raised_fraction=round(fraction, 3),
               occupied=bool(fraction >= OCCUPIED_FRACTION), r_k_mm=round(median - expected, 2))
    out["tier_ok"] = bool(out["occupied"] and abs(median - expected) <= TOL_MM)
    return out


def tier_gate(ref: dict[str, Any], tier: int, spec_id: str = "C3") -> dict[str, Any]:
    """A z_gate dict (same keys as evaluate_signed_tier_residual_mm) from a depth reference: PASS for the right tier."""
    expected = float(TIER_TOP_Z_MM.get(int(tier), 30.0))
    base = {"expected_tier": int(tier), "expected_top_z_mm": expected, "spec_id": spec_id, "basis": "depth_relative_height",
            "tolerance_mm": TOL_MM}
    if not ref.get("ok"):
        return {**base, "verdict": "UNKNOWN", "failure_code": "S5_VIEW_OR_GATE_MISMATCH", "gate_ok": False,
                "reason": "; ".join(ref.get("reasons") or ["no usable depth reference"]), "z_top_mm": None, "r_k_mm": None}
    r_k = ref["r_k_mm"]
    if not ref["occupied"]:
        verdict, code = "FAIL", "S1_TARGET_EMPTY"
    elif abs(r_k) <= TOL_MM:
        verdict, code = "PASS", None
    else:
        verdict, code = "FAIL", "S2_TOPPLED_OR_SLUMPED" if r_k < 0 else "S5_HEIGHT_ANOMALY"
    return {**base, "verdict": verdict, "failure_code": code, "gate_ok": True, "z_top_mm": ref["median_rel_mm"], "r_k_mm": r_k}


def perceive(side_img, top_colour, top_depth, col, row, tier, z_profile, spec_id, slot_roi, floor_rois) -> dict[str, Any] | None:
    """The perceive_slot_z_mm record from a usable depth reference, or None (the caller then runs its original path)."""
    import cell_z_profile

    ref = depth_reference(top_depth, top_colour, slot_roi, floor_rois, tier)
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
