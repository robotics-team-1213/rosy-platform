from types import SimpleNamespace
import hashlib
import json
import os
import stat
import time

from fastapi import Depends, FastAPI, HTTPException
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


def _measured_amr(task):
    return {"robot_id": task["robot_id"], "cell_id": task["cell_id"], "observed_at": time.time(),
            "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "pose": dict(task["pose"])}


def test_cell_ledger_write_failure_preserves_file_and_closes_claim(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)),
                                   amr_evidence_fn=_measured_amr)
    client = TestClient(app)
    original_fsync = routes.os.fsync
    synced = []

    def fsync(fd):
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        return original_fsync(fd)

    monkeypatch.setattr(routes.os, "fsync", fsync)
    first = client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "durable", "cell_id": "cell_s"})
    assert first.status_code == 200
    assert False in synced and (os.name != "posix" or True in synced)
    monkeypatch.setattr(routes.os, "fsync", original_fsync)
    ledger = tmp_path / "rosy-pipeline-ledger.json"
    saved = ledger.read_bytes()
    assert "durable" in json.loads(saved)["omx_cell_tasks"]

    original_replace = routes.os.replace
    monkeypatch.setattr(routes.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    failed = client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "not-durable", "cell_id": "cell_s"})
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "PIPELINE_LEDGER_UNAVAILABLE"
    assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is True
    monkeypatch.setattr(routes.os, "replace", original_replace)
    assert client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "later", "cell_id": "cell_s"}).status_code == 503
    claim = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"task_id": "durable", "cell_id": "cell_s"})
    assert claim.status_code == 503 and claim.json()["detail"]["code"] == "PIPELINE_LEDGER_UNAVAILABLE"
    release = client.post("/api/fleet/pipeline/cell-tasks/durable/complete", json={"phase": "RELEASED"})
    assert release.status_code == 503 and release.json()["detail"]["code"] == "PIPELINE_LEDGER_UNAVAILABLE"
    assert ledger.read_bytes() == saved


def test_invalid_cell_task_numbers_do_not_latch_or_change_ledger(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)),
                                   amr_evidence_fn=_measured_amr)
    client = TestClient(app)
    endpoint = "/api/fleet/pipeline/cell-tasks"
    assert client.post(endpoint, json={"task_id": "baseline", "cell_id": "cell_s"}).status_code == 200
    ledger = tmp_path / "rosy-pipeline-ledger.json"
    saved = ledger.read_bytes()

    invalid = [
        {"task_id": "bad-pose", "cell_id": "cell_s", "x": "NaN"},
        {"task_id": "bad-directive", "cell_id": "cell_s", "directive": {
            "schema": "rosy.omx-cell-area-xyz-directive.v1", "directive_id": "bad-directive",
            "arm_id": "arm_s", "nested": {"z": float("nan")},
        }},
    ]
    for spec in invalid:
        response = client.post(endpoint, content=json.dumps(spec), headers={"content-type": "application/json"})
        assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_CELL_TASK_INPUT"
        assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False
    for field in ("max_step_m", "max_speed_mps"):
        response = client.post("/api/fleet/pipeline/pinky-tasks", json={
            "task_id": f"bad-pinky-{field}", "action": "dock_s3", "cable_guard_micro": False,
            field: "NaN",
        })
        assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_PIPELINE_NUMBER"
        assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False
    overflow = client.post("/api/fleet/pipeline/pinky-tasks", json={
        "task_id": "bad-pinky-duration", "action": "dock_and_unload_s3", "cable_guard_micro": False,
        "max_step_m": 1e308,
    })
    assert overflow.status_code == 422 and overflow.json()["detail"]["code"] == "INVALID_PIPELINE_NUMBER"
    assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False
    handoff = client.post("/api/fleet/pipeline/cell-handoff", json={
        "cell_id": "cell_s", "robot_id": "rosy_01", "robot_kind": "pinky", "phase": "HUMAN_HOLD",
        "x": "NaN", "y": 0.0, "yaw": 0.0, "v_cmd_mps": 0.0,
    })
    assert handoff.status_code == 422 and handoff.json()["detail"]["code"] == "INVALID_PIPELINE_NUMBER"
    assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False
    assert client.post(endpoint, json={"task_id": "after-invalid", "cell_id": "cell_s"}).status_code == 200
    assert "after-invalid" in json.loads(ledger.read_bytes())["omx_cell_tasks"]
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": "baseline", "cell_id": "cell_s",
    }).json()["claimed"] is True
    saved = ledger.read_bytes()
    aborted = client.post("/api/fleet/pipeline/cell-tasks/baseline/complete", content=json.dumps({
        "phase": "ABORTED", "details": {"sensor": float("nan")},
    }), headers={"content-type": "application/json"})
    assert aborted.status_code == 422 and aborted.json()["detail"]["code"] == "INVALID_CELL_COMPLETION"
    assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False


