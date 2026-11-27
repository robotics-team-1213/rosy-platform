#!/usr/bin/env python3
"""Slot prior for a plate with fixed pockets (the OMX temp plate, CAD temp_slot_plate.scad v12: three fanned 30.8 x 96 mm
pockets, 32.4 mm per tier), applied after the top camera's free blob detection (`cell_auto_pick_plan.observe`).

Why (2026-11-27 panel, D:/DevTemp/.../tempplate-panel): the free detection refused every stack on both temp plates. The
object colour range also took the yellow table, so pieces beside the plate became objects (one read as container-2);
3-tier stacks were measured at the 1-tier height; and the 6-20 mm between fanned pockets never passes the 14 mm neighbour
clearance. The prior only explains what was measured, it never replaces a measurement:

- `sites.<site>.slots` ([{name, xy (m), yaw_deg (pocket long axis), pocket_mm [w, l]}]) and `slots_fit`
  ({residual_mm, residual_deg} of the plate's reference marks F1-F4) are measured each time the plate is set down;
  no fit, or a residual over 3 mm / 1 deg, turns the prior off and the site behaves as without slots.
- Each slot's tier count comes from depth (`n = round(top / tier_step)`, within cell_depth_slots.TOL_MM), never from
  the prior. Unknown tiers: the slot's own blobs take the free path; as a neighbour it counts as 3 tiers.
- A slot's blobs are measured again inside the slot's own image outline at the top tier's height. Exactly one
  catalogue match within 8 mm / 5 deg of the slot and 4 mm across it is snapped onto the pocket axis; anything else
  in the slot takes the free path (and is refused there when it fails).
- Blobs outside the plate (outside every slot outline) are never targets; foreground on the plate but in no slot
  turns the prior off. Depth and side readings more than half a tier apart hold the slot.
- Only a snapped object, whose neighbours are not taller, uses the site's `finger_params`; everything else keeps the
  cell defaults. A slot still unmeasured as a site (cell_site_target) refuses SITE_NOT_MEASURED.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

import cell_depth_slots
import cell_site_target

FIT_MM, FIT_DEG = 3.0, 1.0  # plate reference-mark residual over which the prior is off
SNAP_MM, SNAP_DEG, ACROSS_MM = 8.0, 5.0, 4.0  # object to slot: centre distance, axis angle, offset across the axis
TIER_TOL_MM = cell_depth_slots.TOL_MM  # tier identification band (7 mm)
MAX_TIERS = 3
SIDE_HOLD_MM = 16.0  # half a tier: depth and side cameras further apart hold the slot
OUTLINE_PAD_MM = 3.0  # a pocket outline is padded by this much for the side faces' edge pixels


def active(site_cfg: dict) -> tuple[list | None, str]:
    """(slots, why): the site's slots when its plate fit is good enough, else (None, the reason it is off)."""
    slots = site_cfg.get("slots")
    if not slots:
        return None, "no slots"
    if site_cfg.get("tier_of"):  # a -lN copy (cell_place_fit.with_tiers): depth finds the tiers, not the site name
        return None, "tier copy of a slotted site"
    fit = site_cfg.get("slots_fit") or {}
    mm, deg = fit.get("residual_mm"), fit.get("residual_deg")
    if not isinstance(mm, (int, float)) or not isinstance(deg, (int, float)):
        return None, "slots without a measured plate fit (slots_fit residual_mm / residual_deg)"
    if mm > FIT_MM or deg > FIT_DEG:
        return None, f"plate fit residual {mm} mm / {deg} deg over {FIT_MM} mm / {FIT_DEG} deg"
    return slots, "on"


def tier_of(top_mm: float | None, step_mm: float) -> int | None:
    """Tier count from a stack top measured above the plate surface, None outside +-TIER_TOL_MM of a whole tier."""
    if not isinstance(top_mm, (int, float)) or not math.isfinite(top_mm) or step_mm <= 0:
        return None
    n = round(top_mm / step_mm)
    return n if 0 <= n <= MAX_TIERS and abs(top_mm - n * step_mm) <= TIER_TOL_MM else None


def _axes(slot: dict):
    t = math.radians(slot["yaw_deg"])
    return np.array([math.cos(t), math.sin(t)]), np.array([-math.sin(t), math.cos(t)])


