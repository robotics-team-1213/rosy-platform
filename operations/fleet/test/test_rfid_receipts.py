from datetime import datetime, timedelta, timezone
import time

from fastapi.testclient import TestClient
import pytest

from core_common.protocol.port_events import IntakeReading
from fleet.server.port_event_store import PortEventStore
from fleet.server.rfid_receipts import Manifest, RfidReceipts, supply_intervals
from test_pipeline_port_events import _build_app, _complete_s_payload
from test_port_events import app_with, control


TOKEN = {"X-Workcell-Observation-Token": "cell-token"}
READ = "/api/fleet/workcell-observations/supply/intake-readings"
PARENT = {"X-Who": "control-unit:R"}
PEER = "/api/fleet/control-unit/intake-candidates"


def reading(n, at, *, label=None, start=None):
    return IntakeReading(observation_ref=f"scan-{n}", point="rfid_intake",
        state="closed_through" if start else "read" if label else "unreadable",
        observed_at=at, coverage_start=start, reader_seq=n, reader_epoch="reader-1",
        epc=label.encode().hex() if label else None)


def test_normal_supply_to_private_reader_to_harbor_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_INTAKE_RFID_READER_EPOCH", "reader-1")
    monkeypatch.setenv("ROSY_INTAKE_RFID_ENCODED_WORKCELL", "supply")
    cell_dir = tmp_path / "cell"
    cell_dir.mkdir()
    cell = app_with(cell_dir)
    monkeypatch.delenv("ROSY_INTAKE_RFID_ENCODED_WORKCELL")
    monkeypatch.setenv("ROSY_INTAKE_RFID_WORKCELL", "supply")
    app, owner = _build_app(monkeypatch, tmp_path)
    root = TestClient(app)
    unit = control({"cell-a": [], "cell-b": []})
    unit.topology.units["cell-a"].resources += ("observation-workcell:supply",)
    app.state.control_unit = unit

    async def candidates(peer, after, limit):
        assert peer == "cell-a"
        response = cell.get(PEER, params={"after_seq": after, "limit": limit}, headers=PARENT)
        assert response.status_code == 200
        assert "epc" not in response.text.lower()
        return response.json()

    unit.peer.intake_candidates = candidates
    clock = [time.time() - 30]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    coverage = datetime.fromtimestamp(clock[0]-1, timezone.utc)
    task_spec = {"preset": "s3_shuttle", "robot_id": "amr_46", "task_id": "supply-task"}
    created = root.post("/api/fleet/pipeline/cell-tasks", json=task_spec)
    assert created.status_code == 200, created.text
    occurrence = app.state.omx_cell_tasks["supply-task"]["intake_occurrence_id"]
    claimed = root.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s", "task_id": "supply-task"})
    assert claimed.json()["claimed"], claimed.text
    clock[0] += 1
    at = datetime.fromtimestamp(clock[0], timezone.utc)
    body = reading(1, at, label="C-1").model_dump(mode="json")
    assert cell.post(READ, json=body).status_code == 401
    assert cell.post(READ, headers=TOKEN, json=body).status_code == 200
    assert cell.post(READ, headers=TOKEN, json=body).status_code == 200
    assert cell.post(READ, headers=TOKEN, json={**body, "epc": "432D32"}).status_code == 409
    assert cell.get(PEER, headers={"X-Who": "harbor"}).status_code == 403
    assert root.get("/api/fleet/port-events").json()["events"] == []
    clock[0] += 1
    lease = claimed.json()["handoff"]["handoff_lease_id"]
    receipt, stage, hardware, digest = _complete_s_payload("supply-task", lease, 0)
    owner["supply-task"] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}
    res = root.post("/api/fleet/pipeline/cell-tasks/supply-task/complete", json={
        "phase": "RELEASED", "goal_evidence_digest": digest, **owner["supply-task"]})
    assert res.status_code == 200, res.text
    assert root.get("/api/fleet/port-events").json()["events"] == []
    watermark = reading(2, datetime.fromtimestamp(clock[0]+1, timezone.utc), start=coverage)
    assert cell.post(READ, headers=TOKEN, json=watermark.model_dump(mode="json")).status_code == 200
    event, = root.get("/api/fleet/port-events").json()["events"]
    assert event["object_ref"] == "C-1" and event["intake_occurrence_id"] == occurrence
    assert root.get("/api/fleet/port-events").json()["events"] == [event]
    assert cell.post("/api/fleet/workcell-observations/supply/port-events", headers=TOKEN, json=event).status_code == 422
    attempt = "harbor-cell-plan-1"
    spec = {"mode": "harbor_plan", "state": {},
            "steps": [{"src_site": "belt", "dst_site": "yard-r1-c1-l1", "cargo_id": "C-1"}],
            "request_key": attempt, "placement_attempt_id": attempt, "intake_occurrence_id": occurrence}
    path = "/api/fleet/pipeline/cell-plans"
    assert root.post(path, json={**spec, "placement_attempt_id": "wrong"}).status_code == 422
    assert root.post(path, json={**spec, "intake_occurrence_id": "another"}).status_code == 409
    response = root.post(path, json=spec)
    assert response.status_code == 200, response.text
    task = app.state.omx_cell_tasks[response.json()["plan"]["task_ids"][0]]
    assert task["intake_occurrence_id"] == occurrence and task["placement_attempt_id"] == attempt


