"""ARM-CELL run/recover proxy: only three jobs and three reads reach the cell job API (:8781), as the named operator.

A fake job API records what Fleet sends. Cases: allowlist, proposer equal to the operator refused before sending,
the job API's refusal passed through with its own status and body, viewer read-only, config never from the browser.
"""

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.cell_job_proxy_routes import CellJobProxy, load_config
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

OP = {"Authorization": "Bearer op-token"}
VIEW = {"Authorization": "Bearer viewer-token"}
ARM_FILES = {"config": "cell-a.json", "library": "lib-a.json", "site": "s1", "roi": "1,2,3,4"}
MODEL = {"id": "m1", "label": "A 운반 v3", "policy_root": "policies/a", "policy_revision": "f" * 64}


class FakeJobApi:
    def __init__(self, reply=(202, {"id": "20261126-101010-abc123"})):
        self.calls, self.reply = [], reply

    def __call__(self, method, url, token, body=None):
        self.calls.append((method, url, token, body))
        return self.reply


@pytest.fixture
def setup(tmp_path):
    token = tmp_path / "cell-job.token"
    token.write_text("cell-secret\n", encoding="utf-8")
    users = {sha256(b"op-token").hexdigest(): {"principal_id": "operator-a", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "viewer-a", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=())
    app = create_app(FleetConsole([], []), task_service=tasks, site_users=users, start_task_dispatcher=False)
    fake = FakeJobApi()
    cells = {"cell_ab": {"url": "http://cell:8781/", "token_file": str(token),
                         "arms": {"arm_a": ARM_FILES, "arm_b": ARM_FILES}, "models": [MODEL]}}
    app.state.cell_job_proxy = CellJobProxy(cells, request_fn=fake)
    return TestClient(app), fake


RUN = {"arm": "arm_a", "proposer": "proposer-b", "mode": "act", "model": "m1", "max_chunks": 3,
       "paced_chunks": True, "dry_run": True}


def test_policy_drive_carries_the_named_operator_and_fleet_side_files(setup):
    client, fake = setup
    res = client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP, json=RUN)
    assert res.status_code == 202 and res.json() == {"id": "20261126-101010-abc123"}
    method, url, token, body = fake.calls[0]
    assert (method, url, token) == ("POST", "http://cell:8781/jobs/cell_policy_drive", "cell-secret")
    assert body == {"arm": "arm_a", "operator": "operator-a", "proposer": "proposer-b", "config": "cell-a.json",
                    "library": "lib-a.json", "max_chunks": 3, "dry_run": True, "mode": "act", "paced_chunks": True,
                    "policy_root": "policies/a", "policy_revision": "f" * 64}


def test_model_run_settings_come_only_from_the_host_list(setup):
    """2026-11-27: real runs need the backend, calibration, goal and step budget the CLI passed; only listed keys pass."""
    client, fake = setup
    conf = client.app.state.cell_job_proxy.cells["cell_ab"]
    conf["models"] = [{**MODEL, "params": {"act_backend": "openvino", "goal_slot": 1, "n_action": 16,
                                           "model_calibration": "cal-a.json", "operator": "x", "dry_run": False}}]
    assert client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP, json=RUN).status_code == 202
    body = fake.calls[0][3]
    assert (body["act_backend"], body["goal_slot"], body["n_action"], body["model_calibration"]) == ("openvino", 1, 16, "cal-a.json")
    assert body["operator"] == "operator-a" and body["dry_run"] is True
    assert "cal-a.json" not in client.get("/api/fleet/cells/cell_ab/jobs/options", headers=OP).text


@pytest.mark.parametrize("job", ["recover_hold", "safe_home"])
def test_recovery_jobs_send_the_arm_site_files(setup, job):
    client, fake = setup
    assert client.post(f"/api/fleet/cells/cell_ab/jobs/{job}", headers=OP,
                       json={"arm": "arm_b", "proposer": "proposer-b"}).status_code == 202
    assert fake.calls[0][1].endswith(f"/jobs/{job}")
    assert fake.calls[0][3] == {"arm": "arm_b", "operator": "operator-a", "proposer": "proposer-b", **ARM_FILES}


@pytest.mark.parametrize("job", ["cell_policy_run", "home", "auto_carry", "cell_two_arm_policy", "stop"])
def test_jobs_outside_the_allowlist_never_reach_the_cell(setup, job):
    client, fake = setup
    res = client.post(f"/api/fleet/cells/cell_ab/jobs/{job}", headers=OP, json={"arm": "arm_a", "proposer": "p"})
    assert res.status_code == 404 and res.json()["error_code"] == "CELL_JOB_NOT_ALLOWED"
    assert fake.calls == []