def outline_px(slot: dict, z_low: float, z_high: float, pixel_fn) -> np.ndarray | None:
    """The slot's image outline: its padded pocket seen at the floor and at the stack top (pixel_fn(xy_m, z_m))."""
    u, v = _axes(slot)
    w, length = (float(d) / 2000 + OUTLINE_PAD_MM / 1000 for d in slot["pocket_mm"])
    c = np.asarray(slot["xy"], float)
    pts = [pixel_fn(tuple(c + a * length * u + b * w * v), z) for z in (z_low, z_high) for a in (-1, 1) for b in (-1, 1)]
    if any(p is None for p in pts):
        return None
    return cv2.convexHull(np.asarray(pts, np.float32))


def _inside(poly, px) -> bool:
    return poly is not None and cv2.pointPolygonTest(poly, (float(px[0]), float(px[1])), False) >= 0


def _blob_px(o: dict):
    hull = o.get("hull_px")
    return np.asarray(hull, float).mean(axis=0) if hull else None


def snap(o: dict, slot: dict, pocket_len_mm: float, length_mm: float) -> dict | None:
    """The object put on the pocket axis (the walls allow 0.4 mm across), or None when it is not explained by the slot."""
    u, v = _axes(slot)
    d = np.asarray(o["centre_mm"], float) - 1000 * np.asarray(slot["xy"], float)
    turn = (o["long_axis_deg"] - slot["yaw_deg"] + 90) % 180 - 90
    if np.linalg.norm(d) > SNAP_MM or abs(turn) > SNAP_DEG or abs(d @ v) > ACROSS_MM:
        return None
    room = max(0.0, (pocket_len_mm - length_mm) / 2)
    along = float(np.clip(d @ u, -room, room))
    centre = 1000 * np.asarray(slot["xy"], float) + along * u
    axis = (slot["yaw_deg"] + 90) % 180 - 90
    return {**o, "centre_mm": [round(float(centre[0]), 1), round(float(centre[1]), 1)], "long_axis_deg": round(axis, 1),
            "slot_seen": {"centre_mm": o["centre_mm"], "long_axis_deg": o["long_axis_deg"],
                          "across_mm": round(float(d @ v), 1), "turn_deg": round(float(turn), 1)}}


def read_tops(heights, to_depth, plate_mm: float, slots: list, surface_z: float, step_m: float, pixel_fn) -> dict:
    """{slot: stack top in mm above the plate surface} from a depth height map (mm above the table): each tier count is
    tried where its top would show, and kept only when depth reads that same count there. `plate_mm` is the arm's
    own plate above the table (arm z 0, cell_depth.plate_top)."""
    import cell_depth

    tops = {}
    for s in slots:
        for n in range(MAX_TIERS + 1):
            px = pixel_fn(tuple(s["xy"]), surface_z + n * step_m)
            if px is None:
                break
            top = cell_depth.height_at(heights, to_depth, px) - plate_mm - 1000 * surface_z
            if tier_of(top, 1000 * step_m) == n:
                tops[s["name"]] = round(top, 1)
                break
    return tops


def depth_tops(config: dict, slots: list, surface_z: float, step_m: float, pixel_fn, colour) -> dict:
    """read_tops on a fresh top depth frame; {} (every tier unknown) when depth, its alignment or the arm plate is missing."""
    import time

    import cell_depth
    import cell_zone_verification as zones

    try:
        depth, _, error = zones._depth_after(config, time.time())
        if error or depth is None:
            return {}
        raw = depth.astype(np.uint16)
        heights = cell_depth.height_map(raw, cell_depth.table_plane(raw))
        to_depth, _ = cell_depth_slots.frame_alignment(depth, colour)
        plate = cell_depth.plate_top(heights, to_depth, pixel_fn((0.0, 0.0), 0.0))
        return {} if plate is None else read_tops(heights, to_depth, plate, slots, surface_z, step_m, pixel_fn)
    except Exception:  # noqa: BLE001 - any depth failure leaves every tier unknown (the free path), never a crash
        return {}


def pixel_at(config: dict, calibration: dict, site: str, point, z: float):
    """cell_observe.predicted_pixel for a point at height z (m) instead of the site's own z."""
    from cell_observe import predicted_pixel

    return predicted_pixel(dict(config, sites={**config["sites"], site: {**config["sites"][site], "z": z}}), calibration, site, point)


def across(o: dict, closing_deg: float) -> bool:
    """Do the jaws close across the object's slot (within 3 deg of square to the pocket axis), never along it?"""
    return abs((closing_deg - o["slot_yaw_deg"]) % 180 - 90) <= 3.0