def test_nonfinite_amr_evidence_cannot_claim_or_poison_ledger(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    fault = {"kind": "pose"}

    def evidence(task):
        observed = _measured_amr(task)
        if fault["kind"] == "pose":
            observed["pose"]["x"] = float("nan")
        elif fault["kind"] == "extra":
            observed["diagnostics"] = {"raw": float("nan")}
        return observed

    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)),
                                   amr_evidence_fn=evidence)
    client = TestClient(app)
    assert client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "amr-unsafe", "cell_id": "cell_s",
    }).status_code == 200
    ledger = tmp_path / "rosy-pipeline-ledger.json"
    saved = ledger.read_bytes()
    for kind in ("pose", "extra"):
        fault["kind"] = kind
        claim = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"task_id": "amr-unsafe", "cell_id": "cell_s"})
        assert claim.status_code == 200 and claim.json()["claimed"] is False
        assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False
    fault["kind"] = "none"
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": "amr-unsafe", "cell_id": "cell_s",
    }).json()["claimed"] is True


def test_nonfinite_station_zone_cannot_dispatch_or_poison_ledger(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)
    assert client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "zone-baseline", "cell_id": "cell_s",
    }).status_code == 200
    ledger = tmp_path / "rosy-pipeline-ledger.json"
    saved = ledger.read_bytes()
    invalid_yaml = "staging_bays:\n  - id: STG_C2\n    speed_cap_mps: -.inf\n    max_step_m: 0.015\nexport_stations: []\n"
    update = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": invalid_yaml})
    assert update.status_code == 422 and not (tmp_path / "station_zones.yaml").exists()
    for field in ("speed_cap_mps", "max_step_m"):
        malformed = invalid_yaml.replace("speed_cap_mps: -.inf", "speed_cap_mps: 0.02")
        malformed = malformed.replace(f"{field}: 0.02" if field == "speed_cap_mps" else f"{field}: 0.015",
                                      f"{field}: -.inf")
        (tmp_path / "station_zones.yaml").write_text(malformed, encoding="utf-8")
        dispatch = client.post("/api/fleet/pipeline/station-zones/dispatch", json={"zone_id": "STG_C2"})
        assert dispatch.status_code == 422 and dispatch.json()["detail"]["code"] == "INVALID_PIPELINE_NUMBER"
        assert ledger.read_bytes() == saved and app.state._pipeline_ledger_fault is False


def test_corrupt_cell_ledger_stays_held_until_reconciliation(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    ledger = tmp_path / "rosy-pipeline-ledger.json"
    ledger.write_text("{", encoding="utf-8")
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    assert app.state._pipeline_ledger_fault is True
    res = TestClient(app).post("/api/fleet/pipeline/cell-tasks", json={"task_id": "unknown", "cell_id": "cell_s"})
    assert res.status_code == 503 and ledger.read_text(encoding="utf-8") == "{"


def test_volatile_cell_ledger_directory_cannot_accept_tasks(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    real_path = routes.Path
    monkeypatch.setattr(routes, "Path", lambda value: tmp_path if value == "/tmp" else real_path(value))
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    assert app.state._pipeline_ledger_fault is True
    res = TestClient(app).post("/api/fleet/pipeline/cell-tasks", json={"task_id": "volatile", "cell_id": "cell_s"})
    assert res.status_code == 503 and not (tmp_path / "rosy-pipeline-ledger.json").exists()


def test_cell_task_writes_require_operator_guard():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None))
    app = FastAPI()

    def deny_write():
        raise HTTPException(403, detail="fleet.operate required")

    install_pipeline_routes(app, site_maps=maps, operator_guard=[Depends(deny_write)])
    client = TestClient(app)
    assert client.get("/api/fleet/pipeline/cell-tasks").status_code == 200
    assert client.post("/api/fleet/pipeline/cell-tasks", json={"cell_id": "cell_s"}).status_code == 403
    # claim/complete/cell-quality/cell-handoff stay on read_guard: the cell token role is host config
    # (test_pipeline_mutation_guards.VIEWER_MAY_POST).
    assert client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3"}).status_code == 403
    assert client.post("/api/fleet/pipeline/decision-gate", json={"domain": "line_follow"}).status_code == 403
    for path in ("displaced-detection", "human-safety-gate", "station-zones/dispatch",
                 "cable-guard", "vision-auto-check", "arm-holds/clear"):
        assert client.post(f"/api/fleet/pipeline/{path}", json={}).status_code == 403
    assert client.put("/api/fleet/pipeline/station-zones", json={}).status_code == 403
    read_blocked = FastAPI()
    install_pipeline_routes(read_blocked, site_maps=maps, read_guard=[Depends(deny_write)])
    assert TestClient(read_blocked).get("/api/fleet/pipeline/cell-tasks").status_code == 403


