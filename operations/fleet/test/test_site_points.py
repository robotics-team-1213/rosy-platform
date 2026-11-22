"""Tests for GET /api/fleet/site-points unified vehicle-stop, handoff and cell-zone read model."""

from __future__ import annotations

from hashlib import sha256
import sqlite3

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.site_rules import SiteRules
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}

FORBIDDEN_PORT_KEYS = frozenset({
    "x", "y", "yaw", "pose", "edges", "edges_in", "edges_out", "polyline",
    "stop_zone", "approach_m", "approach_pose", "pinned", "width_m", "speed_cap_mps",
    "turn_bans", "drive_mode", "junction", "workcell_id", "instance_id", "marker_id",
    "arm_fk", "arms", "physical", "item", "aliases", "legacy_aliases",
})


def _client_and_store(tmp_path):
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    users = {
        sha256(b"operator-token").hexdigest(): {"principal_id": "op", "role": "operator"},
        sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"},
    }
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store)), store


def _base_v348_map(*, s3_x: float = 0.745) -> dict:
    return {
        "schema": "rosy.site_map/1",
        "map_id": "world_261026",
        "places": [
            {"id": "S1", "kind": "stop", "name": "S1 출구", "x": -0.68, "y": -0.13, "yaw": -1.5708},
            {"id": "S3", "kind": "stop", "name": "S3 상단 하역", "x": s3_x, "y": -0.207, "yaw": 3.14159, "pinned": True},
            {"id": "S4", "kind": "stop", "name": "S4 중앙 대기", "x": 0.16, "y": -0.475, "yaw": 0.0},
            {"id": "S5", "kind": "stop", "name": "S5 U턴 전", "x": 0.91, "y": -0.48, "yaw": 0.0},
            {"id": "J_in", "kind": "junction", "name": "입구 분기", "x": 0.32, "y": -0.25},
            {"id": "J_out", "kind": "junction", "name": "출구 합류", "x": -0.68, "y": -0.25},
            {"id": "C1", "kind": "charge", "name": "충전 1", "x": -0.42, "y": 0.47, "yaw": -1.5708, "pinned": True},
        ],
        "edges": [
            {"id": "lower_east", "from": "S4", "to": "S5", "polyline": [[0.16, -0.475], [0.91, -0.48]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15},
            {"id": "loop_right", "from": "S5", "to": "S3", "polyline": [[0.91, -0.48], [s3_x, -0.207]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
            {"id": "upper_east", "from": "S3", "to": "J_in", "polyline": [[s3_x, -0.207], [0.32, -0.25]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
            {"id": "upper_west", "from": "J_in", "to": "J_out", "polyline": [[0.32, -0.25], [-0.68, -0.25]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15},
            {"id": "loop_left", "from": "J_out", "to": "S4", "polyline": [[-0.68, -0.25], [0.16, -0.475]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15},
            {"id": "bay_1", "from": "J_out", "to": "C1", "polyline": [[-0.68, -0.25], [-0.42, 0.47]], "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05},
        ],
    }


def _activate_map_and_rules(store: SiteMapStore, raw_map: dict, raw_rules: dict):
    sm = SiteMap.model_validate(raw_map)
    draft = store.save_draft(sm, expected_revision=store.draft_view()["revision"], principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    sr = SiteRules.model_validate(raw_rules)
    rdraft = store.rules.save_draft(sr, expected_revision=store.rules.draft_view()["revision"], principal_id="op")
    store.rules.activate(expected_revision=rdraft["revision"], principal_id="op", route_active=False)


def _walk_values(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield ("key", k)
            yield from _walk_values(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_values(item)
    elif isinstance(node, str):
        yield ("str", node)


def test_site_points_auth_missing_and_hash_guard(tmp_path):
    client, store = _client_and_store(tmp_path)
    assert client.get("/api/fleet/site-points").status_code == 401
    assert client.get("/api/fleet/site-points", headers=VIEWER).status_code == 404

    _activate_map_and_rules(store, _base_v348_map(), {"return": {"exit_place": "S1"}, "stops": [{"place": "S3", "role": "unload"}]})
    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE site_map_versions SET sha256='0' WHERE version=(SELECT MAX(version) FROM site_map_versions)")
        con.commit()
    assert client.get("/api/fleet/site-points", headers=VIEWER).status_code == 422


def test_site_points_full_and_port_views_stage_a_fail_closed(tmp_path):
    client, store = _client_and_store(tmp_path)
    rules = {
        "return": {"exit_place": "S1"},
        "stops": [
            {"place": "S1", "role": "load"},
            {"place": "S3", "role": "unload"},
            {"place": "S4", "role": "wait"},
            {"place": "S5", "role": "wait"},
        ],
    }
    _activate_map_and_rules(store, _base_v348_map(s3_x=0.745), rules)

    full = client.get("/api/fleet/site-points", headers=VIEWER).json()
    assert full["schema"] == "rosy.site-points.v1"
    by_id = {p["id"]: p for p in full["vehicle_stops"]}
    assert "J_in" not in by_id and "J_out" not in by_id
    assert by_id["S3"]["pinned"] is True and by_id["S3"]["pose"]["x"] == 0.745
    assert by_id["S_OUT"]["in_active_map"] is False
    assert by_id["S_OUT"]["pose"] is None
    assert by_id["S_OUT"]["status"] == "planned_unverified"
    assert by_id["S_OUT"]["dispatchable"] is False
    assert full["arm_zones"]["count"] == 37
    handoffs = {h["id"]: h for h in full["handoffs"]}
    assert handoffs["outbound_stand_load"]["vehicle_stop_resolved"] is False
    assert handoffs["outbound_stand_load"]["dispatchable"] is False

    # Updating S3 coordinates in the active map immediately reflects in site-points without editing any static config.
    _activate_map_and_rules(store, _base_v348_map(s3_x=0.761), rules)
    updated = client.get("/api/fleet/site-points?include_junctions=true", headers=VIEWER).json()
    updated_by_id = {p["id"]: p for p in updated["vehicle_stops"]}
    assert updated_by_id["S3"]["pose"]["x"] == 0.761
    assert "J_in" in updated_by_id and "J_out" in updated_by_id

    port = client.get("/api/fleet/site-points?view=port", headers=VIEWER).json()
    assert port["schema"] == "rosy.port-site-places.v1"
    seen_keys = {val for kind, val in _walk_values(port) if kind == "key"}
    seen_strs = {val for kind, val in _walk_values(port) if kind == "str"}
    assert not (seen_keys & FORBIDDEN_PORT_KEYS)
    assert not (seen_strs & {"EXP_S1", "J_in", "J_out", "ship-h2r0-l0", "010282"})
    port_places = {p["place_id"]: p for p in port["vehicle_places"]}
    assert port_places["S_OUT"]["status"] == "planned_unverified" and port_places["S_OUT"]["dispatchable"] is False
    assert port_places["C1"]["port_role"] == "charge" and port_places["C1"]["dispatchable"] is False
    assert port["outbound_handoffs"][0]["wire_slot_ref"] == "stand-r1-c1-l1"
    assert port["outbound_handoffs"][0]["status"] == "planned_unverified"


def test_site_points_stage_b_promotes_s_out_when_activated_with_split_edge_and_rules(tmp_path):
    client, store = _client_and_store(tmp_path)
    raw_map = _base_v348_map()
    raw_map["places"].extend([
        {
            "id": "S_OUT",
            "kind": "stop",
            "name": "S_OUT 반출대",
            "x": 0.54,
            "y": -0.478,
            "yaw": 0.0,
            "pinned": True,
            "stop_zone": [[0.45, -0.56], [0.63, -0.56], [0.63, -0.40], [0.45, -0.40]],
            "approach_m": 0.25,
        },
        {"id": "S_EXIT", "kind": "stop", "name": "반출 전용 출구", "x": -0.80, "y": -0.48, "yaw": 0.0, "pinned": True},
    ])
    raw_map["edges"] = [e for e in raw_map["edges"] if e["id"] != "lower_east"] + [
        {"id": "lower_east_a", "from": "S4", "to": "S_OUT", "polyline": [[0.16, -0.475], [0.54, -0.478]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "lower_east_b", "from": "S_OUT", "to": "S5", "polyline": [[0.54, -0.478], [0.91, -0.48]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "exit_edge", "from": "S_EXIT", "to": "S4", "polyline": [[-0.80, -0.48], [0.16, -0.475]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
    ]
    raw_rules = {
        "return": {"exit_place": "S_EXIT"},
        "stops": [
            {"place": "S1", "role": "load"},
            {"place": "S3", "role": "unload"},
            {"place": "S_OUT", "role": "load"},
            {"place": "S_EXIT", "role": "wait"},
        ],
    }
    _activate_map_and_rules(store, raw_map, raw_rules)

    full = client.get("/api/fleet/site-points", headers=VIEWER).json()
    s_out = next(p for p in full["vehicle_stops"] if p["id"] == "S_OUT")
    assert s_out["in_active_map"] is True
    assert s_out["status"] == "verified" and s_out["dispatchable"] is True
    assert s_out["edges_in"] == ["lower_east_a"] and s_out["edges_out"] == ["lower_east_b"]
    assert s_out["approach_pose"] == pytest.approx({"x": 0.29, "y": -0.478, "yaw": 0.0})

    handoff = next(h for h in full["handoffs"] if h["id"] == "outbound_stand_load")
    assert handoff["vehicle_stop_resolved"] is True and handoff["exit_stop_resolved"] is True
    assert handoff["vehicle_exit_stop_id"] == "S_EXIT"

    port = client.get("/api/fleet/site-points?view=port", headers=VIEWER).json()
    port_places = {p["place_id"]: p for p in port["vehicle_places"]}
    assert port_places["S_OUT"]["status"] == "verified" and port_places["S_OUT"]["dispatchable"] is True
    assert port_places["S_EXIT"]["port_role"] == "outbound_exit"


def test_site_points_stage_b_rejects_dangling_s_out_and_ambiguous_or_corrupt_rules(tmp_path):
    client, store = _client_and_store(tmp_path)
    # 1. Active map with NO rules activated yet stays 200 and Fail-Closed.
    sm = SiteMap.model_validate(_base_v348_map())
    draft = store.save_draft(sm, expected_revision=store.draft_view()["revision"], principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    no_rules = client.get("/api/fleet/site-points", headers=VIEWER)
    assert no_rules.status_code == 200
    assert no_rules.json()["sources"]["site_rules"] == {"version": None, "sha256": None}

    # 2. Dangling S_OUT (no incoming/outgoing edges) + conflicting rules stay planned_unverified / dispatchable=False.
    dangling_map = _base_v348_map()
    dangling_map["places"].append({
        "id": "S_OUT",
        "kind": "stop",
        "name": "S_OUT 미연결",
        "x": 0.54,
        "y": -0.478,
        "yaw": 0.0,
        "pinned": True,
        "stop_zone": [[0.45, -0.56], [0.63, -0.56], [0.63, -0.40], [0.45, -0.40]],
        "approach_m": 0.25,
    })
    ambiguous_rules = {
        "return": {"exit_place": "S1"},
        "stops": [
            {"place": "S_OUT", "role": "load"},
            {"place": "S_OUT", "role": "wait"},
            {"place": "S3", "role": "unload"},
        ],
    }
    _activate_map_and_rules(store, dangling_map, ambiguous_rules)
    full = client.get("/api/fleet/site-points", headers=VIEWER).json()
    s_out = next(p for p in full["vehicle_stops"] if p["id"] == "S_OUT")
    assert s_out["status"] == "planned_unverified"
    assert s_out["dispatchable"] is False

    # 3. Corrupted active site_rules sha256 returns HTTP 422 rather than 500.
    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE site_rules_versions SET sha256='0' WHERE version=(SELECT MAX(version) FROM site_rules_versions)")
        con.commit()
    assert client.get("/api/fleet/site-points", headers=VIEWER).status_code == 422
