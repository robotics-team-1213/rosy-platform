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