def test_cell_claim_requires_fresh_amr_brake_and_bed_evidence():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "amr-unmeasured", "cell_id": "cell_s"})
    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()
    assert blocked["claimed"] is False and blocked["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"


def test_vision_auto_check_cannot_clear_hold_from_caller_score():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "held-task", "cell_id": "cell_ab", "tier": 1})
    held = client.post("/api/fleet/pipeline/vision-auto-check", json={
        "cell_id": "cell_ab", "intrusion_score": 0.9,
    })
    assert held.status_code == 200
    assert "held-task" in held.json()["paused_tasks"]

    for fields in ({"intrusion_score": 0.0}, {"human_detected": False}, {}):
        cleared = client.post("/api/fleet/pipeline/vision-auto-check", json={
            "cell_id": "cell_ab", **fields,
        })
        assert cleared.status_code == 409
        assert cleared.json()["detail"]["code"] == "VISION_CLEAR_EVIDENCE_UNAVAILABLE"
        state = client.get("/api/fleet/pipeline/cell-tasks").json()
        assert state["human_safety"]["human_detected"]["cell_ab"] is True
        assert next(t for t in state["tasks"] if t["task_id"] == "held-task")["status"] == "PAUSED_HUMAN"


def test_human_safety_gate_cannot_clear_hold_from_caller_boolean():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "held-task", "cell_id": "cell_s"})
    held = client.post("/api/fleet/pipeline/human-safety-gate", json={
        "cell_id": "cell_s", "human_detected": True,
    })
    assert held.status_code == 200
    assert "held-task" in held.json()["paused_tasks"]
    assert held.json()["pinky_estop"]["v_cmd_mps"] == 0.0
    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()
    assert blocked["claimed"] is False and blocked["blocked_by_human"] is True

    for fields in ({"human_detected": False}, {"toggle": True}):
        cleared = client.post("/api/fleet/pipeline/human-safety-gate", json={
            "cell_id": "cell_s", **fields,
        })
        assert cleared.status_code == 409
        assert cleared.json()["detail"]["code"] == "HUMAN_CLEAR_EVIDENCE_UNAVAILABLE"
        state = client.get("/api/fleet/pipeline/cell-tasks").json()
        assert state["human_safety"]["human_detected"]["cell_s"] is True
        assert next(t for t in state["tasks"] if t["task_id"] == "held-task")["status"] == "PAUSED_HUMAN"

    for facts in ({"human_detected": False, "tangled": False, "displaced_to": "floor_front"},
                  {"facts": {"human_detected": False, "tangled": False, "displaced_to": "floor_front"}}):
        cleared = client.post("/api/fleet/pipeline/decision-gate", json={
            "subject_id": "cell_s", "domain": "arm_target", "auto_execute": False, **facts,
        })
        assert cleared.status_code == 409
        assert cleared.json()["detail"]["code"] == "HUMAN_CLEAR_EVIDENCE_UNAVAILABLE"
        state = client.get("/api/fleet/pipeline/cell-tasks").json()
        assert state["human_safety"]["human_detected"]["cell_s"] is True
        assert next(t for t in state["tasks"] if t["task_id"] == "held-task")["status"] == "PAUSED_HUMAN"
        assert state["cable_tangled"] is True
        assert state["detected_displaced_site"] is None


