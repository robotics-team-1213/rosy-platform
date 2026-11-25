"""Conservative D435 obstacle evidence for the OMX remap planner."""
from __future__ import annotations

import math

REMAP_MIN_RAISED_PX = 20


def site_obstacle_mm(configured: dict, sites: list[str], depth, colour) -> dict:
    """Measure maximum obstacle height above the table, or refuse unusable depth at any remap site."""
    if depth is None or colour is None:  # capture_top_depth_z16 answers None, it never raises: no frame is not "nothing stands here"
        raise ValueError("the D435 depth capture returned no frame" if depth is None else "the top camera returned no frame")
    import numpy as np
    import cell_depth
    from cell_depth_slots import ALIGN_EDGE_MAX_PX, MIN_VALID_RATIO

    plane = cell_depth.table_plane(depth)
    if abs(float(plane[0][2])) < 0.99:
        candidates = [plane, *(cell_depth.table_plane(depth, seed=s) for s in (1, 2, 3))]
        plane = max(candidates, key=lambda p: abs(float(p[0][2])))
    heights = cell_depth.height_map(depth, plane)
    to_depth, edge_px = cell_depth.align_edges(colour, heights)
    if not math.isfinite(float(edge_px)) or float(edge_px) > ALIGN_EDGE_MAX_PX:
        raise ValueError(f"colour/depth alignment is loose ({edge_px:.1f} px): the site ROIs cannot be placed on the depth")
    lo_mm = float(cell_depth.RAISED_MM[0])
    hi_mm = max(float(cell_depth.RAISED_MM[1]), 220.0)
    sites_mm: dict[str, float] = {}
    if not sites:
        raise ValueError("no configured remap sites have a depth ROI")
    rgb_h, rgb_w = colour.shape[:2]
    dep_h, dep_w = heights.shape
    for name in sites:
        site = configured.get(name)
        roi = site.get("auto_roi") if isinstance(site, dict) else None
        if not isinstance(roi, (tuple, list)) or len(roi) != 4:
            raise ValueError(f"{name}: missing remap depth ROI")
        try:
            x1, y1, x2, y2 = (float(v) for v in roi)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}: invalid remap depth ROI") from exc
        if not (0 <= x1 < x2 <= rgb_w and 0 <= y1 < y2 <= rgb_h):
            raise ValueError(f"{name}: remap ROI is outside the colour frame or invalid")
        corners = np.asarray([[x1, y1, 1.], [x1, y2, 1.], [x2, y1, 1.], [x2, y2, 1.]])
        mapped = (to_depth @ corners.T)[:2]
        if not np.isfinite(mapped).all():
            raise ValueError(f"{name}: remap ROI has no finite depth alignment")
        dx1, dy1 = np.floor(mapped.min(axis=1)).astype(int)
        dx2, dy2 = np.ceil(mapped.max(axis=1)).astype(int)
        if not (0 <= dx1 < dx2 <= dep_w and 0 <= dy1 < dy2 <= dep_h):
            raise ValueError(f"{name}: remap ROI is outside the depth frame or clipped")
        patch = heights[dy1:dy2, dx1:dx2]
        valid = np.isfinite(patch)
        count = np.count_nonzero(valid)
        if count < REMAP_MIN_RAISED_PX or count < MIN_VALID_RATIO * patch.size:
            raise ValueError(f"{name}: insufficient depth coverage ({count}/{patch.size} ROI pixels)")
        vals = patch[valid & (patch >= lo_mm)]
        if np.any(vals > hi_mm):
            raise ValueError(f"{name}: obstacle return exceeds the measured height range")
        if 0 < vals.size < REMAP_MIN_RAISED_PX:
            raise ValueError(f"{name}: inconclusive raised obstacle ({vals.size} ROI pixels)")
        # A high obstacle can occupy less than one percent of an otherwise raised site.
        sites_mm[name] = math.ceil(10 * float(vals.max())) / 10 if vals.size else 0.0
    return {
        "obstacle_mm": max(sites_mm.values(), default=0.0),
        "sites_mm": sites_mm,
        "edge_px": round(float(edge_px), 2),
        "plane_nz": round(abs(float(plane[0][2])), 4),
    }
