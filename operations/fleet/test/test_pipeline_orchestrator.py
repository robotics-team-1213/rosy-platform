from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.pipeline import evaluate_fleet_pipeline
from fleet.server.pipeline_routes import install_pipeline_routes
from fleet.server.charge_bay_routes import install_charge_bay_routes
from fleet.site_map import SiteMap
from fleet.routing.graph import build_graph
from fleet.charge_bays import ChargeBays, bays_from_map


def _map():
    return SiteMap(map_id="pipeline-test", places=[
        {"id": "C1", "name": "C1", "x": 0, "y": 0, "kind": "charge"},
        {"id": "C2", "name": "C2", "x": 1, "y": 0, "kind": "charge"},
        {"id": "C3", "name": "C3", "x": 2, "y": 0, "kind": "charge"},
        {"id": "S1", "name": "S1", "x": 3, "y": 0, "kind": "junction"},
    ], edges=[
        {"id": f"e{i}", "from": p1, "to": p2, "direction": "two_way",
         "width_m": 0.5, "speed_cap_mps": 0.15, "polyline": [[i-1, 0], [i, 0]]}
        for i, (p1, p2) in enumerate((("C1", "C2"), ("C2", "C3"), ("C3", "S1")), 1)
    ])


def test_orchestrator_builds_three_layers_for_three_pinkies():
    site_map = _map()
    graph = build_graph(site_map)
    robots = [SimpleNamespace(robot_id=f"pinky_{i}", kind="pinky", online=True,
                              pose=(i - 1, 0), yaw=0.0) for i in range(1, 4)]
    result = evaluate_fleet_pipeline(site_map, graph, robots, bays_from_map(site_map), charge_bays=ChargeBays())
    assert result["general_layer"]["map_version"] == graph.version
    assert result["site_layer"]
    assert [r["robot_id"] for r in result["robot_layer"]["robots"]] == [r.robot_id for r in robots]
    assert all(r["robot_kind"] == "pinky" for r in result["robot_layer"]["robots"])


def test_omx_cell_interlocks_docked_robot():
    site_map = _map()
    graph = build_graph(site_map)
    robot = SimpleNamespace(robot_id="pinky_1", kind="pinky", online=True,
                            pose=(0.68, -0.2528), yaw=0.0)
    result = evaluate_fleet_pipeline(site_map, graph, [robot], bays_from_map(site_map),
                                     cell_states={"cell_s": {"robot_id": "pinky_1",
                                                             "phase": "ARM_IN_BED_ZONE"}})
    cell = result["omx_cell_layer"]["cells"]["cell_s"]
    entry = result["robot_layer"]["robots"][0]
    assert cell["gate"]["amr_motion_inhibited"] is True
    assert result["contract_layer"]["boundary_check"]["valid"] is True
    assert entry["road_command"]["v_cmd_mps"] == 0.0
    assert entry["road_command"]["blocked_by_cell"] is True


