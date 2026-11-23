#!/usr/bin/env python3
"""Calibrated top-camera 640x480 pixel polygons for Pick -> Place goal overlays on the live preview."""
from __future__ import annotations

from pathlib import Path

from bench_record_handoff import load_json_value

_FALLBACK_ZONES = {
    "pallet": [[257, 151], [388, 153], [389, 403], [255, 403]],
    "temp_plate_a": [[405, 351], [611, 347], [624, 470], [402, 475]],
    "temp_plate_b": [[8, 344], [229, 339], [231, 478], [10, 482]],
    "belt": [[271, 19], [356, 20], [356, 162], [270, 161]],
    "stand": [[382, 52], [534, 52], [534, 148], [382, 148]],
}


def _lerp_quad(quad: list[list[float]], u0: float, u1: float, v0: float, v1: float) -> list[list[int]]:
    """Bilinearly crop [tl, tr, br, bl] quad into normalized sub-quad (u: left->right, v: top->bottom)."""
    tl, tr, br, bl = quad
    def pt(u: float, v: float) -> list[int]:
        top_x = tl[0] + (tr[0] - tl[0]) * u
        top_y = tl[1] + (tr[1] - tl[1]) * u
        bot_x = bl[0] + (br[0] - bl[0]) * u
        bot_y = bl[1] + (br[1] - bl[1]) * u
        return [round(top_x + (bot_x - top_x) * v), round(top_y + (bot_y - top_y) * v)]
    return [pt(u0, v0), pt(u1, v0), pt(u1, v1), pt(u0, v1)]


def _valid_quad(raw) -> list[list[float]] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    out = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        out.append([float(p[0]), float(p[1])])
    return out


def build_camera_overlay(prep: Path) -> dict:
    """Return calibrated 640x480 top-camera polygons matching r08 holds (h1=stern/top bay, h2=bow/bottom bay, r0=arm_a right)."""
    stack_a = load_json_value(prep / "cell-arm-a-stack.json", {})
    stack_b = load_json_value(prep / "cell-arm-b-stack.json", {})
    sites_a = stack_a.get("sites") if isinstance(stack_a, dict) and isinstance(stack_a.get("sites"), dict) else {}
    sites_b = stack_b.get("sites") if isinstance(stack_b, dict) and isinstance(stack_b.get("sites"), dict) else {}

    pallet = _valid_quad((sites_a.get("pallet") or {}).get("surface_px")) or _FALLBACK_ZONES["pallet"]
    tmp_a = _valid_quad((sites_a.get("temp_plate_a") or {}).get("surface_px")) or _FALLBACK_ZONES["temp_plate_a"]
    tmp_b = _valid_quad((sites_b.get("temp_plate_b") or {}).get("surface_px")) or _FALLBACK_ZONES["temp_plate_b"]
    belt = _valid_quad((sites_b.get("beltend") or {}).get("surface_px")) or _FALLBACK_ZONES["belt"]
    stand = _valid_quad((sites_a.get("stand") or {}).get("surface_px")) or _FALLBACK_ZONES["stand"]

    zones = {
        "pallet": [[round(x), round(y)] for x, y in pallet],
        "temp_plate_a": [[round(x), round(y)] for x, y in tmp_a],
        "temp_plate_b": [[round(x), round(y)] for x, y in tmp_b],
        "belt": [[round(x), round(y)] for x, y in belt],
        "stand": [[round(x), round(y)] for x, y in stand],
    }
    spots = {
        "pallet": zones["pallet"],
        "belt": zones["belt"],
        "stand": zones["stand"],
        "tmp-a": zones["temp_plate_a"],
        "tmp-b": zones["temp_plate_b"],
    }
    # Ship holds: u left->right maps r2 (arm_b) -> r1 -> r0 (arm_a); v upper bay = h1 (near belt/stern), lower bay = h2 (bow).
    col_u = {2: (0.06, 0.35), 1: (0.36, 0.64), 0: (0.65, 0.94)}
    hold_v = {1: (0.185, 0.515), 2: (0.53, 0.86)}
    for h, (v0, v1) in hold_v.items():
        spots[f"ship-h{h}"] = _lerp_quad(pallet, 0.06, 0.94, v0, v1)
        for r, (u0, u1) in col_u.items():
            spots[f"ship-h{h}r{r}"] = _lerp_quad(pallet, u0, u1, v0, v1)

    # Temp plates: lane 1 is nearest the center ship (left side of plate A, right side of plate B).
    for idx, (u0, u1) in ((1, (0.04, 0.34)), (2, (0.35, 0.65)), (3, (0.66, 0.96))):
        spots[f"tmp-a-{idx}"] = _lerp_quad(tmp_a, u0, u1, 0.08, 0.94)
    for idx, (u0, u1) in ((1, (0.66, 0.96)), (2, (0.35, 0.65)), (3, (0.04, 0.34))):
        spots[f"tmp-b-{idx}"] = _lerp_quad(tmp_b, u0, u1, 0.08, 0.94)

    warp = (((stack_a.get("cameras") or {}).get("top") or {}).get("warp_to_reference") or {}).get("measured") if isinstance(stack_a, dict) else None
    return {
        "frame": {"width": 640, "height": 480},
        "arm_a_side": "right",
        "warp_measured": warp,
        "zones": zones,
        "spots": spots,
    }
