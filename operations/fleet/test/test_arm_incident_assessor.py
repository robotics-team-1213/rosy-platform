"""D-1039: an AI assessor service clears only safe arm incidents, once per arm and cause a day; people clear all."""
from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from core_common.protocol.arm_incidents import ArmIncidentReport
from core_common.protocol.workcell_observations import WorkcellObservationManifest
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.arm_incidents import REPEAT_WINDOW_S, ArmIncidentStore, MachineClearRefused
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.workcell_observations import WorkcellObservations
from fleet.swarm.robots import RobotEndpoint

PATH = "/api/fleet/workcell-observations"
SOURCE = {"X-Workcell-Observation-Token": "arm-b-secret"}
TOKENS = {"assessor-token": ("cell-a-ai-assessor", "service"), "operator-token": ("op-7", "operator")}
ASSESSOR, OPERATOR = {"Authorization": "Bearer assessor-token"}, {"Authorization": "Bearer operator-token"}
WHY = {"note": "folded home, torque off, frames clear", "cause": "blocked", "basis": "measured"}
# 2026-11-17 night: a guard stop on contact while parking, the arm then folded home with torque OFF
SAFE = {"safe_end": True, "latched": {}, "torque_after": {"11": 0, "12": 0, "13": 0}, "folded": True, "windup_hits": [],
        "flagged": [{"command": "park", "error": "contact in park: shoulder_lift lag rose to 2.2 units at PWM -321",
                     "fault": None, "caught": None, "t": 3.2}]}
UNSAFE = {
    "latched": {**SAFE, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}},
    "unfolded": {**SAFE, "folded": False},
    "unsafe end": {**SAFE, "safe_end": False},
    "torque unknown": {**SAFE, "torque_after": {}},
    "torque on": {**SAFE, "torque_after": {"11": 0, "12": 1}},
    "snag": {**SAFE, "windup_hits": [{"reason": "elbow wound up 40 units"}]},
    "caught jaw": {**SAFE, "flagged": [{"command": "grip", "error": "jaws caught", "caught": True}]},
    "truncated": {"safe_end": True, "folded": True, "torque_after": {"11": 0}, "latched": {}, "truncated": True},
}


def body(n, facts):
    return {"source_id": "arm_b", "session_id": f"6f1c2a3e-1b2d-4e5f-8a9b-{n:012x}", "facts": facts,
            "decision": {"hold": True, "reason": "runner: contact in park"}}


def service():
    def arm(name, secret):
        return {"source_id": name, "arm_id": name, "label": name, "board_id": f"{name}-board",
                "joint_topic": f"/omx_commissioning/{name}/joint_states", "joint_names": ["joint1"],
                "token_env": f"{name.upper()}_TOKEN", "credential_sha256": sha256(secret.encode()).hexdigest()}
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "bench", "label": "Bench", "arms": [arm("arm_b", "arm-b-secret")], "cameras": []}]})
    return WorkcellObservations(manifest, {"arm_b": "arm-b-secret"}, wall=lambda: 100.0, monotonic=lambda: 10.0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ROSY_FLEET_ARM_ASSESSORS", raising=False)
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-secret")], [FakeRobot("rosy_01")])
    users = {sha256(t.encode()).hexdigest(): {"principal_id": n, "role": r} for t, (n, r) in TOKENS.items()}
    app = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                                            robot_ids=("rosy_01",)),
                     start_task_dispatcher=False, site_users=users, cell_job_compiler=None,
                     workcell_observations=service())
    return TestClient(app)


def report(client, n, facts=SAFE):
    answer = client.post(f"{PATH}/arms/arm_b/incidents", json=body(n, facts), headers=SOURCE)
    assert answer.status_code == 200, answer.text
    return answer.json()["incident_id"]


