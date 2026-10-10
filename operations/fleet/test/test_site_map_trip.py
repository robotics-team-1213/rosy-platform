"""D-488 M1: rosy.site_map/1 schema, draft/active store, lane graph import, and the
site map + D-490 trip API (plan only)."""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap, from_lane_graph
from fleet.swarm.robots import RobotEndpoint

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}


def _line(**edge) -> dict:
    body = {"places": [{"id": "A", "name": "주차-1", "x": 0, "y": 0, "kind": "park"},
                       {"id": "B", "name": "충전", "x": 2, "y": 0, "kind": "charge"}],
            "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]],
                       "width_m": 0.2, "speed_cap_mps": 0.2, **edge}]}
    return body


# ---- schema -------------------------------------------------------------------------

def test_schema_round_trips_and_defaults_one_way_lane():
    site = SiteMap.model_validate(_line())
    body = site.body()
    assert body["schema"] == "rosy.site_map/1" and body["edges"][0]["from"] == "A"
    assert body["edges"][0]["direction"] == "one_way" and body["edges"][0]["drive_mode"] == "lane"
    assert SiteMap.model_validate(body) == site


@pytest.mark.parametrize("change", [
    lambda b: b["places"].append(dict(b["places"][0])),                    # duplicate place id
    lambda b: b["edges"].append(dict(b["edges"][0])),                      # duplicate edge id
    lambda b: b["edges"][0].update({"to": "Z"}),                           # unknown endpoint
    lambda b: b["edges"][0].update({"polyline": [[0, 0], [1.9, 0]]}),      # ends 0.1 m off B
    lambda b: b["edges"][0].update({"width_m": 0}),
    lambda b: b["edges"][0].update({"speed_cap_mps": -0.1}),
    lambda b: b["edges"][0].update({"direction": "both"}),
    lambda b: b["places"][0].update({"kind": "garage"}),
    lambda b: b.update({"turn_bans": [{"at": "A", "from_edge": "ab", "to_edge": "zz"}]}),
])
def test_schema_refuses_bad_maps(change):
    body = _line()
    change(body)
    with pytest.raises(ValidationError):
        SiteMap.model_validate(body)


def test_lane_graph_import_keeps_edges_directions_and_nodes():
    site = from_lane_graph(LANE_GRAPH)
    assert sorted(p.id for p in site.places) == ["NE", "NW", "SE", "SW"]
    ways = {e.id: e.direction for e in site.edges}
    assert ways == {"east": "two_way", "west": "two_way", "ring_e": "one_way", "ring_n": "one_way",
                    "ring_s": "one_way", "ring_w": "one_way"}
    assert all(e.drive_mode == "lane" and e.width_m == pytest.approx(0.185) for e in site.edges)


# ---- store --------------------------------------------------------------------------

def test_store_imports_once_versions_activation_and_survives_reopen(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = SiteMapStore(path)
    assert store.active() is None and store.draft_view() == {"map": None, "revision": None}
    assert store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml") == 1
    assert store.import_if_empty(SiteMap.model_validate(_line()), source="other") is None
    assert store.active()[0] == 1 and store.active_view()["activated_by"] == "import:lane_graph.yaml"
    assert store.active()[3].line("ring_s").start == "SW"

    with pytest.raises(SiteMapError) as err:
        store.activate(expected_revision="x", principal_id="bob", route_active=False)
    assert err.value.code == "SITE_MAP_NO_DRAFT"
    draft = store.save_draft(SiteMap.model_validate(_line()), expected_revision=None, principal_id="bob")
    with pytest.raises(SiteMapError) as err:
        store.save_draft(SiteMap.model_validate(_line()), expected_revision=None, principal_id="eve")
    assert err.value.code == "SITE_MAP_DRAFT_CHANGED"
    with pytest.raises(SiteMapError) as err:
        store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=True)
    assert err.value.code == "SITE_MAP_ROUTE_ACTIVE" and store.active()[0] == 1
    view = store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=False)
    assert view["version"] == 2 and view["activated_by"] == "bob"
    assert store.draft_view()["map"] is None
    with pytest.raises(KeyError):
        store.active()[3].line("ring_s")
    store.close()

    again = SiteMapStore(path)
    assert again.active()[0] == 2 and [e.id for e in again.active()[1].edges] == ["ab"]
    again.close()


# ---- API ----------------------------------------------------------------------------

def _app(tmp_path, *, state=None, imported=True):
    pose = state or {"robot_id": "rosy_60", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                     "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    robot = FakeRobot("rosy_60", state=pose)
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    if imported:
        store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store)
    return TestClient(app), tasks, store, robot


