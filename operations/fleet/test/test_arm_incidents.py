"""D-971: OMX arm incidents. The control PC reports with its arm token, the AI PC explains, a named operator clears."""
import asyncio
import base64
from hashlib import sha256
import hashlib

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from core_common.protocol.arm_incidents import ARM_INCIDENT_FRAME_BYTES, ArmIncidentReport
from core_common.protocol.workcell_observations import WorkcellObservationManifest
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.arm_incidents import SHOWN_CLEARED, ArmIncidentStore
from fleet.server.workcell_observations import WorkcellObservations
from fleet.swarm.robots import RobotEndpoint

PATH = "/api/fleet/workcell-observations"
SESSION = "6f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b"
SOURCE = {"X-Workcell-Observation-Token": "arm-b-secret"}
ROLE_TOKENS = {"ai-token": ("ai-pc", "ai_observer"), "operator-token": ("op-7", "operator"),
               "viewer-token": ("watcher", "viewer")}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def jpeg(tag=b"top"):
    data = b"\xff\xd8" + tag * 10 + b"\xff\xd9"
    return {"role": tag.decode(), "sha256": hashlib.sha256(data).hexdigest(), "jpeg_b64": base64.b64encode(data).decode()}


def report(session=SESSION, source="arm_b", frames=(b"top", b"side"), **over):
    body = {"source_id": source, "session_id": session, "decision": {"hold": True, "reason": "latched ID 13 overload"},
            "facts": {"latched": {"13": {"hw_error": 32, "bits": ["overload"]}}, "folded": True,
                      "torque_after": {"13": 0}}, "recovery": {"rebooted": [13]}, "frames": [jpeg(t) for t in frames]}
    return {**body, **over}


def service():
    def arm(name, secret):
        return {"source_id": name, "arm_id": name, "label": name, "board_id": f"{name}-board",
                "joint_topic": f"/omx_commissioning/{name}/joint_states", "joint_names": ["joint1"],
                "token_env": f"{name.upper()}_TOKEN", "credential_sha256": sha256(secret.encode()).hexdigest()}
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "bench", "label": "Bench", "arms": [arm("arm_a", "arm-a-secret"), arm("arm_b", "arm-b-secret")],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
                     "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-id/top", "token_env": "TOP_TOKEN",
                     "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})
    return WorkcellObservations(manifest, {"arm_a": "arm-a-secret", "arm_b": "arm-b-secret"},
                                wall=lambda: 100.0, monotonic=lambda: 10.0)


@pytest.fixture
def client(tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-secret")], [FakeRobot("rosy_01")])
    users = {sha256(token.encode()).hexdigest(): {"principal_id": name, "role": role}
             for token, (name, role) in ROLE_TOKENS.items()}
    app = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                                            robot_ids=("rosy_01",)),
                     start_task_dispatcher=False, site_users=users, cell_job_compiler=None,
                     workcell_observations=service())
    return TestClient(app)


def post(client, body=None, source="arm_b", headers=SOURCE):
    return client.post(f"{PATH}/arms/{source}/incidents", json=report() if body is None else body, headers=headers)


def test_contract_is_strict_about_frames_facts_and_identity():
    assert ArmIncidentReport.model_validate(report()).frames[1].role == "side"
    tampered = jpeg()
    big = b"\xff\xd8" + b"x" * ARM_INCIDENT_FRAME_BYTES
    for bad in ({**report(), "extra": 1}, report(session="s1"), report(source="a b"),
                report(frames=(b"top", b"top")), report(frames=(b"top", b"side", b"top")),
                report(frames=[]) | {"frames": [{**tampered, "sha256": "0" * 64}]},
                {**report(), "frames": [{**tampered, "jpeg_b64": base64.b64encode(b"not a jpeg").decode(),
                                         "sha256": sha256(b"not a jpeg").hexdigest()}]},
                {**report(), "frames": [{"role": "top", "jpeg_b64": base64.b64encode(big).decode(),
                                         "sha256": sha256(big).hexdigest()}]},
                {**report(), "facts": {"x": "y" * 13000}}, {**report(), "facts": {"x": float("nan")}},
                {**report(), "facts": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}},
                {**report(), "frames": [{"role": "back", "sha256": "0" * 64, "jpeg_b64": "AAAAAAAA"}]}):
        with pytest.raises(ValidationError):
            ArmIncidentReport.model_validate(bad)
    assert ArmIncidentReport.model_validate({**report(), "recovery": None, "frames": []}).recovery is None


