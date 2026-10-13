"""D-488: the map_v2_fleet lane graph as the site map tests plan and meet on."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from fleet.meet.place import painted_from
from fleet.site_map import from_lane_graph

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"


@lru_cache(maxsize=1)
def painted_track():
    """The ``Painted`` the stuck resolver and /route read from an imported site map."""
    return painted_from(from_lane_graph(LANE_GRAPH))


@lru_cache(maxsize=1)
def painted_without_crosswalks():
    """The same track on a site map without crosswalks (D-573 1): R3 is judged on its other rules."""
    return replace(painted_track(), crosswalks=())