def test_aborted_cell_keeps_motion_hold_through_cancel_and_human_clear():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps, amr_evidence_fn=_measured_amr)
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "aborted-task", "cell_id": "cell_s"})
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={"task_id": "aborted-task", "cell_id": "cell_s"}).json()["claimed"]
    untrusted = client.post("/api/fleet/pipeline/cell-tasks/aborted-task/complete", json={"phase": "RELEASED"})
    assert untrusted.status_code == 422
    assert untrusted.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE"
    aborted = client.post("/api/fleet/pipeline/cell-tasks/aborted-task/complete", json={"phase": "ABORTED"}).json()
    assert aborted["task"]["status"] == "ABORTED"
    assert aborted["gate"]["amr_motion_inhibited"] is True
    assert client.post("/api/fleet/pipeline/cell-tasks/aborted-task/cancel").status_code == 409
    assert client.post("/api/fleet/pipeline/cell-handoff", json={"cell_id": "cell_s", "phase": "RELEASED"}).status_code == 409
    assert client.post("/api/fleet/pipeline/cell-handoff", json={"cell_id": "cell_s", "phase": "HUMAN_HOLD"}).status_code == 409
    for action in ("dock_s3", "dock_and_unload_s3", "return_s1"):
        assert client.post("/api/fleet/pipeline/pinky-tasks", json={
            "robot_id": aborted["task"]["robot_id"], "action": action,
        }).status_code == 409
    app.state.omx_cell_states["cell_ab"] = {"phase": "ABORTED", "robot_id": "pinky_ab", "amr_motion_inhibited": True}
    assert client.post("/api/fleet/pipeline/pinky-tasks", json={
        "robot_id": "pinky_ab", "action": "dock_s5",
    }).status_code == 409
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "next-task", "cell_id": "cell_s"})
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()["claimed"] is False
    client.post("/api/fleet/pipeline/human-safety-gate", json={"cell_id": "cell_s", "human_detected": True})
    cleared = client.post("/api/fleet/pipeline/human-safety-gate", json={"cell_id": "cell_s", "human_detected": False})
    assert cleared.status_code == 409
    assert (app.state.omx_cell_states["cell_s"])["amr_motion_inhibited"] is True
    client.post("/api/fleet/pipeline/vision-auto-check", json={"cell_id": "cell_s", "intrusion_score": 0.82})
    assert client.post("/api/fleet/pipeline/vision-auto-check", json={
        "cell_id": "cell_s", "intrusion_score": 0.04,
    }).json()["detail"]["code"] == "VISION_CLEAR_EVIDENCE_UNAVAILABLE"
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True


def test_human_interrupted_running_cell_is_not_requeued():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps, amr_evidence_fn=_measured_amr)
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "moving-arm", "cell_id": "cell_s"})
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={"task_id": "moving-arm", "cell_id": "cell_s"}).json()["claimed"]
    client.post("/api/fleet/pipeline/human-safety-gate", json={"cell_id": "cell_s", "human_detected": True})
    cleared = client.post("/api/fleet/pipeline/human-safety-gate", json={"cell_id": "cell_s", "human_detected": False})
    assert cleared.status_code == 409
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["summary"]["paused_human"] == 1
    listed = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert app.state.omx_cell_states["cell_s"]["phase"] == "HUMAN_HOLD"
    assert next(t for t in listed["tasks"] if t["task_id"] == "moving-arm")["status"] == "PAUSED_HUMAN"
    assert listed["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True


def test_three_tier_pipeline_waits_for_predecessor_completion():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps, amr_evidence_fn=_measured_amr)
    client = TestClient(app)
    invalid = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "wrong", "cell_id": "cell_ab", "arm_id": "arm_a", "tier": 1,
        "directive": {"schema": "rosy.omx-cell-area-xyz-directive.v1", "directive_id": "other", "arm_id": "arm_a"},
    })
    assert invalid.status_code == 422
    tasks = client.post("/api/fleet/pipeline/cell-tasks", json={
        "preset": "full_s3_to_s5_3tier_pipeline", "task_id": "three-tiers",
    }).json()["tasks"]
    assert [task["tier"] for task in tasks] == [1, 1, 2, 3]
    assert [task["depends_on"] for task in tasks] == [None, tasks[0]["task_id"], tasks[1]["task_id"], tasks[2]["task_id"]]
    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": tasks[1]["task_id"], "cell_id": "cell_ab",
    }).json()
    assert blocked["claimed"] is False and blocked["reason"] == "PREVIOUS_TIER_NOT_VERIFIED"
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": tasks[0]["task_id"], "cell_id": "cell_s",
    }).json()["claimed"] is True


