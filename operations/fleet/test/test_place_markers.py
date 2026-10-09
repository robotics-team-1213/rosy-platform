"""D-564: floor place markers are source-scoped, leased, and teach only draft places."""

from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

NOW = 1_790_000_000.0
SOURCE = {"Authorization": "Bearer source-secret"}
OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
MAP = {"places": [{"id": "A", "name": "주차", "x": 0.0, "y": 0.0, "kind": "park"},
                  {"id": "B", "name": "충전", "x": 2.0, "y": 0.0, "kind": "charge"}],
       "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]],
                  "width_m": 0.2, "speed_cap_mps": 0.2}]}


class _Clock:
    now = NOW

    def __call__(self):
        return self.now


def _app(tmp_path, *, place_markers=(34, 35, 36, 37, 38), map_id="site"):
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    store.import_if_empty(SiteMap.model_validate(MAP), source="test")
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    clock = _Clock()
    sightings = SightingService([SightingSource(
        source_id="ceiling-east", token="source-secret", robot_ids=("rosy_60",), map_id=map_id,
        calibration_revision="cal-v3", corner_marker_ids=(30, 31, 32, 33), robot_markers=(("rosy_60", 40),),
        place_markers=place_markers)], known_robot_ids=console.robot_ids, clock=clock)
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store, sightings=sightings)
    return TestClient(app), clock, store


def _payload(**changes):
    body = {"map_id": "site", "calibration_revision": "cal-v3", "captured_at": NOW - 0.1, "seq": 5,
            "markers": [{"marker_id": 34, "x": 1.5, "y": 0.75, "yaw": 1.0}]}
    body.update(changes)
    return body


def test_place_marker_ingest_is_source_scoped_ordered_and_leased(tmp_path):
    client, clock, _store = _app(tmp_path)
    post = lambda body, headers=SOURCE: client.post("/api/fleet/place-markers", json=body, headers=headers)
    with client:
        assert post(_payload(), headers={}).status_code == 401
        assert post(_payload(), headers=OPERATOR).status_code == 401
        assert post(_payload(source_id="x")).status_code == 422
        refused = {
            "PLACE_MARKER_FORBIDDEN": _payload(markers=[{"marker_id": 39, "x": 0, "y": 0, "yaw": 0}]),
            "MAP_MISMATCH": _payload(map_id="other"),
            "CALIBRATION_MISMATCH": _payload(calibration_revision="cal-v2"),
            "SIGHTING_STALE": _payload(captured_at=NOW - 2.5),
            "SIGHTING_FUTURE": _payload(captured_at=NOW + 1.0),
        }
        for code, body in refused.items():
            answer = post(body)
            assert answer.json()["detail"]["code"] == code, code
        accepted = post(_payload())
        assert accepted.status_code == 200
        assert accepted.json()["markers"][0]["source_id"] == "ceiling-east"
        assert post(_payload()).json()["detail"]["code"] == "SIGHTING_OUT_OF_ORDER"
        assert client.get("/api/fleet/place-markers").status_code == 401
        clock.now += 3.0
        seen = client.get("/api/fleet/place-markers", headers=VIEWER).json()
        assert [(m["marker_id"], m["stale"]) for m in seen["markers"]] == [(34, True)]
        assert seen["lease_s"] == 2.0


def test_teach_place_from_marker_adds_or_moves_a_draft_place_and_refuses_stale(tmp_path):
    client, clock, store = _app(tmp_path)
    teach = lambda body, headers=OPERATOR: client.post("/api/fleet/teach/place-from-marker", json=body,
                                                       headers=headers)
    with client:
        stale = teach({"marker_id": 34, "name": "출발 남", "kind": "start"})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "PLACE_MARKER_STALE"
        assert client.post("/api/fleet/place-markers", json=_payload(), headers=SOURCE).status_code == 200
        assert teach({"marker_id": 34, "name": "출발 남"}, headers=VIEWER).status_code == 403
        added = teach({"marker_id": 34, "name": "출발 남", "kind": "start"})
        assert added.status_code == 200, added.text
        place = next(p for p in added.json()["draft"]["map"]["places"] if p["id"] == added.json()["place_id"])
        assert (place["x"], place["y"], place["yaw"], place["kind"]) == (1.5, 0.75, 1.0, "start")
        revision = added.json()["draft"]["revision"]
        moved = teach({"marker_id": 34, "place_id": "B", "expected_revision": revision})
        assert moved.status_code == 200, moved.text
        b = next(p for p in moved.json()["draft"]["map"]["places"] if p["id"] == "B")
        assert (b["x"], b["y"], b["yaw"], b["name"], b["kind"]) == (1.5, 0.75, 1.0, "충전", "charge")
        assert teach({"marker_id": 34, "place_id": "nope"}).json()["detail"]["code"] == "PLACE_UNKNOWN"
        assert teach({"marker_id": 34}).json()["detail"]["code"] == "PLACE_NAME_REQUIRED"
        clock.now += 2.5
        assert teach({"marker_id": 34, "name": "늦음"}).json()["detail"]["code"] == "PLACE_MARKER_STALE"
    events = [e for e in store.events() if e["action"] == "teach_place"]
    assert [(e["detail"]["marker_id"], e["detail"]["updated"]) for e in events] == [(34, False), (34, True)]
    assert store.active()[1].places[1].x == 2.0   # the active map is untouched


def test_teach_from_marker_refuses_another_map_and_a_site_without_place_markers(tmp_path):
    client, _clock, _store = _app(tmp_path, map_id="other-map")
    with client:
        assert client.post("/api/fleet/place-markers", json=_payload(map_id="other-map"),
                           headers=SOURCE).status_code == 200
        answer = client.post("/api/fleet/teach/place-from-marker", json={"marker_id": 34, "name": "x"},
                             headers=OPERATOR)
        assert answer.status_code == 409 and answer.json()["detail"]["code"] == "PLACE_MARKER_MAP_MISMATCH"
    client, _clock, _store = _app(tmp_path / "off", place_markers=())
    with client:
        answer = client.post("/api/fleet/teach/place-from-marker", json={"marker_id": 34, "name": "x"},
                             headers=OPERATOR)
        assert answer.status_code == 503 and answer.json()["detail"]["code"] == "PLACE_MARKERS_DISABLED"
