"""D-1039/D-1047: a configured AI assessor service clears only safe incidents of its own arms, three per arm a day, marked as a
machine clear whose cause is never scored as truth; people clear every kind as before."""
from hashlib import sha256
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from core_common.protocol.arm_incident.arm_incidents import ArmIncidentReport
from core_common.protocol.arm_incident.workcell_observations import WorkcellObservationManifest
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.arm_incidents import MACHINE_CLEARS_PER_WINDOW, REPEAT_WINDOW_S, ArmIncidentStore, MachineClearRefused
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.workcell_observations import WorkcellObservations
from fleet.swarm.robots import RobotEndpoint

PATH = "/api/fleet/workcell-observations"
SECRETS = {"arm_a": "arm-a-secret", "arm_b": "arm-b-secret"}
BOARDS = {"arm_a": "2B162C9B50323952582E3120FF06202D", "arm_b": "7F31D1FE50323952582E3120FF061D2D"}  # follower serials
TOKENS = {"assessor-token": ("cell-a-ai-assessor", "service"), "operator-token": ("op-7", "operator")}
ASSESSOR, OPERATOR = {"Authorization": "Bearer assessor-token"}, {"Authorization": "Bearer operator-token"}
WHY = {"note": "folded home, torque off, frames clear", "cause": "blocked", "basis": "measured"}
SAFE = {"safe_end": True, "latched": {}, "torque_after": {"11": 0, "12": 0, "13": 0}, "caps_restored": True,
        "folded": True, "windup_hits": [], "flagged": [], "stops": [], "fault_records": []}
# 2026-11-17 night, arm_s: the runner's park strain stop, then folded home torque OFF (the cell holds; a machine clears)
# the real rows (contracts/foundation/test/fixtures/arm_incidents/20261117T122911-arm_s.json): the text in error and
# fault of "run park", and in fault alone of the "state" row after it
STRAIN = ("contact in park: shoulder_lift lag rose to 2.2 units at PWM -321 of 600 "
          "(lags: shoulder_pan 0.1, elbow_flex 0.0, wrist_flex 0.2, wrist_roll 0.1)")
PARK = {"command": "run park", "error": STRAIN, "fault": STRAIN, "caught": None, "t": 3.2}
TONIGHT = {**SAFE, "flagged": [PARK, {"command": "state", "error": None, "fault": STRAIN, "caught": None, "t": 3.3}]}
UNSAFE = {
    "latched": {**SAFE, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}},
    "unfolded": {**SAFE, "folded": False},
    "unsafe end": {**SAFE, "safe_end": False},
    "torque unknown": {**SAFE, "torque_after": {}},
    "torque on": {**SAFE, "torque_after": {"11": 0, "12": 1}},
    "caps not restored": {**SAFE, "caps_restored": ["ID 12 pwm_limit"]},
    "snag": {**SAFE, "windup_hits": [{"reason": "elbow wound up 40 units"}]},
    "caught jaw": {**SAFE, "flagged": [{"command": "grip", "error": "jaws caught", "caught": True}]},
    "park plus caught": {**TONIGHT, "flagged": [PARK, {"command": "grip", "error": "jaws caught", "caught": True}]},
    "park plus pushing": {**TONIGHT, "flagged": [PARK, {"command": "lift", "error": "pushing: elbow lag 3.0 units"}]},
    "park unfolded": {**TONIGHT, "folded": False},
    "park torque on": {**TONIGHT, "torque_after": {"11": 0, "12": 1}},
    "park plus free text": {**TONIGHT, "flagged": [{**PARK, "error": STRAIN + "; a hand is in the jaws",
                                                    "fault": STRAIN + "; a hand is in the jaws"}]},
    "park with a fault": {**TONIGHT, "flagged": [{**PARK, "fault": "overload latched"}]},
    "no stops list": {k: v for k, v in TONIGHT.items() if k != "stops"},
    "jaws short in park": {**SAFE, "flagged": [{**PARK, "error": "contact in park: the jaws stopped 5.0 units short "
                                                                 "at PWM -248 of 300: something is in them"}]},
    "contact stop": {**SAFE, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]},
    "fault record": {**SAFE, "fault_records": ["arm_b-0001.json"]},
    "truncated": {"safe_end": True, "folded": True, "torque_after": {"11": 0}, "latched": {}, "truncated": True},
}


