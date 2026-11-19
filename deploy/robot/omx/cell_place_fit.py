#!/usr/bin/env python3
"""Where a held box fits on the destination: its whole footprint inside the surface and clear of what is already
there (2026-10-30).

The place used to be one configured point with the site's yaw. A 3-cell (90 mm) went to the belt's near edge and
landed leaning half off it, a 2-cell slid off the Pinky tray, and the tray already held a box when a carry to it was
asked. Here the footprint at the place - the box's length and width, turned the way the jaws hold it, plus
place.margin_mm - is projected into the destination's top view and must lie inside sites.<dest>.surface_px and off
the foreground there. Nearby points and the yaw turned 90 degrees are searched, nearest the configured point first,
since that point's reach is the one tried before.
"""
from __future__ import annotations

import math

import numpy as np

import cell_params as prm

TIERS = (1, 2, 3)  # 1단 (l0, layer 0), 2단 (l1, layer 1), 3단 (l2, layer 2)


def tier_step_m(site: dict, catalog: list | None = None) -> float:
    """Vertical step (m) per tier: the site's `tier_step_m`, else the catalogue container height, else 0.03 m."""
    if "tier_step_m" in site:
        return float(site["tier_step_m"])
    heights = [e["top_height_mm"] / 1000 for e in (catalog or ()) if e.get("top_height_mm")]
    return heights[0] if heights else 0.03


def with_tiers(config: dict, calibration: dict | None = None, catalog: list | None = None) -> tuple[dict, dict | None]:
    """Expand every site `<name>` that has `surface_z` into `<name>-l0` (1단), `<name>-l1` (2단), `<name>-l2` (3단)
    sharing `<name>`'s map (`tier_of`), so 1단/2단/3단 pick and place need no duplicate config files."""
    sites = dict(config.get("sites") or {})
    cal_sites = dict(calibration["sites"]) if isinstance(calibration, dict) and "sites" in calibration else None
    for name, site in list(sites.items()):
        if "surface_z" not in site or any(name.endswith(f"-l{k}") for k in (0, 1, 2)):
            continue
        step = tier_step_m(site, catalog)
        base_z = site["surface_z"] - site.get("layer", 0) * step
        map_key = site.get("map_from", name)
        for layer in (0, 1, 2):
            tname = f"{name}-l{layer}"
            if tname not in sites:
                z0 = round(base_z + layer * step, 4)
                tsite = {**site, "layer": layer, "tier": layer + 1, "surface_z": z0, "tier_of": name}
                tsite.pop("tier_step_m", None)
                if "z" in site:
                    tsite["z"] = round(site["z"] + (z0 - site["surface_z"]), 4)
                sites[tname] = tsite
            if cal_sites is not None and tname not in cal_sites and map_key in cal_sites:
                cal_sites[tname] = cal_sites[map_key]
    out_cal = {**calibration, "sites": cal_sites} if cal_sites is not None else calibration
    return {**config, "sites": sites}, out_cal


def with_tier_biases(config: dict, bias_data: dict) -> dict:
    """Share saved bias regions between a base site and its `-l0/-l1/-l2` tier sites (`tier_of` / `map_from`)."""
    regions = list(bias_data.get("regions") or [])
    have = {(r.get("site"), tuple(r.get("point_m") or ())) for r in regions}
    for name, site in (config.get("sites") or {}).items():
        base = site.get("tier_of") or site.get("map_from")
        if not base:
            continue
        for r in list(regions):
            if r.get("site") in (base, name):
                for target in (base, name):
                    key = (target, tuple(r.get("point_m") or ()))
                    if key not in have:
                        regions.append({**r, "site": target})
                        have.add(key)
    return {**bias_data, "regions": regions}


def has_support(xy, pixel_fn, occupied, roi) -> bool:
    """True when the lower tier's container shows in `occupied` (roi-relative) under `xy`."""
    px = pixel_fn(xy)
    if px is None:
        return False
    col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
    patch = occupied[max(0, row - 1):min(occupied.shape[0], row + 2), max(0, col - 1):min(occupied.shape[1], col + 2)]
    return bool(patch.size and patch.any())


def footprint(xy, axis_deg: float, length_mm: float, width_mm: float, step_mm: float = 5.0) -> list:
    """Points (m) covering a box centred at xy with its long axis along axis_deg: a grid plus the outline."""
    u = math.radians(axis_deg)
    x0, y0 = float(xy[0]), float(xy[1])
    ux, uy = math.cos(u) / 1000.0, math.sin(u) / 1000.0
    nx, ny = -uy, ux
    hl, hw = float(length_mm) / 2.0, float(width_mm) / 2.0
    ls = [*np.arange(-hl, hl, step_mm).tolist(), hl]
    ws = [*np.arange(-hw, hw, step_mm).tolist(), hw]
    corners = {(-hl, -hw), (-hl, hw), (hl, -hw), (hl, hw)}
    ordered = sorted(((a, c) for a in ls for c in ws), key=lambda ac: (0 if ac in corners else 1, ac[0] * ac[0] + ac[1] * ac[1]))
    return [(x0 + a * ux + c * nx, y0 + a * uy + c * ny) for a, c in ordered]