def test_cell_ab_tier_input_and_owner_place_tier_require_exact_integer():
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    owner_evidence = {}
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)),
                            amr_evidence_fn=_measured_amr,
                            omx_evidence_fn=lambda task: owner_evidence.get(task["task_id"]))
    client = TestClient(app)
    for index, tier in enumerate((True, 1.0, "1", 0, 4)):
        response = client.post("/api/fleet/pipeline/cell-tasks", json={
            "task_id": f"invalid-tier-{index}", "cell_id": "cell_ab", "arm_id": "arm_a", "tier": tier})
        assert response.status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "missing-tier", "cell_id": "cell_ab", "arm_id": "arm_a"}).status_code == 422

    created = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "strict-tier", "cell_id": "cell_ab", "arm_id": "arm_a", "tier": 1})
    assert created.status_code == 200
    app.state.omx_cell_tasks["strict-tier"]["tier"] = True
    invalid_claim = client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": "strict-tier", "cell_id": "cell_ab"}).json()
    assert invalid_claim["claimed"] is False and invalid_claim["reason"] == "INVALID_CELL_TIER"
    app.state.omx_cell_tasks["strict-tier"]["tier"] = 1
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={
        "task_id": "strict-tier", "cell_id": "cell_ab"}).json()
    assert claimed["claimed"] is True
    lease = claimed["handoff"]["handoff_lease_id"]
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    for place_tier in (True, 1.0, 1):
        stage = {"directive_id": "strict-tier", "arm_id": "arm_a", "task_verified": True,
                 "verification": {"verified": True, "basis": "predefined_side_and_top_target_zones",
                                  "z_gate": {"verdict": "PASS"}},
                 "place": {"area": "pallet", "tier": place_tier}}
        receipt = {"handoff_lease_id": lease, "cell_id": "cell_ab", "stage_id": "strict-tier",
                   "phase": "RELEASED", "physical_completion": True, "simulated_success": False}
        evidence = {"task_id": "strict-tier", "lease": lease, "stage_result": stage,
                    "hardware_telemetry": hardware}
        digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        receipt["goal_evidence_digest"] = digest
        owner_evidence["strict-tier"] = {"receipt": receipt, "stage_result": stage,
                                         "hardware_telemetry": hardware}
        response = client.post("/api/fleet/pipeline/cell-tasks/strict-tier/complete", json={
            "phase": "RELEASED", "goal_evidence_digest": digest, "receipt": receipt,
            "stage_result": stage, "hardware_telemetry": hardware})
        assert response.status_code == (200 if type(place_tier) is int else 422)


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
    install_pipeline_routes(app, site_maps=maps, amr_evidence_fn=_measured_amr)
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
    assert handoff.status_code == 409


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
            "phase": "HUMAN_HOLD", "x": 0.68, "y": -0.2528, "yaw": 0.0,
            "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
            "tier": 1, "stage_id": "stage-1", "goal_evidence_digest": "digest-1"}
    assert client.post("/api/fleet/pipeline/cell-handoff", json=body).status_code == 200

    status = client.get("/api/fleet/pipeline/status").json()
    assert status["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True
    assert status["omx_cell_layer"]["cells"]["cell_s"]["gate"]["cell_can_claim"] is False
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
    assert client.post("/api/fleet/pipeline/cell-handoff", json=body).status_code == 409
    status = client.get("/api/fleet/pipeline/status").json()
    assert status["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True
    bays = client.get("/api/fleet/charge-bays").json()
    assert bays["omx_cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True


def test_cell_handoff_human_hold_pauses_running_task_and_sets_safety_flag():
    site_map = _map()
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site_map, build_graph(site_map), None)))
    app.state.omx_cell_tasks["running"] = {"task_id": "running", "cell_id": "cell_s", "status": "RUNNING"}
    client = TestClient(app)

    hold = client.post("/api/fleet/pipeline/cell-handoff", json={
        "cell_id": "cell_s", "robot_id": "pinky_1", "robot_kind": "pinky",
        "phase": "HUMAN_HOLD", "x": 0.68, "y": -0.2528, "yaw": 0.0, "v_cmd_mps": 0.0,
    })
    assert hold.status_code == 200
    state = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert state["human_safety"]["human_detected"]["cell_s"] is True
    assert state["human_safety"]["active_estop"] is True
    running = next(t for t in state["tasks"] if t["task_id"] == "running")
    assert running["status"] == "PAUSED_HUMAN"
    assert running["paused_from_status"] == "RUNNING"
    assert state["cells"]["cell_s"]["gate"]["amr_motion_inhibited"] is True


