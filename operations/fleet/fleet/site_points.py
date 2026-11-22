"""Unified read-model projection of vehicle stops, handoff bridges and canonical arm cell zones.

Single-owner truth:
- Vehicle coordinates, pinned/stop_zone/approach_m flags, and directed edges come ONLY from the active ``rosy.site_map/1``.
- Vehicle stop operating rules come ONLY from ``rosy.site_rules/1``.
- Canonical 37-site cell topology comes ONLY from ``shared/web/cell-site-map.json``.
- Coordinate-free ``handoffs`` declare how vehicle stops meet arm workcells, exposed either in ``full`` view
  (``rosy.site-points.v1`` for ROSY UI/diagnostics) or ``port`` view (``rosy.port-site-places.v1`` for HarborLogi,
  stripped of coordinates, lane geometry, workcell/arm ids, marker ids and legacy aliases).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from fleet.site_map import SiteMap, approach_pose
from fleet.site_rules import SiteRules

SCHEMA_FULL = "rosy.site-points.v1"
SCHEMA_PORT = "rosy.port-site-places.v1"

PLANNED_VEHICLE_STOPS: tuple[dict[str, str], ...] = (
    {
        "id": "S_OUT",
        "name": "S_OUT 반출대 상차 정지선",
        "kind": "stop",
        "port_role": "outbound_pickup",
        "expected_rule_role": "load",
    },
)

SITE_HANDOFFS: tuple[dict[str, Any], ...] = (
    {
        "id": "s3_cell_s_unload",
        "kind": "intake",
        "direction": "vehicle_to_arm",
        "vehicle_stop_id": "S3",
        "intake_point_ref": "intake-s3",
        "cell_id": "cell_s",
        "arms": ["arm_s"],
        "arm_src": "not_places:vehicle_tray",
        "arm_dst": "not_places:belt",
        "target_cell_zones": ["yard"],
        "requires_arm_fold_for_align": True,
    },
    {
        "id": "outbound_stand_load",
        "kind": "outbound",
        "direction": "arm_to_vehicle",
        "vehicle_stop_id": "S_OUT",
        "vehicle_exit_stop_id": "S1",
        "cell_id": "cell_ab",
        "arms": ["arm_a"],
        "arm_src": "stand:r1-s1-t1",
        "arm_dst": "not_places:vehicle_tray",
        "cell_zone_id": "stand",
        "wire_slot_ref": "stand-r1-c1-l1",
        "requires_arm_fold_for_align": True,
    },
)


def _edge_links(site_map: SiteMap) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    edges_in: dict[str, list[str]] = {}
    edges_out: dict[str, list[str]] = {}
    for edge in site_map.edges:
        edges_out.setdefault(edge.from_, []).append(edge.id)
        edges_in.setdefault(edge.to, []).append(edge.id)
        if edge.direction == "two_way":
            edges_out.setdefault(edge.to, []).append(edge.id)
            edges_in.setdefault(edge.from_, []).append(edge.id)
    return edges_in, edges_out


def _stop_rules_by_place(rules: SiteRules | None) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if rules is None:
        return {}, set()
    by_place: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for stop in rules.stops:
        if stop.place in by_place:
            ambiguous.add(stop.place)
            continue
        by_place[stop.place] = {
            "role": stop.role,
            "release": stop.release,
            "timeout_s": stop.timeout_s,
            "on_timeout": stop.on_timeout,
        }
    return by_place, ambiguous


def _port_role_for(place_id: str, kind: str, rule_role: str | None, exit_place: str | None) -> str | None:
    if place_id == "S_OUT":
        return "outbound_pickup"
    if kind == "charge":
        return "charge"
    if kind == "stop":
        if exit_place is not None and place_id == exit_place and place_id != "S1":
            return "outbound_exit"
        if rule_role == "unload":
            return "intake_dropoff"
        if rule_role == "load":
            return "inbound_load"
        return "wait"
    return None


def _is_verified_stop(
    place,
    rule: dict[str, Any] | None,
    *,
    has_edges_in: bool,
    has_edges_out: bool,
    ambiguous_rule: bool = False,
) -> tuple[str, bool]:
    if place.id == "S_OUT":
        ok = (
            place.kind == "stop"
            and bool(place.pinned)
            and place.stop_zone is not None
            and place.approach_m is not None
            and not ambiguous_rule
            and rule is not None
            and rule.get("role") == "load"
            and has_edges_in
            and has_edges_out
        )
        return ("verified" if ok else "planned_unverified"), ok
    if place.kind == "charge":
        return "verified", False
    if place.kind == "stop":
        return "verified", True
    return "junction", False


def _cell_zone_role(zone_id: str) -> str:
    if zone_id == "stand":
        return "outbound"
    if zone_id.startswith("temp_"):
        return "temporary"
    return "storage"


def _cell_zone_status(status: str) -> str:
    return "verified" if status == "verified" else "planned_unverified"


def _with_digest(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {**payload, "digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def build_site_points(
    *,
    site_map_view: dict[str, Any],
    site_map: SiteMap,
    site_rules_view: dict[str, Any] | None,
    site_rules: SiteRules | None,
    cell_sites: dict[str, Any],
    legacy_station_zones: dict[str, Any] | None = None,
    view: Literal["full", "port"] = "full",
    include_junctions: bool = False,
) -> dict[str, Any]:
    if view not in ("full", "port"):
        raise ValueError(f"unsupported site-points view: {view!r}")

    edges_in, edges_out = _edge_links(site_map)
    stop_rules, ambiguous_rules = _stop_rules_by_place(site_rules)
    exit_place = site_rules.return_.exit_place if site_rules is not None else None

    sources = {
        "site_map": {
            "map_id": site_map.map_id,
            "version": int(site_map_view["version"]),
            "sha256": site_map_view["sha256"],
        },
        "site_rules": {
            "version": int(site_rules_view["version"]) if site_rules_view is not None else None,
            "sha256": site_rules_view["sha256"] if site_rules_view is not None else None,
        },
        "cell_site_map": {
            "schema": cell_sites["schema"],
            "revision": int(cell_sites["revision"]),
            "status": cell_sites["status"],
        },
    }

    active_by_id = {p.id: p for p in site_map.places}
    vehicle_stops: list[dict[str, Any]] = []
    vehicle_places_port: list[dict[str, Any]] = []
    port_stop_by_id: dict[str, dict[str, Any]] = {}

    for place in site_map.places:
        if place.kind not in ("stop", "charge", "park") and not include_junctions and place.id != "S_OUT":
            continue
        rule = stop_rules.get(place.id)
        p_edges_in = edges_in.get(place.id, [])
        p_edges_out = edges_out.get(place.id, [])
        status, dispatchable = _is_verified_stop(
            place,
            rule,
            has_edges_in=bool(p_edges_in),
            has_edges_out=bool(p_edges_out),
            ambiguous_rule=place.id in ambiguous_rules,
        )
        port_role = _port_role_for(place.id, place.kind, rule["role"] if rule else None, exit_place)
        app_pose = approach_pose(place) if place.kind == "stop" else None

        if (place.kind in ("stop", "charge") or place.id == "S_OUT") and port_role is not None:
            port_entry = {
                "place_id": place.id,
                "port_role": port_role,
                "status": "verified" if status == "verified" else "planned_unverified",
                "dispatchable": dispatchable,
                "label": place.name,
            }
            vehicle_places_port.append(port_entry)
            port_stop_by_id[place.id] = port_entry

        vehicle_stops.append(
            {
                "id": place.id,
                "name": place.name,
                "kind": place.kind,
                "port_role": port_role,
                "in_active_map": True,
                "pose": {"x": place.x, "y": place.y, "yaw": place.yaw},
                "pinned": bool(place.pinned),
                "stop_zone": [list(pt) for pt in place.stop_zone] if place.stop_zone is not None else None,
                "approach_m": place.approach_m,
                "approach_pose": (
                    {"x": app_pose[0], "y": app_pose[1], "yaw": app_pose[2]} if app_pose is not None else None
                ),
                "rule": rule,
                "edges_in": edges_in.get(place.id, []),
                "edges_out": edges_out.get(place.id, []),
                "status": status,
                "dispatchable": dispatchable,
            }
        )

    for planned in PLANNED_VEHICLE_STOPS:
        pid = planned["id"]
        if pid in active_by_id:
            continue
        port_entry = {
            "place_id": pid,
            "port_role": planned["port_role"],
            "status": "planned_unverified",
            "dispatchable": False,
            "label": planned["name"],
        }
        vehicle_places_port.append(port_entry)
        port_stop_by_id[pid] = port_entry
        vehicle_stops.append(
            {
                "id": pid,
                "name": planned["name"],
                "kind": planned["kind"],
                "port_role": planned["port_role"],
                "in_active_map": False,
                "pose": None,
                "pinned": False,
                "stop_zone": None,
                "approach_m": None,
                "approach_pose": None,
                "rule": None,
                "edges_in": [],
                "edges_out": [],
                "status": "planned_unverified",
                "dispatchable": False,
            }
        )

    cell_zones_port: list[dict[str, Any]] = []
    zone_status_by_id: dict[str, str] = {}
    for z in cell_sites.get("zones", []):
        zstatus = _cell_zone_status(z.get("status", cell_sites.get("status", "planned_unverified")))
        zone_status_by_id[z["id"]] = zstatus
        cell_zones_port.append(
            {
                "zone_id": z["id"],
                "role": _cell_zone_role(z["id"]),
                "status": zstatus,
                "label": z["label"],
            }
        )

    not_place_ids = [np["id"] for np in cell_sites.get("not_places", [])]

    handoffs_full: list[dict[str, Any]] = []
    intake_handoffs_port: list[dict[str, Any]] = []
    outbound_handoffs_port: list[dict[str, Any]] = []

    for h in SITE_HANDOFFS:
        v_stop = port_stop_by_id.get(h["vehicle_stop_id"])
        stop_resolved = h["vehicle_stop_id"] in active_by_id
        if h["kind"] == "intake":
            targets_ok = all(zone_status_by_id.get(zid) == "verified" for zid in h["target_cell_zones"])
            h_verified = bool(
                stop_resolved
                and v_stop is not None
                and v_stop["status"] == "verified"
                and v_stop["dispatchable"]
                and v_stop["port_role"] == "intake_dropoff"
                and targets_ok
            )
            h_status = "verified" if h_verified else "planned_unverified"
            intake_handoffs_port.append(
                {
                    "handoff_id": h["id"],
                    "vehicle_stop_id": h["vehicle_stop_id"],
                    "intake_point_ref": h["intake_point_ref"],
                    "target_cell_zones": list(h["target_cell_zones"]),
                    "status": h_status,
                    "dispatchable": h_verified,
                }
            )
            handoffs_full.append(
                {
                    **h,
                    "vehicle_stop_resolved": stop_resolved,
                    "status": h_status,
                    "dispatchable": h_verified,
                }
            )
        else:
            exit_id = exit_place or h.get("vehicle_exit_stop_id")
            exit_stop = port_stop_by_id.get(exit_id) if exit_id else None
            zone_ok = zone_status_by_id.get(h["cell_zone_id"]) == "verified"
            h_verified = bool(
                stop_resolved
                and v_stop is not None
                and v_stop["status"] == "verified"
                and v_stop["dispatchable"]
                and exit_stop is not None
                and exit_stop["status"] == "verified"
                and exit_stop["dispatchable"]
                and exit_stop["port_role"] == "outbound_exit"
                and zone_ok
            )
            h_status = "verified" if h_verified else "planned_unverified"
            outbound_handoffs_port.append(
                {
                    "handoff_id": h["id"],
                    "cell_zone_id": h["cell_zone_id"],
                    "wire_slot_ref": h["wire_slot_ref"],
                    "vehicle_pickup_stop_id": h["vehicle_stop_id"],
                    "vehicle_exit_stop_id": exit_id,
                    "status": h_status,
                    "dispatchable": h_verified,
                }
            )
            handoffs_full.append(
                {
                    **h,
                    "vehicle_exit_stop_id": exit_id,
                    "vehicle_stop_resolved": stop_resolved,
                    "exit_stop_resolved": bool(exit_id and exit_id in active_by_id),
                    "status": h_status,
                    "dispatchable": h_verified,
                }
            )

    if view == "port":
        return _with_digest(
            {
                "schema": SCHEMA_PORT,
                "sources": sources,
                "vehicle_places": vehicle_places_port,
                "cell_zones": cell_zones_port,
                "intake_handoffs": intake_handoffs_port,
                "outbound_handoffs": outbound_handoffs_port,
                "not_places": not_place_ids,
            }
        )

    return _with_digest(
        {
            "schema": SCHEMA_FULL,
            "sources": sources,
            "vehicle_stops": vehicle_stops,
            "arm_zones": cell_sites,
            "handoffs": handoffs_full,
            "legacy_aliases": dict(legacy_station_zones or {}),
        }
    )
