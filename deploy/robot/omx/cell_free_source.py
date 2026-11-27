#!/usr/bin/env python3
"""Free-position pick source for auto_pick: `--from free:<anchor> [--at-px U V]`.

An object that lies outside every site surface (a box on the belt housing) is found in the ROI without the surface clip,
its top height is measured with the D435 depth against the anchor site's own surface in the same frames, and the
anchor site's map (with parallax at that height) turns the top-face pixels into arm millimetres. The result is a copy
of the anchor site whose surface_z is the measured base height, so the existing observe / choose / plan_pick / Gate path
runs unchanged. Every number is reported; anything missing or inconsistent refuses (never a guessed z).
"""
from __future__ import annotations

import copy
import json
import math
import tempfile
from pathlib import Path

import cv2
import numpy as np

import cell_calibration as cal
import cell_depth_lock
import cell_depth_pose
import cell_depth_slots
import cell_objects
import cell_pivot
from cell_job_validators import _is_amr_bed_site
from cell_observe import record_key
from cell_pick_geom import grasp_depth, surface_z

PREFIX = "free:"
REF_TOL_MM = 6.0       # the anchor's depth-measured camera height vs its configured one: the cell_cal_eval depth_diff limit
MIN_FRAMES = 5         # depth frames taken and frames with an anchor height needed: one frame has no spread
FRAME_RANGE_MM = 8.0   # max - min of the per-frame top height (2 sigma 3.6 mm live is a range of about 5 mm over 7 frames)
FRAME_SPREAD_MM = 4.0  # top height above the anchor, two standard deviations over the depth frames (live 1.4-3.6 mm, 2026-11-27)
FACE_SPREAD_MM = 10.0  # p90 - p10 over the eroded top face (live 7-8 mm on the red box): a box tilted or half off its support is refused
MIN_FACE_PX, MIN_SITE_PX, MODE_SHARE = 30, 200, 0.25
Z_ERR_MM = 2.0         # height error used for the xy figure when the frames agree better than this


def anchor_of(source):
    """The anchor site of a free source name, or None for an ordinary site."""
    return source[len(PREFIX):] if isinstance(source, str) and source.startswith(PREFIX) else None


def source_error(config, source, dest):
    """Refusal text before any camera step, else None: the source must exist, a free source needs a destination site."""
    anchor = anchor_of(source)
    if (anchor or source) not in config["sites"]:
        return f"refused: source {source!r} is not a site in the config"
    if anchor and dest not in config["sites"]:
        return f"refused: free source {source!r} needs a destination site (an x,y destination would place on the invented site)"
    return None


def inside(o, poly):
    """The object's outline centre lies in the polygon (pixels)."""
    c = np.asarray(o.get("hull_px") or [[-1e9, -1e9]], float).reshape(-1, 2).mean(axis=0)
    return cv2.pointPolygonTest(np.asarray(poly, np.float32).reshape(-1, 1, 2), (float(c[0]), float(c[1])), False) >= 0


def chosen_error(config, name, target):
    """The object the per-attempt observe / choose picked must be the one that was measured, else refuse with the numbers."""
    site, o = config["sites"][name], target["object"]
    if site.get("free_object") == o.get("object") and inside(o, site["blob_px"]):
        return None
    c = np.asarray(o.get("hull_px") or [[0, 0]], float).reshape(-1, 2).mean(axis=0)
    return (f"refused: free source: the chosen object {o.get('object')} (outline centre {[round(float(v), 1) for v in c]} px) is not the "
            f"measured blob {site.get('free_object')} (centre {site.get('blob_centre_px')} px)")


