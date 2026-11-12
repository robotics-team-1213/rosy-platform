"""Site-specific topology and traffic policy layered over general road routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from fleet.charge_bays import Bay, bays_from_map
from fleet.routing.graph import Graph
from fleet.routing.road_path import (
    CorridorRule,
    plan_road_path,
    regional_corridor_for_map,
    station_exit_routes,
)
from fleet.site_map import SiteMap
from fleet.site_rules import SiteRules


@dataclass(frozen=True)
class SiteZonePolicy:
    site_id: str
    map_version: int | None
    charge_bays: tuple[str, ...]
    bay_staging_places: Mapping[str, str]
    entry_gate_place: str | None
    exit_gate_place: str | None
    merge_in_place: str | None
    merge_out_place: str | None
    corridor_rule: CorridorRule | None
    zone_speed_caps_mps: Mapping[str, float]
    _charge_bay_edges: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def classify_edge_zone(self, edge_id: str) -> str:
        if edge_id.startswith("bay_") or edge_id in self._charge_bay_edges:
            return "charge_bay"
        if (self.corridor_rule and edge_id in self.corridor_rule.corridor_edges) or edge_id.startswith(("park_", "bar_", "exit_")):
            return "charge_corridor"
        return "main_loop"

    def speed_cap_for_edge(self, edge_id: str, default_mps: float = 0.15) -> float:
        return self.zone_speed_caps_mps.get(self.classify_edge_zone(edge_id), default_mps)

    def to_dict(self, graph: Graph | None = None) -> dict[str, Any]:
        corridor: dict[str, Any] | None = None
        if self.corridor_rule is not None:
            rule = self.corridor_rule
            corridor = {
                "zone_id": rule.zone_id,
                "exit_place": rule.exit_place,
                "order": rule.order,
                "capacity": rule.capacity,
                "corridor_edges": list(rule.corridor_edges),
                "station_order": [],
            }
            if graph is not None:
                routes = station_exit_routes(graph, rule)
                ordered = sorted(
                    ((station, route) for station, route in routes.items()),
                    key=lambda item: (item[1].length_m, item[0]),
                )
                corridor["station_order"] = [
                    {
                        "bay": station,
                        "rank": rank,
                        "exit_distance_m": round(route.length_m, 4),
                        "places": list(route.places),
                        "edges": list(route.edges),
                    }
                    for rank, (station, route) in enumerate(ordered, 1)
                ]
        return {
            "site_id": self.site_id,
            "map_version": self.map_version,
            "charge_bays": list(self.charge_bays),
            "bay_staging_places": dict(self.bay_staging_places),
            "entry_gate_place": self.entry_gate_place,
            "exit_gate_place": self.exit_gate_place,
            "merge_in_place": self.merge_in_place,
            "merge_out_place": self.merge_out_place,
            "zone_speed_caps_mps": dict(self.zone_speed_caps_mps),
            "corridor": corridor,
        }


def resolve_site_policy(
    site_map: SiteMap | None, graph: Graph | None, site_rules: SiteRules | None = None
) -> SiteZonePolicy:
    bays = bays_from_map(site_map) if site_map is not None else []
    rule = regional_corridor_for_map(graph, bays, site_rules=site_rules)
    bay_ids = {bay.id for bay in bays}
    staging: dict[str, str] = {}
    bay_edges: list[str] = []
    if graph is not None:
        for arc in graph.arcs.values():
            if arc.start_place in bay_ids or arc.end_place in bay_ids:
                bay = arc.start_place if arc.start_place in bay_ids else arc.end_place
                staging.setdefault(bay, arc.end_place if arc.start_place == bay else arc.start_place)
                if arc.edge_id not in bay_edges:
                    bay_edges.append(arc.edge_id)
    places = graph.places if graph is not None else {}
    caps = {
        "charge_bay": 0.05,
        "charge_corridor": 0.08,
        "main_loop": float(site_rules.formation.max_speed_mps)
        if site_rules and site_rules.formation.max_speed_mps else 0.15,
    }
    return SiteZonePolicy(
        site_id=site_map.map_id if site_map is not None else "site",
        map_version=graph.version if graph is not None else None,
        charge_bays=tuple(bay.id for bay in bays),
        bay_staging_places=staging,
        entry_gate_place="S2" if "S2" in places else None,
        exit_gate_place=rule.exit_place if rule else ("S1" if "S1" in places else None),
        merge_in_place="J_in" if "J_in" in places else None,
        merge_out_place="J_out" if "J_out" in places else None,
        corridor_rule=rule,
        zone_speed_caps_mps=caps,
        _charge_bay_edges=tuple(bay_edges),
    )


def plan_site_road_trip(
    policy: SiteZonePolicy,
    graph: Graph,
    start_pose: tuple[float, float] | tuple[float, float, float | None],
    goal: str | tuple[float, float] | tuple[float, float, float | None],
    *,
    step_m: float = 0.12,
) -> dict[str, Any]:
    road_plan = plan_road_path(graph, start_pose, goal, step_m=step_m)
    result = road_plan.to_dict()
    waypoints = []
    zones: list[str] = []
    for waypoint in result["waypoints_site"]:
        annotated = dict(waypoint)
        zone = policy.classify_edge_zone(annotated["edge_id"])
        annotated["zone"] = zone
        annotated["speed_cap_mps"] = policy.speed_cap_for_edge(annotated["edge_id"])
        waypoints.append(annotated)
        if zone not in zones:
            zones.append(zone)
    result.update(site_id=policy.site_id, zones=zones, waypoints_site=waypoints)
    return result
