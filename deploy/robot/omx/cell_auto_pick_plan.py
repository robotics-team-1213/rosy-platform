#!/usr/bin/env python3
"""Top-Camera Observation, Candidate Selection & Place Verification for Autonomous Pick (`cell_auto_pick_plan.py`).

Single Responsibility:
  - Observe catalogue objects on the top camera frame (`observe`).
  - Plan top-down pick/place libraries (`plan_pick`) and rank/filter usable candidates (`choose`).
  - Verify placed object position on the destination site (`verify_placed`).
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_auto_safety import finger_room, object_sized, square_entry  # noqa: E402
import cell_decisions as cd  # noqa: E402
import cell_jaw_axis  # noqa: E402
import cell_objects  # noqa: E402
from cell_observe import keep, predicted_pixel, wrap90  # noqa: E402
import cell_params as prm  # noqa: E402
from cell_pick_geom import across, grasp_depth, grasp_yaw, jaw_open_for, reachable_ends, surface_z  # noqa: E402
import cell_pipeline as cp  # noqa: E402
import cell_pivot  # noqa: E402
import cell_place_fit  # noqa: E402

CLOSING = "gripper.closing_axis_offset_deg"


def _parent_attr(name: str, default):
    mod = sys.modules.get("cell_auto_pick")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default


def observe(cell, config: dict, calibration: dict, site: str, roi, catalog: list):
    import cv2

    config, calibration = cell_place_fit.with_tiers(config, calibration, catalog)
    record = cell_pivot.map_record(calibration, site)
    if record is None:
        return None, None, [], f"no map for {site}"
    img = cell.frame("top")
    cd.see(keep(f"auto-{site}-top", img))
    poly = config["sites"][site].get("surface_px")
    lab = config["sites"][site].get("surface_lab")
    obj = config.get("objects") or {}
    objects = cell_objects.detect(
        img,
        config["sites"][site].get("detect_roi", roi),
        record,
        config["cameras"]["top"],
        catalog,
        surface_z(config, site),
        config.get("params"),
        poly,
        lab,
        obj.get("hsv"),
    )
    for o in objects:
        o["raw_m"] = [
            c / 1000 + d for c, d in zip(o["centre_mm"], config["sites"][site].get("grip_offset_m", (0.0, 0.0)))
        ]
    near = cell_objects.foreground(img, roi, params=config.get("params"), surface_lab=lab)
    for p in config["sites"][site].get("markings_px", []):
        cv2.fillPoly(near, [np.asarray(p, np.int32) - [roi[0], roi[1]]], 0)
    mask = object_sized(near, config.get("params")) | cell_objects.colour_mask(img, roi, obj.get("hsv"))
    for p in config["sites"][site].get("markings_px", []):
        cv2.fillPoly(mask, [np.asarray(p, np.int32) - [roi[0], roi[1]]], 0)
    return img, mask, objects, None


def past_pan_limit(config: dict, point_m) -> float | None:
    """The pan (deg) to a point outside the plan's joint1 limit, else None. 2026-11-13 arm_s: a box at -161 deg (limit 149) was
    refused as packed and the push meant for packed boxes could never reach it either.
    shortcut: the pan alone, from the base axis; radius and height are left to the planner's IK, which runs later."""
    limits = (config.get("plan") or {}).get("limits", {}).get("joints_rad", {}).get("joint1")
    if not limits:
        return None
    pan = math.atan2(point_m[1], point_m[0])
    return None if limits[0] <= pan <= limits[1] else round(math.degrees(pan), 1)