def test_pinky_dock_and_return_do_not_fabricate_claim_or_release():
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    assert client.post("/api/fleet/pipeline/pinky-tasks", json={
        "robot_id": "pinky_1", "action": "dock_and_unload_s3",
    }).json()["pinky_task"]["status"] == "QUEUED"
    assert app.state.omx_cell_states.get("cell_s") is None
    held = client.post("/api/fleet/pipeline/cell-handoff", json={
        "cell_id": "cell_s", "robot_id": "pinky_1", "robot_kind": "pinky",
        "phase": "HUMAN_HOLD", "x": 0.68, "y": -0.2528, "yaw": 0.0,
        "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
    })
    assert held.status_code == 200
    assert held.json()["gate"]["cell_can_claim"] is False
    queued_before = len(app.state.pinky_tasks)
    refused = client.post("/api/fleet/pipeline/pinky-tasks", json={
        "robot_id": "pinky_1", "action": "return_s1",
    })
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "HUMAN_HOLD_ACTIVE"
    assert len(app.state.pinky_tasks) == queued_before
    cells_before = len(app.state.omx_cell_tasks)
    refused_zone = client.post("/api/fleet/pipeline/station-zones/dispatch", json={
        "zone_id": "EXP_S5_PALLET", "robot_id": "pinky_1",
    })
    assert refused_zone.status_code == 409 and refused_zone.json()["detail"]["code"] == "HUMAN_ESTOP_ACTIVE"
    assert len(app.state.pinky_tasks) == queued_before
    assert len(app.state.omx_cell_tasks) == cells_before
    app.state.human_detected["cell_s"] = False  # Simulate an old ledger missing the flag; the phase still holds.
    refused_decision = client.post("/api/fleet/pipeline/decision-gate", json={
        "subject_id": "cell_ab", "domain": "arm_target", "auto_execute": True,
    })
    assert refused_decision.status_code == 409
    assert refused_decision.json()["detail"]["code"] == "HUMAN_HOLD_ACTIVE"
    assert len(app.state.omx_cell_tasks) == cells_before
    decision = client.post("/api/fleet/pipeline/decision-gate", json={
        "subject_id": "rosy_46", "domain": "line_follow", "auto_execute": True,
        "facts": {"tangled": True},
    })
    assert decision.status_code == 200
    assert decision.json()["pinky_task"]["v_cmd_mps"] == 0.0
    assert len(app.state.omx_cell_tasks) == cells_before
    app.state.human_detected["cell_s"] = True
    assert client.post("/api/fleet/pipeline/pinky-tasks", json={
        "robot_id": "pinky_1", "action": "stop_now",
    }).status_code == 200
    assert app.state.omx_cell_states["cell_s"]["phase"] == "HUMAN_HOLD"


def test_untrusted_abort_still_inhibits_amr_motion():
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None))
    app = FastAPI()
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)
    aborted = client.post("/api/fleet/pipeline/cell-handoff", json={
        "cell_id": "cell_s", "robot_id": "pinky_1", "robot_kind": "pinky",
        "phase": "ABORTED", "x": 0.68, "y": -0.2528, "yaw": 0.0,
        "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
    })
    assert aborted.status_code == 200
    assert aborted.json()["gate"]["amr_motion_inhibited"] is True
    assert aborted.json()["gate"]["amr_can_depart"] is False