def test_pipeline_http_status_and_evaluate():
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.bay_inputs = lambda: (None, [SimpleNamespace(robot_id=f"pinky_{i}", kind="pinky", online=True,
                                       pose=(i - 1, 0), yaw=0.0) for i in range(1, 4)], bays_from_map(site_map))
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)
    status = client.get("/api/fleet/pipeline/status")
    assert status.status_code == 200 and len(status.json()["robot_layer"]["robots"]) == 3
    evaluated = client.post("/api/fleet/pipeline/evaluate", json={"robots": [
        {"robot_id": f"pinky_{i}", "x": i - 1, "y": 0, "kind": "pinky", "percent": 10}
        for i in range(1, 4)
    ]})
    assert evaluated.status_code == 200 and evaluated.json()["dispatch"] is False
    assert len(evaluated.json()["robot_layer"]["robots"]) == 3
    contract = client.get("/api/fleet/pipeline/contract")
    assert contract.status_code == 200 and "cell_s" in contract.json()["omx_cells"]
    handoff = client.post("/api/fleet/pipeline/cell-handoff", json={
        "cell_id": "cell_s", "robot_id": "pinky_1", "robot_kind": "pinky",
        "phase": "CLAIMED", "x": 0.68, "y": -0.2528, "yaw": 0.0,
        "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "tier": 1})
    assert handoff.status_code == 200 and handoff.json()["gate"]["amr_motion_inhibited"] is True


def test_cell_handoff_persists_state_across_status_and_charge_bays(tmp_path):
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps

    async def gathered():
        return {"robots": []}

    install_charge_bay_routes(app, SimpleNamespace(_clock=lambda: 0.0), gathered, ())
    client = TestClient(app)
    body = {"cell_id": "cell_s", "robot_id": "pinky_1", "robot_kind": "pinky",
            "phase": "ARM_IN_BED_ZONE", "x": 0.68, "y": -0.2528, "yaw": 0.0,
            "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
            "tier": 1, "stage_id": "stage-1", "goal_evidence_digest": "digest-1"}
    assert client.post("/api/fleet/pipeline/cell-handoff", json=body).status_code == 200

    status = client.get("/api/fleet/pipeline/status").json()
    assert status["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True
    robot = next(r for r in status["robot_layer"]["robots"] if r["robot_id"] == "pinky_1")
    assert robot["road_command"]["blocked_by_cell"] is True
    evaluated = client.post("/api/fleet/pipeline/evaluate", json={"robots": [
        {"robot_id": "pinky_1", "kind": "pinky", "x": 0.68, "y": -0.2528, "yaw": 0.0}
    ]}).json()
    assert evaluated["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True
    assert evaluated["robot_layer"]["robots"][0]["road_command"]["blocked_by_cell"] is True
    bays = client.get("/api/fleet/charge-bays").json()
    assert bays["omx_cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True
    assert next(a for a in bays["actions"] if a["robot_id"] == "pinky_1")["blocked_by_cell"] is True

    body["phase"] = "RELEASED"
    assert client.post("/api/fleet/pipeline/cell-handoff", json=body).status_code == 200
    status = client.get("/api/fleet/pipeline/status").json()
    assert status["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is False
    bays = client.get("/api/fleet/charge-bays").json()
    assert bays["omx_cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is False
    assert not any(a.get("blocked_by_cell") for a in bays["actions"])


def test_cell_tasks_assign_claim_and_complete_lifecycle():
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    created = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "fleet-r-cell-s-01",
        "cell_id": "cell_s",
        "arm_id": "arm_s",
        "robot_id": "pinky_1",
        "src_site": "pinky",
        "dst_site": "belt",
        "displaced_to": "belt_far",
        "tier": 1,
    })
    assert created.status_code == 200 and created.json()["task"]["status"] == "QUEUED"

    listed = client.get("/api/fleet/pipeline/cell-tasks", params={"cell_id": "cell_s", "status": "QUEUED"}).json()
    assert len(listed["tasks"]) == 1 and listed["tasks"][0]["task_id"] == "fleet-r-cell-s-01"

    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()
    assert claimed["claimed"] is True and claimed["gate"]["amr_motion_inhibited"] is True
    assert claimed["handoff"]["displaced_to"] == "belt_far"

    done = client.post("/api/fleet/pipeline/cell-tasks/fleet-r-cell-s-01/complete", json={
        "phase": "RELEASED",
        "goal_evidence_digest": "sha256:1234567890abcdef",
        "reason": "TRANSFER_CONFIRMED",
        "hardware_telemetry": {"folded": True, "final_state": [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]},
    }).json()
    assert done["ok"] is True and done["task"]["status"] == "COMPLETED"
    assert done["gate"]["amr_motion_inhibited"] is False
    assert done["task"]["hardware_telemetry"]["folded"] is True

    chained = client.post("/api/fleet/pipeline/cell-tasks", json={"preset": "full_s3_to_s5_pipeline", "task_id": "chain-01"}).json()
    assert chained["ok"] is True and len(chained["tasks"]) == 3
    assert [t["arm_id"] for t in chained["tasks"]] == ["arm_s", "arm_a", "arm_b"]

    cancelled = client.post(f"/api/fleet/pipeline/cell-tasks/{chained['tasks'][0]['task_id']}/cancel").json()
    assert cancelled["ok"] is True and cancelled["task"]["status"] == "CANCELLED"
    assert cancelled["gate"]["amr_motion_inhibited"] is False

    overview = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert overview["summary"]["total"] == 4
    assert overview["summary"]["completed"] == 1
    assert "cell_s" in overview["cells"] and "cell_ab" in overview["cells"]
    assert len(overview["presets"]) >= 7

    pinky_resp = client.post("/api/fleet/pipeline/pinky-tasks", json={"robot_id": "rosy_42", "action": "dock_and_unload_s3"}).json()
    assert pinky_resp["ok"] is True
    assert pinky_resp["pinky_task"]["target_place"] == "S3"
    assert pinky_resp["spawned_cell_task"]["cell_id"] == "cell_s"

    cam_resp = client.get("/api/fleet/pipeline/cell-camera/cell_s")
    assert cam_resp.status_code == 200 and (
        "svg" in cam_resp.headers["content-type"] or "jpeg" in cam_resp.headers["content-type"]
    )

    retried = client.post(f"/api/fleet/pipeline/cell-tasks/{chained['tasks'][0]['task_id']}/retry").json()
    assert retried["ok"] is True and retried["task"]["status"] == "QUEUED"

    det = client.post("/api/fleet/pipeline/displaced-detection", json={"displaced_to": "floor_front"}).json()
    assert det["ok"] is True and det["detected_displaced_site"] == "floor_front"
    auto_t = client.post("/api/fleet/pipeline/cell-tasks", json={"preset": "s3_auto_recover_or_shuttle"}).json()
    assert auto_t["task"]["displaced_to"] == "floor_front" and auto_t["task"]["auto_recovered"] is True

    micro_resp = client.post(
        "/api/fleet/pipeline/pinky-tasks",
        json={"robot_id": "rosy_46", "action": "micro_forward_2cm", "cable_guard_micro": True},
    ).json()
    assert micro_resp["ok"] is True
    assert micro_resp["pinky_task"]["max_step_m"] <= 0.02
    assert abs(micro_resp["pinky_task"]["v_cmd_mps"]) <= 0.02