def plan_pick(
    config: dict,
    site: str,
    dest_site: str,
    place_xy,
    o: dict,
    entry: dict,
    offset,
    bias_mm,
    work: Path,
    yaw: float | None = None,
    place_yaw: float | None = None,
):
    """Library for one candidate: grasp 15 mm below the top, approach 40 mm above it (else 20)."""
    config = cell_place_fit.with_tiers(config, catalog=[entry])[0]
    cell_pivot.validate_bias({"point_m": o["raw_m"], "bias_mm": bias_mm}, config.get("params"))
    height = entry["top_height_mm"] / 1000 - grasp_depth(config, site)
    x, y = (o["raw_m"][0] - bias_mm[0] / 1000, o["raw_m"][1] - bias_mm[1] / 1000)
    dz = float(o.get("dz_m", 0.0)) + float(config["sites"][site].get("z_offset_m", 0.0)) - (bias_mm[2] / 1000 if len(bias_mm) >= 3 else 0.0)
    yaw0, error = (grasp_yaw(config, site, o, entry, offset) if yaw is None else yaw), "no plan"
    cp_mod = _parent_attr("cp", cp)
    for approach in (config["plan"]["approach_m"], prm.get(config.get("params"), "auto.approach_near_m", 0.020)):
        for yaw_try in (yaw0, yaw0 + 180.0, yaw0 - 180.0):
            pick = {
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(surface_z(config, site) + height + dz, 4),
                "yaw_deg": yaw_try,
            }
            s = config["sites"][dest_site]
            place = {
                "x": place_xy[0],
                "y": place_xy[1],
                "z": round(surface_z(config, dest_site) + height + s.get("place_dz", 0.0), 4),
                "yaw_deg": s["yaw_deg"] if place_yaw is None else place_yaw,
            }
            try:
                jaws = jaw_open_for(across(entry), config.get("params"), o.get("jaw_margin_mm"))
                lib = cp_mod.write_library(
                    dict(config, plan=dict(config["plan"], approach_m=approach, grip_open=jaws)),
                    pick,
                    place,
                    work
                    / f"auto-{site}-{offset}-{round(1000 * o['raw_m'][0])}_{round(1000 * o['raw_m'][1])}.json",
                )
                return lib, pick, place, approach, yaw_try, {"approach_m": approach, "grip_open": jaws}
            except SystemExit as exc:
                error = str(exc)[:160]
    return error