def _on_ring_s(store):
    x, y, yaw = store.active()[2].arcs["ring_s:fwd"].point_at(0.1)
    return {"robot_id": "rosy_60", "pose": {"x": x, "y": y, "yaw": yaw},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def test_site_map_api_reads_edits_and_activates_with_audit(tmp_path):
    client, tasks, store, _robot = _app(tmp_path)
    active = client.get("/api/fleet/site-map/active", headers=VIEWER)
    assert active.status_code == 200 and active.json()["version"] == 1
    assert client.put("/api/fleet/site-map/draft", json={"map": _line()}, headers=VIEWER).status_code == 403
    saved = client.put("/api/fleet/site-map/draft", json={"map": _line()}, headers=OPERATOR)
    assert saved.status_code == 200 and saved.json()["saved_by"] == "bob"
    bad = client.put("/api/fleet/site-map/draft", json={"map": _line(width_m=0)}, headers=OPERATOR)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "SITE_MAP_INVALID"
    assert ["map", "edges", "0", "width_m"] in [e["loc"] for e in bad.json()["detail"]["detail"]["errors"]]
    stale = client.post("/api/fleet/site-map/activate", json={"expected_revision": "nope"}, headers=OPERATOR)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "SITE_MAP_DRAFT_CHANGED"
    done = client.post("/api/fleet/site-map/activate", json={"expected_revision": saved.json()["revision"]},
                       headers=OPERATOR)
    assert done.status_code == 200 and done.json()["version"] == 2
    audit = [(r["path"], r["event_type"], r["status_code"]) for r in tasks.store.api_audit()]
    assert ("/api/fleet/site-map/activate", "RESULT", 200) in audit


def test_activation_needs_a_named_operator_and_a_route_step_no_longer_blocks_it(tmp_path):
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    saved = client.put("/api/fleet/site-map/draft", json={"map": _line()}, headers=OPERATOR).json()
    routed = client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["ring_s"]},
                         headers={**OPERATOR, "Idempotency-Key": "r1"})
    assert routed.status_code == 200, routed.text
    # D-494 5: the guard is a running trip (test_trip_runner), not a /route step in the last 30 s
    done = client.post("/api/fleet/site-map/activate", json={"expected_revision": saved["revision"]},
                       headers=OPERATOR)
    assert done.status_code == 200

    anonymous = TestClient(create_app(FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")],
                                                   [FakeRobot("rosy_60")]),
                                      console_token="op", site_maps=SiteMapStore()))
    denied = anonymous.post("/api/fleet/site-map/activate", json={"expected_revision": "r"},
                            headers={"Authorization": "Bearer op"})
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


def test_route_without_an_active_site_map_is_refused(tmp_path):
    client, _tasks, _store, _robot = _app(tmp_path, imported=False)
    response = client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["ring_s"]},
                           headers={**OPERATOR, "Idempotency-Key": "r1"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "SITE_MAP_NOT_ACTIVE"
    assert client.get("/api/fleet/site-map/active", headers=VIEWER).status_code == 404


def test_trip_returns_a_plan_records_it_and_never_drives(tmp_path):
    client, tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    response = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["edge_id"] for s in body["segments"]] == ["ring_s", "ring_e", "ring_n"]
    assert body["places"] == ["SE", "NE", "NW"] and body["actions"][-1]["action"] == "stop"
    assert body["map_version"] == 1 and body["length_m"] > 1.0 and body["expires_at"] > 0
    assert not [c for c in robot.calls if c[0] == "navigation_goal"]
    assert store.plans()[0]["plan_id"] == body["plan_id"]
    assert ("/api/fleet/robots/rosy_60/trip", "RESULT", 200) in [
        (r["path"], r["event_type"], r["status_code"]) for r in tasks.store.api_audit()]
    x, y = store.active()[2].arcs["ring_n:fwd"].point_at(0.2)[:2]
    point = client.post("/api/fleet/robots/rosy_60/trip", json={"to": {"x": x, "y": y + 0.05}},
                        headers=OPERATOR)
    assert point.status_code == 200 and point.json()["actions"][-1]["place_id"] is None


def test_one_lap_plan_requires_the_robot_at_its_selected_return_place(tmp_path):
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    url = "/api/fleet/robots/rosy_60/trip"
    body = {"to": "NW", "via": ["SE"], "repeat": False, "start_at": "NW"}
    refused = client.post(url, json=body, headers=OPERATOR)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "TRIP_START_PLACE_MISMATCH"
    assert store.plans()[0]["result"]["error"] == "TRIP_START_PLACE_MISMATCH"
    invalid = client.post(url, json={**body, "repeat": True}, headers=OPERATOR)
    assert invalid.status_code == 422


