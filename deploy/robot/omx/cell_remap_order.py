"""The remap's visit order, its scene-check exclusions and its stop-naming fit (2026-11-26, split from cell_remap_plan
for the 400-line module limit)."""
from __future__ import annotations

import math


JOINTS = ("shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos")


def direct_move(start: list, goal: list) -> bool:
    """chunk_library.transit_path's test for a straight move instead of the raised transit (kept equal by
    test_direct_move_matches_transit_path)."""
    return (start[1] >= -35.0 and goal[1] >= -35.0 and abs(start[0] - goal[0]) <= 15.0
            and max(abs(a - b) for a, b in zip(start[:4], goal[:4])) <= 24.0 and abs(start[4] - goal[4]) <= 45.0)


def visit_indices(points: list, hovers: list | None = None, budget: int = 200_000) -> list:
    """Indices into `points`: the point nearest the base first, then always the nearest one not yet visited.

    2026-11-26 arm_a: ordered by distance from the base alone, 6 of 18 moves crossed the grid (80-105 s each at
    remap_transit_speed 0.2) and took half of the 19 min remap. With `hovers` (each point's planned above_pick joints,
    JOINTS order) the same first point starts the order with the fewest moves transit_path sends through the raised
    transit pose (an 87 s close-rise-turn-descend-open on arm_a that afternoon); the search stops after `budget` nodes."""
    if not points:
        return []
    left = sorted(range(len(points)), key=lambda i: math.hypot(*points[i]))
    order = [left.pop(0)]
    while left:  # by position, so a repeated point is visited as often as it is listed
        here = points[order[-1]]
        order.append(left.pop(min(range(len(left)), key=lambda k: math.dist(points[left[k]], here))))
    if hovers is None or len(hovers) != len(points) or any(h is None for h in hovers):
        return order
    near = [[direct_move(a, b) for b in hovers] for a in hovers]
    best, nodes = [sum(not near[a][b] for a, b in zip(order, order[1:])), order], [0]

    def walk(seq: list, rest: list, transits: int) -> None:
        if transits >= best[0] or nodes[0] >= budget:
            return
        nodes[0] += 1
        if not rest:
            best[:] = [transits, list(seq)]
            return
        here = seq[-1]
        for j in sorted(rest, key=lambda j: (not near[here][j], math.dist(points[here], points[j]))):
            walk(seq + [j], [k for k in rest if k != j], transits + (not near[here][j]))

    walk(order[:1], order[1:], 0)
    return best[1]


def visit_order(points: list, hovers: list | None = None) -> list:
    """`points` in visit_indices order."""
    return [points[i] for i in visit_indices(points, hovers)]


def remap_order(config: dict, points: list) -> list:
    """The remap's points ordered from each one's planned hover; the plain nearest chain when no plan can be made."""
    import cell_remap_plan as rp

    try:
        return [row["point"] for row in rp.plan(config, points)]
    except (ImportError, KeyError, TypeError, ValueError, SystemExit):
        return visit_order(points)


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


MOVE_MIN_INLIERS = 100  # the check's ORB match; the 11-26/27 cell reads 539-600, a bad match reads tens


def regions_now(config: dict, found: dict, frame) -> dict:
    """The config with its image regions (site ROIs, surfaces) carried to the current frame when the camera moved.

    2026-11-27 arm_a: the A/B top camera moved 33 px and the remap's depth obstacle check read the pallet through its
    old ROI, half off the pallet ("insufficient depth coverage 6946/11360"), so the remap that would fix the camera
    could never start. The remap step already moves the regions after it; this moves a copy for the depth check only.
    Without a good match (`camera_shift` not ok or under MOVE_MIN_INLIERS inliers) the regions stay and the check refuses."""
    shift = found.get("camera_shift") or {}
    if not found.get("camera_moved") or frame is None or not shift.get("ok") or (shift.get("inliers") or 0) < MOVE_MIN_INLIERS:
        return config
    import copy
    from pathlib import Path

    import cv2
    from cell_calibrate_bound import move_regions

    ref = cv2.imread(str(Path((config.get("preflight") or {}).get("reference_top", "")).expanduser()), cv2.IMREAD_GRAYSCALE)
    if ref is None:
        return config
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    try:
        return move_regions(copy.deepcopy(config), ref, gray)
    except (cv2.error, ValueError, TypeError, AttributeError):  # no usable homography: measure as before, which refuses
        return config

