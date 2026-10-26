"""D-891: Fleet re-checks an uploaded D-874 bundle and records one decision by a second policy admin."""

import hashlib
import sqlite3
import sys
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "contracts/learning/src"))

from rosy.contracts.learning.promotion_request import encoded  # noqa: E402
from fleet.server.app import create_app  # noqa: E402
from fleet.server.console import FleetConsole  # noqa: E402
from fleet.server.site_users import hash_password  # noqa: E402
from fleet.server.task_service import FleetTaskService  # noqa: E402
from fleet.server.task_store import FleetTaskStore  # noqa: E402

TOKENS = {"admin-a": "policy-admin", "admin-b": "policy-admin", "operator-a": "operator", "viewer-a": "viewer"}
URL = "/api/fleet/perception-promotions"
SITE = "https://rosy-site.local:8443"


def auth(name):
    return {"Authorization": f"Bearer {name}-token"}


def bundle(**change):
    doc = {"schema": "rosy.learning.promotion-request/1", "state": "requested", "requester": "검수자",
           "created_at": "2026-10-25T00:00:00+00:00",
           "model": {"revision": "seg-r7", "files": [{"name": "model.pt", "sha256": "b" * 64}]},
           "dataset": {"name": "pinky-floor", "revision": "c" * 64,
                       "external_sources": {"huggingface_frames": 0, "percent": 0.0, "groups": [],
                                            "split": "train_only", "own_forced_train": 0}},
           "evaluation": {"set": "floor-eval", "content_sha": "d" * 64, "sources": ["human_reviewed_eval"],
                          "frames": 40, "miou": 0.71, "iou": [{"class": "floor", "value": 0.8}]},
           "training": {"commit": "e" * 40, "python": "3.12.3", "torch": "2.4.0"}}
    for path, value in change.items():
        *parents, last = path.split(".")
        target = doc
        for key in parents:
            target = target[key]
        target[last] = value
    return doc


def upload(client, raw, who="admin-a", claimed=None, headers=None):
    return client.post(URL, params={"sha256": claimed or hashlib.sha256(raw).hexdigest()},
                       content=raw, headers={**auth(who), **(headers or {})} if who else headers)


@pytest.fixture
def made(tmp_path):
    db = tmp_path / "fleet.db"
    users = {sha256(f"{name}-token".encode()).hexdigest(): {"principal_id": name, "role": role}
             for name, role in TOKENS.items()}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
                     site_users=users, omx_instances={"cell-1": "arm-1"}, omx_stop_transport=object(),
                     start_task_dispatcher=False)
    return TestClient(app), db


def code(response):
    return response.json()["detail"]["code"]


def test_a_second_admin_records_one_decision_and_nothing_else_moves(made, tmp_path):
    client, db = made
    accepted = tmp_path / "models/accepted"
    accepted.mkdir(parents=True)
    raw = encoded(bundle())
    proposed = upload(client, raw)
    assert proposed.status_code == 200, proposed.text
    digest = proposed.json()["bundle_sha256"]
    assert digest == hashlib.sha256(raw).hexdigest() and proposed.json()["state"] == "PENDING"
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if not p.name.startswith("fleet.db"))

    decided = client.post(f"{URL}/{digest}/decision", headers=auth("admin-b"),
                          json={"operator_confirmed": True, "decision": "APPROVED"})
    assert decided.status_code == 200, decided.text
    row = decided.json()
    assert (row["state"], row["decided_by"], row["model_revision"]) == ("APPROVED", "admin-b", "seg-r7")
    assert row["files"] == [{"name": "model.pt", "sha256": "b" * 64}]
    # Approval moves no registry pointer, writes no models/accepted file and grants no policy stage.
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if not p.name.startswith("fleet.db")) == before
    assert not any(accepted.iterdir())
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM fleet_policy_stage").fetchone()[0] == 0
    assert client.get(URL, headers=auth("viewer-a")).json()["proposals"][0]["state"] == "APPROVED"
    assert client.get(f"{URL}/{digest}", headers=auth("viewer-a")).json()["bundle"] == bundle()

    again = client.post(f"{URL}/{digest}/decision", headers=auth("admin-b"),
                        json={"operator_confirmed": True, "decision": "REJECTED"})
    assert (again.status_code, code(again)) == (409, "PROPOSAL_ALREADY_DECIDED")