@pytest.mark.parametrize(("body", "code"), [
    ({"to": "nowhere"}, "TRIP_UNKNOWN_PLACE"),
    ({"to": {"x": 5.0, "y": 5.0}}, "TRIP_OFF_MAP"),
    ({"to": "NW", "arrive_yaw": math.pi / 3}, "TRIP_ARRIVE_YAW_UNREACHABLE"),
])
def test_trip_refusals_use_the_d486_codes(tmp_path, body, code):
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    response = client.post("/api/fleet/robots/rosy_60/trip", json=body, headers=OPERATOR)
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert store.plans()[0]["result"]["error"] == code


def test_trip_start_pose_and_map_refusals_and_execution_is_not_open(tmp_path):
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = {"robot_id": "rosy_60", "pose": {"x": 5.0, "y": 5.0, "yaw": 0.0},
                    "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    off = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert off.json()["detail"]["code"] == "TRIP_START_OFF_MAP"
    state = _on_ring_s(store)
    state["pose"]["yaw"] += math.pi
    robot._state = state
    assert client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"},
                       headers=OPERATOR).json()["detail"]["code"] == "TRIP_HEADING_CONFLICT"
    robot._state = {"robot_id": "rosy_60", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}
    assert client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"},
                       headers=OPERATOR).json()["detail"]["code"] == "TRIP_POSE_UNTRUSTED"
    assert client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=VIEWER).status_code == 403
    assert client.post("/api/fleet/robots/nobody/trip", json={"to": "NW"}, headers=OPERATOR).status_code == 404
    assert client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW", "execute": True},
                       headers=OPERATOR).status_code == 501
    assert client.post("/api/fleet/trips/abc/start", headers=OPERATOR).status_code == 404
    (tmp_path / "empty").mkdir()
    empty, _t, _s, _r = _app(tmp_path / "empty", imported=False)
    assert empty.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"},
                      headers=OPERATOR).json()["detail"]["code"] == "TRIP_NO_ACTIVE_MAP"


def test_cli_imports_the_configured_lane_graph_and_reads_fleet_routing(tmp_path):
    from fleet import cli

    config = tmp_path / "site.yaml"
    config.write_text("fleet:\n  routing:\n    turn_cost_s: 3.5\n", encoding="utf-8")
    args = cli.parse_args(["console", "--site-map-import", str(LANE_GRAPH), "--site-config", str(config)])
    store, routing = cli._build_site_map(args, tmp_path / "fleet.sqlite3")
    assert store.active()[0] == 1 and routing.turn_cost_s == 3.5
    store.close()
    config.write_text("fleet:\n  routing:\n    turn_cost_s: -1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="turn_cost_s"):
        cli._build_site_map(cli.parse_args(["console", "--site-config", str(config)]), None)


# ---- review fixes (2026-10-07) --------------------------------------------------------

def test_draft_save_needs_a_named_operator_is_bounded_and_recorded(tmp_path):
    client, _tasks, store, _robot = _app(tmp_path)
    saved = client.put("/api/fleet/site-map/draft", json={"map": _line()}, headers=OPERATOR)
    assert saved.status_code == 200
    assert store.events()[0]["action"] == "draft_saved" and store.events()[0]["principal_id"] == "bob"
    huge = client.put("/api/fleet/site-map/draft", content=b"{" + b" " * (3 * 1024 * 1024) + b"}",
                      headers={**OPERATOR, "Content-Type": "application/json"})
    assert huge.status_code == 413 and huge.json()["detail"]["code"] == "SITE_MAP_TOO_LARGE"
    anonymous = TestClient(create_app(FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")],
                                                   [FakeRobot("rosy_60")]),
                                      console_token="op", site_maps=SiteMapStore()))
    denied = anonymous.put("/api/fleet/site-map/draft", json={"map": _line()},
                           headers={"Authorization": "Bearer op"})
    assert denied.status_code == 403


def test_site_map_errors_use_the_trip_error_shape(tmp_path):
    client, _tasks, _store, _robot = _app(tmp_path, imported=False)
    missing = client.get("/api/fleet/site-map/active", headers=VIEWER).json()["detail"]
    assert missing == {"code": "SITE_MAP_NOT_ACTIVE", "detail": {}}
    stale = client.post("/api/fleet/site-map/activate", json={"expected_revision": "x"}, headers=OPERATOR)
    assert set(stale.json()["detail"]) == {"code", "detail"}
    assert client.post("/api/fleet/trips/abc/start", headers=OPERATOR).json()["detail"] == \
        {"code": "TRIP_PLAN_UNKNOWN", "detail": {}}


