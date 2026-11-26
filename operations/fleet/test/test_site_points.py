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
    "arm_fk", "arms", "physical", "item", "aliases", "legacy_aliases", "slots", "hold_boundary",
    "berth", "nav2_berth_ready", "berth_missing", "repark_cap_m", "align_tol_deg",
    "intake_cell", "flow", "waypoints", "stand_ref", "zone_rules",
    "coordinate_frames", "conveyor_transfer", "end_to_end_stages", "arm_frame", "belt_end",
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
    arm_zones = {zone["id"]: zone for zone in full["arm_zones"]["zones"]}
    assert {key: len(zone["slots"]) for key, zone in arm_zones.items()} == {
        "yard": 6, "temp_a": 3, "temp_b": 3, "stand": 1,
    }
    yard = arm_zones["yard"]
    assert yard["hold_boundary"] == {"columns": [3, 4]}
    assert yard["slots"][0]["columns"] == [1, 3]
    assert yard["slots"][0]["tiers"][0] == {"id": "yard:r1-s1-t1", "tier": 1}
    assert all(slot["status"] == "planned_unverified"
               for zone in arm_zones.values() for slot in zone["slots"])
    handoffs = {h["id"]: h for h in full["handoffs"]}
    assert handoffs["outbound_stand_load"]["vehicle_stop_resolved"] is False
    assert handoffs["outbound_stand_load"]["dispatchable"] is False
    assert by_id["S3"]["dispatchable"] is True
    assert by_id["S3"]["berth"]["mode"] == "nav2_named_stop"
    assert by_id["S3"]["berth"]["nav2_berth_ready"] is False
    assert by_id["S3"]["berth"]["missing"] == ["stop_zone", "approach_m"]
    assert by_id["S3"]["berth"]["repark_cap_m"] == {"forward_m": 0.1, "left_m": 0.06}
    assert by_id["S3"]["berth"]["align_tol_deg"] == 3.0
    assert by_id["C1"]["berth"]["mode"] == "camera_pink_line"
    assert by_id["C1"]["berth"]["adr"] == "D-1013"
    assert by_id["S_OUT"]["berth"]["nav2_berth_ready"] is False
    assert handoffs["s3_cell_s_unload"]["intake_cell"]["cell_id"] == "cell_s"
    assert handoffs["s3_cell_s_unload"]["nav2_berth_ready"] is False
    assert handoffs["s3_cell_s_unload"]["arm_frame"] == "cell_s_arm_base"
    assert handoffs["s3_cell_s_unload"]["belt_end"] == "belt-in"
    assert handoffs["s3_cell_s_unload"]["waypoints"] == {"approach": "S3:approach_pose", "stop": "S3", "exit_edge": "upper_east"}
    assert handoffs["outbound_stand_load"]["nav2_berth_ready"] is False
    assert handoffs["outbound_stand_load"]["arm_frame"] == "cell_ab_fixture"
    assert handoffs["outbound_stand_load"]["stand_ref"] == "stand:r1-s1-t1"
    assert handoffs["outbound_stand_load"]["waypoints"]["branch_node"] == "J_stand"

    cf = full["coordinate_frames"]
    assert cf["vehicle_world"]["unit"] == "m"
    assert cf["vehicle_world"]["waypoints"]["S1_pickup"]["dual_role_exit_place"] is True
    assert cf["cell_s_arm_base"]["unit"] == "mm" and cf["cell_s_arm_base"]["belt_in"]["safe_x_min_mm"] == 134.0
    assert cf["cell_s_arm_base"]["vehicle_tray"]["xyz_mm"] == [53.5, 172.0, 20.0]
    assert cf["cell_ab_fixture"]["unit"] == "mm" and cf["cell_ab_fixture"]["belt_out"]["stop_x_mm"] == 158.0
    assert cf["cell_ab_fixture"]["stand"]["xyz_mm"] == [214.0, -168.25, 97.1]

    ct = full["conveyor_transfer"]
    assert ct["in_point"]["ref"] == "belt-in" and ct["out_point"]["ref"] == "belt"
    assert ct["transport"]["motor_control"] == "none_manual_power_continuous"
    assert ct["handover_state_machine"]["wired_to_runtime"] is False
    assert ct["occupancy_gate"]["wired_to_runtime"] is False

    stages = full["end_to_end_stages"]
    assert [s["stage"] for s in stages] == [
        "stage_1_vehicle_pickup", "stage_2_cell_s_unload", "stage_3_conveyor_transit",
        "stage_4_cell_ab_store", "stage_5_rehandle_and_outbound", "stage_6_vehicle_outbound",
    ]
    assert stages[0]["runtime_status"] == "ready_dual_role_exit"
    assert stages[2]["runtime_status"] == "manual_power_unwired_gates"

    zr = full["zone_rules"]
    assert zr["layer_counts"] == {"t1": 13, "t2": 12, "t3": 12, "total": 37}
    assert zr["tier_height_mm"] == 32.4 and zr["tiers_per_stack"] == 3
    assert [(b["id"], b["columns"], b["count"]) for b in zr["nine_slot_blocks"]] == [
        ("yard:s1", [1, 3], 9), ("yard:s2", [4, 6], 9), ("temp_a", [1, 3], 9), ("temp_b", [1, 3], 9),
    ]
    assert zr["outbound_single"] == {
        "id": "stand:r1-s1-t1", "zone": "stand", "tier": 1, "count": 1, "role": "outbound", "arms": ["arm_a"],
    }
    rehandle = zr["temporary_rehandling"]
    assert rehandle["zones"] == ["temp_a", "temp_b"]
    assert rehandle["arm_owner"] == {"temp_a": ["arm_a"], "temp_b": ["arm_b"]}
    assert rehandle["long_term_storage_allowed"] is False
    assert rehandle["hold_when_full"] == "NO_LEGAL_TEMPORARY_BAY"

    # Updating S3 coordinates in the active map immediately reflects in site-points without editing any static config.
    _activate_map_and_rules(store, _base_v348_map(s3_x=0.761), rules)
    updated = client.get("/api/fleet/site-points?include_junctions=true", headers=VIEWER).json()
    updated_by_id = {p["id"]: p for p in updated["vehicle_stops"]}
    assert updated_by_id["S3"]["pose"]["x"] == 0.761
    assert updated["coordinate_frames"]["vehicle_world"]["waypoints"]["S3_intake"]["pose"]["x"] == 0.761
    assert updated["coordinate_frames"]["vehicle_world"]["top_camera_vs_world_deg"] == 180
    assert updated["coordinate_frames"]["cell_s_arm_base"]["rotation_deg_vs_world"] == 180
    assert updated["coordinate_frames"]["cell_s_arm_base"]["vehicle_tray_model_x_residual_cm"] == 12.85
    assert updated["coordinate_frames"]["cell_ab_fixture"]["rotation_deg_vs_world"] == -90
    assert updated["coordinate_frames"]["cell_ab_fixture"]["hold_mapping"] == {"s1": "ship-h2", "s2": "ship-h1"}
    assert updated["conveyor_transfer"]["occupancy_gate"]["arm_ab_occlusion_table_wired"] is False
    assert "J_in" in updated_by_id and "J_out" in updated_by_id
    assert updated_by_id["J_in"]["berth"] is None

    # Adding stop_zone and approach_m to S3 makes S3 and intake handoff Nav2-berth ready.
    berth_map = _base_v348_map(s3_x=0.745)
    for place in berth_map["places"]:
        if place["id"] == "S3":
            place["stop_zone"] = [[0.65, -0.27], [0.84, -0.27], [0.84, -0.14], [0.65, -0.14]]
            place["approach_m"] = 0.18
    _activate_map_and_rules(store, berth_map, rules)
    ready_full = client.get("/api/fleet/site-points", headers=VIEWER).json()
    ready_s3 = next(p for p in ready_full["vehicle_stops"] if p["id"] == "S3")
    assert ready_s3["berth"]["nav2_berth_ready"] is True
    assert ready_s3["berth"]["missing"] == []
    assert ready_s3["berth"]["approach_pose"] == pytest.approx({"x": 0.925, "y": -0.207, "yaw": 3.14159}, abs=1e-5)
    ready_intake = next(h for h in ready_full["handoffs"] if h["id"] == "s3_cell_s_unload")
    assert ready_intake["nav2_berth_ready"] is True and ready_intake["berth_missing"] == []

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
        {"id": "J_stand", "kind": "junction", "name": "반출 분기", "x": 0.615, "y": -0.207},
        {
            "id": "S_OUT",
            "kind": "stop",
            "name": "S_OUT 반출대",
            "x": 0.614,
            "y": 0.001,
            "yaw": 1.570796,
            "pinned": True,
            "stop_zone": [[0.55, -0.06], [0.68, -0.06], [0.68, 0.06], [0.55, 0.06]],
            "approach_m": 0.10,
        },
        {"id": "S_EXIT", "kind": "stop", "name": "반출 전용 출구", "x": -0.80, "y": -0.48, "yaw": 0.0, "pinned": True},
    ])
    raw_map["edges"] = [e for e in raw_map["edges"] if e["id"] != "upper_east"] + [
        {"id": "upper_east_a", "from": "S3", "to": "J_stand", "polyline": [[0.745, -0.207], [0.615, -0.207]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "upper_east_b", "from": "J_stand", "to": "J_in", "polyline": [[0.615, -0.207], [0.32, -0.25]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "stand_spur", "from": "J_stand", "to": "S_OUT", "polyline": [[0.615, -0.207], [0.615, -0.103], [0.614, 0.001]], "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.08, "pinned": True},
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
    assert s_out["edges_in"] == ["stand_spur"] and s_out["edges_out"] == ["stand_spur"]
    assert s_out["approach_pose"] == pytest.approx({"x": 0.614, "y": -0.099, "yaw": 1.570796}, abs=1e-4)
    assert s_out["berth"]["mode"] == "nav2_named_stop"
    assert s_out["berth"]["nav2_berth_ready"] is True
    assert s_out["berth"]["missing"] == []

    s3_handoff = next(h for h in full["handoffs"] if h["id"] == "s3_cell_s_unload")
    assert s3_handoff["waypoints"]["exit_edge"] == "upper_east_a"
    handoff = next(h for h in full["handoffs"] if h["id"] == "outbound_stand_load")
    assert handoff["vehicle_stop_resolved"] is True and handoff["exit_stop_resolved"] is True
    assert handoff["vehicle_exit_stop_id"] == "S_EXIT"
    assert handoff["nav2_berth_ready"] is True and handoff["berth_missing"] == []
    assert handoff["waypoints"] == {
        "branch_edge": "upper_east",
        "branch_node": "J_stand",
        "approach": "S_OUT:approach_pose",
        "stop": "S_OUT",
        "exit_stop": "S_EXIT",
    }
    assert full["end_to_end_stages"][0]["runtime_status"] == "ready"
    assert full["end_to_end_stages"][5]["runtime_status"] == "ready" and full["end_to_end_stages"][5]["to"] == "S_EXIT"

    port = client.get("/api/fleet/site-points?view=port", headers=VIEWER).json()
    assert not ({val for kind, val in _walk_values(port) if kind == "key"} & FORBIDDEN_PORT_KEYS)
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


def test_site_points_accepts_raw_unsorted_site_rules_body_hash(tmp_path):
    client, store = _client_and_store(tmp_path)
    _activate_map_and_rules(store, _base_v348_map(), {"return": {"exit_place": "S1"}, "stops": [{"place": "S3", "role": "unload"}]})
    raw_body = '{"stops": [{"place": "S3", "role": "unload"}], "return": {"exit_place": "S1"}}'
    raw_sha = sha256(raw_body.encode("utf-8")).hexdigest()
    with sqlite3.connect(store.path) as con:
        con.execute(
            "UPDATE site_rules_versions SET body=?, sha256=? WHERE version=(SELECT MAX(version) FROM site_rules_versions)",
            (raw_body, raw_sha),
        )
        con.commit()
    ok = client.get("/api/fleet/site-points?view=port", headers=VIEWER)
    assert ok.status_code == 200
    assert client.get("/api/fleet/site-rules/active", headers=VIEWER).status_code == 200

    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE site_rules_versions SET sha256='0' WHERE version=(SELECT MAX(version) FROM site_rules_versions)")
        con.commit()
    bad = client.get("/api/fleet/site-points?view=port", headers=VIEWER)
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "SITE_RULES_BODY_HASH_MISMATCH"
    bad_rules = client.get("/api/fleet/site-rules/active", headers=VIEWER)
    assert bad_rules.status_code == 422
    assert bad_rules.json()["detail"]["code"] == "SITE_RULES_BODY_HASH_MISMATCH"


def test_site_points_requires_edges_in_for_outbound_exit_stop(tmp_path):
    client, store = _client_and_store(tmp_path)
    raw_map = _base_v348_map()
    raw_map["places"].extend([
        {"id": "J_stand", "kind": "junction", "name": "반출 분기", "x": 0.615, "y": -0.207},
        {
            "id": "S_OUT", "kind": "stop", "name": "S_OUT 반출대", "x": 0.614, "y": 0.001, "yaw": 1.570796,
            "pinned": True, "stop_zone": [[0.55, -0.06], [0.68, -0.06], [0.68, 0.06], [0.55, 0.06]],
            "approach_m": 0.10,
        },
        {"id": "S_EXIT", "kind": "stop", "name": "고립 반출 출구", "x": -0.80, "y": -0.48, "yaw": 0.0, "pinned": True},
    ])
    raw_map["edges"] = [e for e in raw_map["edges"] if e["id"] != "upper_east"] + [
        {"id": "upper_east_a", "from": "S3", "to": "J_stand", "polyline": [[0.745, -0.207], [0.615, -0.207]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "upper_east_b", "from": "J_stand", "to": "J_in", "polyline": [[0.615, -0.207], [0.32, -0.25]], "direction": "one_way", "width_m": 0.2, "speed_cap_mps": 0.15, "pinned": True},
        {"id": "stand_spur", "from": "J_stand", "to": "S_OUT", "polyline": [[0.615, -0.207], [0.615, -0.103], [0.614, 0.001]], "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.08, "pinned": True},
    ]
    raw_rules = {
        "return": {"exit_place": "S_EXIT"},
        "stops": [
            {"place": "S1", "role": "load"},
            {"place": "S3", "role": "unload"},
            {"place": "S_OUT", "role": "load"},
        ],
    }
    _activate_map_and_rules(store, raw_map, raw_rules)
    port = client.get("/api/fleet/site-points?view=port", headers=VIEWER).json()
    port_places = {p["place_id"]: p for p in port["vehicle_places"]}
    assert port_places["S_OUT"]["dispatchable"] is True
    assert port_places["S_EXIT"]["port_role"] == "outbound_exit"
    assert port_places["S_EXIT"]["status"] == "planned_unverified"
    assert port_places["S_EXIT"]["dispatchable"] is False
    assert port["outbound_handoffs"][0]["status"] == "planned_unverified"
    assert port["outbound_handoffs"][0]["dispatchable"] is False