@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
def test_the_proposer_never_decides(made, decision):
    client, _ = made
    digest = upload(client, encoded(bundle())).json()["bundle_sha256"]
    refused = client.post(f"{URL}/{digest}/decision", headers=auth("admin-a"),
                          json={"operator_confirmed": True, "decision": decision})
    assert (refused.status_code, code(refused)) == (403, "APPROVER_MUST_DIFFER_FROM_PROPOSER")


@pytest.mark.parametrize("who", ["operator-a", "viewer-a"])
def test_only_policy_admins_propose_or_decide(made, who):
    client, _ = made
    raw = encoded(bundle())
    assert upload(client, raw, who).status_code == 403
    digest = upload(client, raw).json()["bundle_sha256"]
    assert client.post(f"{URL}/{digest}/decision", headers=auth(who),
                       json={"operator_confirmed": True, "decision": "APPROVED"}).status_code == 403


def test_hash_mismatch_and_non_canonical_bytes_are_refused(made):
    client, _ = made
    raw = encoded(bundle())
    assert code(upload(client, raw, claimed="f" * 64)) == "BUNDLE_HASH_MISMATCH"
    for other in (raw.rstrip(b"\n"), raw.decode().encode("ascii", "backslashreplace"),
                  raw.replace(b": ", b":"), b"\xef\xbb\xbf" + raw, b"{not json"):
        response = upload(client, other)
        assert response.status_code == 422 and code(response) in {"BUNDLE_NOT_CANONICAL", "BUNDLE_NOT_JSON"}
    assert client.get(URL, headers=auth("viewer-a")).json()["proposals"] == []


@pytest.mark.parametrize("change", [
    {"approved_by": "admin-b"},                                 # forbidden key at the top
    {"model.files": [{"name": "m.pt", "sha256": "b" * 64, "stage": "L3"}]},  # nested forbidden key
    {"evaluation.sources": ["human_reviewed_eval", "lidar"]},   # not human-confirmed truth
    {"evaluation.sources": ["huggingface"]},
    {"dataset.external_sources.split": "eval"},                 # HF frames used for evaluation
    {"state": "approved"},
])
def test_the_shared_d874_validator_refuses(made, change):
    client, _ = made
    response = upload(client, encoded(bundle(**change)))
    assert (response.status_code, code(response)) == (422, "BUNDLE_INVALID")


def test_oversize_upload_is_refused_unread(made):
    client, _ = made
    from fleet.server.perception_promotion import MAX_BUNDLE_BYTES
    response = upload(client, b" " * (MAX_BUNDLE_BYTES + 1))
    assert (response.status_code, code(response)) == (413, "BUNDLE_TOO_LARGE")


def test_the_same_bundle_is_queued_once(made):
    client, _ = made
    raw = encoded(bundle())
    upload(client, raw)
    assert code(upload(client, raw, "admin-b")) == "PROPOSAL_ALREADY_EXISTS"


def test_cookie_upload_without_this_console_origin_is_refused(tmp_path):
    password = "correct horse"
    logins = {"alice": {"principal_id": "alice", "role": "operator", "policy_admin": True,
                        "password_scrypt": hash_password(password)}}
    db = tmp_path / "fleet.db"
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
                     site_users={}, site_logins=logins, omx_instances={}, omx_stop_transport=object(),
                     start_task_dispatcher=False)
    client = TestClient(app, base_url=SITE)
    assert client.post("/api/fleet/auth/login", headers={"Origin": SITE},
                       json={"login": "alice", "password": password, "remember": False}).status_code == 204
    raw = encoded(bundle())
    refused = upload(client, raw, who=None, headers={})
    assert (refused.status_code, code(refused)) == (403, "CSRF_REJECTED")
    assert upload(client, raw, who=None, headers={"Origin": SITE}).status_code == 200