def on_site(cell, config: dict, calibration: dict, site: str, roi, catalog: list, img, record: dict, objects: list,
            tops_mm: dict | None = None, side_mm: dict | None = None) -> list:
    """observe()'s free detection with the slot prior applied, or unchanged when the site has no active slots.
    `tops_mm` (stack tops above the surface per slot) is read from top depth when not given and a cell is live."""
    import cell_objects
    from cell_pick_geom import surface_z

    s = config["sites"][site]
    slots, _ = active(s)
    if not slots:
        return objects
    sz, step = surface_z(config, site), float(s.get("tier_step_m") or 0.0324)
    at = lambda p, z: pixel_at(config, calibration, site, p, z)  # noqa: E731
    if tops_mm is None and cell is not None:
        tops_mm = depth_tops(config, slots, sz, step, at, img)
    redetect = lambda outline, extra_mm: cell_objects.detect(  # noqa: E731
        img, s.get("detect_roi", roi), record, config["cameras"]["top"],
        [dict(e, top_height_mm=e["top_height_mm"] + extra_mm) for e in catalog], sz, config.get("params"),
        outline.reshape(-1, 2).tolist(), s.get("surface_lab"), (config.get("objects") or {}).get("hsv"))
    try:
        out, _ = apply(objects, slots, tops_mm or {}, sites=config["sites"], surface_z=sz, step_m=step, pixel_fn=at,
                       redetect=redetect, entries={e["id"]: e for e in catalog}, side_mm=side_mm)
    except Exception:  # noqa: BLE001 - the prior failing leaves the free detection to judge, as without slots
        return objects
    return out


def apply(base: list, slots: list, tops_mm: dict, *, sites: dict, surface_z: float, step_m: float, pixel_fn, redetect,
          entries: dict, side_mm: dict | None = None) -> tuple[list, dict]:
    """(objects, note). `base` is the free detection; `redetect(outline, height_mm_extra)` measures blobs inside one slot
    outline with every catalogue top raised by that much. Objects are returned with their arm-mm centres (raw_m is set
    by the caller). A blob outside every slot carries `refuse`; a snapped one carries slot, slot_yaw_deg, layers_below,
    dz_m and slot_params (the site's finger_params may apply)."""
    step_mm = step_m * 1000
    tiers = {s["name"]: tier_of(tops_mm.get(s["name"]), step_mm) for s in slots}
    outlines = {s["name"]: outline_px(s, surface_z, surface_z + (tiers[s["name"]] or MAX_TIERS) * step_m, pixel_fn) for s in slots}
    if any(p is None for p in outlines.values()):
        return base, {"prior": "off", "why": "a slot outline is past the camera model"}
    plate = cv2.convexHull(np.concatenate(list(outlines.values())))
    owner, out = {}, []
    for o in base:
        px = _blob_px(o)
        name = next((n for n, poly in outlines.items() if px is not None and _inside(poly, px)), None)
        if name is not None:
            owner.setdefault(name, []).append(o)
        elif px is not None and _inside(plate, px):
            return base, {"prior": "off", "why": f"foreground on the plate outside every slot at {o['centre_mm']} mm"}
        else:
            out.append({**o, "refuse": "outside the plate's slots: not a target (slot prior)"})
    note = {"prior": "on", "tiers": tiers, "outside": len(out)}
    for s in slots:
        name, n = s["name"], tiers[s["name"]]
        mine = owner.get(name, [])
        if refuse := cell_site_target.unmeasured_refusal(sites, name):
            out += [{**o, "refuse": f"{refuse}: slot {name}"} for o in mine]
            continue
        held = side_mm and isinstance((side_mm or {}).get(name), (int, float)) and isinstance(tops_mm.get(name), (int, float)) \
            and abs(side_mm[name] - tops_mm[name]) >= SIDE_HOLD_MM
        if held:
            out += [{**o, "refuse": f"slot {name} held: depth {tops_mm[name]} mm and side {side_mm[name]} mm differ by half a tier or more"} for o in mine]
            continue
        if not n:  # unknown tiers, or depth reads the slot empty while a blob is there: the free path decides
            out += mine
            continue
        found = redetect(outlines[name], (n - 1) * step_mm)
        hits = [o for o in found if o.get("matched")]
        snapped = snap(hits[0], s, float(s["pocket_mm"][1]), float(entries[hits[0]["object"]]["length_mm"])) \
            if len(hits) == 1 and len(found) == 1 else None
        if snapped is None:
            out += mine
            continue
        neighbours = [tiers[t["name"]] if tiers[t["name"]] is not None else MAX_TIERS for t in slots if t["name"] != name]
        out.append({**snapped, "slot": name, "slot_yaw_deg": float(s["yaw_deg"]), "layers_below": n - 1,
                    "dz_m": round((n - 1) * step_m, 4), "slot_params": all(t <= n for t in neighbours)})
    return out, note