def _depth_frames(config: dict, n: int):
    top = (config.get("cameras") or {}).get("top") or {}
    device = top.get("depth_device") or "/dev/v4l/by-id/rosy-realsense-d435-depth"
    try:
        with cell_depth_lock.hold_depth_lock(timeout_s=8.0):
            with tempfile.TemporaryDirectory(prefix="free-depth-") as scratch:
                frames, receipt = cell_depth_slots.capture_depth_frames(device, n, Path(scratch) / "depth.raw")
    except TimeoutError:
        return None, "depth-d435.lock busy"
    except (OSError, ValueError) as exc:
        return None, f"depth capture failed: {exc}"
    return (np.array(frames), receipt) if frames is not None else (None, str(receipt))


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sample(heights, to_depth, pts):
    """Heights (mm) under colour pixels pts (N, 2), finite ones only."""
    d = np.rint(np.c_[pts, np.ones(len(pts))] @ np.asarray(to_depth, float).T)[:, :2].astype(int)
    ok = (d[:, 0] >= 0) & (d[:, 0] < heights.shape[1]) & (d[:, 1] >= 0) & (d[:, 1] < heights.shape[0])
    v = heights[d[ok, 1], d[ok, 0]]
    return v[np.isfinite(v)]


def _mode(v):
    """The most common height (1 mm bins, 5 mm window): the surface under whatever stands on it, and its share."""
    if len(v) < MIN_SITE_PX:
        return None, 0.0
    lo = math.floor(float(v.min()))
    hist = np.bincount(np.floor(v - lo).astype(int))
    win = np.convolve(hist, np.ones(5), mode="same")
    h = lo + float(np.argmax(win)) + 0.5
    return float(np.median(v[np.abs(v - h) <= 2.5])), float(win.max() / len(v))


def _polygon_pts(poly, shape, step=3):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [np.asarray(poly, np.int32)], 255)
    m = cv2.erode(m, np.ones((5, 5), np.uint8))
    ys, xs = np.nonzero(m)
    return np.c_[xs, ys][::step].astype(float)


def _blob(img, roi, config, at_px):
    """The foreground component of the ROI (not clipped to any surface) at/nearest at_px, or the largest."""
    x0, y0, x1, y1 = roi
    hsv = (config.get("objects") or {}).get("hsv")
    p = config.get("params")
    seen = (cell_objects.object_mask(img, roi, hsv, None, p) if hsv is not None
            else cell_objects.foreground(img, roi, params=p))
    n, labels, stats, cen = cv2.connectedComponentsWithStats(seen)
    ok = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= cell_objects.MIN_PX]
    if not ok:
        return None, f"no foreground object in the ROI {list(roi)}"
    if at_px is None:
        if len(ok) > 1:
            return None, f"{len(ok)} objects in the ROI {list(roi)} and no --at-px: say which one"
        i = ok[0]
    else:
        u, v = at_px[0] - x0, at_px[1] - y0
        hit = int(labels[int(v), int(u)]) if 0 <= v < labels.shape[0] and 0 <= u < labels.shape[1] else 0
        i = hit if hit in ok else min(ok, key=lambda k: math.hypot(cen[k][0] - u, cen[k][1] - v))
        if hit != i and math.hypot(cen[i][0] - u, cen[i][1] - v) > 25:  # also for a pixel outside the ROI
            return None, f"no object within 25 px of {list(at_px)}"
    blob = (labels == i).astype(np.uint8)
    if blob[0].any() or blob[-1].any() or blob[:, 0].any() or blob[:, -1].any():
        return None, f"the object touches the ROI border {list(roi)}: it may be cut off, widen the ROI"
    return {"mask": blob, "n_blobs": len(ok)}, None


def _two_sigma(v):
    """Twice the standard deviation of the per-frame values: the frame-to-frame noise of the height, outliers included."""
    return 2.0 * float(np.std(v))


def _frame_heights(frame, colour, cam):
    flags, report = [], {}
    heights, to_depth = cell_depth_pose.cal_eval_depth_setup(frame, colour, cam, report, flags, None, _load, lambda: None)
    return heights, to_depth, flags, report.get("cam_to_table_mm")