def choose(
    cell,
    config,
    calibration,
    site,
    dest_site,
    place_xy,
    roi,
    objects,
    mask,
    catalog,
    bias_data,
    choices,
    work,
    failed_yaws=(),
    dest_view=None,
):
    """Ordered usable targets: [{object, plan...}], and why the others were refused."""
    config, calibration = cell_place_fit.with_tiers(config, calibration, catalog)
    entries, usable, refused = {e["id"]: e for e in catalog}, [], []
    pixel_fn = lambda p: predicted_pixel(config, calibration, site, p)  # noqa: E731
    p = config.get("params")
    plan_fn = _parent_attr("plan_pick", plan_pick)
    for o in sorted(objects, key=lambda o: ("split_from" in o, math.dist(o["raw_m"], config["sites"][site]["start"]))):
        why = None
        px = pixel_fn(o["raw_m"])
        if o.get("tangled"):
            why = "tangled blob"
        elif not o["matched"]:
            why = "no catalogue match"
        elif w := cell_objects.want_reason(config.get("want"), o):
            why = w
        elif px is None or not (roi[0] + 12 <= px[0] <= roi[2] - 12 and roi[1] + 12 <= px[1] <= roi[3] - 12):
            why = "not inside the camera view"
        elif (pan := past_pan_limit(config, o["raw_m"])) is not None:
            why = f"out of reach: pan {pan} deg past the joint1 limit"
        elif not square_entry(entries, o):
            entry = entries[o["object"]]
            ends = o["long_axis_deg"] if across(entry) == entry["length_mm"] else None
            room = finger_room(mask, roi, pixel_fn, o, ends, p)
            if room["margin_mm"] is None:
                o, room = next(
                    (
                        (e, r)
                        for e in reachable_ends(o, entries[o["object"]], p)
                        if (r := finger_room(mask, roi, pixel_fn, e, None, p))["margin_mm"] is not None
                    ),
                    (o, room),
                )
            if room["margin_mm"] is None:
                why = (("edge of view: a side is past the camera's view, " if room.get("unseen") else "no finger room: ")
                       + f"{room['free_mm'][0]} / {room['free_mm'][1]} mm free beside it")
        if why:
            refused.append(
                {"centre_mm": o["centre_mm"], "object": o.get("object"), "colour": o.get("colour"), "why": why}
            )
            continue
        entry = entries[o["object"]]
        square = abs(entry["length_mm"] - entry["width_mm"]) < 1e-6
        if not square:
            choices.offer(CLOSING, prm.get(p, "auto.closing_theory_deg"), "theory: closes along tool y = yaw + 90")
            choices.offer(CLOSING, prm.get(p, "auto.closing_alt_deg"), "alternative: closes along tool x")
        cell_jaw_axis.offer_measured(config, choices, CLOSING)
        offset, why = (None, None) if square else cell_jaw_axis.offset_for(config, entry, choices.best(CLOSING))
        if why:
            refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": why})
            continue
        yaw = None
        if square:
            closing = prm.get(p, "auto.closing_theory_deg")
            base_yaw = grasp_yaw(config, site, o, entry, None)
            fresh = [
                y for y in (base_yaw, base_yaw + 90.0) if all(abs(wrap90(y - f)) > 5.0 for f in failed_yaws)
            ] or [base_yaw, base_yaw + 90.0]
            rooms = [(y, finger_room(mask, roi, pixel_fn, o, y + closing, p)) for y in fresh]
            yaw, room = next(((y, r) for y, r in rooms if r["margin_mm"] is not None), (None, rooms[0][1]))
            if yaw is None:
                refused.append(
                    {"centre_mm": o["centre_mm"], "object": o["object"], "why": "no finger gap on either closing axis"}
                )
                continue
        region = cell_pivot.bias_at(bias_data, site, o["raw_m"], params=p)
        bias = region["bias_mm"] if region else [0.0, 0.0]
        held_axis = o["long_axis_deg"] - (yaw if yaw is not None else grasp_yaw(config, site, o, entry, offset))
        places, why = cell_place_fit.options(
            config,
            dest_site,
            place_xy,
            held_axis,
            entry,
            lambda q: predicted_pixel(config, calibration, dest_site, q),
            *(dest_view or (None, None)),
        )
        if why:
            refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": f"place: {why}"})
            continue
        o, planned = (
            dict(o, jaw_margin_mm=room["margin_mm"], free_mm=room["free_mm"], mark_half_mm=room["mark_half_mm"]),
            "no place",
        )
        for xy, place_yaw in places:
            planned = plan_fn(config, site, dest_site, xy, o, entry, offset, bias, work, yaw, place_yaw)
            for end in (reachable_ends(o, entry, p) if isinstance(planned, str) and "UNREACHABLE" in planned else []):
                planned = plan_fn(config, site, dest_site, xy, end, entry, offset, bias, work, yaw, place_yaw)
                if not isinstance(planned, str):
                    o = end
                    break
            if not isinstance(planned, str):
                break
        if isinstance(planned, str):
            refused.append({"centre_mm": o["centre_mm"], "object": o["object"], "why": f"planner: {planned}"})
            continue
        usable.append(
            {
                "object": o,
                "entry": entry,
                "offset": offset,
                "bias_region": region,
                "bias_mm": bias,
                "library": planned[0],
                "pick": planned[1],
                "place": planned[2],
                "approach_m": planned[3],
                "plan": planned[5],
            }
        )
    return usable, refused


def verify_placed(cell, config, calibration, dest_site, place_xy, roi, catalog, bias_data, object_id, held):
    record = cell_pivot.map_record(calibration, dest_site)
    if roi is None or record is None:
        return {"found": held, "inside": held, "basis": "arm placement"}
    obs_fn = _parent_attr("observe", observe)
    _, _, objects, _ = obs_fn(cell, config, calibration, dest_site, roi, catalog)
    region = cell_pivot.bias_at(bias_data, dest_site, place_xy, params=config.get("params"))
    bx, by = region["bias_mm"] if region else (0.0, 0.0)
    near = [
        (1000 * math.dist((o["raw_m"][0] - bx / 1000, o["raw_m"][1] - by / 1000), place_xy), o)
        for o in objects
        if o.get("object") == object_id
    ]
    if not near:
        return {"found": False, "inside": False, "basis": "map"}
    off, o = min(near, key=lambda pair: pair[0])
    seen = [round(1000 * (o["raw_m"][0] - place_xy[0]), 1), round(1000 * (o["raw_m"][1] - place_xy[1]), 1)]
    return {
        "found": True,
        "inside": off <= config.get("verify_tol_mm", 10.0),
        "off_mm": round(off, 1),
        "basis": "map",
        "seen_bias_mm": seen,
        "used_bias_mm": [bx, by],
    }