def clear(client, incident_id, headers=ASSESSOR, **over):
    return client.post(f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", json={**WHY, **over}, headers=headers)


def row(client, incident_id):
    listed = client.get(PATH, headers=OPERATOR).json()["workcells"][0]["arms"][0]["incidents"]
    return next(r for r in listed if r["incident_id"] == incident_id)


def test_assessor_clears_a_folded_safe_incident_and_is_recorded_as_the_clearer(client):
    incident_id = report(client, 1)
    answer = clear(client, incident_id)
    assert answer.status_code == 200 and answer.json()["held"] is False
    assert row(client, incident_id)["cleared"] | {"at": 0} == {"by": "cell-a-ai-assessor", "at": 0, "note": WHY["note"],
                                                               "cause": "blocked", "basis": "measured"}


def test_assessor_is_refused_every_kind_that_is_not_safe_and_a_person_still_clears_it(client):
    for n, (kind, facts) in enumerate(UNSAFE.items(), start=10):
        incident_id = report(client, n, facts)
        answer = clear(client, incident_id)
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "AI_CLEAR_KIND_REFUSED", kind
        assert row(client, incident_id)["state"] == "open", kind
        human = client.post(f"{PATH}/arms/arm_b/incidents/{incident_id}/clear", json={"note": "checked"},
                            headers=OPERATOR)
        assert human.status_code == 200 and row(client, incident_id)["cleared"]["by"] == "op-7", kind


def test_assessor_must_name_a_cause_and_its_basis(client):
    incident_id = report(client, 2)
    for missing in ({"cause": None}, {"basis": None}):
        answer = clear(client, incident_id, **missing)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "AI_CLEAR_CAUSE_REQUIRED"
    assert clear(client, incident_id, note="").status_code == 422
    assert row(client, incident_id)["state"] == "open"


def test_one_assessor_clear_per_arm_and_cause_a_day_and_human_clears_do_not_count(client):
    first, second, third, other = (report(client, n) for n in (20, 21, 22, 23))
    assert clear(client, first, headers=OPERATOR).status_code == 200  # a person's blocked clear is not counted
    assert clear(client, second).status_code == 200
    refused = clear(client, third)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "AI_CLEAR_REPEAT_LIMIT"
    assert row(client, third)["state"] == "open"
    assert clear(client, other, cause="other").status_code == 200  # another cause class
    assert clear(client, third, headers=OPERATOR).status_code == 200  # the repeat goes to a person


def test_the_repeat_window_is_a_day_on_the_store_clock():
    clock = [1000.0]
    store = ArmIncidentStore(wall=lambda: clock[0])
    ids = [store.report(ArmIncidentReport.model_validate(body(n, SAFE))) for n in (30, 31, 32)]
    machine = frozenset({"cell-a-ai-assessor"})
    store.clear("arm_b", ids[0], "ok", "cell-a-ai-assessor", "blocked", "measured", machine)
    clock[0] += REPEAT_WINDOW_S - 1
    with pytest.raises(MachineClearRefused):
        store.clear("arm_b", ids[1], "ok", "cell-a-ai-assessor", "blocked", "measured", machine)
    clock[0] += 2
    store.clear("arm_b", ids[1], "ok", "cell-a-ai-assessor", "blocked", "measured", machine)
    store.clear("arm_b", ids[2], "ok", "op-7", "blocked", "measured")  # a person: no limit
    assert store.hold("arm_b").held is False


def test_assessor_reaches_no_other_route(client):
    incident_id = report(client, 3)
    for method, url in (("GET", PATH), ("GET", "/api/fleet/state"), ("POST", "/api/fleet/estop"),
                        ("POST", f"{PATH}/arms/arm_b/incidents/{incident_id}/explanation")):
        answer = client.request(method, url, headers=ASSESSOR, json={})
        assert answer.status_code == 403, (method, url)
        assert answer.json()["detail"]["code"] == "ARM_ASSESSOR_SCOPE_REQUIRED", (method, url)
    assert row(client, incident_id)["state"] == "open"


def test_the_assessor_list_is_configured_and_other_services_stay_out(client, monkeypatch):
    incident_id = report(client, 4)
    monkeypatch.setenv("ROSY_FLEET_ARM_ASSESSORS", "cell-b-ai-assessor")
    answer = clear(client, incident_id)
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "FORBIDDEN"
    monkeypatch.setenv("ROSY_FLEET_ARM_ASSESSORS", "cell-b-ai-assessor, cell-a-ai-assessor")
    assert clear(client, incident_id).status_code == 200