def _tight_roi(roi, mask, margin, shape):
    ys, xs = np.nonzero(mask)
    x0, y0 = roi[0], roi[1]
    return [max(roi[0], int(xs.min()) + x0 - margin), max(roi[1], int(ys.min()) + y0 - margin),
            min(roi[2], int(xs.max()) + x0 + margin + 1, shape[1]), min(roi[3], int(ys.max()) + y0 + margin + 1, shape[0])]


def measure(config, calibration, anchor, roi, at_px, img, frames, refs=None):
    """Top height of the blob above the anchor's surface from depth frames -> (numbers, error). Pure given its inputs."""
    cam = config["cameras"]["top"]
    if len(frames) < MIN_FRAMES:
        return {}, f"{len(frames)} depth frames, at least {MIN_FRAMES} needed"
    blob, err = _blob(img, roi, config, at_px)
    if err:
        return {}, err
    inner = cv2.erode(blob["mask"], np.ones((9, 9), np.uint8))  # 4 px in: the colour-depth edge error is 5-6 px
    ys, xs = np.nonzero(inner)
    if len(xs) < MIN_FACE_PX:
        return {}, f"top face too small to measure ({len(xs)} px inside the blob)"
    pts = np.c_[xs + roi[0], ys + roi[1]].astype(float)
    sites = config["sites"]
    names = {anchor, *(refs if refs is not None else (k for k, s in sites.items() if s.get("surface_px") and "surface_z" in s
                                                      and not s.get("tier_of") and not s.get("layer") and "-l" not in k
                                                      and not s.get("track") and not _is_amr_bed_site(k)))}
    per, face = {k: [] for k in names}, []
    top_h = []
    for frame in frames:
        heights, to_depth, flags, cam_mm = _frame_heights(frame, img, cam)
        if heights is None or "missing_depth" in flags or cam_mm is None:
            return {}, "depth unavailable (no usable height map from the D435 frame)"
        t = _sample(heights, to_depth, pts)
        if len(t) < MIN_FACE_PX:
            return {}, f"depth has no return on the top face ({len(t)} of {len(pts)} px)"
        top_h.append(float(np.median(t)))
        face.append(float(np.percentile(t, 90) - np.percentile(t, 10)))
        for k in names:
            h, share = _mode(_sample(heights, to_depth, _polygon_pts(sites[k]["surface_px"], img.shape)))
            per[k].append((h, share, cam_mm))
    ref = {}
    for k, rows in per.items():
        good = [(h, c) for h, s, c in rows if h is not None and s >= MODE_SHARE]
        if len(good) * 2 > len(rows):
            ref[k] = (float(np.median([h for h, _ in good])), float(np.median([c for _, c in good])))
    if anchor not in ref:
        return {}, f"anchor {anchor}: no stable surface height in its polygon"
    dz = [t - per[anchor][i][0] for i, t in enumerate(top_h) if per[anchor][i][0] is not None]
    if len(dz) < MIN_FRAMES:
        return {}, f"only {len(dz)} of {len(frames)} depth frames have an anchor height, at least {MIN_FRAMES} needed"
    c_px = [float(xs.mean() + roi[0]), float(ys.mean() + roi[1])]
    near = min(ref, key=lambda k: (max(0.0, -cv2.pointPolygonTest(np.asarray(sites[k]["surface_px"], np.float32).reshape(-1, 1, 2), tuple(c_px), True)), k != anchor))
    # the camera's height over each site's surface by depth, against the configured camera height and the site's surface_z
    diff = {k: round(c - h - (float(cam["height_m"]) - surface_z(config, k)) * 1000.0, 1) for k, (h, c) in ref.items()}
    return {
        "frames": len(frames), "top_above_anchor_mm": round(float(np.median(dz)), 1),
        "frame_spread_mm": round(_two_sigma(dz), 1), "frame_range_mm": round(max(dz) - min(dz), 1), "top_per_frame_mm": [round(v, 1) for v in dz], "face_spread_mm": round(float(np.median(face)), 1),
        "anchor_surface_z_m": surface_z(config, anchor), "anchor_surface_rel_mm": round(ref[anchor][0], 1),
        "camera_height_diff_mm": diff, "anchor_ref_diff_mm": diff[anchor], "n_blobs_in_roi": blob["n_blobs"], "blob_centre_px": [round(v, 1) for v in c_px],
        "nearest_site": near, "nearest_ref_diff_mm": diff[near],
        "mask": blob["mask"],
    }, None