@pytest.mark.parametrize("issue", ["second_label", "padding_conflict", "unknown", "overlap", "gap", "epoch", "simulated"])
def test_anonymous_matching_holds_incomplete_or_ambiguous_evidence(tmp_path, issue):
    store = PortEventStore(tmp_path / "fleet.sqlite3")
    rfid = RfidReceipts(store, encoded="supply", workcell="supply", epoch="reader-1")
    start = datetime.now(timezone.utc)-timedelta(seconds=3)
    end = start+timedelta(seconds=2)
    rfid.record("supply", reading(1, start, label="C-2"))
    seq = 2
    if issue in ("second_label", "padding_conflict", "unknown"):
        label = {"second_label": "C-3", "padding_conflict": "C-2\0", "unknown": "foreign"}[issue]
        rfid.record("supply", reading(seq, start+timedelta(seconds=1), label=label))
        seq += 1
    rfid.record("supply", reading(seq, end, start=start+timedelta(milliseconds=1) if issue=="gap" else start))
    rfid.accept_page("cell-a", 0, rfid.page(0, 50))
    if issue == "epoch":
        rfid = RfidReceipts(store, workcell="supply", epoch="replacement")
    task = {"task_id": "t", "handoff_lease_id": "lease", "status": "COMPLETED",
            "claimed_at": start.timestamp(), "completed_at": end.timestamp(),
            "receipt": {"stage_id":"t", "handoff_lease_id":"lease", "phase":"RELEASED",
                        "physical_completion":True, "simulated_success":issue=="simulated"},
            "stage_result": {"task_verified": True}, "intake_occurrence_id":"occurrence"}
    tasks = [task]
    if issue == "overlap":
        tasks.append({**task, "task_id":"later", "status":"RUNNING", "completed_at":None})
    rfid.reconcile("cell-a", tasks)
    assert not store.after(0, 20)


def test_declared_cargo_after_delivery_and_manifest_revisions_survive_restart(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    manifest = Manifest.model_validate({"schema":"rosy.intake-rfid-manifest.v1", "workcell_id":"supply",
                                        "revision":"v1","container_epcs":{"ABCD":"C-1"}})
    store = PortEventStore(path)
    rfid = RfidReceipts(store, manifest=manifest, workcell="supply", window=3)
    at = datetime.now(timezone.utc)-timedelta(seconds=2)
    row = IntakeReading(point="rfid_intake", observation_ref="scan", state="read", epc="abcd", observed_at=at)
    rfid.record("supply", row)
    page = rfid.page(0, 1)
    assert "ABCD" not in str(page)
    rfid.accept_page("cell", 0, page)
    task = {"object_ref":"C-1", "task_id":"s1", "intake_occurrence_id":"first",
            "claimed_at":at.timestamp()-5, "completed_at":at.timestamp()-1, "status":"COMPLETED",
            "handoff_lease_id":"L", "receipt":{"physical_completion":True,"simulated_success":False,
                "phase":"RELEASED","stage_id":"s1","handoff_lease_id":"L"}, "stage_result":{"task_verified":True}}
    rfid.reconcile("cell", [task])
    again = RfidReceipts(PortEventStore(path), manifest=manifest, workcell="supply", window=3)
    again.record("supply", row)
    again.accept_page("cell", 0, page)
    next_task = {**task, "intake_occurrence_id":"next", "claimed_at":at.timestamp()+1,
                 "completed_at":at.timestamp()+2}
    again.reconcile("cell", [task, next_task])
    assert again.received("first", "C-1") and not again.received("next", "C-1")
    assert len(store.after(0, 20)) == 1
    start, end = at.timestamp()+0.1, at.timestamp()+0.5
    move = dict(task_id="place", cell_id="cell_ab", src_site="belt", dst_site="yard", claimed_at=start,
                completed_at=end, intake_occurrence_id="first", object_ref="C-1")
    assert again.tracked_source("first", "C-1", start, end, [task, move])
    assert not again.tracked_source("first", "C-1", start, end, [move])
    for competing in (dict(task_id="new", cell_id="cell_s", claimed_at=start),
                      dict(move, task_id="unidentified", intake_occurrence_id=None)):
        assert not again.tracked_source("first", "C-1", start, end, [task, move, competing])
    with pytest.raises(ValueError, match="revision"):
        RfidReceipts(store, manifest=manifest.model_copy(update={"container_epcs":{"CDEF":"C-2"}}))


def test_resolved_supply_and_retries_never_turn_export_or_recovery_into_intake(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_INTAKE_RFID_WORKCELL", "supply")
    app, _ = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)
    path = "/api/fleet/pipeline/cell-tasks"

    def create(key, preset):
        res = client.post(path, json={"task_id":key, "preset":preset, "robot_id":"amr_46"})
        assert res.status_code == 200, res.text
        return app.state.omx_cell_tasks[key]

    def retry(task):
        res = client.post(f"{path}/{task['task_id']}/retry")
        assert res.status_code == 200, res.text
        return app.state.omx_cell_tasks[res.json()["task"]["task_id"]]

    app.state.detected_displaced_site = "belt_far"
    recovery = create("diverted", "s3_shuttle")
    assert recovery["displaced_to"] == "belt_far" and "intake_occurrence_id" not in recovery
    historical = dict(recovery, claimed_at=100, intake_occurrence_id="legacy", intake_workcell="supply")
    blocker, = supply_intervals([historical], "supply")
    assert not blocker["intake_occurrence_id"]
    export = create("export", "export_s3_belt")
    assert "intake_occurrence_id" not in export and "intake_occurrence_id" not in retry(export)
    inbound = create("normal", "s3_shuttle")
    assert retry(inbound)["intake_occurrence_id"] == inbound["intake_occurrence_id"]