def body(n, facts, source="arm_b"):
    return {"source_id": source, "session_id": f"6f1c2a3e-1b2d-4e5f-8a9b-{n:012x}", "facts": facts,
            "decision": {"hold": True, "reason": "runner: contact in park"}}


def service():
    def arm(name):
        return {"source_id": name, "arm_id": name, "label": name, "board_id": BOARDS[name],
                "joint_topic": f"/omx_commissioning/{name}/joint_states", "joint_names": ["joint1"],
                "token_env": f"{name.upper()}_TOKEN", "credential_sha256": sha256(SECRETS[name].encode()).hexdigest()}
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "bench", "label": "Bench", "arms": [arm("arm_a"), arm("arm_b")],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
                     "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-id/top", "token_env": "TOP_TOKEN",
                     "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})
    return WorkcellObservations(manifest, SECRETS, wall=lambda: 100.0, monotonic=lambda: 10.0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_ARM_ASSESSORS", "cell-a-ai-assessor=arm_b")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-secret")], [FakeRobot("rosy_01")])
    users = {sha256(t.encode()).hexdigest(): {"principal_id": n, "role": r} for t, (n, r) in TOKENS.items()}
    app = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                                            robot_ids=("rosy_01",)),
                     start_task_dispatcher=False, site_users=users, cell_job_compiler=None,
                     workcell_observations=service())
    return TestClient(app)


def report(client, n, facts=SAFE, source="arm_b"):
    answer = client.post(f"{PATH}/arms/{source}/incidents", json=body(n, facts, source),
                         headers={"X-Workcell-Observation-Token": SECRETS[source]})
    assert answer.status_code == 200, answer.text
    return answer.json()["incident_id"]


def clear(client, incident_id, headers=ASSESSOR, source="arm_b", **over):
    return client.post(f"{PATH}/arms/{source}/incidents/{incident_id}/clear", json={**WHY, **over}, headers=headers)


def code(answer):
    return answer.status_code, answer.json()["detail"]["code"]


def row(client, incident_id, source="arm_b"):
    arms = client.get(PATH, headers=OPERATOR).json()["workcells"][0]["arms"]
    return next(r for a in arms if a["source_id"] == source for r in a["incidents"] if r["incident_id"] == incident_id)


def test_assessor_clears_a_safe_incident_marked_as_a_machine_clear_whose_basis_is_never_truth(client):
    incident_id = report(client, 1)
    answer = clear(client, incident_id)
    assert answer.status_code == 200 and answer.json()["held"] is False
    cleared = row(client, incident_id)["cleared"]
    assert {k: cleared[k] for k in ("by", "note", "cause", "basis", "kind")} == {
        "by": "cell-a-ai-assessor", "note": WHY["note"], "cause": "blocked", "basis": "unknown", "kind": "machine"}


def test_assessor_clears_tonights_park_strain_stop_on_a_folded_torque_off_arm(client):
    incident_id = report(client, 6, TONIGHT)
    assert clear(client, incident_id, cause="too_fast").status_code == 200
    assert row(client, incident_id)["cleared"]["kind"] == "machine"


def test_assessor_is_refused_every_kind_that_is_not_safe_and_a_person_still_clears_it(client):
    for n, (kind, facts) in enumerate(UNSAFE.items(), start=10):
        incident_id = report(client, n, facts)
        assert code(clear(client, incident_id)) == (403, "AI_CLEAR_KIND_REFUSED"), kind
        assert row(client, incident_id)["state"] == "open", kind
        human = client.post(f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", json={"note": "checked"},
                            headers=OPERATOR)
        assert human.status_code == 200, kind
        assert {k: row(client, incident_id)["cleared"][k] for k in ("by", "kind")} == {"by": "op-7", "kind": "person"}


def test_assessor_must_name_a_cause_and_its_basis(client):
    incident_id = report(client, 2)
    for missing in ({"cause": None}, {"basis": None}):
        assert code(clear(client, incident_id, **missing)) == (422, "AI_CLEAR_CAUSE_REQUIRED")
    assert clear(client, incident_id, note="").status_code == 422
    assert row(client, incident_id)["state"] == "open"


