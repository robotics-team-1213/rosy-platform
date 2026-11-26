"""2026-11-26 panel: the world_261026 floor survey is served with the map record (display_polyline +
display_source), not kept as a console constant. Additive: maps and edges without it stay byte-equal."""

from __future__ import annotations

import copy
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap, with_floor_surveys
from fleet.swarm.robots import RobotEndpoint

VIEWER = {"Authorization": "Bearer viewer-token"}
P1, C1, S5, S3, J = (-0.43002, 0.04266), (-0.41816, 0.47), (0.89822, -0.48152), (0.745, -0.207), (0.31418, -0.25008)


def _edge(eid, a, b, line):
    return {"id": eid, "from": a, "to": b, "polyline": [list(p) for p in line], "direction": "two_way",
            "width_m": 0.185, "speed_cap_mps": 0.2}


def _world(map_id="world_261026") -> dict:
    return {"schema": "rosy.site_map/1", "map_id": map_id,
            "places": [{"id": pid, "name": pid, "kind": kind, "x": x, "y": y} for pid, kind, (x, y) in
                       (("P1", "junction", P1), ("C1", "charge", C1), ("S5", "stop", S5), ("S3", "stop", S3),
                        ("J_in", "junction", J))],
            "edges": [_edge("bay_1", "P1", "C1", [P1, (-0.4354, 0.3294), C1]),
                      _edge("loop_right", "S5", "S3", [S5, (0.9756, -0.4676), (1.0593, -0.3424), (0.9756, -0.2173),
                                                        (0.9238, -0.207), S3]),
                      _edge("upper_east", "S3", "J_in", [S3, (0.56, -0.207), J])]}


def test_the_survey_reaches_matching_edges_with_its_source():
    body = _world()
    served = with_floor_surveys(body)
    edges = {edge["id"]: edge for edge in served["edges"]}
    assert edges["bay_1"]["display_polyline"] == [[-0.4222, 0.0433], [-0.4386, 0.44]]
    assert edges["bay_1"]["display_source"] == {
        "kind": "survey", "surveyed_at": "2026-11-26", "plane": "ceiling_north",
        "anchors": [list(P1), list(C1)], "stored_until": None, "note": "영상의 분홍 충전선 중심"}
    assert edges["loop_right"]["display_source"]["stored_until"] == [0.9238, -0.207]
    assert edges["upper_east"]["display_polyline"] == [[0.745, -0.25008], [0.31418, -0.25008]]
    assert body == _world()  # the stored record is not touched
    # The served shape is a valid record: an editor draft started from it saves and dumps it back.
    assert SiteMap.model_validate(served).body()["edges"][0]["display_polyline"] == [[-0.4222, 0.0433], [-0.4386, 0.44]]


def test_no_survey_line_for_other_maps_moved_or_renamed_edges_and_stored_lines_win():
    assert with_floor_surveys(_world("site-v1")) == _world("site-v1")
    moved = _world()
    moved["edges"][0]["polyline"][-1] = [-0.41816, 0.48]  # 10 mm: needs a new survey
    moved["edges"][2]["to"] = "S5"
    edges = {edge["id"]: edge for edge in with_floor_surveys(moved)["edges"]}
    assert "display_polyline" not in edges["bay_1"] and "display_polyline" not in edges["upper_east"]
    assert "display_polyline" in edges["loop_right"]
    own = _world()
    own["edges"][0] |= {"display_polyline": [[0, 0], [1, 1]], "display_source": {
        "kind": "survey", "surveyed_at": "2026-12-01", "plane": "ceiling_south", "anchors": [list(P1), list(C1)]}}
    assert with_floor_surveys(own)["edges"][0]["display_polyline"] == [[0, 0], [1, 1]]


def test_display_fields_are_optional_paired_and_finite():
    plain = SiteMap.model_validate(_world())
    assert all("display_polyline" not in edge and "display_source" not in edge for edge in plain.body()["edges"])
    half = _world()
    half["edges"][0]["display_polyline"] = [[0, 0], [1, 1]]
    with pytest.raises(ValidationError, match="come together"):
        SiteMap.model_validate(half)
    bad = copy.deepcopy(with_floor_surveys(_world()))
    bad["edges"][0]["display_polyline"][0] = [float("nan"), 0.0]
    with pytest.raises(ValidationError):
        SiteMap.model_validate(bad)
    wrong_kind = copy.deepcopy(with_floor_surveys(_world()))
    wrong_kind["edges"][0]["display_source"]["kind"] = "guess"
    with pytest.raises(ValidationError):
        SiteMap.model_validate(wrong_kind)


def test_the_active_map_route_serves_the_survey_and_keeps_the_stored_hash(tmp_path):
    robot = FakeRobot("rosy_60", state={"robot_id": "rosy_60"})
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    store.import_if_empty(SiteMap.model_validate(_world()), source="survey-test")
    users = {sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    client = TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store))
    body = client.get("/api/fleet/site-map/active", headers=VIEWER).json()
    edges = {edge["id"]: edge for edge in body["map"]["edges"]}
    assert edges["bay_1"]["display_source"]["kind"] == "survey"
    assert body["sha256"] == store.active_view()["sha256"]
    assert "display_polyline" not in store.active_view()["map"]["edges"][0]  # served, not written
