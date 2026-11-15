#!/usr/bin/env python3
"""Containers stacked by the arm in one slot, read by the top camera: does each tier's top face come out the size,
height and place it is? No board, no tags, no trust in the arm's FK.

Why (2026-11-14): the mentor asked to validate the camera model in a restricted area first; the arm can stack, but
its FK is ~8 mm off, so it only carries. The truths are the containers themselves (CAD top 90 x 30 or 60 x 30 mm,
30 mm per tier) and the empty slot's floor seen by depth. Each top face is cut out by its own colour in the COLOUR
image (depth only drops the side faces by height), its corner rays meet a plane at the measured top height, and the
face's sides are compared with CAD. That tests the colour camera model; depth alone would test only itself.
What decides (simulated, panel 2026-11-14, stack 150 mm off axis): a focal length 3 % off reads the 90 mm side 2.6 mm
and the 30 mm side 0.9 mm off, while an outline edge 1 px off adds ~1.8 mm to both sides alike; so the gate is each
side within 2.5 mm (one systematic edge pixel is ~1.8) and the long-side error minus the short-side error within
1.5 mm (a true model rendered through pixel edges read 0.9; 3 % off reads ~6, 1 % ~1.3: finer K is the tags' or
`cell_device_intrinsics verify`'s job). A face under 85 % of its CAD area is reported hidden (a wall or link over it),
not as a size error. Top faces only: a side face is the same colour but darker, so pixels under 85 % of the face's
bright end are dropped (without it the long side read 2.2 mm long). The spread of the tiers' centres does not see K
or tilt (0.35 mm at 3 %); it is kept as the stack's own consistency (slot tolerance 3.5 mm). The
reference plane is fitted on a box around the slot: a 2 deg tilt pivoting there moves the tops by 0.1 mm, pivoting
150 mm away by up to 5 mm.

  cell_stack_check.py --factory factory.json --roi 300,180,420,320 --cad 90x30 --tier 0=DIR0 --tier 1=DIR1 ...
  DIRk holds top.jpg and depth.raw (Z16 frames of the factory depth size); tier 0 is the empty slot.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_depth_pose as dp
import cell_shared_markers as sm

TIER_MM = 30.0
ORANGE_HSV = ((0, 150, 120), (15, 255, 255))  # 2026-11-13 top frame: containers H 9-12, the yellow deck H 20-22
MAX_HEIGHT_MM, MAX_SIDE_MM, MAX_SCALE_MM, MAX_SPREAD_MM = 3.0, 2.5, 1.5, 3.5  # side: 1 px of edge bias reads ~1.8
MIN_AREA_SHARE = 0.85


def top_face(colour, depth_mm, factory: dict, plane: dict, roi: tuple, expected_mm: float, hsv=ORANGE_HSV) -> dict:
    """The top container's face: its corners in the reference plane's frame (mm), sides, centre and measured height."""
    import cv2

    K = np.asarray(factory["K"], float)
    n = np.asarray(plane["normal"], float)
    d = float(plane["height_mm"])
    h, w = colour.shape[:2]
    z = sm.depth_in_colour(depth_mm, factory, (w, h))
    v, u = np.mgrid[0:h, 0:w]
    pts = np.dstack([(u - K[0, 2]) * z / K[0, 0], (v - K[1, 2]) * z / K[1, 1], z])
    height = pts @ n + d  # mm toward the camera above the reference plane
    x0, y0, x1, y1 = roi
    colour_mask = cv2.inRange(cv2.cvtColor(colour, cv2.COLOR_BGR2HSV), np.array(hsv[0]), np.array(hsv[1]))
    band = np.nan_to_num(np.abs(height - expected_mm), nan=1e9) < 8.0  # the top face, not the side faces or deck
    band = cv2.dilate(band.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0  # depth is coarser than colour edges
    mask = np.zeros((h, w), np.uint8)
    mask[y0:y1, x0:x1] = ((colour_mask > 0) & band)[y0:y1, x0:x1] * 255
    on_face = _largest(cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)))
    if on_face is None:
        return {"ok": False, "reason": "no top face of that colour at that height in the box"}
    # a side face is the same colour but darker (cell_objects.object_mask, top_v_frac); judged within this face only,
    # so another bright object in the box does not trim it
    value = cv2.cvtColor(colour, cv2.COLOR_BGR2HSV)[..., 2]
    on_face = _largest(((on_face & (value >= 0.85 * np.percentile(value[on_face], 90))) * 255).astype(np.uint8))
    if on_face is None:
        return {"ok": False, "reason": "no top face of that colour at that height in the box"}
    measured = float(np.nanmedian(height[on_face]))
    contour, _ = cv2.findContours((on_face * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = max(contour, key=cv2.contourArea).reshape(-1, 2).astype(float)
    # colour rays of the outline to the plane `measured` mm above the reference (the camera model under test); the
    # rectangle is fitted there in mm, since in pixels perspective makes the face a trapezoid and inflates its long side
    rays = np.column_stack([(outline[:, 0] - K[0, 2]) / K[0, 0], (outline[:, 1] - K[1, 2]) / K[1, 1],
                            np.ones(len(outline))])
    hit = rays * ((measured - d) / (rays @ n))[:, None]
    e1 = np.cross(n, [0.0, 1.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    flat = np.column_stack([hit @ e1, hit @ e2]).astype(np.float32)
    (cx, cy), (a, b), yaw = cv2.minAreaRect(flat)
    return {"ok": True, "height_mm": round(measured, 1), "long_mm": round(float(max(a, b)), 2),
            "short_mm": round(float(min(a, b)), 2), "centre_mm": [round(float(cx), 2), round(float(cy), 2)],
            "yaw_deg": round(float(yaw), 1), "area_mm2": round(float(cv2.contourArea(flat)), 1),
            "pixels": int(on_face.sum())}


def _largest(mask):
    """The largest connected blob of a 0/255 mask as a bool image, or None."""
    import cv2

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    return None if count < 2 else labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def check(tiers: dict, factory: dict, roi: tuple, cad_mm: tuple, hsv=ORANGE_HSV) -> dict:
    """tiers: {k: (colour, depth_mm)} with k = 0 the empty slot. Gates as in the module note."""
    if 0 not in tiers or len(tiers) < 2:
        raise ValueError("need the empty slot (tier 0) and at least one stacked tier")
    plane = dp.surface(tiers[0][1], factory, roi)
    if not plane.get("ok"):
        return {"accepted": False, "reason": "empty slot floor not found: " + str(plane.get("reason")), "tiers": {}}
    long_cad, short_cad = max(cad_mm), min(cad_mm)
    rows, centres = {}, []
    for k in sorted(t for t in tiers if t):
        face = top_face(*tiers[k], factory, plane, roi, k * TIER_MM, hsv)
        if face["ok"]:
            long_err, short_err = face["long_mm"] - long_cad, face["short_mm"] - short_cad
            face.update({"long_error_mm": round(long_err, 2), "short_error_mm": round(short_err, 2),
                         "height_error_mm": round(face["height_mm"] - k * TIER_MM, 1)})
            face["ok"] = (abs(face["height_error_mm"]) <= MAX_HEIGHT_MM and abs(long_err) <= MAX_SIDE_MM
                          and abs(short_err) <= MAX_SIDE_MM)
            if face["area_mm2"] < MIN_AREA_SHARE * long_cad * short_cad:  # a wall or link hides part of it
                face.update({"ok": False, "reason": "top face partly hidden: its size says nothing"})
                rows[str(k)] = face
                continue
            centres.append(face["centre_mm"])
        rows[str(k)] = face
    faces = [r for r in rows.values() if "long_error_mm" in r]
    scale = (float(np.mean([r["long_error_mm"] - r["short_error_mm"] for r in faces])) if faces else math.nan)
    spread = (float(np.max(np.linalg.norm(np.asarray(centres) - np.mean(centres, axis=0), axis=1)))
              if len(centres) > 1 else 0.0)
    accepted = (all(r.get("ok") for r in rows.values()) and abs(scale) <= MAX_SCALE_MM and spread <= MAX_SPREAD_MM)
    return {"accepted": bool(accepted), "plane": {k: plane[k] for k in ("height_mm", "tilt_deg", "rms_mm", "share")},
            "scale_signal_mm": round(scale, 2) if math.isfinite(scale) else None, "centre_spread_mm": round(spread, 2),
            "gate": {"height_mm": MAX_HEIGHT_MM, "side_mm": MAX_SIDE_MM, "long_minus_short_mm": MAX_SCALE_MM,
                     "spread_mm": MAX_SPREAD_MM}, "tiers": rows}


def main(argv=None) -> int:
    import argparse

    import cv2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--factory", type=Path, required=True, help="cell_device_intrinsics read output (with depth)")
    ap.add_argument("--roi", required=True, help="x0,y0,x1,y1 around the slot in colour pixels")
    ap.add_argument("--cad", required=True, help="top face LxW mm, e.g. 90x30")
    ap.add_argument("--tier", action="append", required=True, help="K=DIR with top.jpg and depth.raw; 0 = empty slot")
    ap.add_argument("--hsv", help="H,S,V low and high, e.g. 0,150,120,15,255,255 (default: the orange containers)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    factory = json.loads(args.factory.read_text())
    hsv = ORANGE_HSV
    if args.hsv:
        v = [int(x) for x in args.hsv.split(",")]
        if len(v) != 6:
            raise SystemExit("--hsv needs six numbers")
        hsv = (tuple(v[:3]), tuple(v[3:]))
    tiers = {}
    for item in args.tier:
        k, folder = item.split("=", 1)
        colour = cv2.imread(str(Path(folder) / "top.jpg"))
        if colour is None:
            raise SystemExit(f"no top.jpg in {folder}")
        tiers[int(k)] = (colour, sm._depth(Path(folder) / "depth.raw", factory))
    result = check(tiers, factory, tuple(int(v) for v in args.roi.split(",")),
                   tuple(float(v) for v in args.cad.lower().split("x")), hsv)
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
