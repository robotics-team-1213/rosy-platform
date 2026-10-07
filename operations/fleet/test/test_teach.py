"""D-494 6: the teach service with a fake map pose provider, and the teach API (auth, audit)."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization.map_pose import MapPose
from fleet.server import teach_service
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.server.teach_service import TeachError, TeachService
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

MAP = {"places": [{"id": "A", "name": "주차", "x": 0.0, "y": 0.0, "kind": "park"},
                  {"id": "B", "name": "충전", "x": 2.0, "y": 0.0, "kind": "charge"}],
       "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]],
                  "width_m": 0.2, "speed_cap_mps": 0.2}]}


class Poses:
    def __init__(self):
        self.pose = MapPose(x=0.0, y=0.0, yaw=0.0, state="LOCALIZED", source="sighting", dead_reckon_m=0.0, age_s=0.0)
        self.refreshes = 0

    def at(self, x, y, state="LOCALIZED", dead_reckon_m=0.0):
        self.pose = MapPose(x=x, y=y, yaw=0.5, state=state, source="bridged", dead_reckon_m=dead_reckon_m, age_s=0.0)

    def arbitrated_pose(self, robot_id):
        return self.pose

    async def refresh(self, robot_id, force_rest=False):
        assert force_rest  # one REST read per sample, past the hub cache
        self.refreshes += 1


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def _service(active=True):
    store = SiteMapStore(clock=Clock())
    if active:
        store.import_if_empty(SiteMap.model_validate(MAP), source="test")
    poses, clock = Poses(), Clock()
    return TeachService(poses=poses, site_maps=store, roster=lambda: ["rosy_60"], clock=clock), poses, store, clock


def run(coro):
    return asyncio.run(coro)


async def _drive(service, poses, points):
    for x, y, *rest in points:
        poses.at(x, y, *rest)
        await service.sample()


def test_record_stop_confirm_appends_a_draft_edge_and_audits():
    service, poses, store, _clock = _service()

    async def go():
        poses.at(0.02, 0.0)
        view = await service.start("rosy_60", "bob")
        with pytest.raises(TeachError) as err:
            await service.start("rosy_60", "eve")
        assert err.value.code == "TEACH_BUSY" and err.value.status == 409
        await _drive(service, poses, [(0.05, 0.0), (0.5, 0.01), (1.0, 0.0), (1.0, 0.5, "LOCALIZED", 0.6),
                                      (1.5, 0.0, "DEGRADED", 0.3), (1.9, 0.0)])
        assert [p[:2] for p in service.view()["recording"]["points"]] == [
            [0.02, 0.0], [0.5, 0.01], [1.0, 0.0], [1.9, 0.0]]
        return view, await service.stop("bob")

    view, result = run(go())
    assert view["recording"]["robot_id"] == "rosy_60" and poses.refreshes >= 2
    assert result["polyline"] == [[0.02, 0.0], [1.9, 0.0]]                # RDP 0.02 m
    assert result["from_candidates"][0]["place_id"] == "A" and result["to_candidates"][0]["place_id"] == "B"
    assert store.draft_view()["map"] is None                               # stop never writes the map

    def confirm(**changes):
        args = dict(start="A", end={"name": "새 주소", "kind": "stop"}, direction="one_way", drive_mode="lane",
                    speed_cap_mps=0.2, width_m=None, expected_revision=None, principal_id="bob")
        return service.confirm(result["teach_id"], **{**args, **changes})

    with pytest.raises(TeachError) as err:                                  # 1.88 m from B
        confirm(start="B")
    assert (err.value.status, err.value.code) == (422, "TEACH_PLACE_TOO_FAR")
    with pytest.raises(TeachError) as err:                  # schema errors surface: a place 0.02 m from A
        confirm(start={"name": "겹침", "kind": "stop"})
    assert err.value.code == "SITE_MAP_INVALID" and err.value.detail["errors"]
    out = confirm()
    edge = next(e for e in out["draft"]["map"]["edges"] if e["id"] == out["edge_id"])
    place = next(p for p in out["draft"]["map"]["places"] if p["id"] == edge["to"])
    assert edge["from"] == "A" and edge["polyline"] == [[0.0, 0.0], [1.9, 0.0]] and edge["width_m"] == 0.185
    assert (place["name"], place["kind"]) == ("새 주소", "stop") and store.active()[0] == 1
    with pytest.raises(TeachError) as err:                                  # used once
        confirm()
    assert err.value.code == "TEACH_UNKNOWN"
    actions = [e["action"] for e in store.events()]
    assert actions[:4] == ["teach_confirmed", "draft_saved", "teach_stopped", "teach_started"]


def test_confirm_keeps_the_draft_revision_rule():
    service, poses, store, _clock = _service()

    async def go():
        await service.start("rosy_60", "bob")
        await _drive(service, poses, [(0.5, 0.0), (1.0, 0.0)])
        return await service.stop("bob")

    result = run(go())
    store.save_draft(SiteMap.model_validate(MAP), expected_revision=None, principal_id="eve")
    with pytest.raises(SiteMapError) as err:
        service.confirm(result["teach_id"], start="A", end={"name": "끝"}, direction="two_way", drive_mode="free",
                        speed_cap_mps=0.3, width_m=0.3, expected_revision=None, principal_id="bob")
    assert err.value.code == "SITE_MAP_DRAFT_CHANGED"
    revision = store.draft_view()["revision"]
    out = service.confirm(result["teach_id"], start="A", end={"name": "끝"}, direction="two_way",
                          drive_mode="free", speed_cap_mps=0.3, width_m=0.3, expected_revision=revision,
                          principal_id="bob")       # a refused confirm keeps the recording
    assert out["draft"]["saved_by"] == "bob" and len(out["draft"]["map"]["edges"]) == 2


def test_stop_without_confirm_is_dropped_after_10_minutes_and_short_runs_are_refused():
    service, poses, _store, clock = _service(active=False)

    async def record(points):
        poses.at(0.0, 0.0)
        await service.start("rosy_60", "bob")
        await _drive(service, poses, points)
        return await service.stop("bob")

    result = run(record([(1.0, 0.0)]))
    assert result["from_candidates"] == [] and service.view()["pending"] == [result]   # no map yet: new places
    clock.now += 1
    second = run(record([(1.0, 0.0)]))
    assert [p["teach_id"] for p in service.view()["pending"]] == [second["teach_id"], result["teach_id"]]
    clock.now += teach_service.PENDING_S - 0.5
    assert [p["teach_id"] for p in service.view()["pending"]] == [second["teach_id"]]  # 10 min after its stop
    clock.now += 1
    assert service.view()["pending"] == []
    with pytest.raises(TeachError) as err:
        service.confirm(result["teach_id"], start={"name": "a"}, end={"name": "b"}, direction="one_way",
                        drive_mode="lane", speed_cap_mps=0.2, width_m=None, expected_revision=None,
                        principal_id="bob")
    assert err.value.code == "TEACH_UNKNOWN"
    with pytest.raises(TeachError) as err:
        run(record([(0.05, 0.0)]))
    assert (err.value.status, err.value.code) == (422, "TEACH_TOO_SHORT")
    with pytest.raises(TeachError) as err:
        run(service.stop("bob"))
    assert (err.value.status, err.value.code) == (409, "TEACH_NOT_RECORDING")


def test_place_adds_an_address_at_the_localized_pose():
    service, poses, store, _clock = _service()
    poses.at(1.0, 0.5)
    out = run(service.place("rosy_60", name="정류장", kind="stop", expected_revision=None, principal_id="bob"))
    place = next(p for p in out["draft"]["map"]["places"] if p["id"] == out["place_id"])
    assert (place["x"], place["y"], place["yaw"], place["kind"]) == (1.0, 0.5, 0.5, "stop")
    assert store.events()[0]["detail"]["place_id"] == out["place_id"]


def test_untrusted_pose_refuses_start_and_place():
    service, poses, _store, _clock = _service()
    poses.at(0.0, 0.0, "DEGRADED", 0.1)
    for call in (service.start("rosy_60", "bob"), service.place("rosy_60", name="x", kind="stop",
                                                                expected_revision=None, principal_id="bob")):
        with pytest.raises(TeachError) as err:
            run(call)
        assert (err.value.status, err.value.code) == (422, "TEACH_POSE_UNTRUSTED")
    with pytest.raises(TeachError) as err:
        run(service.start("rosy_99", "bob"))
    assert err.value.code == "UNKNOWN_ROBOT"


OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}


def _app(tmp_path):
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    store.import_if_empty(SiteMap.model_validate(MAP), source="test")
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    poses = Poses()
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store, map_pose_port=poses)
    return TestClient(app), tasks, store, poses


def test_teach_api_needs_a_named_operator_and_is_audited(tmp_path):
    client, tasks, store, poses = _app(tmp_path)
    with client:
        assert client.post("/api/fleet/teach/start", json={"robot_id": "rosy_60"}, headers=VIEWER).status_code == 403
        assert client.post("/api/fleet/teach/start", json={"robot_id": "rosy_60"}).status_code == 401
        assert client.get("/api/fleet/teach", headers=VIEWER).json() == {"recording": None, "pending": []}
        started = client.post("/api/fleet/teach/start", json={"robot_id": "rosy_60"}, headers=OPERATOR)
        assert started.status_code == 200 and started.json()["recording"]["started_by"] == "bob"
        busy = client.post("/api/fleet/teach/start", json={"robot_id": "rosy_60"}, headers=OPERATOR)
        assert busy.status_code == 409 and busy.json()["detail"]["code"] == "TEACH_BUSY"
        poses.at(1.0, 0.0)
        client.portal.call(client.app.state.teach.sample)  # one sample now, not the 0.5 s loop
        stopped = client.post("/api/fleet/teach/stop", headers=OPERATOR).json()
        assert stopped["polyline"] == [[0.0, 0.0], [1.0, 0.0]]
        confirm = {"teach_id": stopped["teach_id"], "from": "A", "to": {"name": "중간", "kind": "stop"},
                   "speed_cap_mps": 0.2}
        assert client.post("/api/fleet/teach/confirm", json={**confirm, "speed_cap_mps": 0},
                           headers=OPERATOR).status_code == 422
        done = client.post("/api/fleet/teach/confirm", json=confirm, headers=OPERATOR)
        assert done.status_code == 200 and done.json()["edge_id"] == "teach_e1"
        poses.at(1.0, 0.5, "DEGRADED")
        untrusted = client.post("/api/fleet/teach/place", json={"robot_id": "rosy_60", "name": "여기"},
                                headers=OPERATOR)
        assert untrusted.status_code == 422 and untrusted.json()["detail"] == {
            "code": "TEACH_POSE_UNTRUSTED", "detail": {"state": "DEGRADED"}}
        poses.at(1.0, 0.5)
        stale = client.post("/api/fleet/teach/place", json={"robot_id": "rosy_60", "name": "여기"}, headers=OPERATOR)
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "SITE_MAP_DRAFT_CHANGED"
        placed = client.post("/api/fleet/teach/place", headers=OPERATOR, json={
            "robot_id": "rosy_60", "name": "여기", "expected_revision": done.json()["draft"]["revision"]})
        assert placed.status_code == 200 and placed.json()["place_id"] == "teach_p2"
    audit = [(r["path"], r["event_type"], r["status_code"]) for r in tasks.store.api_audit()]
    for path in ("start", "stop", "confirm", "place"):
        assert (f"/api/fleet/teach/{path}", "RESULT", 200) in audit
    assert {"teach_started", "teach_stopped", "teach_confirmed", "teach_place"} <= {e["action"] for e in store.events()}


def test_site_map_page_serves_the_teach_panel_under_the_csp(tmp_path):
    client, _tasks, _store, _poses = _app(tmp_path)
    page = client.get("/console/site-map")
    script = client.get("/console/assets/site-map-teach.js")
    assert page.status_code == 200 and script.status_code == 200
    assert "script-src 'self'" in page.headers["content-security-policy"]
    for element in ("teach-robot", "teach-start", "teach-stop", "teach-confirm", "teach-place"):
        assert f'id="{element}"' in page.text
    assert "style=" not in page.text and "innerHTML" not in script.text


def test_idle_or_full_recordings_stop_themselves_through_the_stop_path(monkeypatch):
    service, poses, store, clock = _service()

    async def idle():
        await service.start("rosy_60", "bob")
        await _drive(service, poses, [(0.5, 0.0)])
        clock.now += teach_service.PENDING_S
        assert not await service.idle_check()            # exactly 10 min: still recording
        clock.now += 1
        poses.at(0.5, 0.05)                              # too close to keep: no new point
        await service.sample()
        assert await service.idle_check()

    run(idle())
    stopped = store.events()[0]
    assert (stopped["action"], stopped["principal_id"], stopped["detail"]["reason"]) == (
        "teach_stopped", "system:teach_idle", "idle")
    assert service.view()["recording"] is None and len(service.view()["pending"]) == 1

    monkeypatch.setattr(teach_service, "MAX_POINTS", 2)

    async def full():
        poses.at(0.0, 0.0)
        await service.start("rosy_60", "bob")
        await _drive(service, poses, [(0.5, 0.0)])
        assert await service.idle_check()

    run(full())
    assert store.events()[0]["detail"]["reason"] == "full" and len(service.view()["pending"]) == 2
