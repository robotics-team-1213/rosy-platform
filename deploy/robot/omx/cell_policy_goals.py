"""Resolve a Cell job destination to the h1 ACT training slot."""
from pathlib import Path
import sys

GOALS = tuple(f"ship-h1r{column}-l{tier}" for column in range(3) for tier in range(3)) + ("tray",)


def resolve_goal_site(site: str) -> tuple[str, int]:
    if not isinstance(site, str):
        raise ValueError("expected a Cell site ID")
    if site in GOALS[:-1]:
        return site, GOALS.index(site)
    here = Path(__file__).resolve()
    candidates = ((here.parents[3] / "tools" / "sim",) if len(here.parents) > 3 else ()) + (here.parent / "tools" / "sim",)
    sim_tools = str(next((p for p in candidates if p.is_dir()), candidates[0]))
    if sim_tools not in sys.path:
        sys.path.insert(0, sim_tools)
    from cell_site_map import load, tier_places

    cell_map = load()
    if site in ("tray", "vehicle_tray", "not_places:vehicle_tray") and any(
        entry["id"] == "vehicle_tray" for entry in cell_map["not_places"]
    ):
        return "tray", GOALS.index("tray")
    destination = tier_places(cell_map).get(site)
    if destination not in GOALS:
        raise ValueError(f"{site!r} has no h1 policy goal slot")
    return destination, GOALS.index(destination)


def cli_goal(args, shadow, parser) -> tuple[int | None, str | None, int | None]:
    """(goal slot, destination, its h1 slot) from --goal-site/--goal-slot against the checkpoint's goal input (cell_policy_drive)."""
    destination = mapped_slot = None
    goal_slot = args.goal_slot
    goal_size = getattr(shadow, "goal_size", None)
    if args.goal_site is not None:
        if shadow is not None and goal_size is None and args.mode == "act":
            parser.error("checkpoint has no goal input")
        if shadow is not None and goal_size is not None and goal_size != len(GOALS):
            parser.error(f"--goal-site requires the {len(GOALS)}-slot h1 goal input")
        try:
            destination, mapped_slot = resolve_goal_site(args.goal_site)
        except (ValueError, OSError) as error:
            parser.error(str(error))
        if goal_slot is None and shadow is not None and goal_size is not None:
            goal_slot = mapped_slot
        if args.mode == "hybrid" and goal_slot is not None and goal_slot != mapped_slot:
            parser.error("hybrid ACT goal must match the taught destination")
    if shadow is not None and goal_size is not None:
        if goal_slot is None or not 0 <= goal_slot < goal_size:
            parser.error(f"checkpoint requires --goal-site or --goal-slot 0..{goal_size - 1}")
    elif goal_slot is not None:
        parser.error("checkpoint has no goal input")
    if args.mask_pick_goal and (shadow is None or goal_size is None):
        parser.error("--mask-pick-goal requires a goal-conditioned checkpoint")
    if getattr(shadow, "belt_input", False) and list(shadow.env_names[:goal_size]) != list(GOALS):
        parser.error(f"checkpoint goal names {shadow.env_names[:goal_size]} are not the cell's h1 slots {list(GOALS)}")
    return goal_slot, destination, mapped_slot
