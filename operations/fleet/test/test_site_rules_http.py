"""D-982: the site rules HTTP surface - draft/activate need a named operator, judge is read-only advice."""

from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}


def client_and_store(tmp_path):
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store)), store


def test_draft_activate_and_the_defaults_without_a_document(tmp_path):
    client, store = client_and_store(tmp_path)
    none = client.get("/api/fleet/site-rules/active", headers=VIEWER).json()
    assert none["version"] is None and none["rules"]["return"]["go_percent"] == 15.0
    body = {"rules": {"return": {"go_percent": 20}}, "expected_revision": None}
    assert client.put("/api/fleet/site-rules/draft", json=body, headers=VIEWER).status_code == 403
    saved = client.put("/api/fleet/site-rules/draft", json=body, headers=OPERATOR)
    assert saved.status_code == 200 and client.get("/api/fleet/site-rules/draft", headers=VIEWER).json()["rules"]
    past = client.put("/api/fleet/site-rules/draft", json={"rules": {"return": {"go_percent": 5}}}, headers=OPERATOR)
    assert past.status_code == 422
    stale = client.post("/api/fleet/site-rules/activate", json={"expected_revision": "old"}, headers=OPERATOR)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "SITE_RULES_DRAFT_CHANGED"
    done = client.post("/api/fleet/site-rules/activate", json={"expected_revision": saved.json()["revision"]},
                       headers=OPERATOR)
    assert done.status_code == 200 and done.json()["version"] == 1 and done.json()["activated_by"] == "bob"
    assert store.rules.active_rules().return_.go_percent == 20.0
    assert client.get("/api/fleet/site-rules/active").status_code == 401


def test_judge_answers_from_the_active_rules_and_sends_nothing(tmp_path):
    client, _store = client_and_store(tmp_path)
    ask = {"state": {"kind": "return", "robot_id": "rosy_60", "bays": ["C1"],
                     "robots": [{"robot_id": "rosy_60", "percent": 18}]}}
    first = client.post("/api/fleet/site-rules/judge", json=ask, headers=VIEWER).json()
    assert (first["verdict"], first["reason"], first["rules_source"], first["dispatch"]) \
        == ("refuse", "not_needed", "default", False)
    draft = client.put("/api/fleet/site-rules/draft", headers=OPERATOR,
                       json={"rules": {"return": {"go_percent": 20}}, "expected_revision": None}).json()
    by_draft = client.post("/api/fleet/site-rules/judge", json={**ask, "source": "draft"}, headers=VIEWER).json()
    assert (by_draft["verdict"], by_draft["rules_source"], by_draft["detail"]["bay"]) == ("go", "draft", "C1")
    assert client.post("/api/fleet/site-rules/judge", json=ask, headers=VIEWER).json()["rules_source"] == "default"
    client.post("/api/fleet/site-rules/activate", json={"expected_revision": draft["revision"]}, headers=OPERATOR)
    active = client.post("/api/fleet/site-rules/judge", json=ask, headers=VIEWER).json()
    assert (active["verdict"], active["rules_source"]) == ("go", "active")
    given = client.post("/api/fleet/site-rules/judge", headers=VIEWER,
                        json={**ask, "rules": {"return": {"go_percent": 30}, "formation": {"min_gap_m": 0.5}}}).json()
    assert given["rules_source"] == "given"
    assert client.post("/api/fleet/site-rules/judge", headers=VIEWER, json={"state": {"kind": "nope"}}).status_code == 422
    assert client.post("/api/fleet/site-rules/judge", json=ask).status_code == 401