def test_store_is_idempotent_per_session_and_keeps_the_open_explained_cleared_states():
    clock = [10.0]
    store = ArmIncidentStore(wall=lambda: clock[0])
    first = store.report(ArmIncidentReport.model_validate(report()))
    assert store.report(ArmIncidentReport.model_validate(report())) == first  # a re-report is the same incident
    other = store.report(ArmIncidentReport.model_validate(report(session="7f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b")))
    assert other != first and store.hold("arm_b").incident_ids == [first, other] and not store.hold("arm_a").held
    assert [i["incident_id"] for i in store.unexplained()] == [first, other]
    assert store.unexplained()[0]["frames"][0]["jpeg_b64"]
    from core_common.protocol.arm_incidents import ArmIncidentExplanation
    explanation = ArmIncidentExplanation(seen="A box in the jaws.", suspected_cause="Overload from the box.", model="m:1")
    store.explain("arm_b", first, explanation)
    with pytest.raises(ValueError):
        store.explain("arm_b", first, explanation)  # the first explanation stands
    with pytest.raises(KeyError):
        store.explain("arm_a", first, explanation)  # an incident belongs to its arm
    assert [i["incident_id"] for i in store.unexplained()] == [other]
    clock[0] = 20.0
    store.clear("arm_b", first, "box removed", "op-7")
    with pytest.raises(ValueError):
        store.clear("arm_b", first, "again", "op-8")
    states = {i["incident_id"]: i for i in store.snapshot("arm_b")}
    assert states[first]["state"] == "cleared" and states[first]["cleared"] == {"by": "op-7", "at": 20.0, "note": "box removed",
                                                                                "cause": None, "basis": None}
    assert states[first]["explanation"]["seen"] == "A box in the jaws." and states[other]["state"] == "open"
    assert all("jpeg_b64" not in f for i in states.values() for f in i["frames"])  # no bytes in the console list
    assert store.hold("arm_b").incident_ids == [other]
    store.clear("arm_b", other, "checked", "op-7")
    with pytest.raises(ValueError):
        store.explain("arm_b", other, explanation)  # a cleared incident takes no explanation
    assert not store.hold("arm_b").held and len(store.snapshot("arm_b")) == 2  # history stays
    assert store.report(ArmIncidentReport.model_validate(report())) == first and not store.hold("arm_b").held