def test_three_machine_clears_per_arm_a_day_whatever_the_cause_and_human_clears_do_not_count(client, monkeypatch):
    first, *machine, fifth = (report(client, n) for n in (20, 21, 22, 23, 24))
    assert clear(client, first, headers=OPERATOR).status_code == 200  # a person's clear is not counted
    assert all(clear(client, m).status_code == 200 for m in machine)  # D-1047: three a day (was one)
    assert code(clear(client, fifth, cause="other")) == (403, "AI_CLEAR_REPEAT_LIMIT")
    assert row(client, fifth)["state"] == "open"
    assert clear(client, fifth, headers=OPERATOR).status_code == 200  # the repeat goes to a person
    monkeypatch.setenv("ROSY_FLEET_ARM_ASSESSORS", "cell-a-ai-assessor=arm_b,arm_a")
    assert clear(client, report(client, 25, source="arm_a"), source="arm_a").status_code == 200  # another arm


def test_assessor_clears_only_its_own_arms(client):
    incident_id = report(client, 5, source="arm_a")
    assert code(clear(client, incident_id, source="arm_a")) == (403, "AI_CLEAR_ARM_NOT_ASSIGNED")
    assert row(client, incident_id, "arm_a")["state"] == "open"


def test_the_repeat_window_is_a_day_on_the_store_clock_and_counts_the_marker_not_the_name():
    clock = [1000.0]
    store = ArmIncidentStore(wall=lambda: clock[0])
    ids = [store.report(ArmIncidentReport.model_validate(body(n, SAFE))) for n in range(30, 37)]
    for n in range(MACHINE_CLEARS_PER_WINDOW):
        store.clear("arm_b", ids[n], "ok", "cell-a-ai-assessor", "blocked", "measured", True)
    clock[0] += REPEAT_WINDOW_S - 1
    with pytest.raises(MachineClearRefused):  # another assessor id on the same arm is still the same limit
        store.clear("arm_b", ids[3], "ok", "cell-a-renamed-assessor", "other", "seen", True)
    store.clear("arm_b", ids[3], "ok", "cell-a-ai-assessor", "blocked", "measured")  # a person-kind clear: no limit
    clock[0] += 2  # the first machine clears left the window
    store.clear("arm_b", ids[4], "ok", "cell-a-ai-assessor", "blocked", "measured", True)
    basis = {r["incident_id"]: r["cleared"] and r["cleared"]["basis"] for r in store.snapshot("arm_b")}
    assert [basis[i] for i in ids[:6]] == ["unknown", "unknown", "unknown", "measured", "unknown", None]


def test_assessor_reaches_no_other_route(client):
    incident_id = report(client, 3)
    for method, url in (("GET", PATH), ("GET", "/api/fleet/state"), ("POST", "/api/fleet/estop"),
                        ("POST", f"{PATH}/arms/arm_b/incidents/{incident_id}/explanation")):
        answer = client.request(method, url, headers=ASSESSOR, json={})
        assert code(answer) == (403, "ARM_ASSESSOR_SCOPE_REQUIRED"), (method, url)
    assert row(client, incident_id)["state"] == "open"


def test_no_assessor_unless_configured(client, monkeypatch):
    incident_id = report(client, 4)
    monkeypatch.delenv("ROSY_FLEET_ARM_ASSESSORS")
    assert code(clear(client, incident_id)) == (403, "FORBIDDEN")
    assert row(client, incident_id)["state"] == "open"


# D-1040: the two real kinds of 2026-11-17 (arm_b port lost writing torque OFF, arm_a wind-up holding home) clear only
# with a fresh quiet read of the arm sent with the clear; it is kept with the clear row
REMEASURE = Path(__file__).parents[3] / "contracts/foundation/test/fixtures/arm_incidents_remeasure"
PORT_LOST, WOUND_UP = (json.loads((REMEASURE / f"{name}.json").read_text(encoding="utf-8"))["facts"]
                       for name in ("20261117T171027-arm_b", "20261117T182025-arm_a"))
ZERO = {m: 0 for m in ("11", "12", "13", "14", "15", "16")}
# arm_b's one fault record of that port loss as the cell reads it again (the report holds only its name)
LOST = {"name": PORT_LOST["fault_records"][0], "fault_type": "SerialException",
        "fault": "device reports readiness to read but returned no data (device disconnected or multiple access on port?)"}


def read(incident_id, **over):
    return {"arm": "arm_b", "board_serial": BOARDS["arm_b"], "incident_id": incident_id, "at": time.time() + 1,
            "torque_after": ZERO, "hardware_error": ZERO, "folded": True, "max_home_err": 0.4,
            "frames": [{"role": "top", "sha256": "a" * 64}], "fault_records": [LOST], **over}