def test_activation_refuses_a_map_the_planner_cannot_use(tmp_path, monkeypatch):
    import fleet.server.site_map_store as store_module

    client, _tasks, store, _robot = _app(tmp_path)
    saved = client.put("/api/fleet/site-map/draft", json={"map": _line()}, headers=OPERATOR).json()

    def broken(_graph, _config):
        raise RecursionError("planner cannot read this map")

    monkeypatch.setattr(store_module, "prepare", broken)
    refused = client.post("/api/fleet/site-map/activate", json={"expected_revision": saved["revision"]},
                          headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "SITE_MAP_UNPLANNABLE"
    assert store.active()[0] == 1


def test_a_start_place_must_face_along_its_lane(tmp_path):
    """D-513: a start place carries the departure heading and must be a pose a trip can start from."""
    client, _tasks, _store, _robot = _app(tmp_path)

    def activate(yaw):
        body = _line()
        body["places"].append({"id": "S1", "name": "출발-1", "x": 1.0, "y": 0.02, "yaw": yaw, "kind": "start"})
        revision = client.get("/api/fleet/site-map/draft", headers=OPERATOR).json()["revision"]
        saved = client.put("/api/fleet/site-map/draft", json={"map": body, "expected_revision": revision},
                           headers=OPERATOR).json()
        return client.post("/api/fleet/site-map/activate", json={"expected_revision": saved["revision"]},
                           headers=OPERATOR)

    refused = activate(3.0)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "SITE_MAP_START_INVALID"
    assert "TRIP_HEADING_CONFLICT" in str(refused.json()["detail"])
    assert activate(0.1).status_code == 200

    headless = _line()
    headless["places"].append({"id": "S1", "name": "출발-1", "x": 1.0, "y": 0.0, "kind": "start"})
    with pytest.raises(ValueError, match="needs a yaw"):
        SiteMap.model_validate(headless)


def test_an_unexpected_planner_failure_is_a_coded_500_logged_once(tmp_path, monkeypatch, caplog):
    import fleet.server.trip_routes as trip_module

    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)

    def broken(*_args):
        raise RecursionError("boom")

    monkeypatch.setattr(trip_module, "plan_trip", broken)
    for _ in range(2):
        response = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
        assert response.status_code == 500 and response.json()["detail"]["code"] == "TRIP_PLAN_FAILED"
    assert sum("trip planner failed" in r.message for r in caplog.records) == 1
    assert store.plans()[0]["result"]["error"] == "TRIP_PLAN_FAILED"


def test_unknown_robot_is_recorded_and_plans_are_retained_by_count(tmp_path, monkeypatch):
    import fleet.server.site_map_store as store_module

    monkeypatch.setattr(store_module, "PLAN_KEEP", 3)
    client, _tasks, store, _robot = _app(tmp_path)
    for _ in range(5):
        assert client.post("/api/fleet/robots/nobody/trip", json={"to": "NW"}, headers=OPERATOR).status_code == 404
    rows = store.plans()
    assert len(rows) == 3 and rows[0]["result"]["error"] == "UNKNOWN_ROBOT"


def test_the_stuck_resolver_reads_the_active_site_map(tmp_path):
    robot = FakeRobot("rosy_60")
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    store = SiteMapStore()
    app = create_app(console, site_maps=store, stuck_resolver_clients={"rosy_60": robot})
    painted = app.state.stuck_resolver._resolver._painted
    assert painted() is None
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    assert painted().line("ring_s").start == "SW"


def test_cli_warns_about_an_in_memory_store_and_no_active_map(capsys):
    from fleet import cli

    store, _routing = cli._build_site_map(cli.parse_args(["console"]), None)
    err = capsys.readouterr().err
    assert "no --tasks-db" in err and "no active D-488 site map" in err
    store.close()


def test_the_store_warms_the_planner_with_the_site_routing_config():
    from fleet.routing.cost import RoutingConfig

    config = RoutingConfig(turn_cost_s=3.5)
    store = SiteMapStore(routing_config=config)
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    assert list(store.active()[2]._successors) == [config]


def test_site_map_view_turn_is_a_quarter_turn_defaulting_to_zero():
    """D-513 7: one screen orientation per map, display only."""
    assert SiteMap.model_validate(_line()).view_turn_deg == 0
    assert "view_turn_deg" not in SiteMap.model_validate(_line()).body()  # older Fleet can still read it
    assert SiteMap.model_validate({**_line(), "view_turn_deg": 90}).body()["view_turn_deg"] == 90
    for bad in (45, -90, "90"):
        with pytest.raises(ValueError):
            SiteMap.model_validate({**_line(), "view_turn_deg": bad})