def test_cell_tasks_assign_claim_and_complete_lifecycle():
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps
    owner_evidence = {}
    install_pipeline_routes(app, site_maps=maps, amr_evidence_fn=_measured_amr,
                            omx_evidence_fn=lambda task: owner_evidence.get(task["task_id"]))
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
    assert claimed["handoff"]["tier"] == 1
    assert claimed["handoff"]["handoff_lease_id"].endswith(":fleet-r-cell-s-01")
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "same-cell-queued", "cell_id": "cell_s"})
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()["claimed"] is False

    complete_path = "/api/fleet/pipeline/cell-tasks/fleet-r-cell-s-01/complete"
    assert client.post(complete_path, json={}).status_code == 409
    assert client.post(complete_path, json={"phase": "RELEASED"}).status_code == 422
    stage_result = {"directive_id": "fleet-r-cell-s-01", "arm_id": "arm_s", "task_verified": True,
                    "verification": {"verified": True, "basis": "predefined_side_and_top_target_zones"}}
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]}}
    receipt = {"handoff_lease_id": claimed["handoff"]["handoff_lease_id"],
               "cell_id": "cell_s", "stage_id": "fleet-r-cell-s-01", "phase": "RELEASED",
               "physical_completion": True, "simulated_success": False}
    evidence = {"task_id": "fleet-r-cell-s-01", "lease": receipt["handoff_lease_id"],
                "stage_result": stage_result, "hardware_telemetry": hardware}
    digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    receipt["goal_evidence_digest"] = digest
    owner_evidence["fleet-r-cell-s-01"] = {"receipt": receipt, "stage_result": stage_result,
                                          "hardware_telemetry": hardware}
    completion = {"phase": "RELEASED", "goal_evidence_digest": digest,
                  "reason": "TRANSFER_CONFIRMED", "receipt": receipt,
                  "stage_result": stage_result, "hardware_telemetry": hardware}
    simulated = {**receipt, "physical_completion": False, "simulated_success": True}
    owner_evidence["fleet-r-cell-s-01"] = {**owner_evidence["fleet-r-cell-s-01"], "receipt": simulated}
    refused_sim = client.post(complete_path, json={**completion, "receipt": simulated})
    assert refused_sim.status_code == 422 and refused_sim.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"
    owner_evidence["fleet-r-cell-s-01"]["receipt"] = receipt
    app.state.human_detected["cell_s"] = True
    held = client.post(complete_path, json=completion)
    assert held.status_code == 409 and held.json()["detail"]["code"] == "HUMAN_HOLD_ACTIVE"
    assert app.state.omx_cell_tasks["fleet-r-cell-s-01"]["status"] == "RUNNING"
    app.state.human_detected["cell_s"] = False
    original_cell_state = dict(app.state.omx_cell_states["cell_s"])
    app.state.omx_cell_states["cell_s"]["phase"] = "HUMAN_HOLD"
    held = client.post(complete_path, json=completion)
    assert held.status_code == 409 and held.json()["detail"]["code"] == "HUMAN_HOLD_ACTIVE"
    assert app.state.omx_cell_tasks["fleet-r-cell-s-01"]["status"] == "RUNNING"
    app.state.omx_cell_states["cell_s"] = original_cell_state
    app.state.omx_cell_tasks["fleet-r-cell-s-01"]["tier"] = True
    malformed_tier = client.post(complete_path, json=completion)
    assert malformed_tier.status_code == 422 and malformed_tier.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"
    app.state.omx_cell_tasks["fleet-r-cell-s-01"]["tier"] = 1
    done = client.post(complete_path, json=completion).json()
    assert done["ok"] is True and done["task"]["status"] == "COMPLETED"
    assert done["gate"]["amr_motion_inhibited"] is False
    assert done["task"]["hardware_telemetry"]["stop_event"]["folded"] is True

    chained = client.post("/api/fleet/pipeline/cell-tasks", json={"preset": "full_s3_to_s5_pipeline", "task_id": "chain-01"}).json()
    assert chained["ok"] is True and len(chained["tasks"]) == 3
    assert [t["arm_id"] for t in chained["tasks"]] == ["arm_s", "arm_a", "arm_b"]

    cancelled = client.post(f"/api/fleet/pipeline/cell-tasks/{chained['tasks'][0]['task_id']}/cancel").json()
    assert cancelled["ok"] is True and cancelled["task"]["status"] == "CANCELLED"
    assert cancelled["gate"]["amr_motion_inhibited"] is False

    overview = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert overview["summary"]["total"] == 5
    assert overview["summary"]["completed"] == 1
    assert "cell_s" in overview["cells"] and "cell_ab" in overview["cells"]
    assert len(overview["presets"]) >= 7

    pinky_resp = client.post("/api/fleet/pipeline/pinky-tasks", json={"robot_id": "rosy_42", "action": "dock_and_unload_s3"}).json()
    assert pinky_resp["ok"] is True
    assert pinky_resp["pinky_task"]["target_place"] == "S3"
    assert pinky_resp["pinky_task"]["status"] == "QUEUED"
    assert pinky_resp["spawned_cell_task"]["cell_id"] == "cell_s"

    # D-136: Fleet은 영상을 중계하지 않는다 — 셀 카메라 프리뷰 라우트는 없다(Video relay 금지).
    assert client.get("/api/fleet/pipeline/cell-camera/cell_s").status_code == 404
    assert client.get("/api/fleet/pipeline/cameras").status_code == 404
    assert client.post("/api/fleet/pipeline/cell-camera/cell_s", content=b"\xff\xd8").status_code == 404

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
    assert dec_pinky["executed"]["pinky_task"]["status"] == "QUEUED"

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
    assert stg_disp["pinky_task"]["status"] == "QUEUED"

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

    # A caller-supplied score can hold a cell, but cannot clear it without camera evidence.
    vis_intrude = client.post(
        "/api/fleet/pipeline/vision-auto-check",
        json={"cell_id": "cell_ab", "intrusion_score": 0.82, "displaced_to": "belt_far"},
    ).json()
    assert vis_intrude["ok"] is True
    assert vis_intrude["vision"]["human_detected"] is True
    assert vis_intrude["safety_event"]["active_estop"] is True
    assert len(vis_intrude["safety_event"]["paused_tasks"]) >= 1

    for body in ({"intrusion_score": 0.04}, {"human_detected": False}, {}):
        vis_clear = client.post("/api/fleet/pipeline/vision-auto-check", json={
            "cell_id": "cell_ab", **body,
        })
        assert vis_clear.status_code == 409
        assert vis_clear.json()["detail"]["code"] == "VISION_CLEAR_EVIDENCE_UNAVAILABLE"
    still_held = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert still_held["human_safety"]["human_detected"]["cell_ab"] is True
    assert {t["task_id"] for t in still_held["tasks"] if t["status"] == "PAUSED_HUMAN"} >= set(
        vis_intrude["safety_event"]["paused_tasks"])

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
            "arm_states": {
                "arm_s": {
                    "joints_deg": [-0.1, -58.4, 50.9, 50.2, -4.8, 49.5],
                    "folded": True,
                    "temp_c": 31.8,
                    "current_ma": 46.2,
                    "source": "chunk_status_live",
                }
            },
        },
    ).json()
    assert q_res["ok"] is True and q_res["arm_holds"]["arm_b"]["held"] is True
    assert q_res["arm_live_states"]["arm_s"]["folded"] is True
    assert q_res["arm_live_states"]["arm_s"]["temp_c"] == 31.8

    tasks_after_q = client.get("/api/fleet/pipeline/cell-tasks").json()
    assert "arm_live_states" in tasks_after_q
    assert "station_camera_links" in tasks_after_q
    assert tasks_after_q["station_camera_links"]["S3"]["target_id"] == "arm_s"
    assert "cameras" not in tasks_after_q  # 카메라 목록 카탈로그도 중계 금지와 함께 갔다

    clr = client.post(
        "/api/fleet/pipeline/arm-holds/clear",
        json={"arm_id": "cell_ab", "note": "verified folded home on camera"},
    ).json()
    assert clr["ok"] is True and clr["arm_holds"]["arm_b"]["held"] is False


def test_station_zones_put_saves_yaml_and_get_reflects_it(tmp_path, monkeypatch):
    # The override file is redirected: the route would otherwise write /tmp or /var/lib/rosy.
    monkeypatch.setattr("fleet.server.pipeline_routes._storage_dir", lambda: tmp_path)
    site_map = _map()
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    yaml_text = """schema: rosy.station-zones.v1
staging_bays:
  - id: STG_TEST
    name: test bay
"""
    saved = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": yaml_text})
    assert saved.status_code == 200 and saved.json()["ok"] is True
    zones = client.get("/api/fleet/pipeline/station-zones").json()
    assert [z["id"] for z in zones["staging_bays"]] == ["STG_TEST"]
    assert (tmp_path / "station_zones.yaml").read_text(encoding="utf-8") == yaml_text

    empty = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": "  "})
    assert empty.status_code == 422 and empty.json()["detail"]["code"] == "EMPTY_YAML"
    invalid = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": "- not-a-mapping"})
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "INVALID_STATION_ZONES_YAML"
    assert [z["id"] for z in client.get("/api/fleet/pipeline/station-zones").json()["staging_bays"]] == ["STG_TEST"]
