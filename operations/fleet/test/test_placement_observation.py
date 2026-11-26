from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.pipeline.cell_site_targets import list_canonical_sites
from fleet.server.cell_site_recognition_routes import install_cell_site_recognition_routes
from fleet.server.pipeline_port_events import build_completion_events, strip_task_for_claim
from fleet.server.port_event_store import PortEventStore
from fleet.server.workcell_observations import WorkcellObservations


def test_markerless_result_needs_unique_source_and_measured_release(tmp_path):
    from fleet.server.pipeline_port_events import flush_pending_port_events

    task = dict(task_id="ab", src_site="belt", object_ref="C-12", claimed_at=10, completed_at=12, status="COMPLETED",
                cell_id="cell_ab", arm_id="arm_a", dst_wire_ref="yard-r1-c1-l1", dst_area="yard", tier=1,
                dst_site_id="yard:r1-s1-t1", dst_slot=dict(col=1, row=1, tier=1),
                placement_attempt_id="place", intake_occurrence_id="intake", handoff_lease_id="lease",
                receipt=dict(phase="RELEASED", physical_completion=True, simulated_success=False,
                             stage_id="ab", handoff_lease_id="lease"))
    place = dict(area="yard", site="yard:r1-s1-t1", site_id="yard:r1-s1-t1", col=1, row=1, tier=1)
    zone = dict(verified=True, basis="predefined_side_and_top_target_zones", measured_at=11,
                z_gate={"verdict": "PASS"}, target=place, place_slot={"present": True})
    stage = dict(directive_id="ab", arm_id="arm_a", task_verified=True, verification=zone, place=place,
                 raw={"result": "placed", "attempts": [{"observed": 1}]}, source_clearance={"objects": 0, "site": "belt"})
    app = FastAPI()
    store = app.state.port_event_store = PortEventStore(tmp_path / "events")
    app.state.omx_cell_tasks = {"ab": task}
    def pending(payload):
        return build_completion_events(app, task, cell_phase="RELEASED", stage_result=payload, human_detected=False)
    assert not pending({**stage, "source_clearance": {"objects": 1, "site": "belt"}})
    assert not pending({**stage, "raw": {"result": "placed", "attempts": [{"observed": 2}]}})
    assert not pending({**stage, "verification": {**zone, "place_slot": {"present": False}}})
    assert not pending({**stage, "verification": {**zone, "measured_at": 9}})
    task["pending_port_events"] = pending(stage)
    assert len(task["pending_port_events"]) == 1
    assert flush_pending_port_events(app) == 0 and store.after(0, 1) == []
    app.state.rfid_receipts = SimpleNamespace(tracked_source=lambda occ, cargo, start, end, history:
        (occ, cargo, start, end) == ("intake", "C-12", 10, 12) and len(list(history)) == 1)
    assert flush_pending_port_events(app) == 1
    [row] = store.after(0, 10)
    assert (row["event"].slot_ref, row["event"].identity) == ("yard-r1-c1-l1", "attested")


def test_only_bound_camera_and_unique_post_completion_slot_close_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_PLACEMENT_CAMERA_SOURCE", "overhead")
    monkeypatch.setenv("ROSY_PLACEMENT_CALIBRATION_REVISION", "cal-1")
    task = dict(task_id="task-12", object_ref="C-12", created_at=10, completed_at=20, status="COMPLETED",
                cell_id="cell_ab", identity="attested", dst_wire_ref="yard-r1-c1-l1",
                placement_attempt_id="place-12", intake_occurrence_id="intake-12",
                receipt={"physical_completion": True, "simulated_success": False, "phase": "RELEASED",
                         "stage_id": "task-12", "handoff_lease_id": "lease"},
                handoff_lease_id="lease", stage_result={"task_verified": True})
    camera = SimpleNamespace(source_id="overhead", label="cam", role="overhead", arm_id=None, stream="color",
                             credential_sha256=sha256(b"test-camera").hexdigest())
    manifest = SimpleNamespace(workcells=[SimpleNamespace(workcell_id="cell_ab", label="ab", arms=[], cameras=[camera])])
    service = WorkcellObservations(manifest, {})
    app = FastAPI()
    store = app.state.port_event_store = PortEventStore(tmp_path / "events.db")
    app.state.omx_cell_tasks = {task["task_id"]: task}
    install_cell_site_recognition_routes(app, service=service, require_viewer=lambda: None)
    assert build_completion_events(app, task, cell_phase="RELEASED", stage_result={}, human_detected=False) == []
    assert "placement_attempt_id" not in strip_task_for_claim(task)
    assert "intake_occurrence_id" not in strip_task_for_claim(task)
    slot = dict(site_ref="yard-r1-c4-l1", state="OCCUPIED", object_class=None, object_ref_read="C-12", confidence=1)
    rev = list_canonical_sites()["revision"]
    def timestamp(seconds):
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    frame = dict(schema="rosy.cell-site-recognition.v1", snapshot_id="frame", source_id="overhead",
                 site_map_revision=rev, calibration_revision="cal-1", observed_at=timestamp(21), sites=[slot])
    with TestClient(app) as client:
        def post(query="", **fields):
            return client.post("/api/fleet/cell-site-recognition" + query, json={**frame, **fields},
                               headers={"X-Workcell-Observation-Token": "test-camera"})
        assert post(source_id="other").status_code == 200
        assert post(calibration_revision="obsolete").status_code == 200
        assert post(site_map_revision=rev + 1).status_code == 200
        assert post(observed_at=timestamp(19)).status_code == 200
        assert post(sites=[slot, dict(slot, site_ref="yard-r1-c1-l1")]).status_code == 200
        assert post("?task_id=other").status_code == 200
        app.state.omx_cell_tasks["next"] = dict(task, task_id="next", created_at=22, status="RUNNING")
        assert post().status_code == 200
        assert store.after(0, 10) == []
        del app.state.omx_cell_tasks["next"]
        assert post().status_code == 200
        assert post("?task_id=task-12").status_code == 200
        assert post(snapshot_id="later", observed_at=timestamp(24)).status_code == 200
        changed = post(snapshot_id="different-frame", observed_at=timestamp(25),
                       sites=[dict(slot, site_ref="yard-r1-c1-l1")])
        assert changed.status_code == 409 and changed.json()["detail"]["code"] == "PLACEMENT_OBSERVATION_CONFLICT"
        assert post(sites=[dict(slot, site_ref="yard-r1-c1-l1")]).status_code == 409
    [row] = PortEventStore(store.path).after(0, 10)
    event = row["event"]
    assert (event.slot_ref, event.identity, event.intake_occurrence_id, event.placement_attempt_id) == (
        "yard-r1-c4-l1", "observed", "intake-12", "place-12")