def why_not(points, pixel_fn, polygon_px, occupied=None, roi=None, layer: int = 0) -> str | None:
    """None when every point maps inside the polygon and (at layer 0) off the occupied mask or (at layer > 0) stands on
    a lower-tier container, else the reason."""
    import cv2

    poly = polygon_px if isinstance(polygon_px, np.ndarray) and polygon_px.dtype == np.float32 else np.asarray(polygon_px, np.float32)
    for p in points:
        px = pixel_fn(p)
        if px is None:
            return "no map at the destination"
        if cv2.pointPolygonTest(poly, (float(px[0]), float(px[1])), False) < 0:
            return "does not fit on the surface"
        if layer == 0 and occupied is not None and roi is not None:
            col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
            if 0 <= row < occupied.shape[0] and 0 <= col < occupied.shape[1] and occupied[row, col]:
                return "something is already there"
    if layer > 0 and occupied is not None and roi is not None:
        centre = tuple(np.mean(points, axis=0))
        if not has_support(centre, pixel_fn, occupied, roi) or sum(has_support(p, pixel_fn, occupied, roi) for p in points) < 0.6 * len(points):
            return "nothing under it at the lower tier"
    return None


def along_yaw(polygon_px, xy, held_axis_deg: float, base_yaw: float, pixel_fn, ratio: float = 2.0) -> float | None:
    """The place yaw that lays the box along a long surface's long side, judged in the top view (nearest the site's
    yaw among equals); None for a surface that is not long (a tray) or with no map there."""
    import cv2

    (_, _), (w, h), ang = cv2.minAreaRect(np.asarray(polygon_px, np.float32))
    if min(w, h) <= 0 or max(w, h) < ratio * min(w, h):
        return None
    side = math.radians(ang if w >= h else ang + 90)
    target = np.array([math.cos(side), math.sin(side)])

    def misfit(yaw):
        u = math.radians(yaw + held_axis_deg)
        a, b = pixel_fn(xy), pixel_fn((xy[0] + 0.01 * math.cos(u), xy[1] + 0.01 * math.sin(u)))
        d = None if a is None or b is None else np.subtract(b, a)
        return None if d is None or not np.linalg.norm(d) else 1 - abs(float(d @ target)) / float(np.linalg.norm(d))

    scored = [(round(m, 3), abs(y - base_yaw), float(y)) for y in np.arange(base_yaw - 90, base_yaw + 90.01, 5.0)
              if (m := misfit(float(y))) is not None]
    return round(min(scored)[2], 1) if scored else None


def options(config: dict, dest_site: str, place_xy, held_axis_deg: float, entry: dict, pixel_fn, occupied=None,
            roi=None) -> tuple[list, str | None]:
    """([(xy, place_yaw_deg), ...] nearest first, None) or ([], why). held_axis_deg: the box's long axis relative to
    the tool yaw, so at a place yaw Y it lies along Y + held_axis_deg. No surface_px: the configured point as is."""
    site, p = config["sites"][dest_site], config.get("params")
    layer = int(site.get("layer", site.get("tier", 1) - 1))
    polygon = site.get("surface_px")
    base_yaw = site["yaw_deg"]
    if polygon is None:
        if layer > 0 and occupied is not None and roi is not None and not has_support(place_xy, pixel_fn, occupied, roi):
            return [], "nothing under it at the lower tier"
        return [(tuple(place_xy), base_yaw)], None
    margin, reach, step = (prm.get(p, k) for k in ("place.margin_mm", "place.search_mm", "place.step_mm"))
    length, width = entry["length_mm"] + 2 * margin, entry["width_mm"] + 2 * margin
    offsets = sorted(((dx, dy) for dx in np.arange(-reach, reach + 1e-9, step) for dy in np.arange(-reach, reach + 1e-9, step)
                      if math.hypot(dx, dy) <= reach + 1e-9), key=lambda d: math.hypot(*d))
    found, reasons, yaws = [], set(), [base_yaw, base_yaw + 90.0, base_yaw - 90.0]
    poly = np.asarray(polygon, np.float32)
    along = along_yaw(poly, place_xy, held_axis_deg, base_yaw, pixel_fn)
    if along is not None:  # 2026-10-30 dry run: a 2-cell planned diagonally across the belt, which it also fits
        yaws = [along] + [y for y in yaws if abs((y - along + 90) % 180 - 90) > 5.0]
    for yaw in yaws:
        rel_pts = footprint((0.0, 0.0), yaw + held_axis_deg, length, width)
        for dx, dy in offsets:
            x0, y0 = round(place_xy[0] + dx / 1000, 4), round(place_xy[1] + dy / 1000, 4)
            xy = (x0, y0)
            why = why_not([(x0 + rx, y0 + ry) for rx, ry in rel_pts], pixel_fn, poly, occupied, roi, layer=layer)
            if why is None:
                found.append((xy, yaw, math.hypot(dx, dy) + (0 if yaw == yaws[0] else 1000)))
                break  # the nearest point for this yaw is enough
            reasons.add(why)
    if not found:
        return [], " / ".join(sorted(reasons)) or "does not fit on the surface"
    return [(xy, yaw) for xy, yaw, _ in sorted(found, key=lambda f: f[2])], None
