"""D-573 1 (branch b): crosswalk areas on ``rosy.site_map/1`` — lane_graph import, derived
lanes, waiting-band validation, store round trip and the named-operator write. Map data only."""

from __future__ import annotations

import typing
from hashlib import sha256

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.site_map import PlaceKind, SiteMap, crosswalks_from_lane_graph, from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from test_site_map_trip import LANE_GRAPH, OPERATOR, VIEWER, _app

#: Beside cw2 (east lane, centre line y = -0.509, half width 0.0925, x 0.309..0.429).
NORTH_BAND = [[0.309, -0.438], [0.429, -0.438], [0.429, -0.36], [0.309, -0.36]]


def _imported() -> dict:
    return from_lane_graph(LANE_GRAPH).body()


def _with_band(body: dict, band, index: int = 1) -> dict:
    body["crosswalks"][index]["approach"] = [band]
    return body


def test_lane_graph_crosswalks_import_deterministically_onto_their_lanes():
    first, second = from_lane_graph(LANE_GRAPH), from_lane_graph(LANE_GRAPH)
    assert first == second and first.body() == second.body()
    raw = LANE_GRAPH.read_bytes()
    graph = yaml.safe_load(raw)
    rows = first.body()["crosswalks"]
    assert [row["id"] for row in rows] == ["cw1", "cw2"]
    assert [row["polygon"] for row in rows] == [cw["polygon"] for cw in graph["crosswalks"]]
    assert [row["lanes"] for row in rows] == [["west"], ["east"]]
    assert {row["revision"] for row in rows} == {"lane_graph:" + sha256(raw).hexdigest()[:12]}
    assert all(row["approach"] == [] for row in rows)
    assert [c.lanes for c in crosswalks_from_lane_graph(LANE_GRAPH)] == [[], []]  # lanes come with a map


def test_place_kinds_are_unchanged_crosswalks_are_areas():
    assert typing.get_args(PlaceKind) == ("park", "charge", "stop", "junction", "turnaround", "start", "bend")


def test_lanes_are_derived_and_a_map_without_crosswalks_keeps_its_body():
    body = _imported()
    body["crosswalks"][0]["lanes"] = ["east", "made_up"]
    assert SiteMap.model_validate(body).crosswalks[0].lanes == ["west"]
    body.pop("crosswalks")
    assert "crosswalks" not in SiteMap.model_validate(body).body()


def test_a_waiting_band_beside_the_lane_is_kept():
    site = SiteMap.model_validate(_with_band(_imported(), NORTH_BAND))
    assert [list(map(list, band)) for band in site.crosswalks[1].approach] == NORTH_BAND
    assert SiteMap.model_validate(site.body()) == site


@pytest.mark.parametrize("change", [
    lambda b: b["crosswalks"].append(dict(b["crosswalks"][0])),                          # duplicate id
    lambda b: b["crosswalks"][0].update({"polygon": [[0, 0], [1, 0]]}),                  # 2 points
    lambda b: b["crosswalks"][0].update({"polygon": [[0, 0], [1, 0], [2, 0]]}),          # no area
    lambda b: b["crosswalks"][0].update({"polygon": [[-2, -2], [2, -2], [2, 2]]}),       # too large
    lambda b: b["crosswalks"][0].update({"polygon": [[2.0, 2.0], [2.1, 2.0], [2.1, 2.1]]}),  # on no lane
    lambda b: b["crosswalks"][0].update({"revision": ""}),
    lambda b: b["crosswalks"][0].update({"kind": "zebra"}),                              # unknown field
    lambda b: _with_band(b, [[0.309, -0.38], [0.429, -0.38], [0.429, -0.30], [0.309, -0.30]]),  # off its lane
    lambda b: _with_band(b, [[0.309, -0.58], [0.429, -0.58], [0.429, -0.95], [0.309, -0.95]]),    # into the wall
    lambda b: b["crosswalks"][1].update({"approach": [NORTH_BAND] * 5}),                 # too many bands
])
def test_invalid_crosswalks_are_refused(change):
    body = _imported()
    change(body)
    with pytest.raises(ValidationError):
        SiteMap.model_validate(body)


def test_store_round_trips_crosswalks_through_draft_activation_and_reopen(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = SiteMapStore(path)
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    assert [c.id for c in store.active()[1].crosswalks] == ["cw1", "cw2"]
    site = SiteMap.model_validate(_with_band(_imported(), NORTH_BAND))
    draft = store.save_draft(site, expected_revision=None, principal_id="bob")
    assert draft["map"]["crosswalks"][1]["approach"] == [NORTH_BAND]
    store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=False)
    store.close()
    again = SiteMapStore(path)
    assert again.active()[1] == site and again.active_view()["map"]["crosswalks"][1]["lanes"] == ["east"]
    again.close()


def test_crosswalk_writes_need_a_named_operator_and_invalid_bands_are_site_map_invalid(tmp_path):
    client, _tasks, store, _robot = _app(tmp_path)
    body = {"map": _with_band(_imported(), NORTH_BAND)}
    assert client.put("/api/fleet/site-map/draft", json=body, headers=VIEWER).status_code == 403
    shared = TestClient(create_app(FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")], [FakeRobot("rosy_60")]),
                                   console_token="op", site_maps=SiteMapStore()))
    assert shared.put("/api/fleet/site-map/draft", json=body, headers={"Authorization": "Bearer op"}).status_code == 403
    wall = _with_band(_imported(), [[0.309, -0.58], [0.429, -0.58], [0.429, -0.95], [0.309, -0.95]])
    refused = client.put("/api/fleet/site-map/draft", json={"map": wall}, headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "SITE_MAP_INVALID"
    assert "site floor" in refused.text and store.draft_view()["map"] is None
    saved = client.put("/api/fleet/site-map/draft", json=body, headers=OPERATOR)
    assert saved.status_code == 200 and saved.json()["map"]["crosswalks"][1]["approach"] == [NORTH_BAND]


def test_editor_reads_lane_graph_crosswalks_from_the_configured_import(tmp_path):
    client, _tasks, store, _robot = _app(tmp_path)
    missing = client.get("/api/fleet/site-map/lane-graph-crosswalks", headers=VIEWER)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "SITE_MAP_NO_LANE_GRAPH"
    store.import_source = LANE_GRAPH
    read = client.get("/api/fleet/site-map/lane-graph-crosswalks", headers=VIEWER)
    assert read.status_code == 200
    assert read.json() == {"source": "lane_graph.yaml",
                           "crosswalks": [c.model_dump(mode="json") for c in crosswalks_from_lane_graph(LANE_GRAPH)]}
    assert client.get("/api/fleet/site-map/lane-graph-crosswalks").status_code == 401


def test_cli_keeps_the_import_source_for_the_editor(tmp_path):
    from fleet import cli

    args = cli.parse_args(["console", "--site-map-import", str(LANE_GRAPH)])
    store, _routing = cli._build_site_map(args, tmp_path / "fleet.sqlite3")
    assert store.import_source == LANE_GRAPH
    store.close()
