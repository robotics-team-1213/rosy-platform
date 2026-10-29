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


def footprint(xy, axis_deg: float, length_mm: float, width_mm: float, step_mm: float = 5.0) -> list:
    """Points (m) covering a box centred at xy with its long axis along axis_deg: a grid plus the outline."""
    u = math.radians(axis_deg)
    along, across = np.array([math.cos(u), math.sin(u)]), np.array([-math.sin(u), math.cos(u)])
    hl, hw = length_mm / 2, width_mm / 2
    ls = np.append(np.arange(-hl, hl, step_mm), hl)
    ws = np.append(np.arange(-hw, hw, step_mm), hw)
    return [tuple(np.asarray(xy) + (a * along + c * across) / 1000) for a in ls for c in ws]


def why_not(points, pixel_fn, polygon_px, occupied=None, roi=None) -> str | None:
    """None when every point maps inside the polygon and off the occupied mask (roi-relative), else the reason."""
    import cv2

    poly = np.asarray(polygon_px, np.float32)
    for p in points:
        px = pixel_fn(p)
        if px is None:
            return "no map at the destination"
        if cv2.pointPolygonTest(poly, (float(px[0]), float(px[1])), False) < 0:
            return "does not fit on the surface"
        if occupied is not None and roi is not None:
            col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
            if 0 <= row < occupied.shape[0] and 0 <= col < occupied.shape[1] and occupied[row, col]:
                return "something is already there"
    return None


def options(config: dict, dest_site: str, place_xy, held_axis_deg: float, entry: dict, pixel_fn, occupied=None,
            roi=None) -> tuple[list, str | None]:
    """([(xy, place_yaw_deg), ...] nearest first, None) or ([], why). held_axis_deg: the box's long axis relative to
    the tool yaw, so at a place yaw Y it lies along Y + held_axis_deg. No surface_px: the configured point as is."""
    site, p = config["sites"][dest_site], config.get("params")
    polygon = site.get("surface_px")
    base_yaw = site["yaw_deg"]
    if polygon is None:
        return [(tuple(place_xy), base_yaw)], None
    margin, reach, step = (prm.get(p, k) for k in ("place.margin_mm", "place.search_mm", "place.step_mm"))
    length, width = entry["length_mm"] + 2 * margin, entry["width_mm"] + 2 * margin
    offsets = sorted(((dx, dy) for dx in np.arange(-reach, reach + 1e-9, step) for dy in np.arange(-reach, reach + 1e-9, step)
                      if math.hypot(dx, dy) <= reach + 1e-9), key=lambda d: math.hypot(*d))
    found, reasons = [], set()
    for yaw in (base_yaw, base_yaw + 90.0, base_yaw - 90.0):
        for dx, dy in offsets:
            xy = (round(place_xy[0] + dx / 1000, 4), round(place_xy[1] + dy / 1000, 4))
            why = why_not(footprint(xy, yaw + held_axis_deg, length, width), pixel_fn, polygon, occupied, roi)
            if why is None:
                found.append((xy, yaw, math.hypot(dx, dy) + (0 if yaw == base_yaw else 1000)))
                break  # the nearest point for this yaw is enough
            reasons.add(why)
    if not found:
        return [], " / ".join(sorted(reasons)) or "does not fit on the surface"
    return [(xy, yaw) for xy, yaw, _ in sorted(found, key=lambda f: f[2])], None
