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
    assert micro_resp["decision"]["schema"] == "rosy.omx-cell-decision.v1"

    dec_arm = client.post(
        "/api/fleet/pipeline/decision-gate",
        json={"subject_id": "cell_s", "domain": "arm_target", "displaced_to": "floor_front", "auto_execute": True},
    ).json()
    assert dec_arm["ok"] is True
    assert dec_arm["decision"]["choice"] == "object_reacquire"
    assert dec_arm["executed"]["task"]["displaced_to"] == "floor_front"

    dec_pinky = client.post(
        "/api/fleet/pipeline/decision-gate",
        json={"subject_id": "rosy_46", "domain": "line_follow", "tangled": True, "auto_execute": True},
    ).json()
    assert dec_pinky["ok"] is True
    assert dec_pinky["decision"]["choice"] == "back_and_retry"
    assert dec_pinky["decision"]["recommended_action"] == "micro_forward_2cm"
    assert dec_pinky["executed"]["pinky_task"]["max_step_m"] <= 0.02

    # Human safety E-Stop -> pause queued tasks -> block claim -> human clears -> auto-resume
    estop_on = client.post(
        "/api/fleet/pipeline/human-safety-gate",
        json={"cell_id": "cell_s", "human_detected": True, "robot_id": "rosy_46"},
    ).json()
    assert estop_on["ok"] is True and estop_on["active_estop"] is True
    assert len(estop_on["paused_tasks"]) >= 1
    assert estop_on["pinky_estop"]["v_cmd_mps"] == 0.0

    blocked_claim = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()
    assert blocked_claim["claimed"] is False and blocked_claim["blocked_by_human"] is True

    estop_off = client.post(
        "/api/fleet/pipeline/human-safety-gate",
        json={"cell_id": "cell_s", "human_detected": False, "robot_id": "rosy_46"},
    ).json()
    assert estop_off["ok"] is True and estop_off["active_estop"] is False
    assert set(estop_off["resumed_tasks"]) == set(estop_on["paused_tasks"])

    # YAML station zones (staging_bays + export_stations) & immediate dispatch
    zones = client.get("/api/fleet/pipeline/station-zones").json()
    assert zones["ok"] is True and zones["schema"] == "rosy.station-zones.v1"
    assert any(z["id"] == "STG_C2" for z in zones["staging_bays"])
    assert any(z["id"] == "EXP_S5_PALLET" for z in zones["export_stations"])

    stg_disp = client.post(
        "/api/fleet/pipeline/station-zones/dispatch",
        json={"zone_id": "STG_C2", "robot_id": "rosy_46"},
    ).json()
    assert stg_disp["ok"] is True and stg_disp["zone"]["kind"] == "staging"
    assert stg_disp["pinky_task"]["max_step_m"] <= 0.02

    exp_disp = client.post(
        "/api/fleet/pipeline/station-zones/dispatch",
        json={"zone_id": "EXP_S5_PALLET", "robot_id": "rosy_46"},
    ).json()
    assert exp_disp["ok"] is True and exp_disp["zone"]["kind"] == "export"
    assert exp_disp["spawned_cell_task"]["cell_id"] == "cell_ab"
    assert exp_disp["spawned_cell_task"]["arm_id"] == "arm_b"

    # Cable guard one-click toggle + restore
    cg_off = client.post("/api/fleet/pipeline/cable-guard", json={"cable_tangled": False}).json()
    assert cg_off["ok"] is True and cg_off["cable_tangled"] is False
    cg_on = client.post("/api/fleet/pipeline/cable-guard", json={"toggle": True}).json()
    assert cg_on["ok"] is True and cg_on["cable_tangled"] is True

    # Vision auto-check: intrusion_score >= 0.35 triggers HUMAN_HOLD & pauses tasks; < 0.35 clears & auto-resumes
    vis_intrude = client.post(
        "/api/fleet/pipeline/vision-auto-check",
        json={"cell_id": "cell_ab", "intrusion_score": 0.82, "displaced_to": "belt_far"},
    ).json()
    assert vis_intrude["ok"] is True
    assert vis_intrude["vision"]["human_detected"] is True
    assert vis_intrude["safety_event"]["active_estop"] is True
    assert len(vis_intrude["safety_event"]["paused_tasks"]) >= 1

    vis_clear = client.post(
        "/api/fleet/pipeline/vision-auto-check",
        json={"cell_id": "cell_ab", "intrusion_score": 0.04},
    ).json()
    assert vis_clear["ok"] is True
    assert vis_clear["vision"]["human_detected"] is False
    assert vis_clear["safety_event"]["active_estop"] is False
    assert set(vis_clear["safety_event"]["resumed_tasks"]) == set(vis_intrude["safety_event"]["paused_tasks"])

    cams = client.get("/api/fleet/pipeline/cameras").json()
    assert cams["ok"] is True and cams["count"] >= 7
    assert any(c["id"] == "arm_s_top" for c in cams["cameras"])
    assert any(c["id"] == "arm_a_wrist" for c in cams["cameras"])
    assert any(c["id"] == "arm_b_wrist" for c in cams["cameras"])

    q_res = client.post(
        "/api/fleet/pipeline/cell-quality",
        json={
            "schema": "rosy.pipeline.cell-quality.v1",
            "cameras": {
                "arm_s_top": {
                    "fresh": True,
                    "sequence": 148001,
                    "receipt_age_s": 0.02,
                    "quality": {"condition": "NORMAL", "mean_intensity": 112.4, "spatial_contrast": 106.8, "usable": True},
                }
            },
            "arm_holds": {
                "arm_b": {"local_held": True, "local_reason": "alignment deadline exceeded", "incident_ids": ["inc-01"]}
            },
        },
    ).json()
    assert q_res["ok"] is True and q_res["arm_holds"]["arm_b"]["held"] is True

    cams_after = client.get("/api/fleet/pipeline/cameras").json()
    arm_s_cam = next(c for c in cams_after["cameras"] if c["id"] == "arm_s_top")
    assert arm_s_cam["sequence"] == 148001 and arm_s_cam["mean_intensity"] == 112.4

    clr = client.post(
        "/api/fleet/pipeline/arm-holds/clear",
        json={"arm_id": "cell_ab", "note": "verified folded home on camera"},
    ).json()
    assert clr["ok"] is True and clr["arm_holds"]["arm_b"]["held"] is False