def _verdict(m: dict):
    if m["frame_spread_mm"] > FRAME_SPREAD_MM:
        return f"depth frames disagree: top height spread {m['frame_spread_mm']} mm > {FRAME_SPREAD_MM} mm"
    if m["frame_range_mm"] > FRAME_RANGE_MM:
        return f"depth frames disagree: top height range {m['frame_range_mm']} mm > {FRAME_RANGE_MM} mm"
    if m["face_spread_mm"] > FACE_SPREAD_MM:
        return f"top face not flat: {m['face_spread_mm']} mm spread (p90-p10) > {FACE_SPREAD_MM} mm"
    if abs(m["anchor_ref_diff_mm"]) > REF_TOL_MM:
        return (f"anchor surface_z disagrees with the depth by {m['anchor_ref_diff_mm']} mm (> {REF_TOL_MM} mm): the camera height "
                f"over it by depth differs from cameras.top.height_m - surface_z; all sites {m['camera_height_diff_mm']}")
    if abs(m["nearest_ref_diff_mm"]) > REF_TOL_MM:  # the site next to the object, where the map and parallax are anchored too
        return (f"site {m['nearest_site']}, nearest the object, disagrees with the depth by {m['nearest_ref_diff_mm']} mm (> {REF_TOL_MM} mm): "
                f"check its surface_z or cameras.top.height_m; all sites {m['camera_height_diff_mm']}")
    return None


