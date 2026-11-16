"""What a pivot would ask of the arm and the top camera, judged before its first arm command (2026-11-17 panel r6).

Single Responsibility: `pivot_precheck` plans every yaw of a pivot the way `cell_pivot.pivot_calibrate` will and
returns the problems that would make it fail or move the arm into an unchecked pose; an empty list means go. It
never opens a port or a camera and never adjusts `pivot.z_view` or the yaws: a lower view height is a new real-arm
pose set (AGENTS.md four checks), not a fix for marks out of view.

Config `pivot` keys (all optional):
  - `edge_margin_px` (40): every predicted jaw mark stays this far inside the top frame (arm_b belt end 2026-11-17:
    marks at image y 1-23 px, 0 marks).
  - `arc_margin_deg` (0): the planned FK arc must reach MIN_YAW_ARC_DEG plus this (the guard itself never moves).
  - `require_joint_limits` (false): refuse a config with no joint_min/joint_max. Stack configs should set it true.
  - `geometry.z_view` (or `height_m`): the view height the radius/phase were measured at; more than 5 mm from this
    pivot's height and the known-geometry shortcut is refused (2026-11-17: 10-28 mm disagreement).
The camera's frame size is `cameras.top.frame_wh` [w, h] when configured, else the caller's `frame_wh`.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_pipeline_io as cio  # noqa: E402
import cell_pivot  # noqa: E402
import omx_tcp  # noqa: E402

GEOMETRY_Z_TOL_M = 0.005


def geometry_height_problem(config: dict, site: str) -> str | None:
    """Why `pivot.geometry` may not be used at this site's pivot height, None when it may (or carries no height)."""
    geometry = (config.get("pivot") or {}).get("geometry") or {}
    measured = geometry.get("z_view", geometry.get("height_m"))
    z_view = cell_pivot.pivot_z_view(config, site)
    if measured is not None and abs(float(measured) - z_view) > GEOMETRY_Z_TOL_M:
        return (f"pivot.geometry was measured at z_view {measured} m, this pivot is at {z_view} m: "
                "re-measure the full circle at this height")
    return None


def pivot_precheck(config: dict, calibration: dict, site: str, target_xy, yaws, frame_wh=None) -> list[str]:
    """Problems with a pivot at `target_xy` over `yaws` (empty: go). Yaws without IK or outside the joint window are
    dropped exactly as pivot_calibrate drops them (they are never commanded); the rest must still mark in view and
    span the arc the fit needs."""
    pivot = config.get("pivot") or {}
    problems = []
    if pivot.get("require_joint_limits") and not (config.get("joint_min") and config.get("joint_max")):
        problems.append("joint limits missing: pivot.require_joint_limits is set and joint_min/joint_max are not")
    geometry = pivot.get("geometry")
    geo_problem = geometry_height_problem(config, site) if geometry else None
    if geo_problem:
        problems.append(geo_problem)
    record = cell_pivot.map_record(calibration, site)
    if record is None:
        return problems + ["no map for the site"]
    top = (config.get("cameras") or {}).get("top") or {}
    size = top.get("frame_wh") or frame_wh
    if not size:
        problems.append("top frame size unknown: set cameras.top.frame_wh")
    margin = float(pivot.get("edge_margin_px", 40))
    z_view = cell_pivot.pivot_z_view(config, site)
    view = {"x": target_xy[0], "y": target_xy[1], "z": round(z_view - config["plan"]["approach_m"], 4)}
    tcp_x_m = omx_tcp.config_tcp(config)
    fk_yaws, dropped = [], []
    for yaw in yaws:
        pose = dict(view, yaw_deg=yaw)
        try:
            library = cio.plan_library(config, pose, pose, check=False)
        except SystemExit as exc:
            dropped.append(f"{yaw}: {str(exc)[:80]}")
            continue
        error = cio.limit_error(config, library)
        if error:
            dropped.append(f"{yaw}: {error}")
            continue
        state = library["chunks"]["above_pick"][-1]
        fk_yaw = cell_pivot.joints_tcp(state, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))[3]
        fk_yaws.append(fk_yaw)
        raw = list(target_xy)
        if geometry and not geo_problem:  # the mark circles the TCP at the measured radius and phase
            angle = math.radians(fk_yaw + float(geometry["phase_deg"]))
            raw = [raw[0] + geometry["radius_mm"] / 1000 * math.cos(angle),
                   raw[1] + geometry["radius_mm"] / 1000 * math.sin(angle)]
        # shortcut: without a geometry the TCP pixel stands for the mark (~19 mm away); the margin covers it
        if size:
            try:
                px, py = cell_pivot.mark_pixel(record, config, site, raw, z_view)
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                problems.append(f"yaw {yaw}: jaw mark not predictable ({type(exc).__name__}: {exc})")
                continue
            w, h = size
            if not (margin <= px <= w - 1 - margin and margin <= py <= h - 1 - margin):
                problems.append(f"yaw {yaw}: jaw mark predicted at ({px:.0f}, {py:.0f}) px, within {margin:.0f} px "
                                f"of the {w}x{h} top frame edge")
    need = 2 if geometry and not geo_problem else 4
    if len(fk_yaws) < need:
        problems.append(f"{len(fk_yaws)} of {len(yaws)} yaws plan inside the window, need {need}"
                        + (f" (dropped {'; '.join(dropped)})" if dropped else ""))
    elif not (geometry and not geo_problem):
        arc, floor = cell_pivot._yaw_arc_deg(fk_yaws), cell_pivot.MIN_YAW_ARC_DEG + float(pivot.get("arc_margin_deg", 0))
        if arc < floor:
            problems.append(f"planned FK yaw arc {arc:.1f} deg < {floor:.0f} deg (MIN_YAW_ARC_DEG "
                            f"{cell_pivot.MIN_YAW_ARC_DEG:.0f} + pivot.arc_margin_deg)")
    return problems
