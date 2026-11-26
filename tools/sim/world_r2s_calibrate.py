#!/usr/bin/env python3
"""Photo-grounded Real-to-Sim (R2S) palette, floor-plane, and camera calibration for Rosy World.

Samples physical hardware material colors and rectified floor extents from bundled real-site
and cell photography (`site-birdview.jpg`, `field-photo.jpg`, `cell-photo.jpg`), transforms the
D435 top camera (`TOP_CAMERA_20261114`) and canonical `194.0 mm` (`v24-20261114-cad194`) CAD arm
bases into the site CAD frame using `site-registration.json`, runs `omx_map_gate` checks, and
emits `data/r2s-calibration.json` (`rosy.world.r2s-calibration.v1`) with single-frame photo and
future `v25` `190.0 mm` references.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

CANONICAL_PINK_STRIPES_X_M = (-0.414, -0.190, 0.032)
CANONICAL_PINK_BAR_Y_M = 0.022
ARM_PLATE_HALF_MM = 71.25
DEFAULT_ARM_AXES_CELL_M = {
    "arm_a": [0.077, -0.16675, 0.084],
    "arm_b": [0.077, 0.16975, 0.084],
}
DEFAULT_ARM_S_SITE = {
    "pose_m": [0.975, -0.004, 0.072],
    "yaw_rad": round(math.pi, 6),
}
DEFAULT_BIRDVIEW_PLANE = [-1.2875, -0.7147, 1.3184, 0.6885]
DEFAULT_TOP_CAMERA_20261114 = {
    "eye": [-0.0050, 0.0869, 0.6973],
    "focus": [0.0469, 0.0401, 0.2022],
    "up": [0.9943, -0.015, 0.1055],
    "f_px": 618.5,
    "width": 640,
    "height": 480,
}


def _median_hex(img: np.ndarray, y0: float, y1: float, x0: float, x1: float) -> tuple[str, list[int]]:
    h, w = img.shape[:2]
    r0, r1 = max(0, int(y0 * h)), min(h, max(1, int(y1 * h)))
    c0, c1 = max(0, int(x0 * w)), min(w, max(1, int(x1 * w)))
    patch = img[r0:r1, c0:c1]
    med = np.median(patch.reshape(-1, 3), axis=0).astype(int)
    return f"#{med[0]:02x}{med[1]:02x}{med[2]:02x}", [int(med[0]), int(med[1]), int(med[2])]


def _load_rgb(path: Path) -> np.ndarray | None:
    if not path.is_file():
        return None
    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB"))
    except (OSError, ValueError):
        return None


def sample_photo_palette(data_dir: Path) -> dict[str, Any]:
    """Sample median RGB/hex material colors from real cell and ceiling photographs."""
    bv = _load_rgb(data_dir / "site-birdview.jpg")
    fp = _load_rgb(data_dir / "field-photo.jpg")
    cp = _load_rgb(data_dir / "cell-photo.jpg")

    sources: dict[str, Any] = {}

    def record(key: str, img: np.ndarray | None, fname: str, roi: tuple[float, float, float, float], fallback: str) -> str:
        if img is not None:
            hex_val, rgb = _median_hex(img, *roi)
            sources[key] = {"source": fname, "roi": list(roi), "rgb": rgb, "hex": hex_val}
            return hex_val
        sources[key] = {"source": "fallback", "roi": list(roi), "hex": fallback}
        return fallback

    floor_hex = record("floor_mat", bv, "site-birdview.jpg", (0.62, 0.72, 0.25, 0.45), "#686b71")
    if fp is not None:
        record("floor_mat_field_lit", fp, "field-photo.jpg", (0.62, 0.72, 0.25, 0.45), "#a1a4ab")
    table_hex = record("worktable_yellow", cp if cp is not None else bv, "cell-photo.jpg" if cp is not None else "site-birdview.jpg",
                       (0.03, 0.14, 0.05, 0.20) if cp is not None else (0.04, 0.16, 0.69, 0.74), "#d09c19")
    pink_hex = record("pink_guide", bv if bv is not None else fp, "site-birdview.jpg" if bv is not None else "field-photo.jpg",
                      (0.46, 0.49, 0.30, 0.55), "#9a7281")
    green_hex = record("green_bay", bv if bv is not None else fp, "site-birdview.jpg" if bv is not None else "field-photo.jpg",
                       (0.08, 0.25, 0.29, 0.305), "#314f4a")
    ship_hex = record("ship_sky", cp, "cell-photo.jpg", (0.65, 0.75, 0.48, 0.58), "#98ceec")
    cargo_hex = record("orange_cargo", cp, "cell-photo.jpg", (0.42, 0.54, 0.53, 0.57), "#eb7733")

    return {
        "floor_mat_hex": floor_hex,
        "worktable_yellow_hex": table_hex,
        "pink_guide_hex": pink_hex,
        "green_bay_hex": green_hex,
        "ship_sky_hex": ship_hex,
        "orange_cargo_hex": cargo_hex,
        "wall_white_hex": "#e6eaef",
        "samples": sources,
    }


def calibrate_birdview_plane(birdview_path: Path) -> dict[str, Any]:
    """Detect horizontal pink guide bar and 3 charging stripes to align birdview photo to CAD axes."""
    img = _load_rgb(birdview_path)
    if img is None:
        return {
            "bundle_path": f"data/{birdview_path.name}",
            "plane": list(DEFAULT_BIRDVIEW_PLANE),
            "calibrated": False,
            "reason": "missing_image",
        }
    h, w = img.shape[:2]
    r = img[..., 0].astype(np.int32)
    g = img[..., 1].astype(np.int32)
    b = img[..., 2].astype(np.int32)
    mask = (r - g > 18) & (r > 120) & (b > 95) & (r - b < 55)

    x_left, x_right = int(w * 0.25), int(w * 0.65)
    bar_counts = mask[:, int(w * 0.28):int(w * 0.55)].sum(axis=1)
    y_px = int(np.argmax(bar_counts)) if bar_counts.size else -1
    if bar_counts.size == 0 or bar_counts[y_px] < max(15, int(w * 0.05)):
        return {
            "bundle_path": f"data/{birdview_path.name}",
            "size": [w, h],
            "plane": list(DEFAULT_BIRDVIEW_PLANE),
            "calibrated": False,
            "reason": "pink_bar_not_detected",
        }

    stripe_y0 = max(0, y_px - max(20, int(h * 0.22)))
    stripe_y1 = max(stripe_y0 + 1, y_px - max(4, int(h * 0.035)))
    col_counts = mask[stripe_y0:stripe_y1, :].sum(axis=0)
    win = max(6, int(w * 0.015))
    min_gap = max(12, int(w * 0.03))
    peaks: list[float] = []
    for x in range(x_left, x_right):
        val = int(col_counts[x])
        if val >= 8 and val == int(col_counts[max(0, x - win):min(w, x + win + 1)].max()):
            if not peaks or x - peaks[-1] > min_gap:
                # Sub-pixel centroid over half-max plateau eliminates discrete pixel plateau tie bias.
                lo, hi = max(0, x - win), min(w, x + win + 1)
                wgt = col_counts[lo:hi].astype(np.float64)
                half = 0.5 * float(wgt.max())
                wgt = np.where(wgt >= half, wgt, 0.0)
                xs = np.arange(lo, hi, dtype=np.float64)
                cx = float((xs * wgt).sum() / max(1e-9, wgt.sum()))
                peaks.append(cx)

    if len(peaks) != 3:
        return {
            "bundle_path": f"data/{birdview_path.name}",
            "size": [w, h],
            "plane": list(DEFAULT_BIRDVIEW_PLANE),
            "calibrated": False,
            "detected_stripe_peaks_px": peaks,
            "reason": "expected_three_pink_stripes",
        }

    span_m = CANONICAL_PINK_STRIPES_X_M[2] - CANONICAL_PINK_STRIPES_X_M[0]
    px_per_m = (peaks[2] - peaks[0]) / span_m
    x_center_px = peaks[1] - CANONICAL_PINK_STRIPES_X_M[1] * px_per_m
    y_center_px = y_px + CANONICAL_PINK_BAR_Y_M * px_per_m

    x0 = -x_center_px / px_per_m
    x1 = (w - x_center_px) / px_per_m
    y1 = y_center_px / px_per_m
    y0 = (y_center_px - h) / px_per_m

    residuals_mm = [
        round(((px - x_center_px) / px_per_m - ref_x) * 1000.0, 2)
        for px, ref_x in zip(peaks, CANONICAL_PINK_STRIPES_X_M)
    ]
    rms_mm = round(float(math.sqrt(sum(v * v for v in residuals_mm) / 3.0)), 2)

    return {
        "bundle_path": f"data/{birdview_path.name}",
        "size": [w, h],
        "px_per_m": round(float(px_per_m), 2),
        "plane": [round(float(v), 4) for v in (x0, y0, x1, y1)],
        "pink_stripe_peaks_px": [round(p, 2) for p in peaks],
        "pink_bar_y_px": y_px,
        "pink_stripe_residuals_mm": residuals_mm,
        "pink_stripe_residual_rms_mm": rms_mm,
        "calibrated": True,
    }


def _transform_cell_point(site_from_cell: dict[str, Any], pt: list[float]) -> list[float]:
    yaw = float(site_from_cell.get("yaw_rad", -math.pi / 2))
    tx, ty, tz = [float(v) for v in site_from_cell.get("translation_m", (0.793, 0.355, 0.0))]
    c, s = math.cos(yaw), math.sin(yaw)
    return [
        round(c * pt[0] - s * pt[1] + tx, 5),
        round(s * pt[0] + c * pt[1] + ty, 5),
        round(pt[2] + tz, 5),
    ]


def transform_arm_bases_to_site(
    site_from_cell: dict[str, Any],
    arm_axes_m: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform canonical 194.0 mm CAD arm base axes from cell frame into site-CAD coordinates."""
    axes = arm_axes_m if isinstance(arm_axes_m, dict) else {}
    a_cell = axes.get("arm_a") if isinstance(axes.get("arm_a"), list) and len(axes["arm_a"]) >= 3 else DEFAULT_ARM_AXES_CELL_M["arm_a"]
    b_cell = axes.get("arm_b") if isinstance(axes.get("arm_b"), list) and len(axes["arm_b"]) >= 3 else DEFAULT_ARM_AXES_CELL_M["arm_b"]
    a_site = _transform_cell_point(site_from_cell, [float(v) for v in a_cell[:3]])
    b_site = _transform_cell_point(site_from_cell, [float(v) for v in b_cell[:3]])
    yaw = float(site_from_cell.get("yaw_rad", -math.pi / 2))
    span_mm = round(math.hypot(b_site[0] - a_site[0], b_site[1] - a_site[1]) * 1000.0, 2)
    plate_inner_gap_mm = round(span_mm - 2.0 * ARM_PLATE_HALF_MM, 2)
    return {
        "arm_bases_site": {
            "arm_s": dict(DEFAULT_ARM_S_SITE),
            "arm_a": {"pose_m": a_site, "yaw_rad": round((yaw + math.pi / 2) % (2.0 * math.pi), 6)},
            "arm_b": {"pose_m": b_site, "yaw_rad": round((yaw - math.pi / 2) % (2.0 * math.pi), 6)},
        },
        "span_mm": span_mm,
        "plate_inner_gap_mm": plate_inner_gap_mm,
    }