def test_store_survives_a_restart_and_shows_only_the_latest_cleared_history(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = ArmIncidentStore(path)
    ids = []
    for n in range(SHOWN_CLEARED + 3):
        ids.append(store.report(ArmIncidentReport.model_validate(report(session=f"6f1c2a3e-1b2d-4e5f-8a9b-{n:012x}"))))
        store.clear("arm_b", ids[-1], "ok", "op-7")
    held = store.report(ArmIncidentReport.model_validate(report()))
    reopened = ArmIncidentStore(path)
    assert reopened.hold("arm_b").incident_ids == [held]
    shown = reopened.snapshot("arm_b")
    assert shown[0]["incident_id"] == held and len(shown) == 1 + SHOWN_CLEARED


def test_source_token_reports_and_reads_the_hold_of_its_own_arm_only(client):
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json() == {"held": False, "incident_ids": [], "reason": None}
    reply = post(client)
    assert reply.status_code == 200 and reply.headers["Cache-Control"] == "no-store"
    incident_id = reply.json()["incident_id"]
    assert reply.json()["hold"]["held"] and "latched ID 13 overload" in reply.json()["hold"]["reason"]
    assert post(client).json()["incident_id"] == incident_id  # idempotent
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json()["incident_ids"] == [incident_id]
    other_arm = client.get(f"{PATH}/arms/arm_a/hold", headers={"X-Workcell-Observation-Token": "arm-a-secret"})
    assert other_arm.json()["held"] is False  # a hold is per arm
    for headers, source in (({}, "arm_b"), ({"X-Workcell-Observation-Token": "wrong"}, "arm_b"),
                            ({"X-Workcell-Observation-Token": "arm-a-secret"}, "arm_b"),  # another arm's token
                            ({"X-Workcell-Observation-Token": "top-secret"}, "arm_b"),  # a camera token
                            (SOURCE, "nope"), (bearer("operator-token"), "arm_b")):
        assert post(client, source=source, headers=headers).status_code == 401, (headers, source)
        assert client.get(f"{PATH}/arms/{source}/hold", headers=headers).status_code == 401


def test_report_body_is_validated_and_bounded(client):
    assert post(client, report(source="arm_a")).status_code == 422  # the body names another arm
    assert post(client, {**report(), "extra": 1}).status_code == 422
    assert post(client, {**report(), "facts": {"x": "y" * 13000}}).status_code == 422
    assert client.post(f"{PATH}/arms/arm_b/incidents", content=b"{" + b" " * 800_000 + b"}", headers=SOURCE).status_code == 413
    assert client.post(f"{PATH}/arms/arm_b/incidents", content=b"not json", headers=SOURCE).status_code == 422
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json()["held"] is False  # nothing was stored


def test_only_a_named_operator_clears_with_a_note_and_nothing_is_deleted(client):
    incident_id = post(client).json()["incident_id"]
    url = f"{PATH}/arms/arm_b/incidents/{incident_id}/clear"
    note = {"note": "box removed from the jaws"}
    for headers in (SOURCE, bearer("viewer-token"), bearer("ai-token"), {}):
        assert client.post(url, json=note, headers=headers).status_code in (401, 403), headers
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json()["held"]
    operator = bearer("operator-token")
    for bad in ({}, {"note": ""}, {"note": "x", "by": "me"}, {"note": "a\nb"}, {"note": "n" * 401}):
        assert client.post(url, json=bad, headers=operator).status_code == 422
    assert client.post(f"{PATH}/arms/arm_b/incidents/{'f' * 32}/clear", json=note, headers=operator).status_code == 404
    assert client.post(f"{PATH}/arms/arm_a/incidents/{incident_id}/clear", json=note, headers=operator).status_code == 404
    done = client.post(url, json=note, headers=operator)
    assert done.status_code == 200 and done.json()["held"] is False
    assert client.post(url, json=note, headers=operator).status_code == 409
    [row] = [a for a in client.get(PATH, headers=bearer("viewer-token")).json()["workcells"][0]["arms"]
             if a["source_id"] == "arm_b"][0]["incidents"]
    assert row["state"] == "cleared" and row["cleared"]["by"] == "op-7" and row["cleared"]["note"] == note["note"]


def test_only_the_ai_observer_reads_open_incidents_and_posts_an_explanation_that_changes_nothing(client):
    incident_id = post(client).json()["incident_id"]
    listing = f"{PATH}/arm-incidents/unexplained"
    for headers in ({}, SOURCE, bearer("viewer-token"), bearer("operator-token")):
        assert client.get(listing, headers=headers).status_code in (401, 403), headers
    [item] = client.get(listing, headers=bearer("ai-token")).json()["incidents"]
    assert item["incident_id"] == incident_id and item["source_id"] == "arm_b" and len(item["frames"]) == 2
    url = f"{PATH}/arms/arm_b/incidents/{incident_id}/explanation"
    body = {"seen": "A green box between the jaws.", "suspected_cause": "The box blocked the home pose.",
            "model": "qwen3-vl:8b-instruct@abcdef012345:d619-v5:1a2b3c4d"}
    for headers in ({}, SOURCE, bearer("viewer-token"), bearer("operator-token")):
        assert client.post(url, json=body, headers=headers).status_code in (401, 403), headers
    for bad in ({**body, "extra": 1}, {"seen": "x"}, {**body, "seen": ""}, {**body, "model": "has space"},
                {**body, "seen": "x" * 401}):
        assert client.post(url, json=bad, headers=bearer("ai-token")).status_code == 422
    assert client.post(f"{PATH}/arms/arm_b/incidents/{'f' * 32}/explanation", json=body,
                       headers=bearer("ai-token")).status_code == 404
    assert client.post(url, json=body, headers=bearer("ai-token")).status_code == 200
    assert client.post(url, json=body, headers=bearer("ai-token")).status_code == 409
    assert client.get(listing, headers=bearer("ai-token")).json() == {"incidents": []}
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json()["held"]  # an explanation does not release
    snapshot = client.get(PATH, headers=bearer("viewer-token")).json()
    [row] = [a for a in snapshot["workcells"][0]["arms"] if a["source_id"] == "arm_b"][0]["incidents"]
    assert row["state"] == "explained" and row["explanation"]["suspected_cause"] == body["suspected_cause"]
    assert "explanation only" in row["explanation"]["note"]
    assert [a["incidents"] for a in snapshot["workcells"][0]["arms"] if a["source_id"] == "arm_a"] == [[]]
    # the AI PC may post nothing else new: the clear route stays closed to it
    assert client.post(f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", json={"note": "x"},
                       headers=bearer("ai-token")).status_code == 403


def test_frames_are_served_to_viewers_only_for_a_known_role(client):
    incident_id = post(client).json()["incident_id"]
    url = f"{PATH}/arms/arm_b/incidents/{incident_id}/frames/top"
    assert client.get(url).status_code == 401 and client.get(url, headers=SOURCE).status_code == 401
    shown = client.get(url, headers=bearer("viewer-token"))
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg" and shown.content[:2] == b"\xff\xd8"
    assert client.get(url.replace("top", "back"), headers=bearer("viewer-token")).status_code == 404
    assert client.get(url.replace("arm_b", "arm_a"), headers=bearer("viewer-token")).status_code == 404


def test_many_console_tabs_cost_one_database_read_and_never_read_the_jpegs():
    """Each tab polls the list every 500 ms: 20 tabs must not mean 20 database reads, and none may load a frame blob."""
    clock = [0.0]
    store = ArmIncidentStore(monotonic=lambda: clock[0])
    big = b"\xff\xd8" + b"x" * 199_000 + b"\xff\xd9"
    frame = {"role": "top", "sha256": hashlib.sha256(big).hexdigest(), "jpeg_b64": base64.b64encode(big).decode()}
    store.report(ArmIncidentReport.model_validate(report(frames=(), source="arm_b") | {"frames": [frame]}))
    reads = []
    store._db.set_trace_callback(lambda sql: reads.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)

    first = store.snapshot("arm_b")
    one_tab = len(reads)
    for _ in range(19):
        assert store.snapshot("arm_b") == first
    assert len(reads) == one_tab and one_tab > 0  # 20 tabs read what 1 tab reads
    assert first[0]["frames"] == [{"role": "top", "sha256": frame["sha256"], "bytes": len(big)}]
    assert not any("jpeg FROM" in sql or ", jpeg" in sql for sql in reads)

    store.clear("arm_b", first[0]["incident_id"], "checked", "op-7")  # a write shows at once
    assert store.snapshot("arm_b")[0]["state"] == "cleared"
    reads.clear(); clock[0] = 5.0  # the backstop re-reads even without a write
    store.snapshot("arm_b")
    assert reads


def test_incident_store_work_never_runs_on_the_event_loop(client, monkeypatch):
    """The same loop answers every robot's heartbeat; a slow frame write must not hold it."""
    on_loop = []
    def watched(name, original):
        def call(self, *args):
            try:
                asyncio.get_running_loop()
                on_loop.append(name)
            except RuntimeError:
                pass
            return original(self, *args)
        return call
    for name in ("report", "accepted", "clear", "hold", "explain"):
        monkeypatch.setattr(ArmIncidentStore, name, watched(name, getattr(ArmIncidentStore, name)))
    incident_id = post(client).json()["incident_id"]
    assert client.post(f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", json={"note": "checked the jaws"},
                       headers=bearer("operator-token")).json()["held"] is False
    second = post(client, report(session="7f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b")).json()["incident_id"]
    reply = client.post(f"{PATH}/arms/arm_b/incidents/{second}/explanation", json={"seen": "A box in the jaws.", "suspected_cause": "Overload.", "model": "m:1"},
                        headers=bearer("ai-token"))
    assert reply.status_code == 200 and on_loop == []


def evidence(tag=b"tip", camera="top", t=-1.0, kind="tip"):
    data = b"\xff\xd8" + tag * 10 + b"\xff\xd9"
    return {"camera": camera, "t_rel_s": t, "kind": kind, "sha256": hashlib.sha256(data).hexdigest(),
            "jpeg_b64": base64.b64encode(data).decode()}


def test_a_cleared_cause_and_its_basis_are_kept_and_listed_for_learning(client):
    incident_id = post(client).json()["incident_id"]
    url, operator = f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", bearer("operator-token")
    for bad in ({"note": "x", "cause": "ghost"}, {"note": "x", "basis": "hunch"}):
        assert client.post(url, json=bad, headers=operator).status_code == 422
    assert client.get(f"{PATH}/arm-incidents/labelled", headers=bearer("ai-token")).json() == {"incidents": []}
    assert client.post(url, json={"note": "slower retry stopped at the same place", "cause": "blocked", "basis": "repeat"},
                       headers=operator).status_code == 200
    [row] = client.get(f"{PATH}/arm-incidents/labelled", headers=bearer("ai-token")).json()["incidents"]
    assert row["cleared"]["cause"] == "blocked" and row["cleared"]["basis"] == "repeat" and row["facts"]["folded"] is True
    for headers in (bearer("viewer-token"), bearer("operator-token"), SOURCE):
        assert client.get(f"{PATH}/arm-incidents/labelled", headers=headers).status_code in (401, 403)


def test_the_seconds_around_a_stop_arrive_frame_by_frame_from_the_arm_only(client, monkeypatch):
    import fleet.server.arm_incidents as module
    incident_id = post(client).json()["incident_id"]
    url = f"{PATH}/arms/arm_b/incidents/{incident_id}/evidence"
    first = client.post(url, json=evidence(), headers=SOURCE)
    assert first.status_code == 200 and first.json()["seq"] == 0
    assert client.post(url, json=evidence(), headers=SOURCE).json()["seq"] == 0  # the same frame again changes nothing
    for headers in ({}, {"X-Workcell-Observation-Token": "arm-a-secret"}, bearer("operator-token")):
        assert client.post(url, json=evidence(b"x"), headers=headers).status_code == 401, headers
    assert client.post(f"{PATH}/arms/arm_b/incidents/{'f' * 32}/evidence", json=evidence(b"y"), headers=SOURCE).status_code == 404
    assert client.post(url, json={**evidence(b"z"), "kind": "video"}, headers=SOURCE).status_code == 422
    assert client.post(url, json={**evidence(b"z"), "sha256": "0" * 64}, headers=SOURCE).status_code == 422
    assert client.post(url, content=b"{" + b" " * 300_000 + b"}", headers=SOURCE).status_code == 413
    monkeypatch.setattr(module, "ARM_INCIDENT_EVIDENCE_FRAMES", 2)
    assert client.post(url, json=evidence(b"a", "side", 0.5, "full"), headers=SOURCE).json()["seq"] == 1
    assert client.post(url, json=evidence(b"b"), headers=SOURCE).status_code == 409  # the incident's frames are full
    [row] = [a for a in client.get(PATH, headers=bearer("viewer-token")).json()["workcells"][0]["arms"]
             if a["source_id"] == "arm_b"][0]["incidents"]
    assert [(e["camera"], e["kind"], e["t_rel_s"]) for e in row["evidence"]] == [("top", "tip", -1.0), ("side", "full", 0.5)]
    assert "jpeg_b64" not in row["evidence"][0]  # the console list carries no bytes
    image = client.get(f"{url}/1", headers=bearer("viewer-token"))
    assert image.status_code == 200 and image.content.startswith(b"\xff\xd8") and image.headers["Cache-Control"] == "no-store"
    assert client.get(f"{url}/9", headers=bearer("viewer-token")).status_code == 404
    assert client.get(f"{PATH}/arms/arm_a/incidents/{incident_id}/evidence/1", headers=bearer("viewer-token")).status_code == 404


def test_whole_frames_expire_two_weeks_after_clearing_and_the_crops_and_label_stay():
    from core_common.protocol.arm_incidents import ArmIncidentEvidenceFrame
    clock = [10.0]
    store = ArmIncidentStore(wall=lambda: clock[0])
    old = store.report(ArmIncidentReport.model_validate(report()))
    for tag, kind in ((b"t", "tip"), (b"f", "full")):
        store.add_evidence("arm_b", old, ArmIncidentEvidenceFrame.model_validate(evidence(tag, kind=kind)))
    store.clear("arm_b", old, "checked", "op-7", "blocked", "measured")
    clock[0] += 15 * 86400
    new = store.report(ArmIncidentReport.model_validate(report(session="7f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b")))
    store.clear("arm_b", new, "checked", "op-7")  # any later clear expires what is due
    [labelled] = store.labelled()
    assert labelled["incident_id"] == old and [e["kind"] for e in labelled["evidence"]] == ["tip"]
    assert labelled["cleared"]["cause"] == "blocked"


def test_an_older_ledger_gains_the_label_columns_and_keeps_its_incidents(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE arm_incidents (incident_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, session_id TEXT NOT NULL, "
               "reported_at REAL NOT NULL, facts TEXT NOT NULL, decision TEXT NOT NULL, recovery TEXT, seen TEXT, "
               "suspected_cause TEXT, model TEXT, explained_at REAL, cleared_by TEXT, cleared_at REAL, clear_note TEXT, "
               "UNIQUE (source_id, session_id))")
    db.execute("INSERT INTO arm_incidents (incident_id, source_id, session_id, reported_at, facts, decision) "
               "VALUES (?,?,?,?,?,?)", ("a" * 32, "arm_b", SESSION, 1.0, "{}", '{"reason": "old"}'))
    db.commit()
    db.close()
    store = ArmIncidentStore(path)
    assert store.hold("arm_b").incident_ids == ["a" * 32]
    store.clear("arm_b", "a" * 32, "checked", "op-7", "unknown", "seen")
    assert store.snapshot("arm_b")[0]["cleared"]["basis"] == "seen"


def test_a_report_that_does_not_hold_waits_for_its_cause_and_leaves_the_arm_free(client):
    label = post(client, report(decision={"hold": False, "reason": "guard stop: contact in descend_pick; not held"}))
    assert label.status_code == 200 and label.json()["hold"]["held"] is False
    assert client.get(f"{PATH}/arms/arm_b/hold", headers=SOURCE).json()["held"] is False
    held = post(client, report(session="7f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b")).json()
    assert held["hold"]["incident_ids"] == [held["incident_id"]]  # only the holding report holds
    rows = [a for a in client.get(PATH, headers=bearer("viewer-token")).json()["workcells"][0]["arms"]
            if a["source_id"] == "arm_b"][0]["incidents"]
    assert {r["incident_id"] for r in rows if r["state"] == "open"} == {label.json()["incident_id"], held["incident_id"]}


def test_old_whole_frames_go_on_a_report_too_not_only_on_a_clear():
    """Review 2026-11-08: expiry ran only on clear(), so a quiet ledger kept every frame."""
    from core_common.protocol.arm_incidents import ArmIncidentEvidenceFrame
    clock = [10.0]
    store = ArmIncidentStore(wall=lambda: clock[0])
    old = store.report(ArmIncidentReport.model_validate(report()))
    store.add_evidence("arm_b", old, ArmIncidentEvidenceFrame.model_validate(evidence(b"f", kind="full")))
    store.clear("arm_b", old, "checked", "op-7", "blocked", "repeat")
    clock[0] += 15 * 86400
    store.report(ArmIncidentReport.model_validate(report(session="7f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b")))
    assert store.labelled()[0]["evidence"] == []
