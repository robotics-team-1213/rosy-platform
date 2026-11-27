"""PR B tests: Fleet R catalog-only /cell-objects endpoints, CAS readiness, & target_object lifecycle."""
from __future__ import annotations

import time
from fastapi.testclient import TestClient

from test_pipeline_port_events import OP, SVC, VIEW, _build_app


def _sample_ingest(now_s: float, *, gen: int = 3, cat_id: str = "container-1"):
    return {
        "cell_id": "cell_s",
        "arm_id": "arm_s",
        "camera_role": "arm_s_top",
        "frame_wh": [640, 480],
        "source_seq": 42,
        "observed_at": now_s,
        "ttl_s": 15.0,
        "cell_state_gen": gen,
        "objects": [
            {
                "object_ref": "det:42:0",
                "catalog_id": cat_id,
                "label": "small-box",
                "site": "pinky",
                "centre_mm": [15.0, -5.0],
                "centre_px": [320.0, 240.0],
                "corners_px": [[300, 220], [340, 220], [340, 260], [300, 260]],
                "pickable": True,
                "bind_tol_mm": 13.5,
            }
        ],
    }


def test_cell_objects_ingest_query_auth_and_d136_guards(monkeypatch, tmp_path):
    app, _ = _build_app(monkeypatch, tmp_path, guarded=True)
    client = TestClient(app, raise_server_exceptions=False)
    now = time.time()

    assert client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now), headers=VIEW).status_code == 403
    ok = client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now), headers=SVC)
    assert ok.status_code == 200 and ok.json()["count"] == 1

    got = client.get("/api/fleet/pipeline/cell-objects?cell_id=cell_s", headers=VIEW)
    assert got.status_code == 200 and got.headers.get("Cache-Control") == "no-store"
    snap = got.json()["by_arm"]["arm_s"]
    assert snap["cell_state_gen"] == 3 and snap["stale"] is False and len(snap["objects"]) == 1

    # D-136 media & size bounds + catalog-only rejection
    bad_media = _sample_ingest(now)
    bad_media["objects"][0]["label"] = "data:image/jpeg;base64,/9j/4AAQ"
    assert client.post("/api/fleet/pipeline/cell-objects", json=bad_media, headers=SVC).status_code == 422

    bad_unmatched = _sample_ingest(now, cat_id="unmatched")
    assert client.post("/api/fleet/pipeline/cell-objects", json=bad_unmatched, headers=SVC).status_code == 422

    too_many = _sample_ingest(now)
    too_many["objects"] = too_many["objects"] * 65
    assert client.post("/api/fleet/pipeline/cell-objects", json=too_many, headers=SVC).status_code == 422

    too_big = b"{" + b'"pad":"' + (b"x" * 70000) + b'"}'
    assert client.post("/api/fleet/pipeline/cell-objects", content=too_big, headers=SVC).status_code == 413

    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=other_service;cell_ab=service")
    assert client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now), headers=SVC).status_code == 403


def test_target_object_task_cas_readiness_admit_claim_retry_and_d996_isolation(monkeypatch, tmp_path):
    app, _ = _build_app(monkeypatch, tmp_path, guarded=True)
    client = TestClient(app, raise_server_exceptions=False)
    now = time.time()

    client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now, gen=5), headers=SVC)
    rdy1 = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now, gen=6), headers=SVC)
    rdy2 = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    assert rdy1["readiness_digest"] != rdy2["readiness_digest"] and rdy2["cell_state_gen"] == 6

    valid_target = {
        "object_ref": "det:42:0",
        "catalog_id": "container-1",
        "site": "pinky",
        "centroid_mm": [15.0, -5.0],
        "source_seq": 42,
        "observed_at": now,
        "ttl_s": 15.0,
        "tolerance_mm": 13.5,
        "expected_cell_state_gen": 6,
    }
    base_spec = {
        "cell_id": "cell_s", "arm_id": "arm_s", "robot_id": "rosy_01",
        "src_site": "pinky", "dst_site": "belt", "tier": 1, "propose": True,
    }

    # Unknown / unmatched / multi-tier / multi-step rejections
    assert client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": {**valid_target, "extra": 1}}, headers=SVC).status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": {**valid_target, "catalog_id": "unmatched"}}, headers=SVC).status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "tiers": [1, 2], "target_object": valid_target}, headers=SVC).status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", json={"preset": "full_s3_to_s5_pipeline", "propose": True, "target_object": valid_target}, headers=SVC).status_code == 422

    # Stale or missing expected_cell_state_gen / expired TTL -> 409
    no_gen = {k: v for k, v in valid_target.items() if k != "expected_cell_state_gen"}
    miss = client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": no_gen}, headers=SVC)
    assert miss.status_code == 409 and miss.json()["detail"]["code"] == "STALE_CELL_STATE"
    stale = client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": {**valid_target, "expected_cell_state_gen": 5}}, headers=SVC)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_CELL_STATE"
    exp = client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": {**valid_target, "observed_at": now - 20.0}}, headers=SVC)
    assert exp.status_code == 409 and exp.json()["detail"]["code"] == "TARGET_OBJECT_EXPIRED"

    # Valid proposed creation -> admit (after Drift refused!) -> fresh claim -> retry refused
    created = client.post("/api/fleet/pipeline/cell-tasks", json={**base_spec, "target_object": valid_target}, headers=SVC)
    assert created.status_code == 200
    tid = created.json()["task"]["task_id"]

    # Advancing cell_state_gen blocks admission of old target_object
    client.post("/api/fleet/pipeline/cell-objects", json=_sample_ingest(now, gen=7), headers=SVC)
    rdy_after = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    gov_snap = client.get("/api/fleet/pipeline/cell-tasks", headers=VIEW).json()["authority"]
    adm_fail = client.post(
        f"/api/fleet/pipeline/cell-tasks/{tid}/admit",
        json={"expected_readiness_digest": rdy_after["readiness_digest"],
              "expected_dispatch_generation": gov_snap["dispatch_generation"],
              "expected_authority_epoch": gov_snap["authority_epoch"],
              "expected_stop_generation": gov_snap["stop_generation"]},
        headers=OP,
    )
    assert adm_fail.status_code == 409 and adm_fail.json()["detail"]["code"] == "STALE_CELL_STATE"

    # Fresh direct operator queued task claims cleanly with handoff["target_object"] & top-level object_ref still stripped
    direct = client.post("/api/fleet/pipeline/cell-tasks", json={
        **base_spec, "propose": False, "target_object": {**valid_target, "expected_cell_state_gen": 7},
    }, headers=OP)
    assert direct.status_code == 200
    tid2 = direct.json()["task"]["task_id"]

    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s", "task_id": tid2}, headers=SVC).json()
    assert claimed["claimed"] is True
    assert claimed["handoff"]["target_object"]["catalog_id"] == "container-1"
    assert "object_ref" not in claimed["task"]  # D-996 Harbor top-level identity stays stripped

    retry = client.post(f"/api/fleet/pipeline/cell-tasks/{tid2}/retry", headers=OP)
    assert retry.status_code == 409 and retry.json()["detail"]["code"] == "TARGET_OBJECT_REQUIRES_FRESH_PLAN"