@pytest.mark.parametrize("body", [{**RUN, "config": "other.json"}, {**RUN, "operator": "someone"},
                                  {**RUN, "policy_root": "/etc"}, {**RUN, "dry_run": "false"}])
def test_browser_cannot_name_files_or_the_operator(setup, body):
    client, fake = setup
    assert client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP, json=body).status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize("proposer", ["operator-a", "Operator-A ", " OPERATOR-a"])
def test_proposer_equal_to_the_operator_is_refused_before_sending(setup, proposer):
    client, fake = setup
    res = client.post("/api/fleet/cells/cell_ab/jobs/safe_home", headers=OP, json={"arm": "arm_a", "proposer": proposer})
    assert res.status_code == 400 and res.json()["error_code"] == "PROPOSER_IS_OPERATOR"
    assert fake.calls == []


def test_unknown_arm_and_model_are_refused(setup):
    client, fake = setup
    assert client.post("/api/fleet/cells/cell_ab/jobs/safe_home", headers=OP,
                       json={"arm": "arm_s", "proposer": "p"}).json()["error_code"] == "ARM_NOT_CONFIGURED"
    assert client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP,
                       json={**RUN, "model": "nope"}).json()["error_code"] == "MODEL_NOT_CONFIGURED"
    assert fake.calls == []


def test_job_api_refusal_passes_through_unchanged(setup):
    client, fake = setup
    refusal = {"error_code": "PEER_ARM_NOT_FOLDED", "error": "arm_b is not folded"}
    fake.reply = (409, refusal)
    res = client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP, json=RUN)
    assert res.status_code == 409
    assert {k: res.json()[k] for k in refusal} == refusal
    assert res.json()["detail"] == {"code": "PEER_ARM_NOT_FOLDED", "message": "arm_b is not folded"}
    fake.reply = (400, {"error": "operator must differ from proposer (D-1024)"})
    res = client.post("/api/fleet/cells/cell_ab/jobs/cell_policy_drive", headers=OP, json=RUN)
    assert res.status_code == 400 and res.json()["error"] == "operator must differ from proposer (D-1024)"


def test_viewer_reads_but_cannot_start(setup):
    client, fake = setup
    fake.reply = (200, {"arms": {"arm_a": {"folded": True}}})
    assert client.get("/api/fleet/cells/cell_ab/jobs/readiness", headers=VIEW).json() == {"arms": {"arm_a": {"folded": True}}}
    assert fake.calls[-1][:2] == ("GET", "http://cell:8781/readiness?cell=cell_ab")
    assert client.get("/api/fleet/cells/cell_ab/jobs/queue", headers=VIEW).status_code == 200
    assert client.get("/api/fleet/cells/cell_ab/jobs/20261126-101010-abc123", headers=VIEW).status_code == 200
    assert fake.calls[-1][1] == "http://cell:8781/jobs/20261126-101010-abc123"
    sent = len(fake.calls)
    res = client.post("/api/fleet/cells/cell_ab/jobs/safe_home", headers=VIEW, json={"arm": "arm_a", "proposer": "p"})
    assert res.status_code == 403 and len(fake.calls) == sent
    assert client.get("/api/fleet/cells/cell_ab/jobs/readiness").status_code in (401, 403)


def test_options_show_models_without_paths(setup):
    client, _ = setup
    body = client.get("/api/fleet/cells/cell_ab/jobs/options", headers=VIEW).json()
    assert body == {"cell": "cell_ab", "arms": ["arm_a", "arm_b"],
                    "models": [{"id": "m1", "label": "A 운반 v3", "policy_revision": "f" * 64}]}


def test_unconfigured_cell_and_unreachable_api(setup, tmp_path):
    client, fake = setup
    res = client.get("/api/fleet/cells/cell_s/jobs/readiness", headers=VIEW)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "CELL_JOBS_NOT_CONFIGURED"

    def down(*_a, **_k):
        raise OSError("refused")
    client.app.state.cell_job_proxy.request_fn = down
    res = client.get("/api/fleet/cells/cell_ab/jobs/queue", headers=VIEW)
    assert res.status_code == 502 and res.json()["error_code"] == "CELL_JOB_API_UNREACHABLE"


def test_config_comes_from_the_fleet_host_file(tmp_path):
    assert load_config({}) == {}
    path = tmp_path / "cell-jobs.json"
    path.write_text('{"cells": {"cell_ab": {"url": "http://x:8781"}}}', encoding="utf-8")
    assert load_config({"ROSY_FLEET_CELL_JOBS": str(path)}) == {"cell_ab": {"url": "http://x:8781"}}