def run_map_gate_audit(preset: str) -> dict[str, Any]:
    """Run omx_map_gate self-checks on the canonical cell layout when available."""
    import sys

    sim_dir = str(Path(__file__).resolve().parent)
    if sim_dir not in sys.path:
        sys.path.insert(0, sim_dir)
    try:
        import omx_map_gate
        import omx_two_arm_sites as sites
    except ImportError:
        return {"available": False, "preset": preset}
    try:
        result = omx_map_gate.gate(sites.Layout(preset=preset))
    except Exception as exc:
        return {"available": False, "preset": preset, "error": str(exc)}
    checks = [
        {
            "name": str(c.get("name", "")),
            "value_mm": c.get("value_mm"),
            "expected": str(c.get("expected", "")),
            "ok": bool(c.get("ok")),
        }
        for c in (result.get("checks") or [])
        if isinstance(c, dict)
    ]
    why = [str(item) for item in (result.get("why") or [])]
    return {
        "available": True,
        "ok": (not why) and all(c["ok"] for c in checks),
        "verdict": str(result.get("verdict", "")),
        "preset": preset,
        "why": why,
        "unconfirmed": [str(item) for item in (result.get("unconfirmed") or [])],
        "checks": checks,
    }


def transform_d435_to_site(
    site_from_cell: dict[str, Any],
    cam_cell: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map cell-frame TOP_CAMERA_20261114 pose into site-CAD coordinates."""
    cam = dict(DEFAULT_TOP_CAMERA_20261114 if cam_cell is None else cam_cell)
    yaw = float(site_from_cell.get("yaw_rad", -math.pi / 2))
    c, s = math.cos(yaw), math.sin(yaw)

    def map_pt(p: list[float]) -> list[float]:
        return _transform_cell_point(site_from_cell, p)

    def map_vec(v: list[float]) -> list[float]:
        return [
            round(c * v[0] - s * v[1], 5),
            round(s * v[0] + c * v[1], 5),
            round(v[2], 5),
        ]

    vfov_deg = round(math.degrees(2.0 * math.atan((float(cam["height"]) / 2.0) / float(cam["f_px"]))), 3)
    return {
        "source": "TOP_CAMERA_20261114",
        "f_px": float(cam["f_px"]),
        "resolution": [int(cam["width"]), int(cam["height"])],
        "aspect": round(float(cam["width"]) / float(cam["height"]), 4),
        "vfov_deg": vfov_deg,
        "cell_frame": {
            "eye": [float(v) for v in cam["eye"]],
            "focus": [float(v) for v in cam["focus"]],
            "up": [float(v) for v in cam["up"]],
            "vfovDeg": vfov_deg,
        },
        "site_frame": {
            "eye": map_pt(cam["eye"]),
            "focus": map_pt(cam["focus"]),
            "up": map_vec(cam["up"]),
            "vfovDeg": vfov_deg,
        },
    }


def build_r2s_calibration(bundle_dir: Path) -> dict[str, Any]:
    """Build complete R2S calibration artifact from a Rosy World bundle directory."""
    data_dir = bundle_dir / "data"
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    reg = json.loads((data_dir / "site-registration.json").read_text(encoding="utf-8"))
    geom = json.loads((data_dir / "geometry.json").read_text(encoding="utf-8"))

    palette = sample_photo_palette(data_dir)
    birdview = calibrate_birdview_plane(data_dir / "site-birdview.jpg")
    field_meta = manifest.get("field_photo") or {}
    field_entry = None
    if isinstance(field_meta.get("plane"), list) and len(field_meta["plane"]) >= 4:
        field_entry = {
            "bundle_path": field_meta.get("bundle_path", "data/field-photo.jpg"),
            "plane": [round(float(v), 4) for v in field_meta["plane"][:4]],
            "px_per_m": float(field_meta["plane"][4]) if len(field_meta["plane"]) > 4 else None,
            "calibration_revision": field_meta.get("calibration_revision"),
            "captured_at": field_meta.get("captured_at"),
            "calibrated": True,
        }

    preset = str(geom.get("preset", "v24-20261114-cad194"))
    arm_site_info = transform_arm_bases_to_site(reg["site_from_cell"], geom.get("arm_axes_m"))
    map_gate = run_map_gate_audit(preset)
    canonical_gap = round(float(geom.get("plate_inner_gap_mm", arm_site_info["plate_inner_gap_mm"])), 2)
    d435_cam = transform_d435_to_site(reg["site_from_cell"])
    reg_errors_mm = [
        round(float(e.get("error_m", 0.0)) * 1000.0, 6)
        for e in (reg.get("errors") or [])
        if isinstance(e, dict)
    ]

    return {
        "schema": "rosy.world.r2s-calibration.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "photo_calibrated_display",
        "palette": palette,
        "ground_photos": {
            "birdview": birdview,
            "field": field_entry,
        },
        "cameras": {
            "d435_top": d435_cam,
            "ceiling": {
                "eye": [0.0, 0.0, 2.35],
                "focus": [0.0, 0.0, 0.0],
                "up": [0.0, 1.0, 0.0],
                "vfovDeg": 40.0,
            },
        },
        "arm_bases_site": arm_site_info["arm_bases_site"],
        "map_gate": map_gate,
        "geometry_audit": {
            "canonical_preset": preset,
            "canonical_plate_inner_gap_mm": canonical_gap,
            "arm_ab_span_mm": arm_site_info["span_mm"],
            "planned_preset": preset,
            "planned_plate_inner_gap_mm": canonical_gap,
            "photo_reference_preset": "docks-photo",
            "measured_preset": "docks-photo",
            "measured_plate_inner_gap_mm": 189.8,
            "photo_reference_sigma_mm": 3.0,
            "plate_gap_delta_mm": round(189.8 - canonical_gap, 2),
            "future_v25_candidate_mm": 190.0,
            "sigma_xy_mm": 2.0,
            "d435_fit_rms_px": 1.6,
            "d435_fit_points": 17,
            "registration_max_error_mm": max(reg_errors_mm) if reg_errors_mm else None,
            "honest_note": "CAD·실물 기준 194.0 mm (v24-20261114-cad194) · 단일 프레임 참고 189.8 ± 3 mm · v25 후보 190 mm · D435 1.6 px RMS",
        },
    }


def write_r2s_calibration(bundle_dir: Path, *, update_sums: bool = False) -> Path:
    payload = build_r2s_calibration(bundle_dir)
    out_path = bundle_dir / "data" / "r2s-calibration.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if update_sums:
        lines = [
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle_dir).as_posix()}"
            for p in sorted(bundle_dir.rglob("*"))
            if p.is_file() and p.name != "SHA256SUMS.txt" and "__pycache__" not in p.parts
        ]
        (bundle_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="Rosy World bundle root containing manifest.json & data/")
    parser.add_argument("--update-sums", action="store_true", help="Recompute SHA256SUMS.txt after writing data/r2s-calibration.json")
    args = parser.parse_args(argv)
    out = write_r2s_calibration(args.bundle.resolve(), update_sums=args.update_sums)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