@pytest.mark.parametrize("facts", [PORT_LOST, WOUND_UP], ids=["port lost", "wound up"])
def test_assessor_clears_todays_real_kinds_only_with_a_fresh_quiet_read_which_the_row_keeps(client, facts):
    incident_id = report(client, 40, facts)
    assert code(clear(client, incident_id)) == (403, "AI_CLEAR_KIND_REFUSED")  # no read
    other = report(client, 41, facts)
    for bad in (read(incident_id, torque_after={**ZERO, "11": 1}), read(incident_id, hardware_error={**ZERO, "13": 32}),
                read(incident_id, folded=False), read(incident_id, at=time.time() - 3600),  # read before the incident
                read(other),  # a read made for another incident
                read(incident_id, arm="arm_a", board_serial=BOARDS["arm_a"]),  # another arm's read
                read(incident_id, board_serial=BOARDS["arm_a"])):  # this arm's name on another board
        assert code(clear(client, incident_id, remeasured=bad)) == (403, "AI_CLEAR_KIND_REFUSED")
    if facts is PORT_LOST:  # the port kind's fault record must be the lost port's text
        overload = {**LOST, "fault_type": "OverloadError", "fault": "hardware error: overload on id 13"}
        assert code(clear(client, incident_id, remeasured=read(incident_id, fault_records=[overload]))) == (
            403, "AI_CLEAR_KIND_REFUSED")
    assert clear(client, incident_id, remeasured=read(incident_id, torque_after={"11": 0})).status_code == 422
    assert row(client, incident_id)["state"] == "open"
    good = read(incident_id)
    assert clear(client, incident_id, remeasured=good).status_code == 200
    cleared = row(client, incident_id)["cleared"]
    assert cleared["kind"] == "machine" and cleared["remeasured"] == good
    # the day's limit (three, D-1047) still holds for the fourth on this arm, read or not
    extra = [other, report(client, 42, facts), report(client, 43, facts)]
    for incident in extra[:2]:
        assert clear(client, incident, remeasured=read(incident)).status_code == 200
    assert code(clear(client, extra[2], remeasured=read(extra[2]))) == (403, "AI_CLEAR_REPEAT_LIMIT")


def test_a_read_never_frees_another_kind_and_a_persons_clear_does_not_keep_it(client):
    for n, (kind, facts) in enumerate(UNSAFE.items(), start=50):
        incident_id = report(client, n, facts)
        assert code(clear(client, incident_id, remeasured=read(incident_id))) == (403, "AI_CLEAR_KIND_REFUSED"), kind
    incident_id = report(client, 60, PORT_LOST)
    assert clear(client, incident_id, headers=OPERATOR, remeasured=read(incident_id)).status_code == 200
    assert row(client, incident_id)["cleared"]["remeasured"] is None  # a person's clear does not judge the read


HOME6 = [0.0, -58.0, 50.0, 50.0, -5.0, 48.8]


def fold(incident_id, **over):
    return {"kind": "auto_fold", "incident_id": incident_id, "taken_at": 1.0e12, "folded_state": [0.0, -58.0, 50.5, 50.0, -5.0, 48.8],
            "home": HOME6, "torque_after": {str(i): 0 for i in range(11, 17)}, "corridor_clear": True,
            "candidate": "park", **over}


def test_an_extended_contact_stop_clears_only_with_measured_auto_fold_evidence_for_it(client):
    stopped = {**SAFE, "folded": False, "home": HOME6,
               "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}
    incident_id = report(client, 80, stopped)
    assert code(clear(client, incident_id)) == (403, "AI_CLEAR_KIND_REFUSED")  # no fold: still a person
    out_on_reach = fold(incident_id, folded_state=[20.0, -20.0, 20.0, 45.0, -5.0, 48.8])
    assert code(clear(client, incident_id, recovery=out_on_reach)) == (403, "AI_CLEAR_KIND_REFUSED")
    assert code(clear(client, incident_id, recovery=fold("another"))) == (403, "AI_CLEAR_KIND_REFUSED")
    assert clear(client, incident_id, recovery=fold(incident_id)).status_code == 200
    assert row(client, incident_id)["recovery"]["auto_fold"]["kind"] == "auto_fold"
    latched = report(client, 81, {**stopped, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}})
    assert code(clear(client, latched, recovery=fold(latched))) == (403, "AI_CLEAR_KIND_REFUSED")
