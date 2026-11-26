"""cell_calibrate command-line rules: which flag combinations are refused, and the forced map remeasure."""
from __future__ import annotations


def argument_error(args) -> str | None:
    """Why this combination of cell_calibrate flags is refused, or None."""
    if args.obstacle_mm is not None and not 0 < args.obstacle_mm < float("inf"):
        return "--obstacle-mm must be a positive finite number of mm"
    if args.cad_image_evidence is not None and not args.route:
        return "--cad-image-evidence requires check --route"
    if args.remeasure_surface is not None and (args.step != "auto" or args.only != ["surface"]
            or not args.surface_clear or args.plan_only or args.replay_frames or args.targets or args.verify):
        return "--remeasure-surface requires auto --only surface --surface-clear"
    if args.route and (args.step != "check" or args.plan_only or args.replay_frames):
        return "--route requires a live read-only check"
    if args.remeasure_map and (args.step != "auto" or not args.only or "remap" not in args.only
            or args.remeasure_surface is not None or args.plan_only or args.replay_frames or args.targets or args.verify):
        return "--remeasure-map requires auto --only remap"
    return None


def with_remeasure(todo: list, remeasure_map: bool) -> list:
    """The steps to run; --remeasure-map adds the remap even when check finds the map current.

    2026-11-26 arm_s: a supervised remap request ended without moving because check said todo []; an operator who
    wants a fresh map (or to time the remap) had no way to ask for one."""
    return ["remap", *todo] if remeasure_map and "remap" not in todo else todo
