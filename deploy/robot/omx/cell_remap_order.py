"""The remap's visit order, its scene-check exclusions and its stop-naming fit (2026-11-26, split from cell_remap_plan
for the 400-line module limit)."""
from __future__ import annotations

import math


def visit_order(points: list) -> list:
    """The point nearest the base first, then always the nearest point not yet visited.

    2026-11-26 arm_a: ordered by distance from the base alone, 6 of 18 moves crossed the grid (80-105 s each at
    remap_transit_speed 0.2) and took half of the 19 min remap."""
    left = sorted(points, key=lambda q: math.hypot(*q))
    order = left[:1]
    del left[:1]
    while left:  # by position, so a repeated point is visited as often as it is listed
        here = order[-1]
        order.append(left.pop(min(range(len(left)), key=lambda i: math.hypot(left[i][0] - here[0], left[i][1] - here[1]))))
    return order


def scene_ignore(config: dict) -> list:
    """Rects the remap's folded before/after comparison skips: moving sites, `scene_ignore_px`, and
    `calibrate.scene_ignore_px`, the folded arm's own links and cables, which park a few px apart
    (2026-11-24..26 arm_s: 4 of 9 remaps lost to 160-400 px blobs on its own body)."""
    import cell_scene_guard

    return [*cell_scene_guard.moving_rects(config), *(config.get("scene_ignore_px") or ()),
            *((config.get("calibrate") or {}).get("scene_ignore_px") or ())]


def fit_naming_stop(stop: str | None, config: dict, z_view: float, **kw) -> dict:
    """fit_remap_marks; a refusal after a stopped move also names the stop (2026-11-26 arm_a: four contact stops at
    the first point read only "remap: only 0 marks agree of 0")."""
    import cell_remap_plan as rp

    try:
        return rp.fit_remap_marks(config, z_view, **kw)
    except SystemExit as exc:
        if stop is None:
            raise
        raise SystemExit(f"{stop}; {exc}") from exc