def prepare(cell, config, calibration, anchor, roi, catalog, out):
    """-> (config and calibration that hold the measured site named `free:<anchor>`, tight roi, error text or None).
    `out['free_source']` carries every measured number, also for a refusal."""
    name = PREFIX + anchor
    info = out.setdefault("free_source", {"anchor": anchor, "roi": list(roi)})
    site = config["sites"].get(anchor)
    record = cell_pivot.map_record(calibration, anchor)
    if site is None or record is None:
        return config, calibration, roi, f"refused: free source anchor {anchor!r} has no site or no map"
    if site.get("tier_of") or site.get("layer") or site.get("track") or "surface_z" not in site or _is_amr_bed_site(anchor):
        return config, calibration, roi, f"refused: free source anchor {anchor!r} is not a fixed flat site"
    at_px = config.get("_free_px")
    info["at_px"] = list(at_px) if at_px else None
    img = cell.frame("top")
    n = max(MIN_FRAMES, int(config.get("depth_frames", 7)))
    frames, receipt = _depth_frames(config, n)
    if frames is None:
        return config, calibration, roi, f"refused: free source needs depth, none available: {receipt}"
    m, err = measure(config, calibration, anchor, roi, at_px, img, frames)
    mask = m.pop("mask", None)
    info.update(m)
    if err:
        return config, calibration, roi, f"refused: free source: {err}"
    if (why := _verdict(m)):
        return config, calibration, roi, f"refused: free source: {why}"
    z_top = surface_z(config, anchor) + m["top_above_anchor_mm"] / 1000.0
    tight = _tight_roi(roi, mask, 25, img.shape)  # selects the target only; the caller's roi stays for the finger room, scene guard and verify
    cam = config["cameras"]["top"]
    hsv = (config.get("objects") or {}).get("hsv")
    cnts, _ = cv2.findContours(cv2.dilate(mask, np.ones((7, 7), np.uint8)), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    poly = (cv2.approxPolyDP(max(cnts, key=cv2.contourArea), 1.0, True).reshape(-1, 2) + [roi[0], roi[1]]).tolist()  # the measured blob, a few px wider
    cands = []
    for h0 in sorted({e["top_height_mm"] for e in catalog}, reverse=True):
        base = z_top - h0 / 1000.0
        for o in cell_objects.detect(img, tight, record, cam, catalog, base, config.get("params"), None, None, hsv):  # no clip: a neighbour in the tight roi must be seen
            entry = next((e for e in catalog if e["id"] == o.get("object")), None)
            if o["matched"] and entry and entry["top_height_mm"] == h0 and not o.get("split_from"):
                cands.append((h0, base, o))
    heights = sorted({c[0] for c in cands})
    info["candidates"] = [{"object": c[2]["object"], "top_height_mm": c[0]} for c in cands]
    if not cands:
        return config, calibration, roi, (f"refused: free source: no catalogue match for the blob at top z {round(z_top * 1000, 1)} mm "
                                     "(unmatched or tangled, nothing is picked)")
    if len(heights) > 1 or len(cands) > 1:
        return config, calibration, roi, (f"refused: free source: the blob matches {len(cands)} catalogue candidates at heights {heights} mm "
                                     f"({[c[2]['object'] for c in cands]}): the height of what is picked is not unique")
    h0, base, o = cands[0]
    rival = cell_objects.match(o, [e for e in catalog if e["top_height_mm"] != h0], colour=o.get("colour"))
    if rival:  # the same footprint also fits an entry of another height: the footprint does not say how tall it is
        return config, calibration, roi, (f"refused: free source: the blob matches {o['object']} ({h0} mm) and also {rival['id']} "
                                     f"({rival['top_height_mm']} mm): the height of what is picked is not unique")
    if not inside(o, poly):
        return config, calibration, roi, "refused: free source: the one catalogue object found is not the measured blob"
    err_mm = max(Z_ERR_MM, m["frame_spread_mm"])
    c_px = m["blob_centre_px"]
    lo_mm, hi_mm = (cell_objects.to_mm([c_px], record, cam, z_top + s * err_mm / 1000.0)[0] for s in (-1, 1))
    out_cfg = copy.deepcopy(config)
    free = {k: v for k, v in site.items() if k in ("yaw_deg", "grip_offset_m", "z_offset_m", "finger_params", "grasp_depth_m")}
    gd = grasp_depth(config, anchor)
    # z: where this site's targets are held (surface + top height - grasp depth), as every configured site states it
    out_cfg["sites"][name] = {**free, "surface_z": round(base, 4), "surface_px": poly, "detect_roi": tight, "blob_px": poly,
                              "free_object": o["object"], "blob_centre_px": c_px, "z": round(max(z_top - gd, base + gd), 4)}
    out_cfg["_map_only"] = True  # a free name has no bias region and gets no pivot circle or learned bias: the measured map alone
    marks = np.array([p["pixel"] for p in record.get("points", ()) if "pixel" in p], float).reshape(-1, 2)
    info.update({
        "site": name, "map_loo_error_mm": record.get("loo_error_mm"),
        "map_nearest_mark_px": round(float(np.min(np.hypot(*(marks - c_px).T))), 0) if len(marks) else None,
        "detect_roi": tight, "object": o["object"], "top_z_m": round(z_top, 4), "surface_z_used_m": round(base, 4),
        "grasp_z_m": round(z_top - gd, 4), "centre_mm": [round(float(v), 1) for v in o["centre_mm"]],
        "long_axis_deg": o["long_axis_deg"], "size_mm": [o["length_mm"], o["width_mm"]], "height_error_used_mm": err_mm,
        "xy_from_height_error_mm": round(float(np.hypot(*(hi_mm - lo_mm)) / 2), 1),
        "xy_error_note": "plus the anchor map's own error; from height alone it is the parallax of the height error at this pixel",
    })
    return out_cfg, {**calibration, "sites": {**calibration["sites"], record_key(name, "top"): record}}, roi, None
